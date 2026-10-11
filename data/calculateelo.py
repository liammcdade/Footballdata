"""
Premier League Elo + Season Simulator

NFL-inspired improvements over the original:
- Signed Elo difference in the dynamic K (upsets move ratings more)
- Gaussian draw model centred on Elo difference
- Explicit home advantage
- Neutral-venue support
- Interactive mode to record real results
"""

import os
import csv
import random
import math
from collections import defaultdict, Counter
from datetime import datetime

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    def tqdm(iterable, **kwargs):
        return iterable

# ==========================================================
# CONFIGURATION
# ==========================================================
INITIAL_RATING = 1500
HOME_ADV = 65             # Elo points added to home team
ELO_SCALE = 400           # standard Elo scale
DRAW_SIGMA = 250          # how quickly draw prob decays with Elo gap
DRAW_PEAK = 0.285          # peak draw probability at equal Elo
BASE_K = 20               # base K for dynamic formula
N_SIMS = 10000
MIN_PERCENT = 0.05
MIN_ABSOLUTE = 3

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
    ("Bournemouth", "Brentford"): (2, 2),
    ("Aston Villa", "Nott'm Forest"): (1, 2),
    ("Chelsea", "Hull"): (2, 2),
    ("Crystal Palace", "Ipswich"): (2, 3),
    ("Liverpool", "Fulham"): (0, 0),
}

# Neutral-venue fixtures, keyed by (home, away) as they appear in the season file
NEUTRAL_VENUES = set()

# ==========================================================
# CORE PROBABILITY MODEL
# ==========================================================
def outcome_probs(r_home, r_away, is_neutral=False, draw_peak=DRAW_PEAK):
    """
    Returns (p_home, p_draw, p_away, exp_home).
    Draw probability is a Gaussian centred on the Elo difference
    (after home advantage is applied).
    """
    diff = (r_home + (0 if is_neutral else HOME_ADV)) - r_away

    p_draw = draw_peak * math.exp(-0.5 * (diff / DRAW_SIGMA) ** 2)
    p_draw = max(0.01, min(0.55, p_draw))

    p_home_given_no_draw = 1.0 / (1.0 + 10.0 ** (-diff / ELO_SCALE))
    p_home = p_home_given_no_draw * (1 - p_draw)
    p_away = (1 - p_home_given_no_draw) * (1 - p_draw)

    exp_home = p_home + 0.5 * p_draw
    return p_home, p_draw, p_away, exp_home


def calculate_dynamic_k(r_winner, r_loser, margin, base_k=BASE_K):
    """
    FiveThirtyEight-style dynamic K using the SIGNED Elo difference.
    Upsets (lower-rated winner) get a larger K.
    Expected results get a smaller K.
    """
    pd = abs(margin)
    elo_diff = r_winner - r_loser   # signed!

    denom = 0.001 * elo_diff + 2.2
    if denom < 0.1:
        denom = 0.1

    k = base_k * math.log(pd + 1) * (2.2 / denom)
    return max(1.0, min(k, 80.0))


# ==========================================================
# DATE PARSING
# ==========================================================
def parse_date(date_str):
    date_str = date_str.strip()
    if not date_str:
        return None
    if ' ' in date_str:
        date_str = date_str.split(' ')[0]
    for fmt in ('%d/%m/%Y', '%d/%m/%y'):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


