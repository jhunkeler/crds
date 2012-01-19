import pprint
import cPickle
import random
from collections import OrderedDict

import pyodbc

from crds import rmap, log, utils, timestamp
import crds.hst

log.set_verbose(False)

# CONNECTION = pyodbc.connect("DSN=DadsopsDsn;Uid=jmiller;Pwd=")
# CURSOR = CONNECTION.cursor()

CONNECTION = pyodbc.connect("DSN=ReffileOpsDsn;Uid=jmiller;Pwd=")
CURSOR = CONNECTION.cursor()

def get_tables():
    return [row.table_name for row in CURSOR.tables()]

def get_columns(table):
    return [col.column_name for col in CURSOR.columns(table=table)]

def get_db_info(instr):
    info = {}
    for table in get_tables():
        if instr in table:
            info[table] = get_columns(table)
    return info

def make_dicts(table, col_list=None, ordered=False, where="", dataset=None,
               lowercase=True):
    if dataset is not None:
        all_cols = get_columns(table)
        for col in all_cols:
            if "data_set_name" in col:
                dsname = col
                break
        where += "where %s='%s'" % (dsname, dataset)
    if col_list is None:
        col_list = get_columns(table)
    col_names = ", ".join(col_list)
    for row in CURSOR.execute("select %s from %s %s" % (col_names, table, where)):
        items = zip(col_list, [str(x).lower() for x in row] if lowercase else row)
        kind = OrderedDict if ordered else dict
        yield kind(items)

def required_keys(instr):
    imap = rmap.get_cached_mapping("hst_%s.imap" % instr)
    pars = [key.lower() for key in imap.get_required_parkeys()]
    pars.remove("reftype")
    pars.remove("date-obs")
    pars.remove("time-obs")
    pars.append("expstart" if instr != "stis" else "texpstrt")
    pars.append("data_set")
    pars.append("targname")
    pars.extend(imap.selections.keys())
    return pars

def scan_tables(instr):
    pars = required_keys(instr)
    columns = {}
    for table in get_tables():
        if instr not in table:
            continue
        for par in pars:
            for col in get_columns(table):
                if par in col:
                    if par not in columns:
                        columns[par] = []
                    columns[par].append(table + "." + col)
    return columns, set(pars) - set(columns.keys())


def clean_scan(instr):
    columns, remainder = scan_tables(instr)
    if remainder:
        log.warning("For", repr(instr), "can't locate", sorted(list(remainder)))
    else:
        log.info("collected", repr(instr), "ok")
    clean = {}
    for var in columns:
        tvar2 = columns[var]
        tvar = []
        for cand in tvar2:
            if "_old" not in cand:
                tvar.append(cand)

        for cand in tvar:
            if "best" in cand:
                tvar = [cand]
                break

        for cand in tvar:
            if "ref_data" in cand and "tv_ref_data" not in cand:
                tvar = [cand]
                break

        for cand in tvar:
            if "science" in cand and "tv_science" not in cand:
                tvar = [cand]
                break

        if len(tvar) == 1:
            clean[var] = tvar[0]
        elif len(tvar) == 2 and "best" in tvar[1] and "best" not in tvar[0]:
            clean[var] = tvar[1]
        else:
            clean[var] = tvar
    return clean

def gen_header_tables(datfile="header_tables.dat"):
    table = {}
    for instr in crds.hst.INSTRUMENTS:
        table[instr] = clean_scan(instr)
    open(datfile, "w+").write(pprint.pformat(table) + "\n")
        
"""
SELECT Persons.LastName, Persons.FirstName, Orders.OrderNo
FROM Persons
FULL JOIN Orders
ON Persons.P_Id=Orders.P_Id
ORDER BY Persons.LastName
"""

class HeaderGenerator(object):
    def __init__(self, instrument, header_to_db_map):
        self.h_to_db = header_to_db_map
        self.instrument = instrument.lower()

    @property
    def header_keys(self):
        return [key.upper() for key in self.h_to_db.keys()]

    @property
    def db_columns(self):
        return self.h_to_db.values()

    @property
    def db_tables(self):
        tables = set()
        for column in self.db_columns:
            table, col = column.split(".")
            tables.add(table)
        return list(tables)

    def getter_sql(self):
        sql = "SELECT %s FROM %s " % (", ".join(self.db_columns), 
                                      ", ".join(self.db_tables))
        if len(self.db_tables) >= 2:
            sql += "WHERE %s" % self.join_expr()
        return sql

    def join_expr(self):
        all_cols = []
        for table in self.db_tables:
            all_cols += [table + "." + col for col in get_columns(table)]
        clauses = []
        for suffix in ["program_id", "obset_id", "obsnum"]:
            joined = []
            for col in all_cols:
                if col.endswith(suffix):
                    joined.append(col)
            if len(joined) >= 2:
                for more in joined[1:]:
                    clauses.append(joined[0] + "=" + more)
        return (" and ").join(clauses)

    def get_headers(self):
        sql = self.getter_sql()
        for dataset in CURSOR.execute(sql):
            hdr = dict(zip(self.header_keys, [utils.condition_value(x) for x in dataset]))
            self.fix_time(hdr)
            hdr["INSTRUME"] = self.instrument
            yield hdr

    def fix_time(self, hdr):
        expstart = hdr.get("EXPSTART", hdr.get("TEXPSTRT"))
        try:
            hdr["DATE-OBS"], hdr["TIME-OBS"] = timestamp.format_date(expstart).split()
        except:
            log.warning("Bad database EXPSTART", expstart)


