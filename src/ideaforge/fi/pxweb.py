"""Statistics Finland (StatFin) and Luke PxWeb client. Not implemented yet: ticket IF-201.

    python -m ideaforge.fi.pxweb search "<keyword>"
    python -m ideaforge.fi.pxweb get <table_path> --filter Alue=Rääkkylä,Pohjois-Karjala [--json]

Base URLs (wrapped so the newer PxWeb API can be swapped in):
    StatFin: https://pxdata.stat.fi/PXWeb/api/v1/{lang}/StatFin/
    Luke:    https://statdb.luke.fi/PXWeb/api/v1/{lang}/LUKE/

Planned functions: list_tables(path), metadata(table), query(table, filters) -> DataFrame.
Refuses queries over the 100 000-cell limit with a helpful message. 24 h on-disk cache.
"""

import sys

if __name__ == "__main__":
    sys.exit("ideaforge.fi.pxweb is not implemented yet (ticket IF-201)")
