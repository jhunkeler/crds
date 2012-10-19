"""Supports accessing CDBS reference and archive catalogs for the purposes
of generating rmaps and comparing CRDS best refs to CDBS best refs.
"""
import pprint
import getpass
import os.path

# import pyodbc  deferred...

from crds import rmap, log, utils, timestamp, data_file
import crds.hst
import crds.hst.parkeys as parkeys
from collections import OrderedDict

# DATABASE_DSN = "ReffileOpsRepDsn"
REFFILE_OPS_DSN = "HarpoReffileOpsRepDsn"
DADSOPS_DSN = "HarpoDadsOpsRepDsn"

"""  
IPPPSSOOT   ---   dataset naming breakdown

Denotes the instrument type:
J - Advanced Camera for Surveys
L - COS
U - Wide Field / Planetary Camera 2
V - High Speed Photometer
W - Wide Field / Planetary Camera
X - Faint Object Camera
Y - Faint Object Spectrograph
Z - Goddard High Resolution Spectrograph
E - Reserved for engineering data
F - Fine Guide Sensor (Astrometry)
H-I,M - Reserved for additional instruments
N - Near Infrared Camera Multi Object Spectrograph
O - Space Telescope Imaging Spectrograph
S - Reserved for engineering subset data
T - Reserved for guide star position data

PPP     Denotes the program ID, any combination of letters or numbers

SS    Denotes the observation set ID, any combination of letters or numbers

OO    Denotes the observation ID, any combination of letters or numbers
T    Denotes the source of transmission:
R - Real time (not tape recorded)
T - Tape recorded
M - Merged real time and tape recorded
N - Retransmitted merged real time and tape recorded
O - Retransmitted real time
P - Retransmitted tape recorded
"""

IPPPSSOOT_INSTR = {
    "J" : "acs",
    "U" : "wfpc2",
    "V" : "hsp",
    "W" : "wfpc",
    "X" : "foc",
    "Y" : "fos",
    "Z" : "hrs",
    "E" : "eng",
    "F" : "fgs",
    "I" : "wfc3",
    "N" : "nicmos",
    "O" : "stis",
    "L" : "cos",
}

def dataset_to_instrument(dataset):
    instr = dataset[0].upper()
    try:
        return IPPPSSOOT_INSTR[instr]
    except KeyError:
        raise LookupError("Can't determine instrument for dataset " + repr(dataset))

class DB(object):
    def __init__(self, dsn, user, password=None):

        import pyodbc

        self.dsn = dsn
        self.user = user
        if password is None:
            password = getpass.getpass("password: ")
        self.connection = pyodbc.connect(
            "DSN=%s;Uid=%s;Pwd=%s" % (dsn, user, password))
        self.cursor = self.connection.cursor()

    def __repr__(self):
        return self.__class__.__name__ + "(%s, %s)" % (repr(self.dsn), repr(self.user))

    def execute(self, sql):
        log.verbose("Executing SQL:", repr(sql))
        return self.cursor.execute(sql)

    def get_tables(self):
        """Return a list of table names for this database."""
        return [str(row.table_name) for row in self.cursor.tables()]

    def get_columns(self, table):
        """Return a list of column names for table."""
        return [str(col.column_name) for col in self.cursor.columns(table=table)]

    def get_column_info(self, table):
        """Return a list/table of column information for this table."""
        return list(self.cursor.columns(table=table))

    def make_dicts(self, table, col_list=None, ordered=False, 
                   where="", dataset=None, lowercase=True):
        """Generate the dictionaries corresponding to rows of `table`."""
        if dataset is not None:
            all_cols = self.get_columns(table)
            for col in all_cols:
                if "data_set_name" in col:
                    dsname = col
                    break
            if not where:
                where = "where %s='%s'" % (dsname, dataset)
            else:
                where += " and  %s='%s'" % (dsname, dataset)
        if col_list is None:
            col_list = self.get_columns(table)
        col_names = ", ".join(col_list) or "*"

        sql_expr = "select %s from %s %s" % (col_names, table, where)
        for row in self.execute(sql_expr):
            items = zip(col_list, [str(x).lower() for x in row] if lowercase else row)
            kind = OrderedDict if ordered else dict
            yield kind(items)
            
    def get_dataset_map(self, table, col_list=None):
        """Return a mapping { dataset_id : row_dict } for the columns
        in `col_list` of `table`.
        """
        dicts = list(self.make_dicts(table, col_list=col_list))
        if not dicts:
            return {}
        map = {}
        d = dicts[0]
        dataset_col = [col for col in d.keys() if "data_set_name" in col][0]
        for d in dicts:
            map[d[dataset_col].upper()] = d
        return map
            
