"""This module differences two CRDS reference or mapping files on the local
system.   It supports specification of the files using only the basenames or
a full path.   Currently it operates on mapping, FITS, or text files.
"""

from __future__ import print_function
from __future__ import division
from __future__ import absolute_import

from crds import python23

import os
import sys
import re
from collections import defaultdict

import crds
from crds import rmap, log, pysh, cmdline, utils, rowdiff, config, sync

from astropy.io.fits import FITSDiff

# ============================================================================
        
def mapping_diffs(old_file, new_file, include_header_diffs=False, recurse_added_deleted=False):
    """Return the logical differences between CRDS mappings named `old_file` 
    and `new_file`.
    
    IFF include_header_diffs,  include differences in mapping headers.   Some are "boring", e.g. sha1sum or name.
    
    IFF recurse_added_deleted,  include difference tuples for all nested adds and deletes whenever a higher level
        mapping is added or deleted.   Else, only include the higher level mapping,  not contained files.
        
    """
    assert rmap.is_mapping(old_file), \
        "File " + repr(old_file) + " is not a CRDS mapping."
    assert rmap.is_mapping(new_file), \
        "File " + repr(new_file) + " is not a CRDS mapping."
    assert os.path.splitext(old_file)[-1] == os.path.splitext(new_file)[-1], \
        "Files " + repr(old_file) + " and " + repr(new_file) + \
        " are not the same kind of CRDS mapping:  .pmap, .imap, .rmap"
    old_map = rmap.fetch_mapping(old_file, ignore_checksum=True)
    new_map = rmap.fetch_mapping(new_file, ignore_checksum=True)
    differences = old_map.difference(new_map, include_header_diffs=include_header_diffs,
                                     recurse_added_deleted=recurse_added_deleted)
    return differences

def mapping_difference(observatory, old_file, new_file, primitive_diffs=False, check_diffs=False,
                       mapping_text_diffs=False, include_header_diffs=True, hide_boring_diffs=False,
                       recurse_added_deleted=False):
    """Print the logical differences between CRDS mappings named `old_file` 
    and `new_file`.  
    
    IFF primitive_differences,  recursively difference any replaced files found
    in the top level logical differences.
    
    IFF check_diffs, issue warnings about critical differences.   See
    mapping_check_diffs().
    """
    differences = mapping_diffs(old_file, new_file, include_header_diffs=include_header_diffs, 
        recurse_added_deleted=recurse_added_deleted)
    if mapping_text_diffs:   # only banner when there's two kinds to differentiate
        log.write("="*20, "logical differences",  repr(old_file), "vs.", repr(new_file), "="*20)
    if hide_boring_diffs:
        differences = remove_boring(differences)
    for diff in sorted(differences):
        diff = unquote_diff(diff)
        if primitive_diffs:
            log.write("="*80)
        log.write(diff)
        if primitive_diffs and "header" not in diff_action(diff):
            # XXXX fragile, coordinate with selector.py and rmap.py
            if "replaced" in diff[-1]:
                old, new = diff_replace_old_new(diff)
                difference(observatory, old, new, primitive_diffs=primitive_diffs, 
                           recurse_added_deleted=recurse_added_deleted)
    if mapping_text_diffs:
        pairs = sorted(set(mapping_pairs(differences) +  [(old_file, new_file)]))
        for (old, new) in pairs:
            log.write("="*20, "text difference", repr(old), "vs.", repr(new), "="*20)
            text_difference(observatory, old, new)
        log.write("="*80)
    if check_diffs:
        mapping_check_diffs_core(differences)
    return 1 if differences else 0

def mapping_pairs(differences):
    """Return the sorted list of all mapping tuples found in differences."""
    pairs = set()
    for diff in differences:
        for pair in diff:
            if len(pair) == 2 and rmap.is_mapping(pair[0]):
                pairs.add(pair)
    return sorted(pairs)
        
def unquote_diff(diff):
    """Remove repr str quoting in `diff` tuple,  don't change header diffs."""
    return diff[:-1] + (diff[-1].replace("'",""),) if "header" not in diff[-1] else diff

