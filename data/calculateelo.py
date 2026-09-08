import os
import csv
import random
import math
from collections import defaultdict, Counter
from datetime import datetime

# ---------- CONFIGURATION ----------
K_FACTOR = 30                 # used for draws and as a fallback
INITIAL_RATING = 1500
MIN_PERCENT = 0.05
MIN_ABSOLUTE = 3
# MARGIN_FACTOR is no longer used – dynamic K replaces it

LEAGUE_WEIGHTS = {
    'premier league': 1.0,
    'championship': 0.8,
    'league1': 0.6,
    'league2': 0.4,
    'national league': 0.25,
    'nationalleaguenorth': 0.1,
    'nationalleaguesouth': 0.1,
}

EXTRA_RESULTS = {
    ("Newcastle", "Bournemouth"): (2, 2),
    ("Brentford", "Sunderland"): (1, 1),
    ("Brighton", "Leeds"): (1, 1),
    ("Fulham", "Crystal Palace"): (2, 3),
    ("Man City", "Coventry"): (1, 0),
    ("Nott'm Forest", "Tottenham"): (0, 0),
    ("Hull", "Aston Villa"): (0, 0),
}

# ---------- DYNAMIC K-FACTOR (FiveThirtyEight style) ----------
def calculate_dynamic_k(r_winner, r_loser, margin, base_k=20):
    """
    Returns a K‑factor that grows with the margin of victory and
    shrinks when the gap between the two ratings is large.
    For draws (margin=0) we return a fixed K (handled outside).
    """
    pd = abs(margin)
    elo_diff = abs(r_winner - r_loser)   # absolute difference to avoid negative denominator
    
    denom = 0.001 * elo_diff + 2.2
    if denom < 0.1:
        denom = 0.1
    
    k = base_k * math.log(pd + 1) * (2.2 / denom)
    return max(1.0, min(k, 80.0))        # clamp between 1 and 80

# ---------- DATE PARSING ----------
def parse_date(date_str):
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

# ---------- READ ALL MATCHES ----------
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
                    
                    required = ['hometeam', 'awayteam', 'fthg', 'ftag', 'ftr']
                    if not all(col in col_map for col in required):
                        print(f"Warning: {rel} missing required columns; skipping file.")
                        break
                    
                    has_date = 'date' in col_map
                    if not has_date and weight > 0.2:
                        print(f"Warning: {rel} has no date column and weight > 0.2; skipping file.")
                        break
                    
                    idx_home = col_map['hometeam']
                    idx_away = col_map['awayteam']
                    idx_hg = col_map['fthg']
                    idx_ag = col_map['ftag']
                    idx_res = col_map['ftr']
                    idx_date = col_map.get('date', -1)

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

                        if has_date and idx_date != -1 and len(row) > idx_date:
                            date_str = row[idx_date].strip()
                            dt = parse_date(date_str)
                            if dt is None and weight > 0.2:
                                continue
                            elif dt is None:
                                dt = datetime(2000, 1, 1)
                        else:
                            dt = datetime(2000, 1, 1)

                        matches.append((dt, home, away, home_goals, away_goals, ftr, weight))
                break
            except UnicodeDecodeError:
                continue
        else:
            print(f"Warning: Could not read {rel} with any encoding; skipping.")
    print(f"Total matches read: {len(matches)}")
    return sorted(matches, key=lambda x: x[0])

