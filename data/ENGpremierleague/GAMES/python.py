import os
import csv
import glob
import datetime

def detect_encoding(filename):
    """Try common encodings until one works."""
    encodings = ['utf-8', 'cp1252', 'latin-1', 'iso-8859-1']
    for enc in encodings:
        try:
            with open(filename, 'r', newline='', encoding=enc) as f:
                f.read()
            return enc
        except UnicodeDecodeError:
            continue
    return None

def parse_date(date_str):
    """Try multiple date formats and return datetime object or None."""
    date_str = date_str.strip()
    if not date_str:
        return None
    formats = ["%d/%m/%y", "%d/%m/%Y"]
    for fmt in formats:
        try:
            return datetime.datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None

def get_year_range(filename):
    encoding = detect_encoding(filename)
    if encoding is None:
        print(f"  Could not detect encoding for {filename}, skipping.")
        return None

    dates = []
    with open(filename, 'r', newline='', encoding=encoding) as f:
        reader = csv.reader(f)
        try:
            next(reader)  # skip header
        except StopIteration:
            return None

        for row in reader:
            if not row or len(row) < 2:
                continue
            dt = parse_date(row[1])
            if dt:
                dates.append(dt)

    if not dates:
        return None
    return min(dates).year, max(dates).year

def get_unique_filename(base_name, existing_files):
    if base_name not in existing_files:
        return base_name
    name, ext = os.path.splitext(base_name)
    counter = 2
    while f"{name} ({counter}){ext}" in existing_files:
        counter += 1
    return f"{name} ({counter}){ext}"

def main():
    files = glob.glob("E0*.csv")
    if not files:
        print("No E0*.csv files found.")
        return

    used_names = set()
    for file in files:
        print(f"Processing: {file}")
        years = get_year_range(file)
        if years is None:
            print(f"  Skipping {file}: no valid dates.")
            continue

        start, end = years
        new_name = get_unique_filename(f"{start}-{end}.csv", used_names)
        os.rename(file, new_name)
        print(f"  Renamed to: {new_name}")
        used_names.add(new_name)

if __name__ == "__main__":
    main()