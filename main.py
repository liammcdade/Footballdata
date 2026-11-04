import os
import re
import time
import json
import argparse
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, date

BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"

LEAGUES = {
    "E1": r"C:\Users\liam\Documents\GitHub\Footballdata\data\ENGLAND\championship\games",
    "E2": r"C:\Users\liam\Documents\GitHub\Footballdata\data\ENGLAND\League1\games",
    "E3": r"C:\Users\liam\Documents\GitHub\Footballdata\data\ENGLAND\League2\games",
    "EC": r"C:\Users\liam\Documents\GitHub\Footballdata\data\ENGLAND\NationalLeague\games",
    "SC0": r"C:\Users\liam\Documents\GitHub\Footballdata\data\SCOTLAND\Premiership\games",
    "SC1": r"C:\Users\liam\Documents\GitHub\Footballdata\data\SCOTLAND\Championship\games",
    "SC2": r"C:\Users\liam\Documents\GitHub\Footballdata\data\SCOTLAND\League1\games",
    "SC3": r"C:\Users\liam\Documents\GitHub\Footballdata\data\SCOTLAND\League2\games",
    "I1": r"C:\Users\liam\Documents\GitHub\Footballdata\data\ITALY\serie-a\games",
    "I2": r"C:\Users\liam\Documents\GitHub\Footballdata\data\ITALY\serie-b\games",
    "D1": r"C:\Users\liam\Documents\GitHub\Footballdata\data\GERMANY\bundesliga\games",
    "D2": r"C:\Users\liam\Documents\GitHub\Footballdata\data\GERMANY\2-bundesliga\games",
    "SP1": r"C:\Users\liam\Documents\GitHub\Footballdata\data\SPAIN\la-liga\games",
    "SP2": r"C:\Users\liam\Documents\GitHub\Footballdata\data\SPAIN\la-liga-2\games",
    "F1": r"C:\Users\liam\Documents\GitHub\Footballdata\data\FRANCE\ligue-1\games",
    "F2": r"C:\Users\liam\Documents\GitHub\Footballdata\data\FRANCE\ligue-2\games",
    "B1": r"C:\Users\liam\Documents\GitHub\Footballdata\data\BELGIUM\jupiler-pro-league\games",
    "N1": r"C:\Users\liam\Documents\GitHub\Footballdata\data\NETHERLANDS\eredivisie\games",
    "P1": r"C:\Users\liam\Documents\GitHub\Footballdata\data\PORTUGAL\primeira-liga\games",
}

START_YEAR = 1993
END_YEAR = 2026
ROOT_DIR = r"C:\Users\liam\Documents\GitHub\Footballdata"

# ---------------------------------------------------------------------------
# How Excel stores dates vs scores
# ---------------------------------------------------------------------------
# If your Excel uses DD/MM (UK, AU, EU, most non-US) → "EU"
# If your Excel uses MM/DD (US)                        → "US"
#
# This matters: typing '1-2' in Excel gives Feb 1 in EU locale but Jan 2 in
# US locale. We use this to reverse the auto-conversion back to a score.
DATE_LOCALE = "EU"

DISCOVERED_ROOT = os.path.join(ROOT_DIR, "data", "_discovered")
DISCOVERY_REPORT = os.path.join(DISCOVERED_ROOT, "discovery.json")

SEARCH_NEW_CSVS = False

