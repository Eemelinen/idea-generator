"""Free Finnish/EU open-data clients exposed to research subagents as CLIs.

Each tool prints the exact request URL so a claim can cite it with source_type "api".
"""

# Request-URL prefixes of the APIs these tools call. The tools print the URL to cite, but Bash
# output is not logged to .seen_urls.txt, so the research validator accepts these unseen.
API_URL_PREFIXES: tuple[str, ...] = (
    "https://pxdata.stat.fi/PXWeb/api/",  # StatFin (pxweb.py)
    "https://statdb.luke.fi/PXWeb/api/",  # Luke (pxweb.py)
    "https://avoindata.prh.fi/opendata-ytj-api/",  # PRH / YTJ (prh.py)
    "https://ec.europa.eu/eurostat/api/dissemination/",  # Eurostat JSON-stat (eurostat.py)
)
