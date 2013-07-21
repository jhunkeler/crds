"""Supports accessing CDBS reference and archive catalogs for the purposes
of generating rmaps and comparing CRDS best refs to CDBS best refs.
"""
import sys
import cPickle
import random
import datetime
import cProfile
import os.path

import cdbs_db

# import pyodbc  deferred...

from crds import rmap, log, pysh, utils
import crds.hst

import opus_bestref

log.set_verbose(False)

DEFAULT_PKL_PATH = "../datasets/"
    
def fix_iraf_paths(header):
    """Get rid of the iref$ prefixes on filenames."""
    header2 = {}
    for key, value in header.items():
        if "$" in value:
            header2[key] = value.split("$")[1]
        else:
            header2[key] = value
    return header2

def lookup_key(pmap, header):
    """Convert a parameters+bestrefs dict into a tuple which can be used
    to locate it in the dictionary of alternate headers.
    
    In theory then,  auxilliary datasets can be loaded into an "improved
    bestrefs recommendations" dictionary keyed off their input parameters.
    Then,  when a set of catalog inputs are known,  they can be used to 
    search for any possible improved answers not found in the catalog.
    
    This basic key includes parameters for all reftypes,  which is inadequate.
    minimize_inputs() reduces the key to those required for one reftype,
    which is more suitable for identifying dataset equivalence sets within
    a single reftype.
    """
    min_header = pmap.minimize_header(header)
    result = []
    for key, val in sorted(min_header.items()):
        if ".FITS" in val or key.endswith("FILE") or key.endswith("TAB"):
            continue
        if val in ["NOT FOUND"]:
            continue
        if key in ["DATE-OBS", "TIME-OBS", "EXPSTART", "DATA_SET"]:
            continue
        result.append((key, val.upper()))
    return tuple(result)

def minimize_inputs(instrument, filekind, inputs):
    """Return an item tuple of only those inputs required by filekind.
    """
    mapping = rmap.get_cached_mapping("hst_"+instrument+"_"+filekind+".rmap")
    required = mapping.get_required_parkeys()
    min_inputs = { key : val for key, val in inputs if key in required }
    min_inputs["INSTRUME"] = instrument.upper()
    min_inputs["REFTYPE"] = filekind.upper()
    return tuple([(key.upper(), val.upper()) for (key, val) in sorted(min_inputs.items())])

def same_keys(dict1, dict2):
    """return a copy of dict2 reduced to the same keywords as dict1"""
    return { key:val for (key, val) in dict2 if key in dict1 }

def dump_header(title, pmap, header):
    """Pretty print header as lookup parameters and results in verbose mode."""
    if log.get_verbose():
        header = dict(header)
        log.verbose("-"*60)
        log.verbose(title, ": lookup parameters")
        lookup = pmap.minimize_header(header)
        log.verbose(log.PP(lookup))
        log.verbose(title, ": results")
        results = { key:val for (key,val) in header.items() if key not in lookup }
        log.verbose(log.PP(results))
        return results
    else:
        return None

def dump_results_differences(db, opus):
    """Show changes in results between DB and OPUS"""
    if db is None or opus is None:
        return
    log.verbose("Results difference between DB and OPUS")
    log.verbose("In DB, not OPUS")
    log.verbose(log.PP({ key:db[key] for key in db if key not in opus}))        
    log.verbose("In OPUS, not DB")
    log.verbose(log.PP({ key:opus[key] for key in opus if key not in db}))        
    log.verbose("DB != OPUS")
    log.verbose(log.PP({ key:(db[key], opus[key]) for key in db if key in opus and opus[key] != db[key]}))        
    

