"""PRH open data (YTJ) company search. Not implemented yet: ticket IF-202.

    python -m ideaforge.fi.prh search --name "<text>"
    python -m ideaforge.fi.prh search --industry <TOL> --municipality Rääkkylä [--json]

Endpoint: https://avoindata.prh.fi/opendata-ytj-api/v3/companies
Returns count + rows (name, business id, registration date, status).
Limitations: no sole traders (toiminimi) and no contact details in the open data.
24 h on-disk cache.
"""

import sys

if __name__ == "__main__":
    sys.exit("ideaforge.fi.prh is not implemented yet (ticket IF-202)")