# ---------- COMPUTE ELO AND PERFORMANCE (with dynamic K) ----------
def compute_elo_and_performance(matches):
    ratings = defaultdict(lambda: INITIAL_RATING)
    performance = defaultdict(lambda: defaultdict(lambda: {
        'count': 0,
        'weighted_actual': 0.0,
        'weighted_expected': 0.0,
        'weighted_count': 0.0
    }))

    extremes = defaultdict(lambda: {'min': (INITIAL_RATING, None), 'max': (INITIAL_RATING, None)})

    for dt, home, away, home_goals, away_goals, ftr, weight in matches:
        Rh = ratings[home]
        Ra = ratings[away]

        Eh = 1.0 / (1.0 + 10.0 ** ((Ra - Rh) / 400.0))
        Ea = 1.0 - Eh

        if ftr == 'H':
            ah, aa = 1.0, 0.0
        elif ftr == 'A':
            ah, aa = 0.0, 1.0
        else:  # 'D'
            ah, aa = 0.5, 0.5

        # ---------- DYNAMIC K ----------
        gd = abs(home_goals - away_goals)
        if gd == 0:
            # Draw – use a constant K (or you could use a different formula)
            k = K_FACTOR
        else:
            # Determine winner and loser for the dynamic formula
            if home_goals > away_goals:
                winner_rating = Rh
                loser_rating = Ra
            else:
                winner_rating = Ra
                loser_rating = Rh
            k = calculate_dynamic_k(winner_rating, loser_rating, gd, base_k=20)
            # Apply league weight to K (you could also weight afterwards – we do it here)
            k *= weight

        # Update ratings (no margin multiplier – dynamic K already accounts for margin)
        new_Rh = Rh + k * (ah - Eh)
        new_Ra = Ra + k * (aa - Ea)

        ratings[home] = new_Rh
        ratings[away] = new_Ra

        # Update extremes
        if new_Rh < extremes[home]['min'][0]:
            extremes[home]['min'] = (new_Rh, dt)
        if new_Rh > extremes[home]['max'][0]:
            extremes[home]['max'] = (new_Rh, dt)
        if new_Ra < extremes[away]['min'][0]:
            extremes[away]['min'] = (new_Ra, dt)
        if new_Ra > extremes[away]['max'][0]:
            extremes[away]['max'] = (new_Ra, dt)

        # Performance tracking (unchanged)
        perf_home = performance[home][away]
        perf_home['count'] += 1
        perf_home['weighted_actual'] += weight * ah
        perf_home['weighted_expected'] += weight * Eh
        perf_home['weighted_count'] += weight

        perf_away = performance[away][home]
        perf_away['count'] += 1
        perf_away['weighted_actual'] += weight * aa
        perf_away['weighted_expected'] += weight * Ea
        perf_away['weighted_count'] += weight

    return ratings, performance, extremes

# ---------- PERFORMANCE ANALYSIS (unchanged) ----------
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
            wc = stats['weighted_count']
            if wc == 0:
                continue
            wa = stats['weighted_actual'] / wc
            we = stats['weighted_expected'] / wc
            avg_dev = wa - we
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

# ---------- SEASON FILE READER (unchanged) ----------
def read_season_file(file_path, extra_results=None):
    teams = set()
    points = defaultdict(int)
    played = set()
    try:
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return set(), {}, set()
            col_map = {name.strip().lower(): idx for idx, name in enumerate(header)}
            required = ['hometeam', 'awayteam', 'fthg', 'ftag', 'ftr']
            if not all(col in col_map for col in required):
                print(f"Warning: {file_path} missing required columns.")
                return set(), {}, set()
            idx_home = col_map['hometeam']
            idx_away = col_map['awayteam']
            idx_hg = col_map['fthg']
            idx_ag = col_map['ftag']
            idx_res = col_map['ftr']
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
                    continue
                teams.add(home)
                teams.add(away)
                played.add((home, away))
                if ftr == 'H':
                    points[home] += 3
                elif ftr == 'A':
                    points[away] += 3
                else:  # 'D'
                    points[home] += 1
                    points[away] += 1
        if extra_results:
            for (home, away), (hg, ag) in extra_results.items():
                teams.add(home)
                teams.add(away)
                played.add((home, away))
                if hg > ag:
                    points[home] += 3
                elif hg < ag:
                    points[away] += 3
                else:
                    points[home] += 1
                    points[away] += 1
        return teams, points, played
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return set(), {}, set()