def testit(header_spec, context="hst.pmap", datasets=[], 
         filekinds=[], alternate_headers={}, inject_errors=None):
    """Evaluate the best references cases from `header_generator` against 
    similar results attained from CRDS running on pipeline `context`.
    """
    log.reset()
    
    headers = get_headers(header_spec)

    pmap = rmap.get_cached_mapping(context)

    start = datetime.datetime.now()

    dataset_count = 0
    mismatched = {}
    
    for header in headers:
        
        dataset = header["DATA_SET"].lower()
        if datasets and dataset not in datasets:
            continue
        dataset_count += 1
        
        db_results = dump_header("Header From Database", pmap, header)
        
        if dataset in alternate_headers:
            header.update(alternate_headers[dataset])
            opus_results = dump_header("Alternate header from OPUS", pmap, header)
            dump_results_differences(db_results, opus_results)

        if inject_errors:
            header = inject_random_error(inject_errors, dataset, header)
            
        instrument = pmap.get_instrument(header)        
        imap = pmap.get_imap(instrument)
        if not filekinds:
            filekinds = imap.get_filekinds()

        crds_refs = rmap.get_best_references(pmap, header, include=filekinds)

        mismatches = 0
        matches = 0
        for filekind in filekinds:            
            if filekind.upper() not in imap.get_filekinds():
                raise ValueError("Unknown filekind " + repr(filekind) + " for " + repr(instrument))
            try:
                old_bestref = header[filekind.upper()].lower()
            except KeyError:
                log.verbose_warning("No CDBS comparison for", repr(filekind))
                sys.exc_clear()
                continue

            if old_bestref in ["n/a", "*", "none",'']:
                log.verbose("Ignoring", repr(filekind), "as n/a")
                continue
    
            try:
                new_bestref = crds_refs[filekind.lower()]
            except KeyError:
                log.verbose_warning("No CRDS result for", filekind, "of", dataset)
                sys.exc_clear()
                continue

            if "n/a" in new_bestref.lower():
                log.verbose_warning("N/A MISMATCH:", dataset, instrument, filekind, old_bestref, new_bestref)
                continue

            if old_bestref != new_bestref:
                mismatches += 1
                log.error("MISMATCH:", dataset, instrument, filekind, old_bestref, new_bestref)
                if log.get_verbose():
                    try:
                        reference_info(old_bestref)
                    except Exception, exc:
                        log.warning("No info for", repr(new_bestref), ":", str(exc))
                    try:
                        if "NOT FOUND" not in new_bestref:
                            reference_info(new_bestref)
                        else:
                            log.warning("No info", new_bestref)
                    except Exception, exc:
                        log.warning("No info for", repr(new_bestref), ":", str(exc))
                category = (instrument, filekind, old_bestref, new_bestref)
                if category not in mismatched:
                    mismatched[category] = set()
                mismatched[category].add(dataset)
            else:
                matches += 1
                log.verbose("CDBS/CRDS matched:", filekind, old_bestref)
            
        if not mismatches:
            # Output a single character count of the number of correct bestref
            # recommendations for this dataset.
            char = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"[matches]
            log.write(char, end="", sep="")

    elapsed = datetime.datetime.now() - start
    summarize_results(instrument, mismatched, dataset_count, elapsed)

def summarize_results(instrument, mismatched, dataset_count, elapsed):
    """Output summary of mismatch errors."""
    log.info("-"*80)
    totals = {}
    for category, datasets in mismatched.items():
        instrument, filekind, old, new = category
        log.info("Erring Inputs:", instrument, filekind, len(datasets), old, new)
        log.info("Datasets:", instrument, filekind, len(datasets), " ".join(sorted(datasets)))
        if (instrument, filekind) not in totals:
            totals[(instrument, filekind)] = 0
        totals[(instrument, filekind)] += len(datasets)
    for key in totals:
        log.info(key, totals[key], "mismatch errors")
    log.info(instrument, dataset_count, "datasets")
    log.info(instrument, elapsed, "elapsed")
    log.info(instrument, dataset_count/elapsed.total_seconds(), "datasets / sec")
    log.standard_status()

def get_headers(header_spec):
    """Get a header generator either as a database generator or a pickle."""
    if header_spec in crds.hst.INSTRUMENTS:
        log.info("Getting headers from", repr(header_spec))
        headers = cdbs_db.HEADER_GENERATORS[header_spec].get_headers()
    elif isinstance(header_spec, str): 
        log.info("Loading pickle", repr(header_spec))
        headers = cPickle.load(open(header_spec)).values()
    else:
        raise ValueError("header_spec should name an instrument or pickle file.")
    headers = {hdr["DATA_SET"].lower() : hdr for hdr in headers}.values() 
    return headers

def testall(context="hst.pmap", instruments=[], 
            suffix="_headers.pkl", filekinds=[], datasets=[],
            path=DEFAULT_PKL_PATH, profile=False, inject_errors=None):
    alternate_headers = opus_bestref.load_alternate_dataset_headers()
    if not instruments:
        pmap = rmap.get_cached_mapping(context)
        instruments = pmap.selections
    for instr in instruments:
        log.info(70*"=")
        log.info("instrument", instr + ":")
        headers = path+instr+suffix
        if profile:
            cProfile.runctx("testit(headers, context, "
                            "filekinds=filekinds, datasets=datasets, "
                            "alternate_headers=alternate_headers,"
                            "inject_errors=inject_errors)",
                            globals(), locals(), instr + ".stats")
        else:
            testit(headers, context, datasets=datasets, filekinds=filekinds,
                 alternate_headers=alternate_headers, inject_errors=inject_errors) 
        log.info("="*80)

