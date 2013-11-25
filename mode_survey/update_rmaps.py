"""This script is used to apply rowkeys updates to the latest version of a paritcular
rmap.
"""
import sys
import os.path

import crds
from crds import log

def load_rowkeys():
    row_keys = {}
    lines = open("row_keys.dat").read().splitlines()
    for i in range(0,len(lines),2):
        rmap = os.path.basename(lines[i].split()[1])
        keytxt = lines[i+1].split(":")[1]
        if keytxt[-1] == ",":
            keytxt = keytxt[:-1]
        keys = eval(keytxt)
        row_keys[rmap] = keys
    return row_keys

def update_rmaps(context, rowkeys):
    p = crds.get_cached_mapping(context)
    for rmap in rowkeys:
        q = crds.get_cached_mapping(rmap)
        r = p.get_imap(q.instrument).get_rmap(q.filekind)
        keys = rowkeys[rmap]
        log.info("Updating rowkeys for", repr(r.name), "to", repr(keys))
        r.header["row_keys"] = keys
        r.write()

def main(context):
    rowkeys = load_rowkeys()
    update_rmaps(context, rowkeys)

if __name__ == "__main__":
    main(sys.argv[1])