def unquote(name):
    """Remove string quotes from simple `name` repr."""
    return name.replace("'","").replace('"','')

# XXXX fragile,  coordinate with selector.py and rmap.py
def diff_replace_old_new(diff):
    """Return the (old, new) filenames from difference tuple `diff`."""
    _replaced, old, _with, new = diff[-1].split()
    return unquote(old), unquote(new)

# XXXX fragile,  coordinate with selector.py and rmap.py
def diff_added_new(diff):
    """Return the (old, new) filenames from difference tuple `diff`."""
    new = diff[-1].split()[-1]
    return unquote(new)
    
# XXXX fragile,  coordinate with selector.py and rmap.py
def diff_action(diff):
    """Return 'add', 'replace', or 'delete' based on action represented by
    difference tuple `d`.   Append "_rule" if the change is a Selector.
    """
    if "replace" in diff[-1]:
        result = "replace"
    elif "add" in diff[-1]:
        result = "add"
    elif "delete" in diff[-1]:
        result = "delete"
    elif "different classes" in diff[-1]:
        result = "class_difference"
    elif "different parameter" in diff[-1]:
        result = "parkey_difference"
    else:
        raise ValueError("Bad difference action: "  + repr(diff))
    if "rule" in diff[-1]:
        result += "_rule"
    elif "header" in diff[-1]:
        result += "_header"
    return result
# ============================================================================

def mapping_affected_modes(old_file, new_file, include_header_diffs=True):
    """Return a sorted set of flat tuples describing the matching parameters affected by the differences 
    between old_file and new_file.
    """
    affected = defaultdict(int)
    differences = mapping_diffs(old_file, new_file, include_header_diffs=include_header_diffs)
    for diff in differences:
        mode = affected_mode(diff)
        if mode is not None:
            affected[mode] += 1
    return [ tup + (("DIFF_COUNT", str(affected[tup])),) for tup in sorted(affected) ]
    
DEFAULT_EXCLUDED_PARAMETERS = ("DATE-OBS", "TIME-OBS", "META.OBSERVATION.DATE", 
                               "META_OBSERVATION_DATE", "DIFFERENCE", "INSTRUME", "REFTYPE")
BORING_VARS = ["NAME", "DERIVED_FROM", "SHA1SUM", "ROW_KEYS"]  # XXX ROW_KEYS obsolete

def affected_mode(diff, excluded_parameters=DEFAULT_EXCLUDED_PARAMETERS):
    """Return a list of parameter items which characterize the effect of a difference in 
    terms of instrument, type, and instrument mode.
    """
    instrument = filekind = None
    affected = []
    flat = diff.flat
    for (i, val) in enumerate(flat):
        var = flat.parameter_names[i]
        if var == "PipelineContext":
            pass
        elif var == "InstrumentContext":
            instrument = diff.instrument
        elif var == "ReferenceMapping":
            instrument = diff.instrument
            filekind = diff.filekind
        elif var not in excluded_parameters:
            affected.append((var, val))
        elif var == "DIFFERENCE" and "header" in val:
            for boring in BORING_VARS:
                if "REPLACED " + repr(boring) in val.upper():
                    break
            else:
                affected.append((var, val))
    if not affected:
        return None
    if filekind:
        affected = [("REFTYPE", filekind.upper())] + affected
    if instrument:
        affected = [("INSTRUMENT", instrument.upper())] + affected
    return tuple(affected)

def format_affected_mode(mode):
    """Format an affected mode as a string."""
    return " ".join(["=".join([item[0], repr(item[1])]) for item in mode])

def remove_boring(diffs):
    """Remove routine differences from a list of diff tuples."""
    result = diffs[:]
    for diff in diffs:
        for var in BORING_VARS:
            if var.lower() in diff[-1]:
                result.remove(diff)
    return result