def inject_random_error(inject_errors, dataset, header):
    """Randomly set an element of dataset to 'foo'"""
    words = inject_errors.split(",")
    if len(words) == 1:
        thresh = float(words[0])
        mode = "bestrefs"
    else:
        assert len(words) == 2, "-random-errors=[params|bestrefs|both|<thresh>][,<thresh>]"
        mode = words[0]
        assert mode in ["params", "bestrefs", "both"],"-random-errors=[params|bestrefs|both|<thresh>][,<thresh>]"
        thresh = float(words[1])

    # log.info("mode",repr(mode),"thresh",repr(thresh))

    if random.random() >= thresh:
        return header

    witherr = dict(header)
    keys = witherr.keys()
    key = None

    if mode == "params":
        while (not key) or key.endswith(("FILE", "TAB")) or key in ["INSTRUME", "DATA_SET",]:
            which = int(random.random()*len(keys))
            key = keys[which]
    elif mode == "bestrefs":
        while (not key) or not key.endswith(("FILE", "TAB")):
            which = int(random.random()*len(keys))
            key = keys[which]
    else: # both
        while (not key) or key in ["INSTRUME", "DATA_SET",]:
            which = int(random.random()*len(keys))
            key = keys[which]
    log.info("Injecting error on dataset", repr(dataset), 
             "at key", repr(key), "=", repr("foo"))
    witherr[key] = "foo"
    return witherr

def dump(instr, suffix="_headers.pkl", path=DEFAULT_PKL_PATH):
    """Store `ncases` header records taken from DADSOPS for `instr`ument in 
    a pickle file,  optionally sampling randomly from all headers.
    """
    log.info("Collecting", repr(instr))
    headers = list(cdbs_db.HEADER_GENERATORS[instr].get_headers())
    samples = { h["DATA_SET"] : h for h in headers }
    pickle = path + instr + suffix
    log.info("Saving pickle", repr(pickle))
    utils.ensure_dir_exists(pickle)
    cPickle.dump(samples, open(pickle, "w+"))

def dumpall(context="hst.pmap", suffix="_headers.pkl", path=DEFAULT_PKL_PATH):
    """Generate header pickles for all instruments referred to by `context`,
    where the headers are taken from the DADSOPS database.   Optionally collect
    only `ncases` samples taken randomly accoring to the `random_samples` flag.
    """
    pmap = rmap.get_cached_mapping(context)
    for instr in pmap.selections.keys():
        dump(instr, suffix, path)
    
class DictTable(object):
    """DictTable supports printing a list of dicts as a table."""
    def __init__(self, dicts, columns=None, max_field_len=80):
        self.dicts = dicts
        self.columns = tuple(columns if columns is not None else sorted(dicts[0].keys()))
        self.max_field_len = max_field_len
        self.format = self.get_format()
    
    def get_row(self, i):
        d = self.dicts[i]
        return tuple([ str(d[key]).replace("\n",";")[:self.max_field_len]
                      for key in self.columns])
    
    @property
    def rows(self):
        return [self.get_row(i) for i in range(len(self.dicts))]
    
    def get_format(self):
        lengths = [len(col) for col in self.columns ]
        for i, col in enumerate(self.columns):
            for r  in self.rows:
                lengths[i] = min(max(lengths[i], len(str(r[i]))), self.max_field_len)
        return "  ".join(["%%%ds" % -l for l in lengths])
    
    def __str__(self):
        s = [ self.format.replace("-","") % self.columns + "\n"]
        for r in self.rows:
            s.append(self.format % r + "\n")
        return "".join(s)

    @property
    def width(self):
        return len(self.format % self.get_row(0))-1
        