# ==========================================================
# READ ALL MATCHES
# ==========================================================
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
            print(f"Warning: Unknown league '{league}' - using weight 1.0")

        for enc in ('utf-8-sig', 'latin-1', 'cp1252'):
            try:
                with open(f, 'r', encoding=enc) as infile:
                    reader = csv.reader(infile)
                    header = next(reader, None)
                    if header is None:
                        continue
                    col_map = {name.strip().lower(): idx for idx, name in enumerate(header)}

                    required = ['hometeam', 'awayteam', 'fthg', 'ftag', 'ftr']
                    if not all(col in col_map for col in required):
                        print(f"Warning: {rel} missing required columns; skipping.")
                        break

                    has_date = 'date' in col_map
                    if not has_date and weight > 0.2:
                        print(f"Warning: {rel} has no date column and weight > 0.2; skipping.")
                        break

                    idx_home = col_map['hometeam']
                    idx_away = col_map['awayteam']
                    idx_hg   = col_map['fthg']
                    idx_ag   = col_map['ftag']
                    idx_res  = col_map['ftr']
                    idx_date = col_map.get('date', -1)

                    for row in reader:
                        if len(row) <= max(idx_home, idx_away, idx_hg, idx_ag, idx_res):
                            continue
                        home = row[idx_home].strip()
                        away = row[idx_away].strip()
                        ftr  = row[idx_res].strip()
                        if not home or not away or not ftr:
                            continue
                        try:
                            hg = int(row[idx_hg].strip()) if row[idx_hg].strip() else 0
                            ag = int(row[idx_ag].strip()) if row[idx_ag].strip() else 0
                        except (ValueError, IndexError):
                            hg = ag = 0

                        if has_date and idx_date != -1 and len(row) > idx_date:
                            dt = parse_date(row[idx_date].strip())
                            if dt is None and weight > 0.2:
                                continue
                            elif dt is None:
                                dt = datetime(2000, 1, 1)
                        else:
                            dt = datetime(2000, 1, 1)

                        matches.append((dt, home, away, hg, ag, ftr, weight))
                break
            except UnicodeDecodeError:
                continue
        else:
            print(f"Warning: Could not read {rel} with any encoding; skipping.")

    print(f"Total matches read: {len(matches)}")
    return sorted(matches, key=lambda x: x[0])


# ==========================================================
# COMPUTE ELO AND PERFORMANCE
# ==========================================================
def compute_elo_and_performance(matches, draw_peak=DRAW_PEAK):
    ratings = defaultdict(lambda: INITIAL_RATING)
    performance = defaultdict(lambda: defaultdict(lambda: {
        'count': 0,
        'weighted_actual': 0.0,
        'weighted_expected': 0.0,
        'weighted_count': 0.0,
    }))
    extremes = defaultdict(lambda: {
        'min': (INITIAL_RATING, None),
        'max': (INITIAL_RATING, None),
    })

    for dt, home, away, home_goals, away_goals, ftr, weight in matches:
        Rh = ratings[home]
        Ra = ratings[away]

        is_neutral = (home, away) in NEUTRAL_VENUES
        p_home, p_draw, p_away, Eh = outcome_probs(Rh, Ra, is_neutral, draw_peak)
        Ea = 1.0 - Eh

        if ftr == 'H':
            ah, aa = 1.0, 0.0
        elif ftr == 'A':
            ah, aa = 0.0, 1.0
        else:
            ah, aa = 0.5, 0.5

        gd = abs(home_goals - away_goals)
        if gd == 0:
            k = BASE_K * weight
        else:
            if home_goals > away_goals:
                winner_rating, loser_rating = Rh, Ra
            else:
                winner_rating, loser_rating = Ra, Rh
            k = calculate_dynamic_k(winner_rating, loser_rating, gd, BASE_K) * weight

        new_Rh = Rh + k * (ah - Eh)
        new_Ra = Ra + k * (aa - Ea)
        ratings[home] = new_Rh
        ratings[away] = new_Ra

        if new_Rh < extremes[home]['min'][0]:
            extremes[home]['min'] = (new_Rh, dt)
        if new_Rh > extremes[home]['max'][0]:
            extremes[home]['max'] = (new_Rh, dt)
        if new_Ra < extremes[away]['min'][0]:
            extremes[away]['min'] = (new_Ra, dt)
        if new_Ra > extremes[away]['max'][0]:
            extremes[away]['max'] = (new_Ra, dt)

        perf_home = performance[home][away]
        perf_home['count'] += 1
        perf_home['weighted_actual']   += weight * ah
        perf_home['weighted_expected'] += weight * Eh
        perf_home['weighted_count']    += weight

        perf_away = performance[away][home]
        perf_away['count'] += 1
        perf_away['weighted_actual']   += weight * aa
        perf_away['weighted_expected'] += weight * Ea
        perf_away['weighted_count']    += weight

    return ratings, performance, extremes


# ==========================================================
# PERFORMANCE ANALYSIS
# ==========================================================
def analyse_performance(performance):
    results = {}
    for team, opponents in performance.items():
        team_total = sum(stats['count'] for stats in opponents.values())
        min_games = max(MIN_ABSOLUTE, int(MIN_PERCENT * team_total))

        valid_opponents = {}
        for opp, stats in opponents.items():
            if stats['count'] < min_games:
                continue
            wc = stats['weighted_count']
            if wc == 0:
                continue
            wa = stats['weighted_actual'] / wc
            we = stats['weighted_expected'] / wc
            valid_opponents[opp] = {
                'count': stats['count'],
                'avg_dev': wa - we,
                'avg_actual': wa,
                'avg_expected': we,
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
            'all': valid_opponents,
        }
    return results


