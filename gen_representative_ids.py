from __future__ import print_function

import sys
from collections import defaultdict

from crds.client import api
from crds import log, timestamp, utils, rmap

SM4 = timestamp.reformat_date("2009-05-14 00:00:00.000000")

def main(context): 
    """Determine ids for unique cases,  discriminating between pre and post SM4 but otherwise
    removing DATE-OBS and TIME-OBS.   Keeping both pre and post SM4 cases exposes different
    special case matching hook branches.   Matching parameters still determined independently
    by CDBS OPUS pipeline bestrefs (CDBS) and DADSOPS (CRDS).
    """
    pmap = rmap.get_cached_mapping(context)
    unique = defaultdict(list)
    for instr in pmap.selections:
        headers = api.get_dataset_headers_by_instrument(context, instr)
        params = pmap.get_imap(instr).get_required_parkeys()
        for (dataset_id, header) in headers.items():
            unique[get_unique_key(header, params)].append(dataset_id)
    for key, val in unique.items():
        print(val[-1])
        log.info(val[-1], len(val))
    log.standard_status()
    
def get_unique_key(header, params):
    header = dict(header)
    expstart = timestamp.reformat_date(header.pop("DATE-OBS") + " " + header.pop("TIME-OBS"))
    key = tuple([(key, utils.condition_value(val)) for (key, val) in header.items() if key in params])
    key = key + (("SM4", expstart  <= SM4,),)
    return key

if __name__ == "__main__":
    main(sys.argv[1])
    