def get_affected(old_pmap, new_pmap, include_header_diffs=True, observatory=None):
    """Examine the diffs between `old_pmap` and `new_pmap` and return sorted lists of affected instruments and types.
    
    Returns { affected_instrument : { affected_type, ... } }
    """
    instrs = defaultdict(set)
    diffs = mapping_diffs(old_pmap, new_pmap, include_header_diffs=include_header_diffs)
    diffs = remove_boring(diffs)
    if observatory is None:
        observatory = rmap.get_cached_mapping(old_pmap).observatory
    for diff in diffs:
        for step in diff:
            if len(step) == 2 and rmap.is_mapping(step[0]):
                instrument, filekind = utils.get_file_properties(observatory, step[0])
                if instrument.strip() and filekind.strip():
                    if filekind not in instrs[instrument]:
                        log.verbose("Affected", (instrument, filekind), "based on diff", diff, verbosity=20)
                        instrs[instrument].add(filekind)
    return { key:list(val) for (key, val) in instrs.items() }

# ============================================================================

def mapping_check_diffs(mapping, derived_from):
    """Issue warnings for *deletions* in self relative to parent derived_from
    mapping.  Issue warnings for *reversions*,  defined as replacements which
    where the replacement is older than the original,  as defined by the names.   
    
    This is intended to check for missing modes and for inadvertent reversions
    to earlier versions of files.   For speed and simplicity,  file time order
    is currently determined by the names themselves,  not file contents, file
    system,  or database info.
    """
    mapping = rmap.asmapping(mapping, cached="readonly")
    derived_from = rmap.asmapping(derived_from, cached="readonly")
    log.info("Checking diffs from", repr(derived_from.basename), "to", repr(mapping.basename))
    diffs = derived_from.difference(mapping)
    mapping_check_diffs_core(diffs)

def mapping_check_diffs_core(diffs):
    """Perform the core difference checks on difference tuples `diffs`."""
    categorized = sorted([ (diff_action(d), d) for d in diffs ])
    for action, msg in categorized:
        if "header" in action:
            log.verbose("In", _diff_tail(msg)[:-1], msg[-1])
        elif action == "add":
            log.verbose("In", _diff_tail(msg)[:-1], msg[-1])
        elif "rule" in action:
            log.warning("Rule change at", _diff_tail(msg)[:-1], msg[-1])
        elif action == "replace":
            old_val, new_val = list(map(os.path.basename, diff_replace_old_new(msg)))
            if newer(new_val, old_val):
                log.verbose("In", _diff_tail(msg)[:-1], msg[-1])
            else:
                log.warning("Reversion at", _diff_tail(msg)[:-1], msg[-1])
        elif action == "delete":
            log.warning("Deletion at", _diff_tail(msg)[:-1], msg[-1])
        elif action == "parkey_difference":
            log.warning("Different lookup parameters", _diff_tail(msg)[:-1], msg[-1])
        elif action == "class_difference":
            log.warning("Different classes at", _diff_tail(msg)[:-1], msg[-1])
        else:
            raise ValueError("Unexpected difference action:", action)

def _diff_tail(msg):
    """`msg` is an arbitrary length difference "path",  which could
    be coming from any part of the mapping hierarchy and ending in any kind of 
    selector tree.   The last item is always the change message: add, replace, 
    delete <blah>.  The next to last should always be a selector key of some kind.  
    Back up from there to find the first mapping tuple.
    """
    tail = []
    for part in msg[::-1]:
        if isinstance(part, tuple) and len(part) == 2 and isinstance(part[0], str) and part[0].endswith("map"):
            tail.append(part[1])
            break
        else:
            tail.append(part)
    return tuple(reversed(tail))

# =============================================================================================================

def newstyle_name(name):
    """Return True IFF `name` is a CRDS-style name, e.g. hst_acs.imap
    
    >>> newstyle_name("s7g1700gl_dead.fits")
    False
    >>> newstyle_name("hst.pmap")
    True
    >>> newstyle_name("hst_acs_darkfile_0001.fits")
    True
    """
    return name.startswith(tuple(crds.ALL_OBSERVATORIES))