# ---------- SEASON SIMULATION (with dynamic K) ----------
def simulate_season(ratings, current_points, played_fixtures, all_teams,
                    draw_prob, gd_distribution, num_simulations=10000):
    """
    gd_distribution: dict with keys 'H', 'A', 'D' each a list of goal differences
    (positive for home win, negative for away win, 0 for draw)
    Returns:
        counts: dict of team -> dict of outcomes percentages (win, top4, euro, finish5, relegation)
        total_points: dict of team -> average points
        streak_probs: dict with keys 'win', 'loss', 'draw' giving percentage of simulations
                      where at least one team had a streak of 5 consecutive results.
        relegation_triple_counter: Counter with keys = tuple of 3 teams (sorted), values = count of simulations
    """
    all_fixtures = [(h, a) for h in all_teams for a in all_teams if h != a]
    remaining = [fix for fix in all_fixtures if fix not in played_fixtures]
    if not remaining:
        print("No remaining fixtures to simulate.")
        return {}, {}, {'win':0.0, 'loss':0.0, 'draw':0.0}, Counter()

    counts = {team: {'win':0, 'top4':0, 'euro':0, 'finish5':0, 'relegation':0} for team in all_teams}
    total_points = {team: 0.0 for team in all_teams}

    streak_win = 0
    streak_loss = 0
    streak_draw = 0

    relegation_triple_counter = Counter()

    for sim in range(num_simulations):
        sim_ratings = ratings.copy()
        sim_points = current_points.copy()
        fixtures_order = remaining[:]
        random.shuffle(fixtures_order)

        results_seq = {team: [] for team in all_teams}

        for home, away in fixtures_order:
            Rh = sim_ratings[home]
            Ra = sim_ratings[away]
            Eh = 1.0 / (1.0 + 10.0 ** ((Ra - Rh) / 400.0))
            Ea = 1.0 - Eh

            home_win_prob = Eh * (1 - draw_prob)
            away_win_prob = Ea * (1 - draw_prob)

            r = random.random()
            if r < home_win_prob:
                outcome = 'H'
                ah, aa = 1.0, 0.0
                res_pts_home, res_pts_away = 3, 0
                home_res = 'W'
                away_res = 'L'
            elif r < home_win_prob + draw_prob:
                outcome = 'D'
                ah, aa = 0.5, 0.5
                res_pts_home, res_pts_away = 1, 1
                home_res = 'D'
                away_res = 'D'
            else:
                outcome = 'A'
                ah, aa = 0.0, 1.0
                res_pts_home, res_pts_away = 0, 3
                home_res = 'L'
                away_res = 'W'

            # Sample goal difference from historical distribution
            gd_list = gd_distribution[outcome]
            if gd_list:
                gd = random.choice(gd_list)
            else:
                if outcome == 'H':
                    gd = 1
                elif outcome == 'A':
                    gd = -1
                else:
                    gd = 0

            # ---------- DYNAMIC K ----------
            if gd == 0:
                k = K_FACTOR   # draw – use constant K
            else:
                # Determine winner/loser
                if outcome == 'H':
                    winner_rating = Rh
                    loser_rating = Ra
                else:  # outcome == 'A'
                    winner_rating = Ra
                    loser_rating = Rh
                k = calculate_dynamic_k(winner_rating, loser_rating, abs(gd), base_k=20)
                # In simulation we don't have league weight, but you could apply one if desired

            # Update Elo (no margin multiplier)
            new_Rh = Rh + k * (ah - Eh)
            new_Ra = Ra + k * (aa - Ea)

            sim_ratings[home] = new_Rh
            sim_ratings[away] = new_Ra

            sim_points[home] += res_pts_home
            sim_points[away] += res_pts_away

            results_seq[home].append(home_res)
            results_seq[away].append(away_res)

        # Streak checks (unchanged)
        win_streak_hit = False
        loss_streak_hit = False
        draw_streak_hit = False

        for team, seq in results_seq.items():
            if len(seq) < 5:
                continue
            current = seq[0]
            count = 1
            for res in seq[1:]:
                if res == current:
                    count += 1
                else:
                    if count >= 5:
                        if current == 'W':
                            win_streak_hit = True
                        elif current == 'L':
                            loss_streak_hit = True
                        elif current == 'D':
                            draw_streak_hit = True
                    current = res
                    count = 1
            if count >= 5:
                if current == 'W':
                    win_streak_hit = True
                elif current == 'L':
                    loss_streak_hit = True
                elif current == 'D':
                    draw_streak_hit = True

            if win_streak_hit and loss_streak_hit and draw_streak_hit:
                break

        if win_streak_hit:
            streak_win += 1
        if loss_streak_hit:
            streak_loss += 1
        if draw_streak_hit:
            streak_draw += 1

        # Standings
        sorted_teams = sorted(all_teams, key=lambda t: (sim_points[t], random.random()), reverse=True)
        bottom3 = tuple(sorted(sorted_teams[-3:]))
        relegation_triple_counter[bottom3] += 1

        for rank, team in enumerate(sorted_teams, start=1):
            if rank == 1:
                counts[team]['win'] += 1
            if rank <= 4:
                counts[team]['top4'] += 1
            if rank <= 5:
                counts[team]['euro'] += 1
            if rank == 5:
                counts[team]['finish5'] += 1
            if rank >= 18:
                counts[team]['relegation'] += 1

        for team in all_teams:
            total_points[team] += sim_points[team]

    # Convert to percentages and averages
    for team in counts:
        for key in counts[team]:
            counts[team][key] = counts[team][key] / num_simulations * 100.0
    for team in total_points:
        total_points[team] /= num_simulations

    streak_probs = {
        'win': (streak_win / num_simulations) * 100.0,
        'loss': (streak_loss / num_simulations) * 100.0,
        'draw': (streak_draw / num_simulations) * 100.0
    }

    return counts, total_points, streak_probs, relegation_triple_counter