HERE = os.path.dirname(__file__) or "."

def get_password():
    if not hasattr(get_password, "_password"):
        try:
            get_password._password = open(HERE + "/password").read().strip()
        except:
            get_password._password = getpass.getpass("password: ")
    return get_password._password

def get_dadsops(user="jmiller"):
    """Cache and return a database connection to DADSOPS."""
    if not hasattr(get_dadsops, "_dadsops"):
        get_dadsops._dadsops = DB(DADSOPS_DSN, user, get_password())
    return get_dadsops._dadsops

def get_reffile_ops(user="jmiller"):
    """Cache and return a database connection to REFFILE_OPS."""
    if not hasattr(get_reffile_ops, "_reffile_ops"):
        get_reffile_ops._reffile_ops = DB(REFFILE_OPS_DSN, user, get_password())
    return get_reffile_ops._reffile_ops

def get_instrument_db_parkeys(instrument):
    """Return the union of the database versions of all parkeys for all
    filekinds of instrument.
    """
    dbkeys = set()
    for filekind in parkeys.get_filekinds(instrument):
        dbkeys = dbkeys.union(set(parkeys.get_db_parkeys(instrument, filekind)))
        dbkeys = dbkeys.union(set(parkeys.get_extra_keys(instrument, filekind)))
    return list(dbkeys)

def required_keys(instr):
    """Get both the input parkeys and expected results keywords for
    all filekinds of `instr`ument`.
    """
    pars = get_instrument_db_parkeys(instr)
    pars.append("expstart" if instr != "stis" else "texpstrt")
    pars.append("data_set")
    imap = rmap.get_cached_mapping("hst_%s.imap" % instr)
    pars.extend(imap.selections.keys())
    return pars

def gen_header_tables(datfile="header_tables.dat"):
    """gen_header_tables() generates the mapping: 
    
    { instrument : { best_refs_item : "table.column"  } }
    
    where best_refs_item is nominally the name of a best refs parameter or
    result or other relevant info,  assumed to be a substring of `column`.
    """
    table = {}
    for instr in crds.hst.INSTRUMENTS:
        table[instr] = clean_scan(instr)
    open(datfile, "w+").write(pprint.pformat(table) + "\n")
    return table

def clean_scan(instr):
    """clean_scan() sorts out the map produced by scan_tables(),  mapping each
    parameter of `instr` to a single "table.column" database location.
    Emits a warning for parameters which are not automatically mapped to the
    database.
    """
    columns, remainder = scan_tables(instr)
    if remainder:
        log.warning("For", repr(instr), "can't locate", sorted(list(remainder)))
    else:
        log.info("Collected", repr(instr), "ok")
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