def newer(name1, name2):
    """Determine if `name1` is a more recent file than `name2` accounting for 
    limited differences in naming conventions. Official CDBS and CRDS names are 
    comparable using a simple text comparison,  just not to each other.
    
    >>> newer("s7g1700gl_dead.fits", "hst_cos_deadtab_0001.fits")
    False
    >>> newer("hst_cos_deadtab_0001.fits", "s7g1700gl_dead.fits")
    True
    >>> newer("s7g1700gl_dead.fits", "bbbbb.fits")
    True
    >>> newer("bbbbb.fits", "s7g1700gl_dead.fits")
    False
    >>> newer("hst_cos_deadtab_0001.rmap", "hst_cos_deadtab_0002.rmap")
    False
    >>> newer("hst_cos_deadtab_0002.rmap", "hst_cos_deadtab_0001.rmap")
    True
    >>> newer("hst_cos_deadtab_0001.asdf", "hst_cos_deadtab_0050.fits")
    True
    >>> newer("hst_cos_deadtab_0051.fits", "hst_cos_deadtab_0050.asdf")
    False
    >>> newer("hst_cos_deadtab_0001.fits", "hst_cos_deadtab_99991.fits")
    False
    >>> newer("hst_cos_deadtab_99991.fits", "hst_cos_deadtab_0001.fits")
    True
    """
    if newstyle_name(name1):
        if newstyle_name(name2): # compare CRDS names
            if extension_rank(name1) == extension_rank(name2):
                serial1, serial2 = newstyle_serial(name1), newstyle_serial(name2)
                result = serial1 > serial2   # same extension compares by counter
            else:  
                result = extension_rank(name1) > extension_rank(name2)
        else:  # CRDS > CDBS
            result = True
    else:
        if newstyle_name(name2):  # CDBS < CRDS
            result = False
        else:  # compare CDBS names
            result = name1 > name2
    log.verbose("Comparing filename time order:", repr(name1), ">", repr(name2), "-->", result)
    return result

def extension_rank(filename):
    """Return a date ranking for `filename` based on extension, lowest numbers are oldest.
    
    >>> extension_rank("fooo.r0h")
    0.0
    >>> extension_rank("fooo.fits")
    1.0
    >>> extension_rank("fooo.json")
    2.0
    >>> extension_rank("fooo.yaml")
    3.0
    >>> extension_rank("/some/path/fooo.asdf")
    4.0
    """
    ext = os.path.splitext(filename)[-1]
    if re.match(r"\.r\dh", ext) or re.match(r"\.r\dd", ext):
        return 0.0
    elif ext == ".fits":
        return 1.0
    elif ext == ".json":
        return 2.0
    elif ext == ".yaml":
        return 3.0
    elif ext == ".asdf":
        return 4.0
    else:
        return 5.0

def newstyle_serial(name):
    """Return the serial number associated with a CRDS-style name.

    >>> newstyle_serial("hst_0042.pmap")
    42
    >>> newstyle_serial("hst_0990999.pmap")    
    990999
    >>> newstyle_serial("hst_cos_0999.imap")
    999
    >>> newstyle_serial("hst_cos_darkfile_0998.fits")
    998
    >>> newstyle_serial("hst.pmap")
    0
    """
    assert isinstance(name, python23.string_types)
    serial_search = re.search(r"_(\d+)\.\w+", name)
    if serial_search:
        return int(serial_search.groups()[0], 10)
    else:
        return 0

# ============================================================================


def fits_difference(observatory, old_file, new_file):
    """Run fitsdiff on files named `old_file` and `new_file`.

    Returns:

    0 no differences
    1 some differences
    """
    assert old_file.endswith(".fits"), \
        "File " + repr(old_file) + " is not a FITS file."
    assert new_file.endswith(".fits"), \
        "File " + repr(new_file) + " is not a FITS file."
    loc_old_file = rmap.locate_file(old_file, observatory)
    loc_new_file = rmap.locate_file(new_file, observatory)

    # Do the standard diff.
    fdiff = FITSDiff(loc_old_file, loc_new_file)

    # Do the diff by rows.
    rdiff = rowdiff.RowDiff(loc_old_file, loc_new_file)

    if not fdiff.identical:
        fdiff.report(fileobj=sys.stdout)
        print('\n', rdiff)

    return 0 if fdiff.identical else 1