try:
    HEADER_MAP = eval(open("header_tables.dat").read())

    HEADER_GENERATORS = {}
    for instr in HEADER_MAP:
        HEADER_GENERATORS[instr] = HeaderGenerator(instr, HEADER_MAP[instr])
except:
    log.error("Failed loading 'header_tables.dat'")


def test(header_generator, ncases=None, context="hst.pmap", dataset=None, ignore=None):
    """Evaluate the first `ncases` best references cases from 
    `header_generator` against similar results attained from CRDS running
    on pipeline `context`.
    """
    log.reset()
    if header_generator in crds.hst.INSTRUMENTS:
        headers = HEADER_GENERATORS[instr].get_headers()
    elif isinstance(header_generator, str): 
        if header_generator.endswith(".pkl"):
            headers = cPickle.load(open(header_generator))
        else:
            headers = eval(open(header_generator).read())
    else:
        raise ValueError("header_generator should name an instrument, pickle, or eval file.")
    count = 0
    mismatched = {}
    oldv = log.get_verbose()
    for header in headers:
        if dataset is not None:
            if dataset != header["DATA_SET"]:
                continue
            log.set_verbose(True)
        crds_refs = rmap.get_best_references(context, header)
        compare_results(header, crds_refs, mismatched, ignore)
        count += 1
        if ncases is not None and count >= ncases:
            break
    log.write()
    log.write()
    for filekind in mismatched:
        log.write(filekind, "mismatched:", mismatched[filekind])
    log.write()
    log.write(count, "datasets")
    log.standard_status()
    log.set_verbose(oldv)

def compare_results(header, crds_refs, mismatched, ignore):
    """Compare the old best ref recommendations in `header` to those 
    in `crds_refs`,  recording a list of error tuples by filekind in
    dictionary `mismatched`.  Disregard any filekind listed in `ignore`.
    """
    mismatches = 0
    for filekind in crds_refs:
        if ignore and filekind in ignore:
            continue
        if filekind not in mismatched:
            mismatched[filekind] = {}
        try:
            old = header[filekind.upper()].lower()
        except:
            log.warning("No comparison for", repr(filekind))
            continue
        new = crds_refs[filekind]
        if old in ["n/a", "*", "none"]:
            log.verbose("Ignoring", repr(filekind), "as n/a")
            continue
        if old != new:
            dataset = header["DATA_SET"]
            if not mismatches:
                log.verbose("dataset", dataset, "...", "ERROR")
            mismatches += 1
            log.error("mismatch:", dataset, filekind, old, new)
            if (old, new) not in mismatched[filekind]:
                mismatched[filekind][(old,new)] = 0
            mismatched[filekind][(old,new)] += 1
    if not mismatches:
        log.write(".", eol="", sep="")

def testall(ncases=10**10, context="hst.pmap", instruments=None, 
            suffix="_headers.pkl"):
    if instruments is None:
        pmap = rmap.get_cached_mapping(context)
        instruments = pmap.selections
    for instr in instruments:
        log.write(70*"=")
        log.write(instr, ":")
        test(instr+suffix, ncases, context)
        log.write()

def dump(instr, ncases=10**10, random_samples=True, suffix="_headers.pkl"):
    """Store `ncases` header records taken from DADSOPS for `instr`ument in 
    a pickle file,  optionally sampling randomly from all headers.
    """
    samples = []
    headers = list(HEADER_GENERATORS[instr].get_headers())
    while len(samples) < ncases and headers:
        selected = int(random.random()*len(headers)) if random_samples else 0
        samples.append(headers.pop(selected))
    cPickle.dump(samples, open(instr + suffix, "w+"))


def dumpall(context="hst.pmap", ncases=1000, random_samples=True, 
            suffix="_headers.pkl"):
    """Generate header pickles for all instruments referred to by `context`,
    where the headers are taken from the DADSOPS database.   Optionally collect
    only `ncases` samples taken randomly accoring to the `random_samples` flag.
    """
    pmap = rmap.get_cached_mapping(context)
    for instr in pmap.selections.keys():
        log.info("collecting", repr(instr))
        dump(instr, ncases, random_samples, suffix)