# ---------- MAIN ----------
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

    # Compute historical draw rate and goal difference distributions for PL
    pl_matches = [m for m in matches if m[6] == 1.0]   # weight == 1.0
    if pl_matches:
        draws = sum(1 for m in pl_matches if m[5] == 'D')
        draw_prob = draws / len(pl_matches)
        print(f"Premier League historical draw rate: {draw_prob:.3f} ({draws}/{len(pl_matches)})")
        gd_dist = {'H': [], 'A': [], 'D': []}
        for m in pl_matches:
            dt, home, away, hg, ag, ftr, w = m
            gd = hg - ag
            if ftr == 'H':
                gd_dist['H'].append(gd)
            elif ftr == 'A':
                gd_dist['A'].append(gd)
            else:
                gd_dist['D'].append(0)
        print(f"  Samples for H: {len(gd_dist['H'])}, A: {len(gd_dist['A'])}, D: {len(gd_dist['D'])}")
    else:
        draw_prob = 0.25
        gd_dist = {'H': [1], 'A': [-1], 'D': [0]}
        print("No Premier League matches found; using default draw rate 0.25 and simple goal diff.")

    print("Computing Elo ratings and performance deviations (using dynamic K‑factor)...")
    ratings, performance, extremes = compute_elo_and_performance(matches)

    print("Analysing results...")
    analysis = analyse_performance(performance)

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
    for team, rating in sorted_ratings[:10]:
        print(f"  {team}: {rating:.1f}")

    # ---------- Season simulation ----------
    season_file = r'C:\Users\liam\Documents\GitHub\Footballdata\data\ENGLAND\Premier league\GAMES\2026-2027.csv'
    if not os.path.isfile(season_file):
        print(f"\nSeason file not found: {season_file}. Skipping simulation.")
    else:
        print("\nReading current Premier League standings from:", season_file)
        teams_set, current_points, played = read_season_file(season_file, EXTRA_RESULTS)
        if not teams_set:
            print("No data found in the season file.")
        else:
            all_teams = list(teams_set)
            if len(all_teams) != 20:
                print(f"Warning: Expected 20 teams, found {len(all_teams)}. Proceeding anyway.")
            current_ratings = {team: ratings.get(team, INITIAL_RATING) for team in all_teams}
            print(f"Running 10,000 simulations of the remaining season (draw rate = {draw_prob:.3f})...")
            sim_results, avg_points, streak_probs, relegation_triple_counter = simulate_season(
                current_ratings, current_points, played, all_teams,
                draw_prob, gd_dist, num_simulations=10000
            )
            if sim_results:
                print("\n=== SIMULATION RESULTS (sorted by average final points) ===\n")
                print(f"{'Team':<25} {'Curr Pts':>8} {'Avg Pts':>8} {'Win%':>8} {'Top4%':>8} {'5th%':>8} {'Euro%':>8}  {'Rel%':>8}")
                print("-" * 100)
                for team in sorted(all_teams, key=lambda t: avg_points[t], reverse=True):
                    pts_cur = current_points[team]
                    pts_avg = avg_points[team]
                    w = sim_results[team]['win']
                    t4 = sim_results[team]['top4']
                    euro = sim_results[team]['euro']
                    f5 = sim_results[team]['finish5']
                    rel = sim_results[team]['relegation']
                    print(f"{team:<25} {pts_cur:8d} {pts_avg:8.1f} {w:7.1f}% {t4:7.1f}% {f5:7.1f}% {euro:7.1f}% {rel:7.1f}%")

                print("\n=== STREAK PROBABILITIES (during the remaining fixtures) ===\n")
                print(f"Chance that ANY team wins 5 games in a row:  {streak_probs['win']:6.2f}%")
                print(f"Chance that ANY team loses 5 games in a row: {streak_probs['loss']:6.2f}%")
                print(f"Chance that ANY team draws 5 games in a row: {streak_probs['draw']:6.2f}%")

                if relegation_triple_counter:
                    print("\n=== MOST LIKELY RELEGATION TRIPLE ===\n")
                    most_common = relegation_triple_counter.most_common(1)[0]
                    triple, count = most_common
                    prob = count / 10000 * 100.0
                    print(f"The three teams most likely to be relegated together:")
                    print(f"  {', '.join(triple)}")
                    print(f"Probability that these three are the exact relegation trio: {prob:.2f}%")
                    print("\nTop 5 most common relegation triples:")
                    for triple, cnt in relegation_triple_counter.most_common(5):
                        p = cnt / 10000 * 100.0
                        print(f"  {', '.join(triple)}: {p:.2f}%")
                else:
                    print("No relegation triple data available.")
            else:
                print("No simulation results (maybe no remaining fixtures).")

    # --- Global Elo extremes ---
    print("\n=== GLOBAL ELO EXTREMES (across all teams and all time) ===\n")
    global_min = None
    global_min_team = None
    global_min_date = None
    global_max = None
    global_max_team = None
    global_max_date = None

    for team, ex in extremes.items():
        min_rating, min_date = ex['min']
        max_rating, max_date = ex['max']

        if global_min is None or min_rating < global_min:
            global_min = min_rating
            global_min_team = team
            global_min_date = min_date
        if global_max is None or max_rating > global_max:
            global_max = max_rating
            global_max_team = team
            global_max_date = max_date

    min_date_str = global_min_date.strftime('%Y-%m-%d') if global_min_date else "initial (no match date)"
    max_date_str = global_max_date.strftime('%Y-%m-%d') if global_max_date else "initial (no match date)"

    print(f"Lowest Elo ever: {global_min:.1f}  (achieved by {global_min_team} on {min_date_str})")
    print(f"Highest Elo ever: {global_max:.1f}  (achieved by {global_max_team} on {max_date_str})")

if __name__ == '__main__':
    main()