def scan_tables(instr):
    """scan_tables() automatically matches the required parameters for each
    instrument against the available instrument tables and columns in DADSOPS,
    returning a map  { parameter : [ "table.column", ...] } finding plausible
    locations for each CRDS best refs parameter in the dataset catalog.
    """
    dadsops = get_dadsops()
    pars = required_keys(instr)
    columns = {}
    for table in dadsops.get_tables():
        if instr not in table:
            continue
        for par in pars:
            for col in dadsops.get_columns(table):
                if par in col:
                    if par not in columns:
                        columns[par] = []
                    columns[par].append(table + "." + col)
    return columns, set(pars) - set(columns.keys())

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

    def getter_sql(self, extra_constraints={}):
        sql = "SELECT %s FROM %s " % (", ".join(self.db_columns), 
                                      ", ".join(self.db_tables))
        if len(self.db_tables) >= 2:
            sql += "WHERE %s" % self.join_expr(extra_constraints)
        return sql

    def join_expr(self, extra_constraints={}):
        dadsops = get_dadsops()
        all_cols = []
        for table in self.db_tables:
            all_cols += [table + "." + col for col in dadsops.get_columns(table)]
        clauses = []
        for suffix in ["program_id", "obset_id", "obsnum"]:
            joined = []
            for col in all_cols:
                if col.endswith(suffix):
                    joined.append(col)
            if len(joined) >= 2:
                for more in joined[1:]:
                    clauses.append(joined[0] + "=" + more)
        for key in extra_constraints:
            for col in all_cols:
                if key.lower() in col:
                    break
            else:
                raise ValueError("No db column found for constraint " + repr(key))
            clauses.append(col + "=" + repr(extra_constraints[key]))
        return (" and ").join(clauses)

    def get_headers(self, extra_constraints={}, condition=True):
        dadsops = get_dadsops()
        sql = self.getter_sql(extra_constraints)
        for dataset in dadsops.execute(sql):
            if condition:
                hdr = dict(zip(self.header_keys, [utils.condition_value(x) for x in dataset]))
            else:
                hdr = dict(zip(self.header_keys, dataset))
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


def get_dataset_header(dataset, condition=True):
    """Get the header for a particular dataset,  nominally in a context where
    one only cares about a small list of specific datasets.
    """
    if dataset.endswith(".fits"):
        instrument = dataset.get_header(dataset)["INSTRUME"].lower()
    else:
        instrument = dataset_to_instrument(dataset)
    if instrument.lower() not in crds.hst.INSTRUMENTS:
        raise LookupError("Unsupported instrument for dataset lookup " + repr(instrument))
    try:
        igen = HEADER_GENERATORS[instrument]
        if dataset.endswith(".fits"):
            constraints = {"FILE_NAME":dataset.upper()} 
        else:
            constraints = {"DATA_SET":dataset.upper()}
        headers = list(igen.get_headers(constraints, condition))
    except Exception, exc:
        raise RuntimeError("Error accessing DADSOPS for dataset" + repr(dataset) + ":" + str(exc))
    if len(headers) == 1:
        return headers[0]
    elif len(headers) == 0:
        raise LookupError("No header found for " + repr(instrument) + " dataset " + repr(dataset))
    elif len(headers) > 1:
        return headers
        raise LookupError("More than one header found for " + repr(instrument) + " dataset " + repr(dataset))

# =============================================================================
    
FILE_TABLES = {
   "nicmos"  : "nic_file",
}

def get_file_table(instrument):
    return FILE_TABLES.get(instrument, instrument + "_file")

ROW_TABLES = {
   "nicmos"  : "nic_row",
}

def get_row_table(instrument):
    return ROW_TABLES.get(instrument, instrument + "_row")

def _get_reference_info(reference, table_func, kind):
    r = get_reffile_ops()
    db_filename = os.path.basename(reference).upper()
    for instrument in crds.hst.INSTRUMENTS:
        table = table_func(instrument)
        dicts = list(r.make_dicts(table, where="where file_name='%s'" % db_filename))
        if dicts:
            return (instrument, dicts)
    else:
        raise LookupError("Reference file not found in " + kind + " table for any instrument.")

def get_reference_info_rows(reference):
    return _get_reference_info(reference, get_row_table, "row")

def get_reference_info_files(reference):
    return _get_reference_info(reference, get_file_table, "file")


# =================================================================================

if __name__ == "__main__":
    gen_header_tables()
        
