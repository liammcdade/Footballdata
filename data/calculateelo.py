# elo.py
# Local Elo calculator — reads one or more CSVs, processes chronologically,
# carries Elo state seamlessly across sources, and drops unwanted rows per source.

from pathlib import Path
import pandas as pd

# ============================================================
# PATHS
# ============================================================
DATA_DIR = Path(r"C:\Users\liam\Documents\GitHub\Footballdata\data\ENGLAND\Premier league\GAMES")

# ============================================================
# STANDARD COLUMN NAMES (internal use)
# ============================================================
STD_DATE, STD_SEASON = "Date", "Season"
STD_HOME, STD_AWAY   = "HomeTeam", "AwayTeam"
STD_HG,   STD_AG     = "hGoal", "aGoal"

# ============================================================
# ELO PARAMETERS
# ============================================================
K                 = 20      # update step
HOME_ADV          = 65      # Elo points added to home side
START_ELO         = 1500
SEASON_REGRESSION = 0.25    # pull toward 1500 between seasons (0 = off)

# ============================================================
# COLUMN MAPPING  (standard name -> whatever each CSV calls it)
# Adjust this once you see what the Premier League CSVs look like.
# The script will try each candidate name and use the first that exists.
# ============================================================
COLUMN_CANDIDATES = {
    STD_DATE:   ["Date", "date", "MatchDate", "match_date"],
    STD_SEASON: ["Season", "season"],
    STD_HOME:   ["HomeTeam", "home_team", "Home", "home"],
    STD_AWAY:   ["AwayTeam", "away_team", "Away", "away"],
    STD_HG:     ["hGoal", "FTHG", "home_goals", "HomeGoals", "HG"],
    STD_AG:     ["aGoal", "FTAG", "away_goals", "AwayGoals", "AG"],
}

def pick(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None

# ============================================================
# LOADER — reads every CSV in DATA_DIR (recursively)
# ============================================================
def load_all(data_dir: Path):
    files = sorted(data_dir.rglob("*.csv"))
    print(f"Found {len(files)} CSV file(s) in {data_dir}")

    frames = []
    for f in files:
        try:
            df = pd.read_csv(f, low_memory=False)
        except Exception as e:
            print(f"  ! Skipping {f.name}: {e}")
            continue

        rename = {}
        for std, cands in COLUMN_CANDIDATES.items():
            col = pick(df, cands)
            if col is None:
                print(f"  ! {f.name}: no column found for {std} (tried {cands})")
                rename = None
                break
            rename[col] = std

        if not rename:
            continue

        df = df.rename(columns=rename)
        df = df[[STD_DATE, STD_SEASON, STD_HOME, STD_AWAY, STD_HG, STD_AG]].copy()

        # Type clean-up
        df[STD_DATE] = pd.to_datetime(df[STD_DATE], errors="coerce", dayfirst=False)
        df = df.dropna(subset=[STD_DATE, STD_HOME, STD_AWAY, STD_HG, STD_AG])
        df[STD_HG] = df[STD_HG].astype(int)
        df[STD_AG] = df[STD_AG].astype(int)

        df["_source"] = str(f)
        frames.append(df)
        print(f"  + {f.name}: {len(df)} rows")

    if not frames:
        raise SystemExit("No usable CSVs found.")

    return pd.concat(frames, ignore_index=True)

# ============================================================
# ELO MATH
# ============================================================
def expected(elo_a, elo_b):
    return 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))

def actual(hg, ag):
    return 1.0 if hg > ag else 0.0 if hg < ag else 0.5

# ============================================================
# RUN
# ============================================================
def run_elo(matches):
    matches = matches.sort_values(STD_DATE).reset_index(drop=True)

    elo = {}
    history = []
    last_season = None

    for _, row in matches.iterrows():
        season = row[STD_SEASON]
        home, away = row[STD_HOME], row[STD_AWAY]

        if last_season is not None and season != last_season and SEASON_REGRESSION > 0:
            for t in elo:
                elo[t] += SEASON_REGRESSION * (START_ELO - elo[t])
        last_season = season

        elo.setdefault(home, START_ELO)
        elo.setdefault(away, START_ELO)

        exp_h = expected(elo[home] + HOME_ADV, elo[away])
        act_h = actual(row[STD_HG], row[STD_AG])

        elo[home] += K * (act_h - exp_h)
        elo[away] += K * ((1 - act_h) - (1 - exp_h))

        history.append({
            "Date":     row[STD_DATE],
            "Season":   season,
            "HomeTeam": home,
            "AwayTeam": away,
            "hGoal":    row[STD_HG],
            "aGoal":    row[STD_AG],
            "HomeElo":  elo[home],
            "AwayElo":  elo[away],
            "Source":   row["_source"],
        })

    return pd.DataFrame(history), elo

# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    matches = load_all(DATA_DIR)
    print(f"\nTotal matches loaded: {len(matches)}")

    history, final = run_elo(matches)

    hist_path  = DATA_DIR / "elo_history.csv"
    final_path = DATA_DIR / "elo_final.csv"

    history.to_csv(hist_path, index=False)

    final_df = (
        pd.DataFrame(sorted(final.items(), key=lambda x: -x[1]),
                     columns=["Team", "Elo"])
    )
    final_df.to_csv(final_path, index=False)

    print(f"\nWrote {hist_path}")
    print(f"Wrote {final_path}")
    print()
    print(final_df.head(20).to_string(index=False))