# ==========================================================
# SEASON FILE READER
# ==========================================================
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
            idx_hg   = col_map['fthg']
            idx_ag   = col_map['ftag']
            idx_res  = col_map['ftr']

            for row in reader:
                if len(row) <= max(idx_home, idx_away, idx_hg, idx_ag, idx_res):
                    continue
                home = row[idx_home].strip()
                away = row[idx_away].strip()
                ftr  = row[idx_res].strip()
                if not home or not away or not ftr:
                    continue
                try:
                    hg = int(row[idx_hg].strip()) if row[idx_hg].strip() else 0
                    ag = int(row[idx_ag].strip()) if row[idx_ag].strip() else 0
                except (ValueError, IndexError):
                    continue
                teams.add(home); teams.add(away)
                played.add((home, away))
                if ftr == 'H':
                    points[home] += 3
                elif ftr == 'A':
                    points[away] += 3
                else:
                    points[home] += 1
                    points[away] += 1

        if extra_results:
            for (home, away), (hg, ag) in extra_results.items():
                teams.add(home); teams.add(away)
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


def get_losses_from_season_file(file_path, extra_results=None):
    losses = defaultdict(int)
    try:
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return losses
            col_map = {name.strip().lower(): idx for idx, name in enumerate(header)}
            required = ['hometeam', 'awayteam', 'ftr']
            if not all(col in col_map for col in required):
                return losses
            idx_home = col_map['hometeam']
            idx_away = col_map['awayteam']
            idx_res  = col_map['ftr']
            for row in reader:
                if len(row) <= max(idx_home, idx_away, idx_res):
                    continue
                home = row[idx_home].strip()
                away = row[idx_away].strip()
                ftr  = row[idx_res].strip()
                if not home or not away or not ftr:
                    continue
                if ftr == 'H':
                    losses[away] += 1
                elif ftr == 'A':
                    losses[home] += 1
        if extra_results:
            for (home, away), (hg, ag) in extra_results.items():
                if hg > ag:
                    losses[away] += 1
                elif hg < ag:
                    losses[home] += 1
        return losses
    except Exception as e:
        print(f"Error reading {file_path} for losses: {e}")
        return losses


