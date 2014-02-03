import sys
import pprint
import os.path

from crds.hst import substitutions, tpn
from crds import (rmap, log, timestamp)
from crds.compat import OrderedDict

import crds.hst.parkeys as parkeys

NOW = str(timestamp.now())

OUTDIR = "../CRDS/crds/cache/mappings/hst"  

def generate_pmap(imaps, serial):
    name = "hst" + serial + ".pmap"
    header = OrderedDict([
      ("name", name),
      ("derived_from", "generated " + NOW),
      ("mapping", "PIPELINE"),
      ("observatory" , "HST"),
      ('parkey', ('INSTRUME',)),
    ])

    pmap_path = OUTDIR + "/" + name

    log.info("writing", pmap_path)
    selector = OrderedDict([(instr.upper(), imap) for (instr, imap) in imaps.items()])
    pmap = rmap.Mapping(pmap_path, header, selector)
    pmap.write()
    return name

def generate_imap(instr, rmaps, jmap, serial):
    name = "hst_" + instr + serial + ".imap"
    
    header = OrderedDict([
      ("name", name),
      ("derived_from", "generated " + NOW),
      ("mapping", "INSTRUMENT"),
      ("observatory" , "HST"),
      ("instrument", instr.upper()),
      ('parkey', ('REFTYPE',)),
      # ('metadata', jmap),
      # ("description", ("Initially generated on " + NOW)),
    ])

    rmaps_items = rmaps.items()
    for filekind, rmap_name in rmaps_items:
        if not os.path.exists(OUTDIR+ "/" + rmap_name):
            log.warning("Skipping non-existent", rmap_name)
            del rmaps[filekind]

    imap_path = OUTDIR + "/" + name
    log.info("writing", imap_path)
    imap = rmap.Mapping(imap_path, header, rmaps)
    imap.write()
    return name

def generate_jmap(instr):
    """The .jmap contains infrequently changing metadata which is used to
    associate references with rmaps and update rmaps.
    """
    name = "hst_"  + instr + ".jmap"
    path = "./"+name
    typenames, parkeys, selector = tpn.get_filekind_metadata(instr)
    header = OrderedDict([
      ("name", name),
      ("derived_from", "generated " + NOW),
      ("mapping", "META"),
      ("observatory" , "HST"),
      ("instrument", instr.upper()),
      ('parkey', parkeys),
      ('typenames', typenames),
      ('expansion_rules', substitutions.get_substitutions(instr)),
    ])
    log.info("writing", path)
    jmap = rmap.Mapping(path, header, selector)
    jmap.write()
    return name

def main():
    serial = int(sys.argv[1])
    if serial >= 0:
        serial = "_%04d" % serial
    else:
        serial = ""
    imaps = {}
    for instr in parkeys.get_instruments():
        jmap = generate_jmap(instr)
        rmaps = { filekind:"hst_{}_{}".format(instr, filekind) + serial + ".rmap"
                  for filekind in parkeys.get_filekinds(instr) }
        imaps[instr.upper()] = generate_imap(instr, rmaps, jmap, serial)
    generate_pmap(imaps, serial)
    log.standard_status()

if __name__ == "__main__":
    main()
