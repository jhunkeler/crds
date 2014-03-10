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

def remote_bestrefs_output(dataset):
    dataset = dataset.lower()
    lines = pysh.lines("ssh ${DMS_HOST} 'source /home/jmiller/overrides/defs/opus_login.csh; bestref.py -m dball -d ${dataset}'")
    return lines

def opus_bestrefs(dataset):
    lines = remote_bestrefs_output(dataset)
    bestrefs = {}
    for line in lines:
        words = line.split()
        db_colname = words[0]
        if db_colname.endswith(("file","tab")):
            keyword = db_colname.split("_")[2].upper()
            value = words[2].split("'")[1]
            bestrefs[keyword] = value
        if "FATAL" in line or "ERROR" in line:
            raise RuntimeError("FATAL or ERROR in output: " + str(lines))
    return bestrefs

def load_alternate_dataset_headers():
    try:
        log.info("Loading improved opus dataset headers", BESTREF_PKL)
        alternate_headers = cPickle.load(open(BESTREF_PKL))
    except:
        alternate_headers = {}
        log.warning("Loading opus headers failed.")
    else:
        items = alternate_headers.items()
        for dataset, header in items:
            if isinstance(header, str):
                log.warning("No update for", repr(dataset), ":", header)
                del alternate_headers[dataset]
        log.info("Loaded", BESTREF_PKL)
    return alternate_headers

def save_alternate_dataset_headers(alternates):
    log.info("Saving improved opus dataset headers", BESTREF_PKL)
    with open(BESTREF_PKL, "w+") as f:
        cPickle.dump(alternates, f)
    log.info("Saved", BESTREF_PKL)
    

def main():
    alternates = load_alternate_dataset_headers()

    if sys.argv[1].startswith("@"):
        datasets = open(sys.argv[1][1:]).read().splitlines()
    else:
        datasets = sys.argv[1:]

    for dataset in datasets:
        dataset = dataset.strip()
        try:
            bestrefs = opus_bestrefs(dataset)
            alternates[dataset] = bestrefs
            log.info("Bestrefs for", dataset, ":", " ".join(["=".join([key, repr(value)]) for (key, value) in sorted(bestrefs.items())]))
        except Exception, exc:
            log.error("Exception on dataset", dataset, ":", str(exc))
            alternates[dataset] = "NOT FOUND " + str(exc)
    save_alternate_dataset_headers(alternates)
    log.standard_status()

if __name__ == "__main__":
    main()
