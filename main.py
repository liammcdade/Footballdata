import os
import time
import urllib.request
import urllib.error

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
}

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
    for year in range(START_YEAR, END_YEAR + 1):
        start = str(year)[-2:]
        end = str(year + 1)[-2:]
        yield f"{start}{end}"


def ensure_folders():
    """Create every destination folder up-front. Returns dict of league->folder."""
    ready = {}
    for league, folder in LEAGUES.items():
        try:
            os.makedirs(folder, exist_ok=True)
            ready[league] = folder
        except OSError as e:
            print(f"!! Could not create folder for {league}: {folder}\n   {e}")
    return ready


def download(url, dest):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp, open(dest, "wb") as f:
        f.write(resp.read())


def main():
    folders = ensure_folders()          # <-- create once, before any downloads
    if not folders:
        print("No destination folders available – aborting.")
        return

    for code in season_codes():
        for league, folder in folders.items():
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

    print("Done.")


if __name__ == "__main__":
    main()