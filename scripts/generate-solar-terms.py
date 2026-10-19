"""Build offline UTC+8 solar-term dates from HKO's 1901–2100 calendars."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import hashlib
import http.client
import json
from pathlib import Path
import re
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "build/calendar-source-hko"
URL = "https://www.hko.gov.hk/en/gts/time/calendar/text/files/T{year}e.txt"
PATTERN = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})\s+.+?\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(\S.*?)\s*$")

def parse(year, content):
    terms = []
    # Historical headers use Big5 and newer files use UTF-8. The date,
    # weekday and English solar-term columns being parsed are all ASCII.
    for line in content.decode("latin-1").splitlines():
        match = PATTERN.match(line)
        if match:
            y, month, day = map(int, match.group(1, 2, 3))
            if y != year:
                raise ValueError("Unexpected calendar year")
            date(y, month, day)
            terms.append((month, day, match.group(4).strip()))
    if len(terms) != 24 or [row[0] for row in terms] != [month for month in range(1, 13) for _ in range(2)]:
        raise ValueError(f"Incomplete solar terms for {year}: {len(terms)}")
    return terms

def fetch(year):
    target = CACHE / f"T{year}e.txt"
    if target.exists():
        data = target.read_bytes()
    else:
        request = urllib.request.Request(URL.format(year=year), headers={"User-Agent": "Mozilla/5.0"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=25) as response:
                    data = response.read(128 * 1024 + 1)
                break
            except (OSError, http.client.HTTPException):
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)
        if len(data) > 128 * 1024:
            raise ValueError("Unexpected calendar response size")
        parse(year, data)
        target.write_bytes(data)
        time.sleep(.25)
    terms = parse(year, data)
    return year, terms, {"year": year, "url": URL.format(year=year), "sha256": hashlib.sha256(data).hexdigest()}

def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    rows = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for row in pool.map(fetch, range(1901, 2101)):
            rows.append(row)
            if len(rows) % 25 == 0:
                print(f"Validated {len(rows)}/200 annual calendars", flush=True)
    reference = [row[2] for row in next(row[1] for row in rows if row[0] == 2026)]
    if any([term[2] for term in terms] != reference for _, terms, _ in rows):
        raise ValueError("Solar-term ordering or naming differs between source years")
    lines = ["/* Solar-term day-of-month, 1901–2100, HKO Gregorian–lunar tables (UTC+8).",
             " * Source URLs and verified content hashes: assets/solar-terms-sources.json.",
             " * Regenerate with scripts/generate-solar-terms.py. Factual date data. */",
             "static const unsigned char solar_term_days[200][24] = {"]
    lines += ["    {" + ",".join(str(item[1]) for item in terms) + "}, /* " + str(year) + " */" for year, terms, _ in rows]
    lines += ["};", ""]
    (ROOT / "native/solar-terms-data.h").write_text("\n".join(lines), encoding="utf-8")
    record = {"provider": "Hong Kong Observatory", "timezone": "UTC+8", "range": [1901, 2100],
              "index_order": reference, "sources": [item[2] for item in rows]}
    (ROOT / "assets/solar-terms-sources.json").write_text(json.dumps(record, indent=2) + "\n")
    print("Generated 4800 verified offline solar-term dates.", flush=True)

if __name__ == "__main__":
    main()
