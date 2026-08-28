import csv
import sys
import re
from pathlib import Path

def is_number(value: str) -> bool:
    """Return True if the string can be parsed as a number."""
    try:
        float(value)
        return True
    except (ValueError, TypeError):
        return False

def count_numeric_cells(file_path):
    """
    Try UTF-8 first; if that fails, fall back to Latin-1.
    Returns (numeric_count, error_message) or (0, error).
    """
    for encoding in ('utf-8', 'latin-1'):
        try:
            with open(file_path, 'r', newline='', encoding=encoding) as f:
                reader = csv.reader(f)
                count = 0
                for row in reader:
                    for cell in row:
                        stripped = cell.strip()
                        if stripped and is_number(stripped):
                            count += 1
                return count, None
        except UnicodeDecodeError:
            continue
        except Exception as e:
            return 0, str(e)
    return 0, "Unsupported encoding"

def update_readme(readme_path: Path, total_csv: int, total_numeric: int):
    """
    Update README.md with total CSV files and total numeric cells.
    """
    if not readme_path.exists():
        print(f"WARNING: {readme_path} not found – skipping update.")
        return

    content = readme_path.read_text(encoding='utf-8')

    # Pattern for CSV files count
    pattern_csv = r'(-\s*\*\*Total CSV files:\*\*\s*)([\d,]+)'
    # Pattern for numeric cells count
    pattern_num = r'(\*\*Total data points \(numeric cells\):\*\*\s*)([\d,]+)'

    def repl_csv(match):
        return match.group(1) + f"{total_csv:,}"

    def repl_num(match):
        return match.group(1) + f"{total_numeric:,}"

    # Replace both
    new_content, count_csv = re.subn(pattern_csv, repl_csv, content)
    new_content, count_num = re.subn(pattern_num, repl_num, new_content)

    # If either line not found, append missing lines
    lines_to_append = []
    if count_csv == 0:
        lines_to_append.append(f"- **Total CSV files:** {total_csv:,}")
    if count_num == 0:
        lines_to_append.append(f"- **Total data points (numeric cells):** {total_numeric:,}")

    if lines_to_append:
        # Add them at the end, but maybe keep the bullet list formatting
        new_content = new_content.rstrip()
        # Ensure there's a newline before appending
        if not new_content.endswith('\n'):
            new_content += '\n'
        new_content += '\n'.join(lines_to_append) + '\n'
        print("INFO: One or both lines not found – appended to README.")
    else:
        print(f"INFO: Updated README with total CSV files: {total_csv:,} and numeric cells: {total_numeric:,}")

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
        count, error = count_numeric_cells(file_path)
        grand_total += count

        status = "OK" if error is None else f"ERROR: {error}"
        print(f"[{idx}/{len(csv_files)}] {file_path.name:<40} -> {count:>8} numeric cells  ({status})")

    print("\n" + "=" * 70)
    print(f"GRAND TOTAL numeric cells across all CSV files: {grand_total:,}")
    print("=" * 70)

    # ----- NEW: Update README.md -----
    readme_path = Path(r"C:\Users\liam\Documents\GitHub\Footballdata\README.md")
    update_readme(readme_path, len(csv_files), grand_total)
    # ---------------------------------

    input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()