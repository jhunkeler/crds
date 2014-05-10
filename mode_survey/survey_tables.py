"""Utility script to dump table hdu column names and formats for a sample reference
of every table type in a context.
"""
import sys
import re

import pyfits

import crds
from crds import log, pysh, utils

def table_rmaps(context):
    """Survey mapping name `context` for rmaps which control tables as defined by the
    rmap.reffile_format or by a name ending with 'tab.rmap'.
    """
    c = crds.get_cached_mapping(context)
    table_rmaps = [mapping for mapping in c.mapping_names() if mapping.endswith(".rmap") and crds.get_cached_mapping(mapping).reffile_format == "table"]
    keyword_rmaps = [mapping for mapping in c.mapping_names() if re.match(r".*ta?b(_\d\d\d\d)?.rmap", mapping)]
    if set(table_rmaps) - set(keyword_rmaps):
        log.warning("Rmaps with format 'table' and non-tab keyword:", set(table_rmaps) - set(keyword_rmaps))
    if set(keyword_rmaps) - set(table_rmaps):
        log.warning("Rmaps with tab keyword but not format 'table':", set(keyword_rmaps) - set(table_rmaps))
    return table_rmaps

def rmaps_and_examples(table_rmaps):
    """Returns [(rmap_name, example_reference), ...]"""
    return [ (rmap, crds.get_cached_mapping(rmap).reference_names()[0]) for rmap in table_rmaps 
             if crds.get_cached_mapping(rmap).reference_names()]

def main(context):
    rmaps = table_rmaps(context)
    pmap = crds.get_cached_mapping(context)
    log.info("Rmaps with tab-keyword or reffile_format == 'table':", rmaps)
    pairs = rmaps_and_examples(rmaps)
    tables = open("example_tables.txt", "w+")
    for rmap_name, example_reference in pairs:
        with log.error_on_exception("Failed surveying", repr(example_reference)):
            instrument, filekind = utils.get_file_properties(pmap.observatory, example_reference)
            tables.write("{} {} {}\n".format(instrument, filekind, example_reference))
            dump_survey(rmap_name, example_reference)
    tables.close()
    log.standard_status()

def dump_survey(rmap_name, example_reference):
    rmap = crds.get_cached_mapping(rmap_name)
    reference_path = rmap.locate.locate_server_reference(example_reference)
    log.info("="*80)
    log.info("Surveying", repr(rmap_name), "with example reference", repr(reference_path))
    if "row_keys" in rmap.header:
        log.info("rmap:", repr(rmap_name), "rmap.row_keys:", rmap.row_keys)
        if "--dump-all" not in sys.argv:
            return
    else:
        log.warning("rmap:", repr(rmap_name), "rmap.row_keys not found.")

    hdus = pyfits.open(reference_path)
    for i, hdu in enumerate(hdus):
        if not hdu or hdu.data is None:
            continue
        log.info("HDU[%d]" % i, "rmap:", repr(rmap_name), "example_reference:", repr(reference_path))
        log.info("HDU[%d]" % i, "rmap:", repr(rmap_name), "column_names:", hdu.data.names)
        log.info(repr(hdu.data[:10]))
        if i != len(hdus)-1:
            log.info("-"*80)

if __name__ == "__main__":
    main(sys.argv[1])