# ==========================================================
# SEASON SIMULATION
# ==========================================================
def simulate_season(ratings, current_points, played_fixtures, all_teams,
                    gd_distribution, num_simulations=N_SIMS,
                    current_losses=None, draw_peak=DRAW_PEAK):
    if current_losses is None:
        current_losses = defaultdict(int)

    all_fixtures = [(h, a) for h in all_teams for a in all_teams if h != a]
    remaining = [fix for fix in all_fixtures if fix not in played_fixtures]

    if not remaining:
        print("No remaining fixtures to simulate.")
        return {}, {}, {'win': 0.0, 'loss': 0.0, 'draw': 0.0}, Counter(), 0.0

    counts = {team: {'win': 0, 'top4': 0, 'euro': 0, 'finish5': 0, 'relegation': 0}
              for team in all_teams}
    total_points = {team: 0.0 for team in all_teams}

    streak_win = 0
    streak_loss = 0
    streak_draw = 0
    relegation_triple_counter = Counter()
    unbeaten_count = 0

    iterator = tqdm(range(num_simulations), desc="Simulating seasons") if HAS_TQDM \
               else range(num_simulations)

    for _ in iterator:
        sim_ratings = ratings.copy()
        sim_points = current_points.copy()
        fixtures_order = remaining[:]
        random.shuffle(fixtures_order)

        results_seq = {team: [] for team in all_teams}
        simulated_losses = defaultdict(int)

        for home, away in fixtures_order:
            Rh = sim_ratings[home]
            Ra = sim_ratings[away]

            is_neutral = (home, away) in NEUTRAL_VENUES
            p_home, p_draw, p_away, Eh = outcome_probs(Rh, Ra, is_neutral, draw_peak)
            Ea = 1.0 - Eh

            r = random.random()
            if r < p_home:
                outcome = 'H'
                ah, aa = 1.0, 0.0
                res_pts_home, res_pts_away = 3, 0
                home_res, away_res = 'W', 'L'
                simulated_losses[away] += 1
            elif r < p_home + p_draw:
                outcome = 'D'
                ah, aa = 0.5, 0.5
                res_pts_home, res_pts_away = 1, 1
                home_res, away_res = 'D', 'D'
            else:
                outcome = 'A'
                ah, aa = 0.0, 1.0
                res_pts_home, res_pts_away = 0, 3
                home_res, away_res = 'L', 'W'
                simulated_losses[home] += 1

            gd_list = gd_distribution.get(outcome, [])
            if gd_list:
                gd = random.choice(gd_list)
            else:
                gd = {'H': 1, 'A': -1, 'D': 0}[outcome]

            if gd == 0:
                k = BASE_K
            else:
                if outcome == 'H':
                    winner_rating, loser_rating = Rh, Ra
                else:
                    winner_rating, loser_rating = Ra, Rh
                k = calculate_dynamic_k(winner_rating, loser_rating, abs(gd), BASE_K)

            sim_ratings[home] = Rh + k * (ah - Eh)
            sim_ratings[away] = Ra + k * (aa - Ea)
            sim_points[home] += res_pts_home
            sim_points[away] += res_pts_away

            results_seq[home].append(home_res)
            results_seq[away].append(away_res)

        # Unbeaten check
        unbeaten_hit = any(
            current_losses.get(t, 0) + simulated_losses.get(t, 0) == 0
            for t in all_teams
        )
        if unbeaten_hit:
            unbeaten_count += 1

        # Streak check
        win_streak_hit = loss_streak_hit = draw_streak_hit = False
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
                        if current == 'W':   win_streak_hit = True
                        elif current == 'L': loss_streak_hit = True
                        elif current == 'D': draw_streak_hit = True
                    current = res
                    count = 1
            if count >= 5:
                if current == 'W':   win_streak_hit = True
                elif current == 'L': loss_streak_hit = True
                elif current == 'D': draw_streak_hit = True
            if win_streak_hit and loss_streak_hit and draw_streak_hit:
                break
        if win_streak_hit:  streak_win += 1
        if loss_streak_hit: streak_loss += 1
        if draw_streak_hit: streak_draw += 1

        # Standings
        sorted_teams = sorted(
            all_teams,
            key=lambda t: (sim_points[t], random.random()),
            reverse=True
        )
        bottom3 = tuple(sorted(sorted_teams[-3:]))
        relegation_triple_counter[bottom3] += 1

        for rank, team in enumerate(sorted_teams, start=1):
            if rank == 1:  counts[team]['win'] += 1
            if rank <= 4:  counts[team]['top4'] += 1
            if rank <= 5:  counts[team]['euro'] += 1
            if rank == 5:  counts[team]['finish5'] += 1
            if rank >= 18: counts[team]['relegation'] += 1

        for team in all_teams:
            total_points[team] += sim_points[team]

    for team in counts:
        for key in counts[team]:
            counts[team][key] = counts[team][key] / num_simulations * 100.0
    for team in total_points:
        total_points[team] /= num_simulations

    streak_probs = {
        'win':  streak_win  / num_simulations * 100.0,
        'loss': streak_loss / num_simulations * 100.0,
        'draw': streak_draw / num_simulations * 100.0,
    }
    unbeaten_prob = unbeaten_count / num_simulations * 100.0

    return counts, total_points, streak_probs, relegation_triple_counter, unbeaten_prob


