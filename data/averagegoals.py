import pandas as pd
import glob
import os

# ================================
#  USER CONFIGURATION
# ================================
FOLDERS_TO_SCAN = [
    r'C:\Users\liam\Documents\GitHub\Footballdata\data\ENGLAND',
    r'C:\Users\liam\Documents\GitHub\Footballdata\data\international\games'
]

# Common column names for home and away goals – extend as needed
HOME_GOAL_NAMES = [
    'FTHG', 'home_goal', 'hgoal', 'home_score', 'goals_home', 'hg',
    'home_goals', 'HTHG', 'homeTeamGoals', 'HomeGoals'
]
AWAY_GOAL_NAMES = [
    'FTAG', 'away_goal', 'agoal', 'away_score', 'goals_away', 'ag',
    'away_goals', 'HTAG', 'awayTeamGoals', 'AwayGoals'
]

# ================================
#  HELPER FUNCTIONS
# ================================

def read_csv_with_fallback(filepath):
    """Try common encodings; read the whole file."""
    encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
    for enc in encodings:
        try:
            df = pd.read_csv(filepath, encoding=enc)
            return df
        except (UnicodeDecodeError, ValueError):
            continue
    raise UnicodeDecodeError(f"Could not decode {filepath} with any of {encodings}")

def find_goal_columns(df):
    """Identify home and away goal columns from the DataFrame."""
    cols_lower = {col.lower(): col for col in df.columns}
    home_col = None
    away_col = None

    for name in HOME_GOAL_NAMES:
        lower_name = name.lower()
        if lower_name in cols_lower:
            home_col = cols_lower[lower_name]
            break

    for name in AWAY_GOAL_NAMES:
        lower_name = name.lower()
        if lower_name in cols_lower:
            away_col = cols_lower[lower_name]
            break

    if home_col is None or away_col is None:
        raise ValueError(
            f"Could not identify goal columns.\n"
            f"Available columns: {df.columns.tolist()}\n"
            f"Add the correct names to HOME_GOAL_NAMES / AWAY_GOAL_NAMES."
        )
    return home_col, away_col

def extract_goals(df, home_col, away_col):
    """Return numeric Series for home/away goals, keeping only valid rows."""
    home = pd.to_numeric(df[home_col], errors='coerce')
    away = pd.to_numeric(df[away_col], errors='coerce')
    valid = home.notna() & away.notna()
    return home[valid], away[valid]

# ================================
#  MAIN PROCESSING
# ================================

def process_folder(root_folder):
    """Process all CSV files under a single root folder.
       Returns (total_games, home_sum, away_sum, file_avg_dict)."""
    csv_files = glob.glob(os.path.join(root_folder, '**', '*.csv'), recursive=True)
    if not csv_files:
        print(f"  No CSV files found in {root_folder}")
        return 0, 0, 0, {}

    total_games = 0
    total_home = 0
    total_away = 0
    file_avg = {}  # relative path -> (avg_home, avg_away, avg_total)

    for file in csv_files:
        try:
            df = read_csv_with_fallback(file)
            home_col, away_col = find_goal_columns(df)
            home_goals, away_goals = extract_goals(df, home_col, away_col)
            games = len(home_goals)

            if games == 0:
                print(f"  Skipped {os.path.basename(file)} – no valid numeric goal data")
                continue

            total_games += games
            total_home += home_goals.sum()
            total_away += away_goals.sum()

            avg_home_file = home_goals.sum() / games
            avg_away_file = away_goals.sum() / games
            avg_total_file = (home_goals.sum() + away_goals.sum()) / games

            rel_path = os.path.relpath(file, root_folder)
            file_avg[rel_path] = (avg_home_file, avg_away_file, avg_total_file)

            # Print per‑file details with home/away split
            print(f"  Processed {rel_path}: {games} matches | home {avg_home_file:.2f} | away {avg_away_file:.2f} | total {avg_total_file:.2f}")

        except Exception as e:
            print(f"  Error processing {os.path.basename(file)}: {e}")

    return total_games, total_home, total_away, file_avg

def print_folder_summary(folder_name, total_games, home_sum, away_sum, file_avg):
    """Print aggregate statistics for a single folder."""
    if total_games == 0:
        print(f"\n===== {folder_name} – NO VALID DATA =====")
        return

    avg_home = home_sum / total_games
    avg_away = away_sum / total_games
    avg_total = (home_sum + away_sum) / total_games

    print(f"\n===== {folder_name} – AGGREGATE STATISTICS =====")
    print(f"  Total matches: {total_games}")
    print(f"  Average home goals per match: {avg_home:.2f}")
    print(f"  Average away goals per match: {avg_away:.2f}")
    print(f"  Average total goals per match: {avg_total:.2f}")

    if file_avg:
        # Find extremes based on total average
        max_file = max(file_avg, key=lambda k: file_avg[k][2])
        min_file = min(file_avg, key=lambda k: file_avg[k][2])
        print(f"\n  Highest average total goals: {max_file} → {file_avg[max_file][2]:.2f} (home {file_avg[max_file][0]:.2f}, away {file_avg[max_file][1]:.2f})")
        print(f"  Lowest average total goals:  {min_file} → {file_avg[min_file][2]:.2f} (home {file_avg[min_file][0]:.2f}, away {file_avg[min_file][1]:.2f})")

def compute_average_scores(folders):
    global_games = 0
    global_home = 0
    global_away = 0

    for root in folders:
        print(f"\n--- Scanning folder: {root} ---")
        games, home, away, file_avg = process_folder(root)

        global_games += games
        global_home += home
        global_away += away

        folder_name = os.path.basename(root)
        print_folder_summary(folder_name, games, home, away, file_avg)

    if global_games > 0:
        avg_home = global_home / global_games
        avg_away = global_away / global_games
        avg_total = (global_home + global_away) / global_games
        print("\n===== COMBINED GLOBAL AVERAGE (all folders) =====")
        print(f"  Total matches across all folders: {global_games}")
        print(f"  Average home goals per match: {avg_home:.2f}")
        print(f"  Average away goals per match: {avg_away:.2f}")
        print(f"  Average total goals per match: {avg_total:.2f}")
    else:
        print("\nNo valid data found in any folder.")

if __name__ == "__main__":
    compute_average_scores(FOLDERS_TO_SCAN)