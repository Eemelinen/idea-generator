"""Eurostat JSON-stat client. Not implemented yet: ticket IF-203.

    python -m ideaforge.fi.eurostat get <dataset> --geo FI [--json]

Endpoint: https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/<dataset>
Planned function: get(dataset, filters). 24 h on-disk cache.
"""

import sys

if __name__ == "__main__":
    sys.exit("ideaforge.fi.eurostat is not implemented yet (ticket IF-203)")
