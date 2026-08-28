import os
import csv
from collections import defaultdict
from datetime import datetime

# ---------- CONFIGURATION ----------
K_FACTOR = 30
INITIAL_RATING = 1500
MIN_PERCENT = 0.05
MIN_ABSOLUTE = 3

# League weights: 1.0 for Premier League, down to 0.0 for National League North
# Adjust these values as you see fit.
LEAGUE_WEIGHTS = {
    'premier league': 1.0,
    'championship': 0.8,
    'league1': 0.6,
    'league2': 0.4,
    'national league': 0.25,
    'nationalleaguenorth': 0.1,
    'nationalleaguesouth': 0.1,
}
# -----------------------------------

def parse_date(date_str):
    """Strip time and convert DD/MM/YYYY or DD/MM/YY to datetime."""
    date_str = date_str.strip()
    if not date_str:
        return None
    if ' ' in date_str:
        date_str = date_str.split(' ')[0]
    try:
        return datetime.strptime(date_str, '%d/%m/%Y')
    except ValueError:
        pass
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
        parts = rel.split(os.sep)
        league = parts[0].lower() if len(parts) > 1 else ''
        weight = LEAGUE_WEIGHTS.get(league, 1.0)
        if league and league not in LEAGUE_WEIGHTS:
            print(f"Warning: Unknown league '{league}' – using weight 1.0")

        encodings = ['utf-8-sig', 'latin-1', 'cp1252']
        for enc in encodings:
            try:
                with open(f, 'r', encoding=enc) as infile:
                    reader = csv.reader(infile)
                    header = next(reader, None)
                    if header is None:
                        continue
                    col_map = {name.strip().lower(): idx for idx, name in enumerate(header)}
                    
                    # Required columns (date is optional if weight is low)
                    required = ['hometeam', 'awayteam', 'fthg', 'ftag', 'ftr']
                    if not all(col in col_map for col in required):
                        print(f"Warning: {rel} missing required columns; skipping file.")
                        break
                    
                    # Date handling: if missing, only allow if weight is low
                    has_date = 'date' in col_map
                    if not has_date and weight > 0.2:
                        print(f"Warning: {rel} has no date column and weight > 0.2; skipping file.")
                        break
                    
                    idx_home = col_map['hometeam']
                    idx_away = col_map['awayteam']
                    idx_hg = col_map['fthg']
                    idx_ag = col_map['ftag']
                    idx_res = col_map['ftr']
                    idx_date = col_map.get('date', -1)  # -1 if missing

                    for row in reader:
                        if len(row) <= max(idx_home, idx_away, idx_hg, idx_ag, idx_res):
                            continue
                        home = row[idx_home].strip()
                        away = row[idx_away].strip()
                        ftr = row[idx_res].strip()
                        if not home or not away or not ftr:
                            continue
                        try:
                            home_goals = int(row[idx_hg].strip()) if row[idx_hg].strip() else 0
                            away_goals = int(row[idx_ag].strip()) if row[idx_ag].strip() else 0
                        except (ValueError, IndexError):
                            home_goals = away_goals = 0

                        # Parse date or use dummy
                        if has_date and idx_date != -1 and len(row) > idx_date:
                            date_str = row[idx_date].strip()
                            dt = parse_date(date_str)
                            if dt is None and weight > 0.2:
                                continue  # skip only if we actually need the date
                            elif dt is None:
                                dt = datetime(2000, 1, 1)  # dummy for low-weight
                        else:
                            dt = datetime(2000, 1, 1)  # dummy if no date column

                        matches.append((dt, home, away, home_goals, away_goals, ftr, weight))
                break
            except UnicodeDecodeError:
                continue
        else:
            print(f"Warning: Could not read {rel} with any encoding; skipping.")
    print(f"Total matches read: {len(matches)}")
    return sorted(matches, key=lambda x: x[0])