def text_difference(observatory, old_file, new_file):
    """Run UNIX diff on two text files named `old_file` and `new_file`.
    
    Returns:
      0 no differences
      1 some differences
      2 errors
    """
    assert os.path.splitext(old_file)[-1] == os.path.splitext(new_file)[-1], \
        "Files " + repr(old_file) + " and " + repr(new_file) + " are of different types."
    _loc_old_file = config.check_path(rmap.locate_file(old_file, observatory))
    _loc_new_file = config.check_path(rmap.locate_file(new_file, observatory))
    return pysh.sh("diff -b -c ${_loc_old_file} ${_loc_new_file}", raise_on_error=False)   # secure

def difference(observatory, old_file, new_file, primitive_diffs=False, check_diffs=False, mapping_text_diffs=False,
               include_header_diffs=False, hide_boring_diffs=False, recurse_added_deleted=False):
    """Difference different kinds of CRDS files (mappings, FITS references, etc.)
    named `old_file` and `new_file` against one another and print out the results 
    on stdout.

    Returns:

    0 no differences
    1 some differences
    2 errors in subshells

    """
    filetype = config.filetype(old_file)
    if filetype == "mapping":
        status = mapping_difference(
            observatory, old_file, new_file, primitive_diffs=primitive_diffs, check_diffs=check_diffs,
            mapping_text_diffs=mapping_text_diffs, include_header_diffs=include_header_diffs,
            hide_boring_diffs=hide_boring_diffs, recurse_added_deleted=recurse_added_deleted)
    elif filetype == "fits":
        status = fits_difference(observatory, old_file, new_file)
    elif filetype in ["yaml", "json", "text"]:
        status = text_difference(observatory, old_file, new_file)
    else:
        log.warning("Cannot difference file of type", repr(filetype), ":", repr(old_file), repr(new_file))
        status = 2   #  arguably, this should be an error not a warning.  wary of changing now.
    return status
        
def get_added_references(old_pmap, new_pmap, cached=True):
    """Return the list of references from `new_pmap` which were not in `old_pmap`."""
    old_pmap = rmap.asmapping(old_pmap, cached=cached)
    new_pmap = rmap.asmapping(new_pmap, cached=cached)
    return sorted(list(set(new_pmap.reference_names()) - set(old_pmap.reference_names())))

def get_deleted_references(old_pmap, new_pmap, cached=True):
    """Return the list of references from `new_pmap` which were not in `old_pmap`."""
    old_pmap = rmap.asmapping(old_pmap, cached=cached)
    new_pmap = rmap.asmapping(new_pmap, cached=cached)
    return sorted(list(set(old_pmap.reference_names()) - set(new_pmap.reference_names())))

def get_updated_files(context1, context2):
    """Return the sorted list of files names which are in `context2` (or any intermediate context)
    but not in `context1`.   context2 > context1.
    """
    extension1 = os.path.splitext(context1)[1]
    extension2 = os.path.splitext(context2)[1]
    assert extension1 == extension2, "Only compare mappings of same type/extension."
    old_map = rmap.get_cached_mapping(context1)
    old_files = set(old_map.mapping_names() + old_map.reference_names())
    all_mappings = rmap.list_mappings("*"+extension1, old_map.observatory)
    updated = set()
    context1, context2 = os.path.basename(context1), os.path.basename(context2)
    for new in all_mappings:
        new = os.path.basename(new)
        if context1 < new <= context2:
            new_map = rmap.get_cached_mapping(new)
            updated |= set(new_map.mapping_names() + new_map.reference_names())
    return sorted(list(updated - old_files))

# ==============================================================================================================
    
