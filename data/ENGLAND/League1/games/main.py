import webbrowser
import time

# Base URL without the season code
BASE_URL = "https://www.football-data.co.uk/mmz4281/{}/E2.csv"

# We want seasons from 1993–94 up to 2025–26
START_YEAR = 1993
END_YEAR = 2025

# Generate all season codes like 9394, 9495, ..., 2526
season_codes = []
for year in range(START_YEAR, END_YEAR + 1):
    # The first two digits of the starting year
    start = str(year)[-2:]          # e.g. "93" for 1993
    end = str(year + 1)[-2:]        # e.g. "94" for 1994
    season_codes.append(start + end)

# Open each URL in a new browser tab
for code in season_codes:
    url = BASE_URL.format(code)
    print(f"Opening: {url}")
    webbrowser.open_new_tab(url)
    # Small delay to avoid overwhelming your browser/OS
    time.sleep(0.5)

print("All links have been opened.")