DISCOVERY_PAGES = [
    "https://www.football-data.co.uk/downloadm.php",
    "https://www.football-data.co.uk/englandm.php",
    "https://www.football-data.co.uk/scotlandm.php",
    "https://www.football-data.co.uk/germanym.php",
    "https://www.football-data.co.uk/italym.php",
    "https://www.football-data.co.uk/spainm.php",
    "https://www.football-data.co.uk/francem.php",
    "https://www.football-data.co.uk/hollandm.php",
    "https://www.football-data.co.uk/portugalm.php",
    "https://www.football-data.co.uk/belgiumm.php",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

_HREF_CSV_RE = re.compile(r'href=["\']([^"\']+\.csv[^"\']*)["\']', re.IGNORECASE)
_SEASON_LINK_RE = re.compile(r"mmz4281/(\d{4})/([A-Za-z0-9]+)\.csv", re.IGNORECASE)
_NEW_PATH_RE = re.compile(r"/new/([A-Za-z0-9]+)\.csv", re.IGNORECASE)

# Column names we treat as "this contains a score"
_SCORE_COLUMN_KEYWORDS = ("result", "score", "scoreline", "ftscore", "fulltime")


def season_codes():
    for year in range(START_YEAR, END_YEAR + 1):
        yield f"{str(year)[-2:]}{str(year + 1)[-2:]}"


def ensure_folders():
    ready = {}
    for league, folder in LEAGUES.items():
        try:
            os.makedirs(folder, exist_ok=True)
            ready[league] = folder
        except OSError as e:
            print(f"!! Could not create folder for {league}: {folder}\n   {e}")
    return ready


# ---------------------------------------------------------------------------
# XLSX -> CSV with score-recovery
# ---------------------------------------------------------------------------

def _fix_date_in_score_columns(df, locale=None):
    """Reverse Excel's auto-conversion of scores like '1-2' into dates.

    Returns (df, fixed_count).
    """
    try:
        import pandas as pd
    except ImportError:
        return df, 0

    locale = (locale or DATE_LOCALE or "EU").upper()
    score_columns = [
        c for c in df.columns
        if any(k in str(c).lower() for k in _SCORE_COLUMN_KEYWORDS)
    ]
    if not score_columns:
        return df, 0

    df = df.copy()
    fixed = 0

    for col in score_columns:
        def _fix(v):
            nonlocal fixed
            if pd.isna(v):
                return v
            if isinstance(v, (pd.Timestamp, datetime, date)):
                fixed += 1
                if locale == "US":
                    return f"{v.month} - {v.day}"
                return f"{v.day} - {v.month}"
            return v

        df[col] = df[col].apply(_fix)

    return df, fixed


def convert_xlsx_to_csv(root):
    try:
        import pandas as pd
    except ImportError:
        print("!! pandas not installed – skipping XLSX conversion.")
        print("   Install with: pip install pandas openpyxl")
        return

    converted = 0
    failed = 0

    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            if fname.startswith("~$"):
                continue  # Excel lock file
            if not fname.lower().endswith(".xlsx"):
                continue

            src = os.path.join(dirpath, fname)
            base = os.path.splitext(fname)[0]
            xls = None

            try:
                xls = pd.ExcelFile(src)
                sheets = xls.sheet_names

                if len(sheets) == 1:
                    df = xls.parse(sheets[0])
                    df, fixed = _fix_date_in_score_columns(df)
                    dest = os.path.join(dirpath, base + ".csv")
                    df.to_csv(dest, index=False)
                    if fixed:
                        print(f"   ↻ {fname}: converted {fixed} date-in-score cell(s) "
                              f"back to scores (locale={DATE_LOCALE})")
                else:
                    for sheet in sheets:
                        df = xls.parse(sheet)
                        df, fixed = _fix_date_in_score_columns(df)
                        safe_sheet = "".join(
                            c if c.isalnum() or c in "-_" else "_" for c in sheet
                        )
                        dest = os.path.join(dirpath, f"{base}_{safe_sheet}.csv")
                        df.to_csv(dest, index=False)
                        if fixed:
                            print(f"   ↻ {fname} [{sheet}]: converted {fixed} "
                                  f"date-in-score cell(s) back to scores")

                # CRITICAL: release the file handle BEFORE trying to delete it.
                # On Windows, os.remove() fails with WinError 32 if the xlsx is
                # still open somewhere (including inside pandas).
                try:
                    xls.close()
                except Exception:
                    pass
                xls = None

                try:
                    os.remove(src)
                    print(f"XLSX->CSV: {src}")
                except OSError as e:
                    print(f"!! Converted to CSV but could NOT delete {src}: {e}")
                    print(f"   Close the file in Excel and re-run, or delete it manually.")

                converted += 1

            except Exception as e:
                failed += 1
                print(f"!! Failed to convert {src}: {e}")
            finally:
                # Belt-and-braces: make sure handle is closed even on error
                if xls is not None:
                    try:
                        xls.close()
                    except Exception:
                        pass

    print(f"XLSX conversion done: {converted} converted, {failed} failed.")


# ---------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------

def download(url, dest):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp, open(dest, "wb") as f:
        f.write(resp.read())


def _fetch_page(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def discover_available():
    seasonal, flat = {}, {}
    for url in DISCOVERY_PAGES:
        try:
            html = _fetch_page(url)
        except urllib.error.HTTPError as e:
            if e.code != 404:
                print(f"   !! HTTP {e.code} fetching {url}")
            continue
        except Exception as e:
            print(f"   !! Could not fetch {url}: {e}")
            continue

        for href in _HREF_CSV_RE.findall(html):
            full = urllib.parse.urljoin(url, href)
            m = _SEASON_LINK_RE.search(full)
            if m:
                seasonal.setdefault(m.group(2).upper(), set()).add(m.group(1))
                continue
            m = _NEW_PATH_RE.search(full)
            if m:
                flat[m.group(1).upper()] = full
    return {"seasonal": seasonal, "flat": flat}


def save_discovery_report(discovered, path):
    data = {
        "seasonal": {c: sorted(s) for c, s in discovered["seasonal"].items()},
        "flat": discovered["flat"],
    }
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        print(f"Saved discovery report: {path}")
    except OSError as e:
        print(f"!! Could not write discovery report: {e}")


def register_discovered_leagues(discovered, folders):
    added = []
    for code, seasons in discovered["seasonal"].items():
        if code in folders:
            continue
        folder = os.path.join(DISCOVERED_ROOT, code, "games")
        try:
            os.makedirs(folder, exist_ok=True)
            folders[code] = folder
            added.append((code, folder, len(seasons)))
        except OSError as e:
            print(f"   !! Could not create folder for new league {code}: {e}")
    return added


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Download football-data.co.uk CSVs.")
    parser.add_argument("--search", action="store_true",
                        help="Search the site for new leagues/seasons first.")
    parser.add_argument("--no-search", action="store_true",
                        help="Disable discovery even if SEARCH_NEW_CSVS=True.")
    parser.add_argument("--discover-only", action="store_true",
                        help="Only discover what's on the site, don't download.")
    parser.add_argument("--date-locale", choices=["US", "EU"],
                        help="Excel locale used for reversing date->score. Overrides DATE_LOCALE.")
    args = parser.parse_args()

    # Allow overriding locale from CLI
    global DATE_LOCALE
    if args.date_locale:
        DATE_LOCALE = args.date_locale

    search = args.search or (SEARCH_NEW_CSVS and not args.no_search)

    print(f"Scanning {ROOT_DIR} for XLSX files...")
    convert_xlsx_to_csv(ROOT_DIR)

    folders = ensure_folders()

    discovered = None
    flat_leagues = {}
    if search:
        print("Searching football-data.co.uk for available CSVs...")
        discovered = discover_available()
        flat_leagues = discovered["flat"]
        known = sum(len(s) for s in discovered["seasonal"].values())
        print(f"   Found {len(discovered['seasonal'])} seasonal league(s) "
              f"({known} season files) and {len(flat_leagues)} flat league(s).")

        new_leagues = register_discovered_leagues(discovered, folders)
        if new_leagues:
            print(f"NEW leagues discovered ({len(new_leagues)}):")
            for code, folder, n in sorted(new_leagues):
                print(f"  + {code}: {n} season(s) -> {folder}")
        else:
            print("   No new leagues found.")

        if flat_leagues:
            print(f"Single-file leagues under /new/ ({len(flat_leagues)}):")
            for code in sorted(flat_leagues):
                print(f"  + {code}  ({flat_leagues[code]})")

        save_discovery_report(discovered, DISCOVERY_REPORT)

    if args.discover_only:
        print("Discovery complete (no downloads performed).")
        return

    if not folders:
        print("No destination folders available – aborting.")
        return

    seasonal_map = discovered["seasonal"] if discovered is not None else None

    for code in season_codes():
        for league, folder in folders.items():
            if seasonal_map is not None and league in seasonal_map:
                if code not in seasonal_map[league]:
                    continue

            dest = os.path.join(folder, f"{code}.csv")
            if os.path.exists(dest) and os.path.getsize(dest) > 0:
                print(f"SKIP (already exists): {dest}")
                continue

            url = BASE_URL.format(season=code, league=league)
            print(f"GET  {url}")
            try:
                download(url, dest)
                print(f"  -> saved to {dest} ({os.path.getsize(dest):,} bytes)")
            except urllib.error.HTTPError as e:
                print(f"  !! HTTP {e.code} – not available")
                if os.path.exists(dest) and os.path.getsize(dest) == 0:
                    os.remove(dest)
            except Exception as e:
                print(f"  !! Error: {e}")
                if os.path.exists(dest) and os.path.getsize(dest) == 0:
                    os.remove(dest)
            time.sleep(0.3)

    for league, url in sorted(flat_leagues.items()):
        folder = os.path.join(DISCOVERED_ROOT, league)
        dest = os.path.join(folder, f"{league}.csv")
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            print(f"SKIP (already exists): {dest}")
            continue
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            print(f"  !! Could not create folder for {league}: {e}")
            continue
        print(f"GET  {url}")
        try:
            download(url, dest)
            print(f"  -> saved to {dest} ({os.path.getsize(dest):,} bytes)")
        except urllib.error.HTTPError as e:
            print(f"  !! HTTP {e.code} – not available")
            if os.path.exists(dest) and os.path.getsize(dest) == 0:
                os.remove(dest)
        except Exception as e:
            print(f"  !! Error: {e}")
            if os.path.exists(dest) and os.path.getsize(dest) == 0:
                os.remove(dest)
        time.sleep(0.3)

    print("Done.")


if __name__ == "__main__":
    main()