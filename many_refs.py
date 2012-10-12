"""This script gets the best references as determined by the same code which
runs in OPUS,  which under some circumstances might have different answers
than the catalog.
"""
import sys
import pprint
import cPickle

from crds import pysh, log

DMS_HOST = "dmsdevvm4.stsci.edu"

BESTREF_PKL = "../datasets/opus_bestref.pkl"

def remote_bestrefs_output(datasets_file):
    datasets = open(datasets_file).read().split()
    open("many_refs.in","w+").write("\n".join(datasets)+"\n")
    pysh.sh("scp many_refs.in ${DMS_HOST}:many_refs.in", raise_on_error=True)
    lines = pysh.lines("ssh ${DMS_HOST} bestref.py -mdball -d'\\!many_refs.in'")
    open("many_refs.out", "w+").write(''.join(lines))
    return lines

def opus_bestrefs(datasets_file):
    lines = remote_bestrefs_output(datasets_file)
    return lines_to_dict(lines)

"""
CRDS        : WARNING  skipping: #0 'CRDS        : INFO     Loading opus dataset headers ../datasets/opus_bestref.pkl'
CRDS        : WARNING  skipping: #1 '2012286151108-I-INFO-Running command-line mode.'
CRDS        : WARNING  skipping: #2 '2012286151112-I-INFO-XTRACTAB value changed: U8K1433NL_1DX.FITS => N/A'
CRDS        : WARNING  skipping: #90 ''
"""

EXEMPTIONS = [ "value changed", "opus dataset headers", "command-line mode" ]

def lines_to_dict(lines):
    state = "searching"
    results = {}
    for no, line in enumerate(lines):
        line = line.strip()
        words = line.split()
        if state == "searching" and line.startswith("UPDATE"):
            state = "in_bestrefs"
            newrefs = {}
            continue
        if state == "in_bestrefs":
            if line.startswith("WHERE"):
                state = "searching"
                assert words[2] == "="
                id = words[3].split("'")[1]
                results[id] = newrefs
            else:
                filekind = words[0].upper().split("_")[2]
                assert words[1] == "="
                bestref = words[2].split("'")[1]
                newrefs[filekind] = bestref
            continue
        for pattern in EXEMPTIONS:
            if not line or pattern in line:
                break
        else:
            log.warning("skipping: #" + str(no), repr(line))
    return results

def load_alternate_dataset_headers():
    try:
        alternate_headers = cPickle.load(open(BESTREF_PKL))
        log.info("Loading opus dataset headers", BESTREF_PKL)
    except:
        alternate_headers = {}
        log.warning("Loading opus headers failed.")
    return alternate_headers

def main():
    alternates = load_alternate_dataset_headers()
    datasets_file = sys.argv[1]
    bestrefs = opus_bestrefs(datasets_file)
    print bestrefs
    sys.exit(-1)
    
    try:
        alternates[dataset] = bestrefs
        log.info("Bestrefs for", dataset, "=", bestrefs)
    except Exception, exc:
        log.error("Exception on dataset", dataset)
    with open(BESTREF_PKL, "w+") as f:
        cPickle.dump(alternates, f)
    log.standard_status()

if __name__ == "__main__":
    main()
