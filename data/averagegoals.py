#!/usr/bin/env python3
"""
Football data scanner – reads CSV files with varying column structures,
extracts full‑time home/away goals, and prints per‑file, per‑folder,
and global averages.

Usage:
    python scan_football.py /path/to/data/folder
"""

import os
import sys
import csv
from collections import defaultdict

# ----------------------------------------------------------------------
#  Configuration
# ----------------------------------------------------------------------
ENCODINGS = ['utf-8', 'latin-1', 'cp1252']   # try these in order


def safe_open_csv(filepath):
    """Try to open a CSV file with encodings, ignoring errors."""
    # Try common encodings
    for enc in ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']:
        try:
            f = open(filepath, 'r', encoding=enc, errors='ignore')
            reader = csv.DictReader(f)
            # Test first row
            first = next(reader, None)
            if first is not None and 'FTHG' in first and 'FTAG' in first:
                # Success: rewind file and return reader with same encoding
                f.seek(0)
                reader = csv.DictReader(f)
                return reader, f
            f.close()
        except (UnicodeDecodeError, csv.Error, StopIteration):
            if f:
                f.close()
            continue
    return None, None


def process_csv_file(filepath):
    """
    Process a single CSV file.
    Returns a dict with:
        matches, total_home, total_away, avg_home, avg_away, avg_total
    or None if the file cannot be read or lacks goal columns.
    """
    reader, fh = safe_open_csv(filepath)
    if reader is None:
        return None

    match_count = 0
    total_home = 0
    total_away = 0

    # Check if required columns exist
    fieldnames = reader.fieldnames
    if 'FTHG' not in fieldnames or 'FTAG' not in fieldnames:
        fh.close()
        return None

    for row in reader:
        try:
            hg = int(row['FTHG'])
            ag = int(row['FTAG'])
        except (ValueError, TypeError):
            continue   # skip malformed rows

        match_count += 1
        total_home += hg
        total_away += ag

    fh.close()

    if match_count == 0:
        return None

    avg_home = total_home / match_count
    avg_away = total_away / match_count
    avg_total = (total_home + total_away) / match_count

    return {
        'matches': match_count,
        'home_goals': total_home,
        'away_goals': total_away,
        'avg_home': avg_home,
        'avg_away': avg_away,
        'avg_total': avg_total,
    }


def scan_folder(root_dir):
    """
    Walk through root_dir, process every .csv file, and print statistics.
    Returns overall aggregates and a list of per‑file stats.
    """
    all_stats = []          # list of (relative_path, stats_dict)
    folder_aggregates = defaultdict(lambda: {'matches': 0, 'total_home': 0, 'total_away': 0})

    # Walk the directory tree
    for dirpath, dirnames, filenames in os.walk(root_dir):
        for fname in filenames:
            if not fname.lower().endswith('.csv'):
                continue

            full_path = os.path.join(dirpath, fname)
            # Make a relative path for display
            rel_path = os.path.relpath(full_path, root_dir)

            stats = process_csv_file(full_path)
            if stats is None:
                # Print an error message for unreadable files (like in your log)
                print(f"  Error processing {rel_path}: cannot read or missing FTHG/FTAG")
                continue

            # Save for global aggregation
            all_stats.append((rel_path, stats))

            # Add to folder‑level aggregate (use the immediate parent folder name)
            folder_name = os.path.basename(os.path.dirname(full_path))
            folder_aggregates[folder_name]['matches'] += stats['matches']
            folder_aggregates[folder_name]['total_home'] += stats['home_goals']
            folder_aggregates[folder_name]['total_away'] += stats['away_goals']

            # Print per‑file line (like the original scan)
            print(f"  Processed {rel_path}: {stats['matches']} matches | "
                  f"home {stats['avg_home']:.2f} | away {stats['avg_away']:.2f} | "
                  f"total {stats['avg_total']:.2f}")

    # Now print folder summaries
    print("\n===== FOLDER AGGREGATES =====")
    for folder, data in folder_aggregates.items():
        matches = data['matches']
        if matches == 0:
            continue
        avg_home = data['total_home'] / matches
        avg_away = data['total_away'] / matches
        avg_total = (data['total_home'] + data['total_away']) / matches
        print(f"  {folder}: {matches} matches | "
              f"home {avg_home:.2f} | away {avg_away:.2f} | total {avg_total:.2f}")

    # Global aggregates
    total_matches = sum(s['matches'] for _, s in all_stats)
    total_home = sum(s['home_goals'] for _, s in all_stats)
    total_away = sum(s['away_goals'] for _, s in all_stats)

    if total_matches == 0:
        print("\nNo valid matches found.")
        return

    global_avg_home = total_home / total_matches
    global_avg_away = total_away / total_matches
    global_avg_total = (total_home + total_away) / total_matches

    # Find file with highest and lowest total average
    if all_stats:
        highest = max(all_stats, key=lambda x: x[1]['avg_total'])
        lowest = min(all_stats, key=lambda x: x[1]['avg_total'])
        print("\n===== GLOBAL STATISTICS =====")
        print(f"  Total matches: {total_matches}")
        print(f"  Average home goals per match: {global_avg_home:.2f}")
        print(f"  Average away goals per match: {global_avg_away:.2f}")
        print(f"  Average total goals per match: {global_avg_total:.2f}")
        print()
        print(f"  Highest average total goals: {highest[0]} → {highest[1]['avg_total']:.2f} "
              f"(home {highest[1]['avg_home']:.2f}, away {highest[1]['avg_away']:.2f})")
        print(f"  Lowest average total goals:  {lowest[0]} → {lowest[1]['avg_total']:.2f} "
              f"(home {lowest[1]['avg_home']:.2f}, away {lowest[1]['avg_away']:.2f})")


def main():
    if len(sys.argv) < 2:
        print("Usage: python scan_football.py /path/to/data/folder")
        sys.exit(1)

    root = sys.argv[1]
    if not os.path.isdir(root):
        print(f"Error: '{root}' is not a valid directory.")
        sys.exit(1)

    print(f"--- Scanning folder: {root} ---")
    scan_folder(root)


if __name__ == "__main__":
    main()