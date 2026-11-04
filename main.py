import os
import time
import urllib.request
import urllib.error

BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/{league}.csv"

# League code -> destination folder
LEAGUES = {
    "E1": r"C:\Users\liam\Documents\GitHub\Footballdata\data\ENGLAND\championship\games",
    "E2": r"C:\Users\liam\Documents\GitHub\Footballdata\data\ENGLAND\League1\games",
    "E3": r"C:\Users\liam\Documents\GitHub\Footballdata\data\ENGLAND\League2\games",
    "EC": r"C:\Users\liam\Documents\GitHub\Footballdata\data\ENGLAND\NationalLeague\games",
}

# Last start-year = 2026 -> generates codes up to 2627 (2026-27 season)
START_YEAR = 1993
END_YEAR = 2026

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}


def season_codes():
    """Yield season codes like '9394', '9495', ..., '2627'."""
    for year in range(START_YEAR, END_YEAR + 1):
        start = str(year)[-2:]          # e.g. '93' for 1993
        end = str(year + 1)[-2:]        # e.g. '94' for 1994
        yield f"{start}{end}"


def download(url, dest):
    """Download url -> dest. Raises on failure."""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp, open(dest, "wb") as f:
        f.write(resp.read())


def main():
    for code in season_codes():
        for league, folder in LEAGUES.items():
            os.makedirs(folder, exist_ok=True)
            dest = os.path.join(folder, f"{code}.csv")

            # Skip if already present and non-empty
            if os.path.exists(dest) and os.path.getsize(dest) > 0:
                print(f"SKIP (already exists): {dest}")
                continue

            url = BASE_URL.format(season=code, league=league)
            print(f"GET  {url}")
            try:
                download(url, dest)
                print(f"  -> saved to {dest} "
                      f"({os.path.getsize(dest):,} bytes)")
            except urllib.error.HTTPError as e:
                print(f"  !! HTTP {e.code} – not available")
                if os.path.exists(dest) and os.path.getsize(dest) == 0:
                    os.remove(dest)
            except Exception as e:
                print(f"  !! Error: {e}")
                if os.path.exists(dest) and os.path.getsize(dest) == 0:
                    os.remove(dest)

            # Be polite to the server
            time.sleep(0.3)

    print("Done.")


if __name__ == "__main__":
    main()