import csv
import sys
import re
from pathlib import Path

def count_data_rows(file_path):
    """
    Try UTF-8 first; if that fails, fall back to Latin-1.
    Skips the first row (header) and counts each remaining non-empty row as one game.
    Returns (row_count, error_message) or (0, error).
    """
    for encoding in ('utf-8', 'latin-1'):
        try:
            with open(file_path, 'r', newline='', encoding=encoding) as f:
                reader = csv.reader(f)
                count = 0
                for i, row in enumerate(reader):
                    if i == 0:
                        continue  # skip header row
                    # Count row as a game if it has at least one non-empty cell
                    if any(cell.strip() for cell in row):
                        count += 1
                return count, None
        except UnicodeDecodeError:
            continue
        except Exception as e:
            return 0, str(e)
    return 0, "Unsupported encoding"

def update_readme(readme_path: Path, total_csv: int, total_games: int):
    """
    Update README.md with total CSV files and total games (data rows).
    """
    if not readme_path.exists():
        print(f"WARNING: {readme_path} not found – skipping update.")
        return

    content = readme_path.read_text(encoding='utf-8')

    # Pattern for CSV files count
    pattern_csv = r'(-\s*\*\*Total CSV files:\*\*\s*)([\d,]+)'
    # Pattern for games count – matches both the old label and the new one
    pattern_games = (
        r'(\*\*(?:Total data points \(numeric cells\)|Total games(?: \(data rows\))?):\*\*\s*)([\d,]+)'
    )

    def repl_csv(match):
        return match.group(1) + f"{total_csv:,}"

    def repl_games(match):
        return "**Total games (data rows):** " + f"{total_games:,}"

    new_content, count_csv = re.subn(pattern_csv, repl_csv, content)
    new_content, count_games = re.subn(pattern_games, repl_games, new_content)

    # If either line not found, append missing lines
    lines_to_append = []
    if count_csv == 0:
        lines_to_append.append(f"- **Total CSV files:** {total_csv:,}")
    if count_games == 0:
        lines_to_append.append(f"- **Total games (data rows):** {total_games:,}")

    if lines_to_append:
        new_content = new_content.rstrip()
        if not new_content.endswith('\n'):
            new_content += '\n'
        new_content += '\n'.join(lines_to_append) + '\n'
        print("INFO: One or both lines not found – appended to README.")
    else:
        print(f"INFO: Updated README with total CSV files: {total_csv:,} and games: {total_games:,}")

    readme_path.write_text(new_content, encoding='utf-8')

def main():
    # -------- CONFIGURATION --------
    default_dir = r"C:\Users\liam\Documents\GitHub\Footballdata"
    # -------------------------------

    if len(sys.argv) > 1:
        root_dir = sys.argv[1]
    else:
        root_dir = default_dir

    root_path = Path(root_dir)

    if not root_path.exists():
        print(f"ERROR: Folder not found: {root_dir}")
        input("Press Enter to exit...")
        return

    print(f"Scanning: {root_dir}")
    print("=" * 70)

    # Deduplicate (important on Windows)
    csv_files = list({p.resolve() for p in root_path.rglob("*.csv")})

    if not csv_files:
        print("No CSV files found.")
        input("Press Enter to exit...")
        return

    print(f"Found {len(csv_files)} CSV file(s). Processing...\n")

    grand_total = 0

    for idx, file_path in enumerate(csv_files, 1):
        count, error = count_data_rows(file_path)
        grand_total += count

        status = "OK" if error is None else f"ERROR: {error}"
        print(f"[{idx}/{len(csv_files)}] {file_path.name:<40} -> {count:>8} games  ({status})")

    print("\n" + "=" * 70)
    print(f"GRAND TOTAL games (data rows) across all CSV files: {grand_total:,}")
    print("=" * 70)

    readme_path = Path(r"C:\Users\liam\Documents\GitHub\Footballdata\README.md")
    update_readme(readme_path, len(csv_files), grand_total)

    input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()