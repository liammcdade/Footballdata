#!/usr/bin/env python3
"""
Home/away goal averages with recency weighting.
Season year is taken from (in order): Season column, Date column, filename.

weight = 0.5 ** (age / HALF_LIFE_YEARS)
"""

import os
import sys
import csv
import re
from datetime import datetime
from collections import defaultdict

DATA_DIR = r"C:\Users\liam\Documents\GitHub\Footballdata\data\ENGLAND\Premier league\GAMES"

# How fast does trust decay? Try 10, 20, or 40.
HALF_LIFE_YEARS = 20

HOME_COLS   = ["FTHG", "hGoal", "home_goals", "HomeGoals", "HG", "Home Goals"]
AWAY_COLS   = ["FTAG", "aGoal", "away_goals", "AwayGoals", "AG", "Away Goals"]
DATE_COLS   = ["Date", "date", "MatchDate", "match_date"]
SEASON_COLS = ["Season", "season"]
ENCODINGS   = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]

def find_col(fieldnames, candidates):
    for c in candidates:
        if c in fieldnames:
            return c
    return None

def parse_date(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(s).strip(), fmt)
        except ValueError:
            continue
    return None

def season_year_from_date(dt):
    if dt is None:
        return None
    return dt.year if dt.month >= 7 else dt.year - 1

def season_year_from_string(s):
    """'1993/1994' or '1993-1994' or '1993_1994' -> 1993"""
    if not s:
        return None
    m = re.match(r"(\d{4})", str(s).strip())
    return int(m.group(1)) if m else None

def season_year_from_filename(fname):
    m = re.match(r"(\d{4})", fname)
    return int(m.group(1)) if m else None

def read_file(path):
    for enc in ENCODINGS:
        try:
            with open(path, "r", encoding=enc, errors="ignore", newline="") as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    return None
                hcol = find_col(reader.fieldnames, HOME_COLS)
                acol = find_col(reader.fieldnames, AWAY_COLS)
                if not hcol or not acol:
                    return None
                dcol = find_col(reader.fieldnames, DATE_COLS)
                scol = find_col(reader.fieldnames, SEASON_COLS)
                return hcol, acol, dcol, scol, list(reader)
        except (UnicodeDecodeError, csv.Error):
            continue
    return None

def main():
    root = sys.argv[1] if len(sys.argv) > 1 else DATA_DIR
    if not os.path.isdir(root):
        print(f"Not a directory: {root}")
        sys.exit(1)

    season_stats = defaultdict(lambda: [0, 0, 0])   # year -> [matches, home, away]
    files_used = 0
    files_skipped = []

    for dirpath, _, filenames in os.walk(root):
        for fname in sorted(filenames):
            if not fname.lower().endswith(".csv"):
                continue
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, root)

            parsed = read_file(full)
            if parsed is None:
                files_skipped.append(rel)
                continue

            hcol, acol, dcol, scol, rows = parsed
            file_matches = 0

            for r in rows:
                try:
                    hg = int(r[hcol]); ag = int(r[acol])
                except (ValueError, TypeError, KeyError):
                    continue

                year = None
                if scol:
                    year = season_year_from_string(r.get(scol))
                if year is None and dcol:
                    year = season_year_from_date(parse_date(r.get(dcol)))
                if year is None:
                    year = season_year_from_filename(fname)
                if year is None:
                    continue

                s = season_stats[year]
                s[0] += 1
                s[1] += hg
                s[2] += ag
                file_matches += 1

            if file_matches:
                files_used += 1
            else:
                files_skipped.append(rel)

    if not season_stats:
        print("No valid matches found.")
        return

    latest_year = max(season_stats.keys())

    print(f"\nFiles used:       {files_used}")
    print(f"Reference season: {latest_year}/{latest_year+1}")
    print(f"Half-life:        {HALF_LIFE_YEARS} years")
    print(f"Seasons covered:  {min(season_stats)} to {latest_year}\n")

    print("===== PER-SEASON (with weight) =====")
    print(f"{'Season':<12}{'Matches':>8}{'Weight':>9}"
          f"{'Home':>8}{'Away':>8}{'Total':>8}")

    w_matches = w_home = w_away = 0.0

    for year in sorted(season_stats):
        m, h, a = season_stats[year]
        if m == 0:
            continue
        age = latest_year - year
        w = 0.5 ** (age / HALF_LIFE_YEARS)

        w_matches += w * m
        w_home    += w * h
        w_away    += w * a

        print(f"{year}/{year+1:<7}{m:>8}{w:>9.3f}"
              f"{h/m:>8.2f}{a/m:>8.2f}{(h+a)/m:>8.2f}")

    # Unweighted
    tm = sum(s[0] for s in season_stats.values())
    th = sum(s[1] for s in season_stats.values())
    ta = sum(s[2] for s in season_stats.values())

    # Weighted
    w_home_avg = w_home / w_matches
    w_away_avg = w_away / w_matches
    w_total    = (w_home + w_away) / w_matches

    print("\n===== UNWEIGHTED vs WEIGHTED =====")
    print(f"{'':<14}{'Home':>10}{'Away':>10}{'Total':>10}{'Home%':>10}")
    print(f"{'Unweighted':<14}{th/tm:>10.4f}{ta/tm:>10.4f}"
          f"{(th+ta)/tm:>10.4f}{th/(th+ta):>10.2%}")
    print(f"{'Weighted':<14}{w_home_avg:>10.4f}{w_away_avg:>10.4f}"
          f"{w_total:>10.4f}{w_home/(w_home+w_away):>10.2%}")

    print(f"\nWeighted match count: {w_matches:,.0f}")
    print(f"Actual match count:   {tm:,}")
    print(f"Effective fraction:   {w_matches/tm:.1%}")

    if files_skipped:
        print(f"\nSkipped {len(files_skipped)} file(s):")
        for s in files_skipped:
            print(f"  - {s}")

if __name__ == "__main__":
    main()