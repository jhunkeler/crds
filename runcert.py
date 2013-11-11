#! /usr/bin/env python

from __future__ import print_function

import sys

from crds.hst import locate
from crds import pysh, log, certify


def main(comparison_files, other_params):
    for line in open(comparison_files):
        if not line.strip():
            continue
        file1, file2 = line.split()
        with log.error_on_exception("Failed certifying", repr(file1), "and", repr(file2)):
            path1 = locate.locate_server_reference(file1)
            path2 = locate.locate_server_reference(file2)
            cert = certify.CertifyScript("certify.py {} --comparison-context=hst.pmap "
                                         "--comparison-reference={} {}".format(" ".join(other_params), path1, path2))
            cert()

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])