# ==========================================================
# INTERACTIVE MODE
# ==========================================================
def interactive_mode(ratings, remaining_fixtures, draw_peak=DRAW_PEAK):
    """
    Simple interactive loop:
      - 'list'      : show all remaining fixtures with predictions
      - 'record'    : record a result (prompts for teams and score)
      - 'q'         : quit
    """
    elo = ratings.copy()
    remaining = list(remaining_fixtures)

    print("\n" + "=" * 70)
    print("INTERACTIVE MODE - Predict & Record Results")
    print("=" * 70)
    print("Commands:")
    print("  list    - show remaining fixtures with predictions")
    print("  record  - record a real result and update Elo")
    print("  q       - quit")
    print("=" * 70)

    while True:
        cmd = input("\nCommand: ").strip().lower()
        if cmd == 'q':
            break

        if cmd == 'list':
            if not remaining:
                print("No remaining fixtures.")
                continue
            for home, away in remaining:
                Rh, Ra = elo[home], elo[away]
                is_neutral = (home, away) in NEUTRAL_VENUES
                p_home, p_draw, p_away, _ = outcome_probs(Rh, Ra, is_neutral, draw_peak)
                diff = (Rh + (0 if is_neutral else HOME_ADV)) - Ra
                exp_margin = diff / 25.0   # rough: 25 Elo ~ 1 goal
                tag = " (neutral)" if is_neutral else ""
                print(f"{home:<25} vs {away:<25}{tag} "
                      f"H {p_home:.1%}  D {p_draw:.1%}  A {p_away:.1%}  "
                      f"Exp margin {exp_margin:+.2f}")

        elif cmd == 'record':
            home = input("Home team: ").strip()
            away = input("Away team: ").strip()
            if (home, away) not in remaining:
                # try reversed
                if (away, home) in remaining:
                    home, away = away, home
                    print("(Swapped to match fixture list)")
                else:
                    print("That fixture isn't in the remaining list.")
                    continue
            try:
                hg = int(input("Home goals: ").strip())
                ag = int(input("Away goals: ").strip())
            except ValueError:
                print("Invalid score.")
                continue

            Rh, Ra = elo[home], elo[away]
            is_neutral = (home, away) in NEUTRAL_VENUES
            p_home, p_draw, p_away, Eh = outcome_probs(Rh, Ra, is_neutral, draw_peak)
            Ea = 1.0 - Eh

            if hg > ag:
                ah, aa = 1.0, 0.0
            elif hg < ag:
                ah, aa = 0.0, 1.0
            else:
                ah, aa = 0.5, 0.5

            gd = abs(hg - ag)
            if gd == 0:
                k = BASE_K
            else:
                winner_rating, loser_rating = (Rh, Ra) if hg > ag else (Ra, Rh)
                k = calculate_dynamic_k(winner_rating, loser_rating, gd, BASE_K)

            elo[home] = Rh + k * (ah - Eh)
            elo[away] = Ra + k * (aa - Ea)
            remaining.remove((home, away))
            print(f"Recorded. New Elo: {home} {elo[home]:.1f} | {away} {elo[away]:.1f}")

        else:
            print("Unknown command.")