def compute_elo_and_performance(matches):
    ratings = defaultdict(lambda: INITIAL_RATING)
    # performance: team -> opponent -> dict with unweighted count and weighted sums
    performance = defaultdict(lambda: defaultdict(lambda: {
        'count': 0,                # number of matches (unweighted)
        'weighted_actual': 0.0,
        'weighted_expected': 0.0,
        'weighted_count': 0.0      # sum of weights for averaging
    }))

    for dt, home, away, home_goals, away_goals, ftr, weight in matches:
        Rh = ratings[home]
        Ra = ratings[away]

        # Expected points (win probability)
        Eh = 1.0 / (1.0 + 10.0 ** ((Ra - Rh) / 400.0))
        Ea = 1.0 - Eh

        # Actual points
        if ftr == 'H':
            ah, aa = 1.0, 0.0
        elif ftr == 'A':
            ah, aa = 0.0, 1.0
        else:  # 'D'
            ah, aa = 0.5, 0.5

        # Update Elo ratings – scaled by league weight
        ratings[home] = Rh + K_FACTOR * weight * (ah - Eh)
        ratings[away] = Ra + K_FACTOR * weight * (aa - Ea)

        # Update performance stats for home team against away
        perf_home = performance[home][away]
        perf_home['count'] += 1
        perf_home['weighted_actual'] += weight * ah
        perf_home['weighted_expected'] += weight * Eh
        perf_home['weighted_count'] += weight

        # Update performance stats for away team against home
        perf_away = performance[away][home]
        perf_away['count'] += 1
        perf_away['weighted_actual'] += weight * aa
        perf_away['weighted_expected'] += weight * Ea
        perf_away['weighted_count'] += weight

    return ratings, performance

def analyse_performance(performance):
    results = {}
    for team, opponents in performance.items():
        # Total matches (unweighted) for this team
        team_total = sum(stats['count'] for stats in opponents.values())
        min_games = max(MIN_ABSOLUTE, int(MIN_PERCENT * team_total))

        valid_opponents = {}
        for opp, stats in opponents.items():
            cnt = stats['count']
            if cnt < min_games:
                continue
            # Weighted averages
            wc = stats['weighted_count']
            if wc == 0:
                continue
            wa = stats['weighted_actual'] / wc
            we = stats['weighted_expected'] / wc
            avg_dev = wa - we   # because (weighted_actual - weighted_expected) / wc
            valid_opponents[opp] = {
                'count': cnt,
                'avg_dev': avg_dev,
                'avg_actual': wa,
                'avg_expected': we
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

    print("Computing Elo ratings and performance deviations (league‑weighted)...")
    ratings, performance = compute_elo_and_performance(matches)

    print("Analysing results...")
    analysis = analyse_performance(performance)

    # Output
    for team, data in sorted(analysis.items()):
        print(f"\nTeam: {team} (total matches: {data['total_matches']}, min games vs opponent: {data['min_games']})")
        best_opp, best_stats = data['best']
        worst_opp, worst_stats = data['worst']
        print(f"  Most favourable opponent: {best_opp}")
        print(f"    Games: {best_stats['count']}, Weighted Avg Actual PPG: {best_stats['avg_actual']:.3f}, "
              f"Weighted Avg Expected PPG: {best_stats['avg_expected']:.3f}, "
              f"Weighted Avg Deviation: {best_stats['avg_dev']:+.3f}")
        print(f"  Least favourable opponent: {worst_opp}")
        print(f"    Games: {worst_stats['count']}, Weighted Avg Actual PPG: {worst_stats['avg_actual']:.3f}, "
              f"Weighted Avg Expected PPG: {worst_stats['avg_expected']:.3f}, "
              f"Weighted Avg Deviation: {worst_stats['avg_dev']:+.3f}")

    print("\nFinal Elo ratings (top 10):")
    sorted_ratings = sorted(ratings.items(), key=lambda x: x[1], reverse=True)
    for team, rating in sorted_ratings:
        print(f"  {team}: {rating:.1f}")

if __name__ == '__main__':
    main()