import sys

from crds.client import api
from crds import log, timestamp, utils, rmap

SM4 = timestamp.reformat_date("2009-05-14 00:00:00.000000")

def main(context):   
    headers = api.get_dataset_headers_by_instrument(context, "acs")
    params = rmap.get_cached_mapping(context).get_imap("acs").get_required_parkeys()
    unique = { get_unique_key(header, params) : dataset_id for (dataset_id, header) in headers.items() }
    print "\n".join(sorted(unique.values()))
    
def get_unique_key(header, params):
    header = dict(header)
    EXPSTART = timestamp.reformat_date(header.pop("DATE-OBS") + " " + header.pop("TIME-OBS"))
    key = tuple([(key, utils.condition_value(val)) for (key, val) in header.items() if key in params])
    key = key + (("SM4", EXPSTART <= SM4,),)
    return key

if __name__ == "__main__":
    main(sys.argv[1])
    