# ==========================================================
# MAIN
# ==========================================================
def main():
    data_dir = r'C:\Users\liam\Documents\GitHub\Footballdata\data\ENGLAND'
    if not os.path.isdir(data_dir):
        print(f"ERROR: Directory not found: {data_dir}")
        return

    print("Reading all matches...")
    matches = read_all_matches(data_dir)
    if not matches:
        print("No valid matches found.")
        return

    # Historical draw rate and goal-difference distributions (PL only)
    pl_matches = [m for m in matches if m[6] == 1.0]
    if pl_matches:
        draws = sum(1 for m in pl_matches if m[5] == 'D')
        hist_draw = draws / len(pl_matches)
        print(f"Premier League historical draw rate: {hist_draw:.3f} "
              f"({draws}/{len(pl_matches)})")

        gd_dist = {'H': [], 'A': [], 'D': []}
        for m in pl_matches:
            _, _, _, hg, ag, ftr, _ = m
            if ftr == 'H':
                gd_dist['H'].append(hg - ag)
            elif ftr == 'A':
                gd_dist['A'].append(hg - ag)
            else:
                gd_dist['D'].append(0)
        print(f"  Samples: H={len(gd_dist['H'])} "
              f"A={len(gd_dist['A'])} D={len(gd_dist['D'])}")
    else:
        hist_draw = 0.25
        gd_dist = {'H': [1], 'A': [-1], 'D': [0]}
        print("No PL matches found; using defaults.")

    # Scale draw peak so average roughly matches history
    # (Gaussian averages lower than its peak across a distribution of Elo gaps)
    draw_peak = min(0.55, hist_draw * 1.25)
    print(f"Using draw peak = {draw_peak:.3f}, sigma = {DRAW_SIGMA}")

    print("Computing Elo ratings and performance deviations...")
    ratings, performance, extremes = compute_elo_and_performance(matches, draw_peak)

    print("Analysing results...")
    analysis = analyse_performance(performance)
    for team, data in sorted(analysis.items()):
        best_opp, best_stats = data['best']
        worst_opp, worst_stats = data['worst']
        print(f"\nTeam: {team} (total matches: {data['total_matches']}, "
              f"min games vs opponent: {data['min_games']})")
        print(f"  Most favourable opponent: {best_opp}")
        print(f"    Games: {best_stats['count']}, "
              f"Avg Actual PPG: {best_stats['avg_actual']:.3f}, "
              f"Avg Expected PPG: {best_stats['avg_expected']:.3f}, "
              f"Deviation: {best_stats['avg_dev']:+.3f}")
        print(f"  Least favourable opponent: {worst_opp}")
        print(f"    Games: {worst_stats['count']}, "
              f"Avg Actual PPG: {worst_stats['avg_actual']:.3f}, "
              f"Avg Expected PPG: {worst_stats['avg_expected']:.3f}, "
              f"Deviation: {worst_stats['avg_dev']:+.3f}")

    print("\nFinal Elo ratings (top 10):")
    for team, rating in sorted(ratings.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  {team}: {rating:.1f}")

    # ----------------------------------------------------
    # Season simulation
    # ----------------------------------------------------
    season_file = (r'C:\Users\liam\Documents\GitHub\Footballdata\data\ENGLAND'
                   r'\Premier league\GAMES\2026-2027.csv')
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
                print(f"Warning: Expected 20 teams, found {len(all_teams)}.")

            current_ratings = {t: ratings.get(t, INITIAL_RATING) for t in all_teams}

            current_losses = get_losses_from_season_file(season_file, EXTRA_RESULTS)
            for t in all_teams:
                if t not in current_losses:
                    current_losses[t] = 0

            print(f"Running {N_SIMS} simulations...")
            sim_results, avg_points, streak_probs, rel_counter, unbeaten_prob = \
                simulate_season(
                    current_ratings, current_points, played, all_teams,
                    gd_dist, num_simulations=N_SIMS,
                    current_losses=current_losses, draw_peak=draw_peak
                )

            if sim_results:
                print("\n=== SIMULATION RESULTS (sorted by avg final points) ===\n")
                print(f"{'Team':<25} {'Curr':>6} {'Avg':>7} "
                      f"{'Win%':>7} {'Top4%':>7} {'5th%':>7} {'Euro%':>7} {'Rel%':>7}")
                print("-" * 90)
                for team in sorted(all_teams, key=lambda t: avg_points[t], reverse=True):
                    print(f"{team:<25} "
                          f"{current_points[team]:>6d} {avg_points[team]:>7.1f} "
                          f"{sim_results[team]['win']:>6.1f}% "
                          f"{sim_results[team]['top4']:>6.1f}% "
                          f"{sim_results[team]['finish5']:>6.1f}% "
                          f"{sim_results[team]['euro']:>6.1f}% "
                          f"{sim_results[team]['relegation']:>6.1f}%")

                print("\n=== STREAK PROBABILITIES (remaining fixtures) ===\n")
                print(f"ANY team wins 5 in a row:  {streak_probs['win']:6.2f}%")
                print(f"ANY team loses 5 in a row: {streak_probs['loss']:6.2f}%")
                print(f"ANY team draws 5 in a row: {streak_probs['draw']:6.2f}%")
                print(f"\nANY team goes unbeaten all season: {unbeaten_prob:6.2f}%")

                if rel_counter:
                    print("\n=== MOST LIKELY RELEGATION TRIPLE ===\n")
                    for triple, cnt in rel_counter.most_common(5):
                        p = cnt / N_SIMS * 100.0
                        print(f"  {', '.join(triple)}: {p:.2f}%")

                # Interactive mode on the remaining fixtures
                remaining = [(h, a) for h in all_teams for a in all_teams
                             if h != a and (h, a) not in played]
                interactive_mode(current_ratings, remaining, draw_peak)

    # ----------------------------------------------------
    # Global Elo extremes
    # ----------------------------------------------------
    print("\n=== GLOBAL ELO EXTREMES (all teams, all time) ===\n")
    global_min = global_max = None
    global_min_team = global_max_team = None
    global_min_date = global_max_date = None

    for team, ex in extremes.items():
        min_rating, min_date = ex['min']
        max_rating, max_date = ex['max']
        if global_min is None or min_rating < global_min:
            global_min, global_min_team, global_min_date = min_rating, team, min_date
        if global_max is None or max_rating > global_max:
            global_max, global_max_team, global_max_date = max_rating, team, max_date

    min_str = global_min_date.strftime('%Y-%m-%d') if global_min_date else "n/a"
    max_str = global_max_date.strftime('%Y-%m-%d') if global_max_date else "n/a"
    print(f"Lowest Elo ever:  {global_min:.1f}  ({global_min_team} on {min_str})")
    print(f"Highest Elo ever: {global_max:.1f}  ({global_max_team} on {max_str})")


if __name__ == '__main__':
    main()