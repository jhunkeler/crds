#! /usr/bin/env pysh
#-*-python-*-

"""This is a script to reduce the output of testall.err into a list
of datasets important enough to download.
"""
from crds.pysh import *

# Datasets: wfc3 biasfile 5 IBWVA2OUQ IBWV02OPQ IBWVA2P0Q IBWVA2P5Q IBWVA2PBQ 

def get_mismatched_objects(filename="testall.err"):
    objects = []
    for line in lines("grep 'Datasets:' ${filename}"):
        words = line.strip().split()
        instrument = words[4]
        filekind = words[5]
        count = int(words[6])
        datasets = words[7:]
        objects.append((count, datasets))
    return objects

def main(filename, important):
    ids = []
    for mismatched in get_mismatched_objects(filename):
        if mismatched[0] >= important:
            ids.extend(mismatched[1])
    for id in ids:
        print id

if __name__ == "__main__":
    usage("<source_file> <test_count_importance_threshhold>", 2, 2);
    main(sys.argv[1], int(sys.argv[2]))
