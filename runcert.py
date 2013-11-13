#! /usr/bin/env python

from __future__ import print_function

import sys

from crds.hst import locate
from crds import pysh, log, certify


def main(context, comparison_files, other_params):
    for line in open(comparison_files):
        if not line.strip():
            continue
        words = line.split()
        if len(words) == 5:  # comparison reference exists
            file1, file2 = words[-2:]
            try:
                path1 = locate.locate_server_reference(file1)
                path2 = locate.locate_server_reference(file2)
            except:
                log.error("Failed locating files", repr(file1), "and/or", repr(file2))
                continue            
            cert = certify.CertifyScript(
                "certify.py {} --comparison-context={} "
                "--comparison-reference={} {}".format(" ".join(other_params), context, path1, path2))
        else:  # no comparison reference
            file1, file2 = None, words[-1]
            try:
                path2 = locate.locate_server_reference(file2)
            except:
                log.error("Failed locating", repr(file2))
                continue
            cert = certify.CertifyScript(
                "certify.py {} --comparison-context={} {}".format(" ".join(other_params), context, path2))
        cert()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: runcert <context> <comparison_file_list_file> [<other-certify-options...]")
        sys.exit(-1)
    main(sys.argv[1], sys.argv[2], sys.argv[3:])

"""

"""
