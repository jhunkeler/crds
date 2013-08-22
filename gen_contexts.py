import sys
import pprint
import os.path

from crds.hst import substitutions, tpn
from crds import (rmap, log, timestamp)
from crds.compat import OrderedDict

import crds.hst.parkeys as parkeys

def generate_imap(instr, filekinds, jmap):
    now = str(timestamp.now())
    name = "hst_" + instr + ".imap"
    header = OrderedDict([
      ("name", name),
      ("derived_from", "generated " + now),
      ("mapping", "INSTRUMENT"),
      ("observatory" , "HST"),
      ("instrument", instr.upper()),
      ('parkey', ('REFTYPE',)),
      ('metadata', jmap),
      # ("description", ("Initially generated on " + now)),
    ])

    imap = "../CRDS/hst/mappings/hst/hst_"  + instr + ".imap"
    log.info("writing", imap)
    selector = {}
    for keyword in filekinds:
        eventually_generated_rmap = "hst_" + instr + "_" + keyword + ".rmap"
        if os.path.exists("../CRDS/hst/mappings/hst/" + eventually_generated_rmap):
            selector[keyword] = eventually_generated_rmap
        else:
            log.warning("Skipping non-existent", eventually_generated_rmap)
    imap = rmap.Mapping(imap, header, selector)
    imap.write()

def generate_jmap(instr):
    """The .jmap contains infrequently changing metadata which is used to
    associate references with rmaps and update rmaps.
    """
    now = str(timestamp.now())
    path = "../CRDS/hst/mappings/hst/hst_"  + instr + ".jmap"
    name = os.path.basename(path)
    typenames, parkeys, selector = tpn.get_filekind_metadata(instr)
    header = OrderedDict([
      ("name", name),
      ("derived_from", "generated " + now),
      ("mapping", "META"),
      ("observatory" , "HST"),
      ("instrument", instr.upper()),
      ('parkey', parkeys),
      ('typenames', typenames),
      # ('fi_equivalents', tpn.FILETYPE_TO_SUFFIX[instr]),
      # ('filekind_to_suffix', tpn.FILEKIND_TO_SUFFIX[instr]),
      ('expansion_rules', substitutions.get_substitutions(instr)),
      # ("description", ("Initially generated on " + now)),
    ])
    log.info("writing", path)
    jmap = rmap.Mapping(path, header, selector)
    jmap.write()
    return name

def main():
    for instr in parkeys.get_instruments():
        jmap = generate_jmap(instr)
        generate_imap(instr, parkeys.get_filekinds(instr), jmap)
    log.standard_status()

if __name__ == "__main__":
    main()