def reference_info(reference_filename, context="hst.pmap"):
    """Print out the CDBS database information about a reference file."""
    vstate = log.set_verbose(False)
    instrument, files = cdbs_db.get_reference_info_files(reference_filename)
    if instrument.lower() not in crds.hst.INSTRUMENTS:
        log.info("File " + repr(reference_filename) + " corresponds to unsupported instrument " + repr(instrument))
    else:
        log.info("File " + repr(reference_filename) + " corresponds to instrument " + repr(instrument))
    if not files:
        raise LookupError("Can't find reference " + repr(reference_filename))
    file_columns = "file_name,reject_flag,opus_flag,useafter_date,archive_date,general_availability_date,comment".split(",")
    file_table = DictTable(files[:1], file_columns)
    
    instrument, rows = cdbs_db.get_reference_info_rows(reference_filename)
    imap = rmap.get_cached_mapping("hst_" + instrument + ".imap")
    row_columns = "file_name,observation_begin_date,observation_end_date,pedigree".split(",")
    row_columns += [ key.lower() for key in imap.get_required_parkeys() if key.lower() in rows[0].keys()]
    row_columns += ["comment"]
    row_table = DictTable(rows, row_columns)

    print("=" * (row_table.width//2) + " reference " + "=" * (row_table.width//2))
    print(file_table)
    print("-" * row_table.width)
    print("Files rows = %d" % len(row_table.rows))
    print("-" * row_table.width)
    print(row_table)
    print("=" * row_table.width)
    print(("Matches for " + repr(reference_filename) + " in '%s': ") % context)
    basename = os.path.basename(reference_filename)
    print(pysh.out_err("python -m crds.matches --contexts ${context} --files ${basename}"))
    log.set_verbose(vstate)
    
def dataset_info(dataset_filename, context):
    """Print out the CDBS database information about a dataset file."""
    dataset_filename = os.path.basename(dataset_filename)
    dataset_id = dataset_filename.split("_")[0]
    header = cdbs_db.get_dataset_header(dataset_id)[0]
    instrument = header["INSTRUME"]
    header = { key.lower():value for (key,value) in header.items() }
    imap = rmap.get_cached_mapping(context).get_imap(instrument)
    header["file_name"] = dataset_filename
    row_columns = ["file_name"]
    row_columns += [ key for key in imap.get_required_parkeys() if key in header.keys()]
    row_table = DictTable([header], row_columns)
    print("=" * (row_table.width//2) + " dataset " + "=" * (row_table.width//2))
    print(row_table)
        
def info(file, context):
    try:
        reference_info(file, context)
    except LookupError:
        log.info("Couldn't find " + repr(file) + " as a reference or datsaset.")
    try:
        dataset_info(file, context)
    except LookupError:
        pass

def main():
    if len(sys.argv) == 1:
        sys.argv.append("--help")
    if "--verbose" in sys.argv:
        sys.argv.remove("--verbose")
        log.set_verbose(50)
    if "--no-profile" in sys.argv:
        sys.argv.remove("--no-profile")
        profile = False
    else:
        profile = True

    context = "hst.pmap"
    inject_errors = None        
    for i, arg in enumerate(sys.argv):
        if arg.startswith("--random-errors"):
            parts = arg.split("=")
            if len(parts) == 1:
                inject_errors = "0.005"
            else:
                inject_errors = parts[1]
            del sys.argv[i]
        elif arg.endswith(".pmap"):
            context = sys.argv[i]
            del sys.argv[i]
    log.info("Context is", repr(context))
    log.info("Inject errors is", inject_errors)

    if sys.argv[1] == "dumpall":
        dumpall(context=context)
    elif sys.argv[1] == "dump":
        dump(sys.argv[2])
    elif sys.argv[1] == "info":
        info(sys.argv[2], context=context)
    elif sys.argv[1] == "testall":
        testall(context=context, path=DEFAULT_PKL_PATH, profile=profile)
    elif sys.argv[1] == "test":
        if len(sys.argv) > 2:
            instruments = [instr.lower() for instr in sys.argv[2].split(",")]
        else:
            instruments = []
            filekinds = []
        if len(sys.argv) > 3:
            filekinds = [kind.lower() for kind in sys.argv[3].split(",")]
        else:
            filekinds = []
        if len(sys.argv) > 4:
            datasets = [d.lower() for d in sys.argv[4:]]
            log.set_verbose(80)
            profile = False
        else:
            datasets = []
        testall(context=context, instruments=instruments, filekinds=filekinds, datasets=datasets,
                path=DEFAULT_PKL_PATH, profile=profile, inject_errors=inject_errors)
    else:
        log.info("""usage:
python db_test.py dumpall
python db_test.py dump <instrument>
python db_test.py info <reference_file>|<dataset_file>
python db_test.py testall <context>
python db_test.py test <context> [instrument [filekind [dataset...]]]
""")
        sys.exit(-1)
    sys.exit(0)   # Bypass Python garbage collection if possible.

if __name__ == "__main__":
    main()
