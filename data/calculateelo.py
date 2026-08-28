import os
import csv
from collections import defaultdict
from datetime import datetime

# ---------- CONFIGURATION ----------
K_FACTOR = 30
INITIAL_RATING = 1500
MIN_PERCENT = 0.05
MIN_ABSOLUTE = 3
# -----------------------------------

def parse_date(date_str):
    """Strip time and convert DD/MM/YYYY or DD/MM/YY to datetime."""
    date_str = date_str.strip()
    if not date_str:
        return None
    # If there's a time part (e.g., "14/08/93 15:00"), remove it
    if ' ' in date_str:
        date_str = date_str.split(' ')[0]
    # Try 4-digit year first
    try:
        return datetime.strptime(date_str, '%d/%m/%Y')
    except ValueError:
        pass
    # Try 2-digit year
    try:
        return datetime.strptime(date_str, '%d/%m/%y')
    except ValueError:
        return None

def read_all_matches(data_dir):
    matches = []
    csv_files = []
    for root, _, files in os.walk(data_dir):
        for f in files:
            if f.lower().endswith('.csv'):
                csv_files.append(os.path.join(root, f))

    if not csv_files:
        print(f"No CSV files found under {data_dir}")
        return []

    print(f"Found {len(csv_files)} CSV files.")
    for f in csv_files:
        rel = os.path.relpath(f, data_dir)
        encodings = ['utf-8-sig', 'latin-1', 'cp1252']
        for enc in encodings:
            try:
                with open(f, 'r', encoding=enc) as infile:
                    reader = csv.reader(infile)
                    header = next(reader, None)
                    if header is None:
                        continue
                    # Map column names to indices (case‑insensitive)
                    col_map = {name.strip().lower(): idx for idx, name in enumerate(header)}
                    # Required columns
                    required = ['date', 'hometeam', 'awayteam', 'fthg', 'ftag', 'ftr']
                    if not all(col in col_map for col in required):
                        print(f"Warning: {rel} missing required columns; skipping file.")
                        break
                    idx_date = col_map['date']
                    idx_home = col_map['hometeam']
                    idx_away = col_map['awayteam']
                    idx_hg = col_map['fthg']
                    idx_ag = col_map['ftag']
                    idx_res = col_map['ftr']

                    for row in reader:
                        if len(row) <= max(idx_date, idx_home, idx_away, idx_hg, idx_ag, idx_res):
                            continue
                        date_str = row[idx_date].strip()
                        home = row[idx_home].strip()
                        away = row[idx_away].strip()
                        ftr = row[idx_res].strip()
                        if not date_str or not home or not away or not ftr:
                            continue
                        try:
                            home_goals = int(row[idx_hg].strip()) if row[idx_hg].strip() else 0
                            away_goals = int(row[idx_ag].strip()) if row[idx_ag].strip() else 0
                        except (ValueError, IndexError):
                            home_goals = away_goals = 0

                        dt = parse_date(date_str)
                        if dt is None:
                            continue
                        matches.append((dt, home, away, home_goals, away_goals, ftr))
                # Successfully read the file, break encoding loop
                break
            except UnicodeDecodeError:
                continue
        else:
            print(f"Warning: Could not read {rel} with any encoding; skipping.")
    print(f"Total matches read: {len(matches)}")
    return sorted(matches, key=lambda x: x[0])

def compute_elo_and_performance(matches):
    ratings = defaultdict(lambda: INITIAL_RATING)
    performance = defaultdict(lambda: defaultdict(lambda: {'actual': 0.0, 'expected': 0.0, 'count': 0}))

    for dt, home, away, home_goals, away_goals, ftr in matches:
        Rh = ratings[home]
        Ra = ratings[away]

        # Expected points (win probability)
        Eh = 1.0 / (1.0 + 10.0 ** ((Ra - Rh) / 400.0))
        Ea = 1.0 - Eh

        # Actual points: 1 for win, 0.5 for draw, 0 for loss
        if ftr == 'H':
            ah, aa = 1.0, 0.0
        elif ftr == 'A':
            ah, aa = 0.0, 1.0
        else:  # 'D'
            ah, aa = 0.5, 0.5

        # Update Elo ratings
        ratings[home] = Rh + K_FACTOR * (ah - Eh)
        ratings[away] = Ra + K_FACTOR * (aa - Ea)

        # Record performance for home team against away
        perf_home = performance[home][away]
        perf_home['actual'] += ah
        perf_home['expected'] += Eh
        perf_home['count'] += 1

        # Record performance for away team against home
        perf_away = performance[away][home]
        perf_away['actual'] += aa
        perf_away['expected'] += Ea
        perf_away['count'] += 1

    return ratings, performance

def analyse_performance(performance):
    results = {}
    for team, opponents in performance.items():
        team_total = sum(stats['count'] for stats in opponents.values())
        min_games = max(MIN_ABSOLUTE, int(MIN_PERCENT * team_total))

        valid_opponents = {}
        for opp, stats in opponents.items():
            cnt = stats['count']
            if cnt < min_games:
                continue
            actual = stats['actual']
            expected = stats['expected']
            avg_dev = (actual - expected) / cnt
            valid_opponents[opp] = {
                'count': cnt,
                'avg_dev': avg_dev,
                'avg_actual': actual / cnt,
                'avg_expected': expected / cnt
            }

        if not valid_opponents:
            continue

        best = max(valid_opponents.items(), key=lambda x: x[1]['avg_dev'])
        worst = min(valid_opponents.items(), key=lambda x: x[1]['avg_dev'])

        results[team] = {
            'total_matches': team_total,
            'min_games': min_games,
            'best': best,
            'worst': worst,
            'all': valid_opponents
        }
    return results

def main():
    data_dir = r'C:\Users\liam\Documents\GitHub\Footballdata\data\ENGLAND'
    if not os.path.isdir(data_dir):
        print(f"ERROR: Directory not found: {data_dir}")
        return

    print("Reading all matches (this may take a moment)...")
    matches = read_all_matches(data_dir)
    if not matches:
        print("No valid matches found.")
        return

    print("Computing Elo ratings and performance deviations...")
    ratings, performance = compute_elo_and_performance(matches)

    print("Analysing results...")
    analysis = analyse_performance(performance)

    # Output
    for team, data in sorted(analysis.items()):
        print(f"\nTeam: {team} (total matches: {data['total_matches']}, min games vs opponent: {data['min_games']})")
        best_opp, best_stats = data['best']
        worst_opp, worst_stats = data['worst']
        print(f"  Most favourable opponent: {best_opp}")
        print(f"    Games: {best_stats['count']}, Avg Actual PPG: {best_stats['avg_actual']:.3f}, "
              f"Avg Expected PPG: {best_stats['avg_expected']:.3f}, "
              f"Avg Deviation: {best_stats['avg_dev']:+.3f}")
        print(f"  Least favourable opponent: {worst_opp}")
        print(f"    Games: {worst_stats['count']}, Avg Actual PPG: {worst_stats['avg_actual']:.3f}, "
              f"Avg Expected PPG: {worst_stats['avg_expected']:.3f}, "
              f"Avg Deviation: {worst_stats['avg_dev']:+.3f}")

    # Print final Elo ratings (now in normal range)
    print("\nFinal Elo ratings (top 10):")
    sorted_ratings = sorted(ratings.items(), key=lambda x: x[1], reverse=True)
    for team, rating in sorted_ratings:
        print(f"  {team}: {rating:.1f}")

if __name__ == '__main__':
    main()