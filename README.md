# Football Data & Analysis Repository

This repository contains a comprehensive collection of clean, historical football (soccer) datasets spanning domestic leagues, international fixtures, FIFA World Cups, and player-level analytics, alongside Python analysis scripts and data tools.

- **Total CSV files:** 147
- **Total data points (numeric cells):** 4,063,466
- **Temporal Scope:** 1993/94 Season to Present / Future Projections (2026+)

---

## 📋 Data Collections & Coverage

### 1. English Football Pyramid (`data/ENGLAND/`)
Comprehensive season-by-season match logs and results across five tiers of English professional football:

| Tier | Modern Name | Directory Path | Seasons / Scope | Matches Per Season |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 1** | Premier League | `data/ENGLAND/Premier league/GAMES/` | 1993/94 – 2026/27 | 380 (462 in 93/94 & 94/95) |
| **Tier 2** | EFL Championship | `data/ENGLAND/championship/games/` | 1993/94 – 2025/26 | 552 |
| **Tier 3** | EFL League One | `data/ENGLAND/League1/games/` | 1993/94 – 2025/26 | 552 |
| **Tier 4** | EFL League Two | `data/ENGLAND/League2/games/` | 1993/94 – 2025/26 | 552 |
| **Tier 6** | National League North | `data/ENGLAND/nationalleaguenorth/` | 2022 – 2026 (Flat CSVs) | Flat fixtures/results |

### 2. International Football (`data/international/`)
* **Match Results:** Historical international match results (`data/international/games/results.csv`) covering global international fixtures, goalscorers, and match outcomes.

### 3. World Cup Datasets (`data/worldcup/`)
* **2022 FIFA World Cup:** Squad listings and player statistics (`2022squad.csv`, `2022players.csv`).
* **2026 FIFA World Cup:** Projected and current squad listings and player rosters (`2026squad.csv`, `2026players.csv`).

### 4. Top 5 European Leagues (`data/top5combined/`)
Combined data covering Europe's top five domestic leagues (Premier League, La Liga, Serie A, Bundesliga, Ligue 1):
* **Team Data (`team/`):** Annual aggregated team statistics for 2021, 2022, 2023, 2024, and 2025.
* **Player Data:** Comprehensive player-level performance metrics for 2026 (`top5leaguesdata-playerdata2026.csv`).

---

## 📊 Core Data Features

### Match Datasets (`.csv`)
Standard match logs contain:
* **Identification:** `Date`, `HomeTeam`, `AwayTeam` (standardized team names).
* **Match Outcomes:** `FTHG` (Full-Time Home Goals), `FTAG` (Full-Time Away Goals), `FTR` (Full-Time Result: `H` = Home Win, `D` = Draw, `A` = Away Win).
* **Interval Stats:** `HTHG`, `HTAG`, `HTR` (Half-Time goals and result, where available).
* **In-Game Statistics:** Shots, shots on target, corners, fouls, yellow/red cards (varies by vintage and league).
* **Betting Market Data:** Odds from major bookmakers (e.g., Bet365, Ladbrokes, William Hill) where available.

---

## 🛠️ Analysis & Utility Scripts

The repository includes several Python scripts for dataset maintenance, analytics, and modeling:

* **`datapointcounter.py`**
  Recursively scans all `.csv` files in the repository, counts non-empty numeric data points, and automatically updates the total summary figures in `README.md`.
  ```bash
  python datapointcounter.py .
  ```

* **`data/calculateelo.py`**
  Calculates league-weighted Elo ratings for English football clubs across all historical fixtures, tracking team expected vs. actual performance deviations and identifying each club's most and least favourable opponents.

* **`data/averagegoals.py`**
  Scans match CSV files to aggregate total, home, and away goal averages per game across folders, identifying historical high-scoring and low-scoring seasons.

* **Scraping & Renaming Utilities (`data/ENGLAND/League2/games/`)**
  * `main.py`: Automated script to fetch historical season CSVs from Football-Data.co.uk.
  * `python.py`: Utility script to parse match dates in CSVs and standardize file names based on detected season date ranges (e.g., `1993-1994.csv`).
