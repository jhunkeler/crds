"""Supports accessing CDBS reference and archive catalogs for the purposes
of generating rmaps and comparing CRDS best refs to CDBS best refs.
"""
import sys
import cPickle
import random
import datetime
import cProfile

import cdbs_db

# import pyodbc  deferred...

from crds import rmap, log
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
        
        log.verbose("Header from database")
        log.verbose(log.PP(header))
            
        
        if dataset in alternate_headers:
            header.update(alternate_headers[dataset])
            log.verbose("Alternate header")
            log.verbose(log.PP(header))
        
        if inject_errors:
            header = inject_random_error(inject_errors, dataset, header)
            
        instrument = header["INSTRUME"]
        imap = pmap.get_imap(instrument)
        if not filekinds:
            filekinds = imap.get_filekinds()

        crds_refs = pmap.get_best_references(header, include=filekinds)

        mismatches = 0
        matches = 0
        for filekind in filekinds:
            try:
                old_bestref = header[filekind.upper()].lower()
            except KeyError:
                log.verbose_warning("No CDBS comparison for", repr(filekind))
                sys.exc_clear()
                continue

            if old_bestref in ["n/a", "*", "none"]:
                log.verbose("Ignoring", repr(filekind), "as n/a")
                continue
    
            try:
                new_bestref = crds_refs[filekind.lower()]
            except KeyError:
                log.verbose_warning("No CRDS result for", filekind, "of", dataset)
                sys.exc_clear()
                continue

            if old_bestref != new_bestref:
                mismatches += 1
                log.error("mismatch:", dataset, instrument, filekind, old_bestref, new_bestref)
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
    log.write()
    log.write()
    totals = {}
    for category, datasets in mismatched.items():
        instrument, filekind, old, new = category
        log.write("Erring Inputs:", instrument, filekind, len(datasets), old, new)
        log.write("Datasets:", instrument, filekind, len(datasets), " ".join(sorted(datasets)))
        if (instrument, filekind) not in totals:
            totals[(instrument, filekind)] = 0
        totals[(instrument, filekind)] += len(datasets)
    log.write()
    for key in totals:
        log.write(key, totals[key], "mismatch errors")
    log.write()
    log.write(instrument, dataset_count, "datasets")
    log.write(instrument, elapsed, "elapsed")
    log.write(instrument, dataset_count/elapsed.total_seconds(), "datasets / sec")
    log.write()
    log.standard_status()

def get_headers(header_spec):
    """Get a header generator either as a database generator or a pickle."""
    if header_spec in crds.hst.INSTRUMENTS:
        log.write("Getting headers from", repr(header_spec))
        headers = cdbs_db.HEADER_GENERATORS[header_spec].get_headers()
    elif isinstance(header_spec, str): 
        log.write("Loading pickle", repr(header_spec))
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
        log.write(70*"=")
        log.write("instrument", instr + ":")
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
        log.write()

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

    # log.write("mode",repr(mode),"thresh",repr(thresh))

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
    headers = list(cdbs_db.HEADER_GENERATORS[instr].get_headers())
    samples = { h["DATA_SET"] : h for h in headers }
    pickle = path + instr + suffix
    log.write("Saving pickle", repr(pickle))
    cPickle.dump(samples, open(pickle, "w+"))

def dumpall(context="hst.pmap", suffix="_headers.pkl", path=DEFAULT_PKL_PATH):
    """Generate header pickles for all instruments referred to by `context`,
    where the headers are taken from the DADSOPS database.   Optionally collect
    only `ncases` samples taken randomly accoring to the `random_samples` flag.
    """
    pmap = rmap.get_cached_mapping(context)
    for instr in pmap.selections.keys():
        log.info("collecting", repr(instr))
        dump(instr, suffix, path)
    
class DictTable(object):
    """DictTable supports printing a list of dicts as a table."""
    def __init__(self, dicts, columns=None):
        self.dicts = dicts
        self.columns = tuple(columns if columns is not None else sorted(dicts[0].keys()))
        self.format = self.get_format()
    
    def get_row(self, i):
        d = self.dicts[i]
        return tuple([ str(d[key]).replace("\n",";") for key in self.columns])
    
    @property
    def rows(self):
        return [self.get_row(i) for i in range(len(self.dicts))]
    
    def get_format(self):
        lengths = [len(col) for col in self.columns ]
        for i, col in enumerate(self.columns):
            for d in self.dicts:
                lengths[i] = max(lengths[i], len(str(d[col])))
        return "  ".join(["%%%ds" % -l for l in lengths])
    
    def __str__(self):
        s = [ self.format.replace("-","") % self.columns + "\n"]
        for r in self.rows:
            s.append(self.format % r + "\n")
        return "".join(s)

    @property
    def width(self):
        return len(self.format % self.get_row(0))-1
        
def reference_info(reference):
    """Print out the CDBS database information about a reference file."""
    _instrument, files = cdbs_db.get_reference_info_files(reference)
    file_columns = "file_name,reject_flag,opus_flag,useafter_date,archive_date,general_availability_date,comment".split(",")
    file_table = DictTable(files, file_columns)
    
    instrument, rows = cdbs_db.get_reference_info_rows(reference)
    imap = rmap.get_cached_mapping("hst_" + instrument + ".imap")
    row_columns = "observation_begin_date,observation_end_date,pedigree".split(",")
    row_columns += [ key.lower() for key in imap.get_required_parkeys() if key.lower() in rows[0].keys()]
    row_columns += ["comment"]
    row_table = DictTable(rows, row_columns)

    log.write("=" * file_table.width)
    log.write(file_table)
    log.write("-" * file_table.width)
    log.write(row_table)

def main():
    if "--verbose" in sys.argv:
        sys.argv.remove("--verbose")
        log.set_verbose(60)
    if "--no-profile" in sys.argv:
        sys.argv.remove("--no-profile")
        profile = False
    else:
        profile = True
    for i, arg in enumerate(sys.argv):
        if arg.startswith("--random-errors"):
            parts = arg.split("=")
            if len(parts) == 1:
                inject_errors = "0.005"
            else:
                inject_errors = parts[1]
            del sys.argv[i]
            break
    else:
        inject_errors = None
    if sys.argv[1] == "dumpall":
        dumpall()
    elif sys.argv[1] == "dump":
        dump(sys.argv[2])
    elif sys.argv[1] == "info":
        reference_info(sys.argv[2])
    elif sys.argv[1] == "testall":
        testall(path=DEFAULT_PKL_PATH, profile=profile)
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
            datasets = [d.lower() for d in sys.argv[4].split(",")]
            log.set_verbose(60)
        else:
            datasets = []
        testall(instruments=instruments, filekinds=filekinds, datasets=datasets,
                path=DEFAULT_PKL_PATH, profile=profile, inject_errors=inject_errors)
    else:
        log.write("""usage:
python cdbs_db.py dumpall
python cdbs_db.py dump <instrument>
python cdbs_db.py info <reference_file>
python cdbs_db.py testall
python cdbs_db.py test [instrument [filekind [dataset]]]
""")
        sys.exit(-1)
    sys.exit(0)   # Bypass Python garbage collection if possible.

if __name__ == "__main__":
    main()