class DiffScript(cmdline.Script):
    """Python command line script to difference mappings or references."""
    
    description = """Difference CRDS mapping or reference files."""
    
    epilog = """Reference files are nominally differenced using FITS-diff or diff.
    
Mapping files are differenced using CRDS machinery to recursively compare too mappings and 
their sub-mappings.
    
Differencing two mappings will find all the logical differences between the two contexts
and any nested mappings.
    
By specifying --mapping-text-diffs,  UNIX diff will be run on mapping files in addition to 
CRDS logical diffs.   (Duplicate/overlapping cases can be collapsed by the default mapping loader
and hence missed in logical differences,  but are revealed by text differences.   crds.certify 
can also detect duplicate entries,  but at the cost of mapping load speed.)
    
By specifying --primitive-diffs,  FITS diff will be run on all references which are replaced
in the logical differences between two mappings.
    
For example:
    
    % python -m crds.diff hst_0001.pmap  hst_0005.pmap  --mapping-text-diffs --primitive-diffs
    
Will recursively produce logical, textual, and FITS diffs for all changes between the two contexts.
    
    NOTE: mapping logical differences (the default) do not compare CRDS mapping headers,  use
    --include-header-diffs to get those as well.

    NOTE: mapping logical differences do not normally include nested files which are implicitly
    added or deleted by a hgher level mapping change.  See --recurse-added-deleted to include those.

    NOTE: crds.diff has "non-standard" exit status similar to UNIX diff:
         0 no differences
         1 some differences
         2 errors or warnings
    """
    
    def add_args(self):
        """Add diff-specific command line parameters."""
        self.add_argument("old_file",  help="Prior file of difference.""")
        self.add_argument("new_file",  help="New file of difference.""")
        self.add_argument("-P", "--primitive-diffs", dest="primitive_diffs",
            help="Fitsdiff replaced reference files when diffing mappings.", 
            action="store_true")
        self.add_argument("-T", "--mapping-text-diffs",  dest="mapping_text_diffs", action="store_true",
            help="In addition to CRDS mapping logical differences,  run UNIX context diff for mappings.")
        self.add_argument("-U", "--recurse-added-deleted",  dest="recurse_added_deleted", action="store_true",
            help="When a mapping is added or deleted, include all nested files as also added or deleted.  Else only top mapping change listed.")
        self.add_argument("-K", "--check-diffs", dest="check_diffs", action="store_true",
            help="Issue warnings about new rules, deletions, or reversions.")
        self.add_argument("-N", "--print-new-files", dest="print_new_files", action="store_true",
            help="Rather than printing diffs for mappings,  print the names of new or replacement files.  Excludes intermediaries.")
        self.add_argument("-A", "--print-all-new-files", dest="print_all_new_files", action="store_true",
            help="Print the names of every new or replacement file in diffs between old and new.  Includes intermediaries.")
        self.add_argument("-i", "--include-header-diffs", dest="include_header_diffs", action="store_true",
            help="Include mapping header differences in logical diffs: sha1sum, derived_from, etc.")
        self.add_argument("-B", "--hide-boring-diffs", dest="hide_boring_diffs", action="store_true",
            help="Include mapping header differences in logical diffs: sha1sum, derived_from, etc.")
        self.add_argument("--print-affected-instruments", dest="print_affected_instruments", action="store_true",
            help="Print out the names of instruments which appear in diffs,  rather than diffs.")
        self.add_argument("--print-affected-types", dest="print_affected_types", action="store_true",
            help="Print out the names of instruments and types which appear in diffs,  rather than diffs.")
        self.add_argument("--print-affected-modes", dest="print_affected_modes", action="store_true",
            help="Print out the names of instruments, types, and matching parameters,  rather than diffs.")
        self.add_argument("--sync-files", dest="sync_files", action="store_true",
            help="Fetch any missing files needed for the requested difference from the CRDS server.")

    # locate_file = cmdline.Script.locate_file_outside_cache

    def main(self):
        """Perform the differencing."""
        self.args.files = [ self.args.old_file, self.args.new_file ]   # for defining self.observatory
        self.old_file = self.resolve_context(self.locate_file(self.args.old_file))
        self.new_file = self.resolve_context(self.locate_file(self.args.new_file))
        if self.args.sync_files:
            if self.args.print_all_new_files:
                serial_old = newstyle_serial(self.old_file)
                serial_new = newstyle_serial(self.new_file) + 1
                if None not in [serial_old, serial_new]:
                    errs = sync.SyncScript("crds.sync --range {0}:{1}".format(serial_old, serial_new))()
                    assert not errs, "Errors occurred while syncing all rules to CRDS cache."
                else:
                    log.warning("Cannot sync non-standard mapping names,  results may be incomplete.")
            else:
                self.sync_files([self.old_file, self.new_file])
        elif self.args.print_all_new_files:
            log.warning("--print-all-new-files requires a complete set of rules.  suggest --sync-files.")
            
        # self.args.files = [ self.old_file, self.new_file ]   # for defining self.observatory

        if self.args.print_new_files:
            status = self.print_new_files()
        elif self.args.print_all_new_files:
            status = self.print_all_new_files()
        elif self.args.print_affected_instruments:
            status = self.print_affected_instruments()
        elif self.args.print_affected_types:
            status = self.print_affected_types()
        elif self.args.print_affected_modes:
            status = self.print_affected_modes()
        else:
            status = difference(self.observatory, self.old_file, self.new_file, 
                                primitive_diffs=self.args.primitive_diffs, check_diffs=self.args.check_diffs,
                                mapping_text_diffs=self.args.mapping_text_diffs,
                                include_header_diffs=self.args.include_header_diffs,
                                hide_boring_diffs=self.args.hide_boring_diffs,
                                recurse_added_deleted=self.args.recurse_added_deleted)
        if log.errors() or log.warnings():
            return 2
        else:
            return status
    
    def print_new_files(self):
        """Print the references or mappings which are in the second (new) context and not
        the firtst (old) context.
        """
        if not rmap.is_mapping(self.old_file) or not rmap.is_mapping(self.new_file):
            log.error("--print-new-files really only works for mapping differences.")
            return -1
        old = rmap.get_cached_mapping(self.old_file)
        new = rmap.get_cached_mapping(self.new_file)
        old_mappings = set(old.mapping_names())
        new_mappings = set(new.mapping_names())
        old_references = set(old.reference_names())
        new_references = set(new.reference_names())
        status = 0
        for name in sorted(new_mappings - old_mappings):
            print(name)
            status = 1
        for name in sorted(new_references - old_references):
            print(name)
            status = 1
        return status

    def print_all_new_files(self):
        """Print the names of all files which are in `new_file` (or any intermediary context) but not
        in `old_file`.   new_file > old_file.  Both new_file and old_file are similar mappings.
        """
        updated = get_updated_files(self.old_file, self.new_file)
        for mapping in updated:
            if rmap.is_mapping(mapping):
                print(mapping, self.instrument_filekind(mapping))
        for reference in updated:
            if not rmap.is_mapping(reference):
                print(reference, self.instrument_filekind(reference))
        return 1 if updated else 0

    def instrument_filekind(self, filename):
        """Return the instrument and filekind of `filename` as a space separated string."""
        instrument, filekind = utils.get_file_properties(self.observatory, filename)
        return instrument + " " + filekind 

    def print_affected_instruments(self):
        """Print the instruments affected in a switch from `old_pmap` to `new_pmap`."""
        instrs = get_affected(self.old_file, self.new_file, self.args.include_header_diffs, self.observatory)
        for instrument in sorted(instrs):
            print(instrument)
        return 1 if instrs else 0

    def print_affected_types(self):
        """Print the (instrument, filekind) pairs affected in a switch from `old_pmap` to `new_pmap`."""
        instrs = get_affected(self.old_file, self.new_file, self.args.include_header_diffs, self.observatory)
        status = 0
        for instrument in sorted(instrs):
            for filekind in sorted(instrs[instrument]):
                if filekind.strip():
                    print("%-10s %-10s" % (instrument, filekind))
                    status = 1
        return status
                    
    def print_affected_modes(self):
        """Print out all the affected mode tuples associated with the differences.""" 
        assert rmap.is_mapping(self.old_file) and rmap.is_mapping(self.new_file), \
            "for --print-affected-modes both files must be mappings."
        modes = mapping_affected_modes(self.old_file, self.new_file, self.args.include_header_diffs)
        for affected in modes:
            print(format_affected_mode(affected))
        return 1 if modes else 0

def test():
    import doctest
    from crds import diff
    return doctest.testmod(diff)

if __name__ == "__main__":
    sys.exit(DiffScript()())