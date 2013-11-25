from astropy.io import fits
import difflib

def proto_diff(ta, tb):
    
    ta_string=str(fits.open(ta)[1].data).strip('[]').splitlines()
    tb_string=str(fits.open(tb)[1].data).strip('[]').splitlines()

    sm=difflib.SequenceMatcher()
    sm.set_seqs(ta_string, tb_string)
    print(sm.get_opcodes())

if __name__ == "__main__":
    import sys

    proto_diff(sys.argv[1], sys.argv[2])
