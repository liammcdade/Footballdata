import pandas as pd
import numpy as np
import glob
import os

# ------------------------------
# 1. Read all season CSVs
# ------------------------------
data_dir = r'C:\Users\liam\Documents\GitHub\Footballdata\data\ENGLAND\Premier league\GAMES'
file_pattern = os.path.join(data_dir, '*.csv')
file_list = glob.glob(file_pattern)

# Keep only season files (e.g., 2005-2006.csv ... 2025-2026.csv)
season_files = [f for f in file_list if '-20' in os.path.basename(f)]
print(f"Found {len(season_files)} season files.")

df_list = []
for file in season_files:
    try:
        df_season = pd.read_csv(file, encoding='utf-8-sig')
        df_season.columns = df_season.columns.str.strip()
        if 'Date' in df_season.columns:
            df_season['Date'] = pd.to_datetime(df_season['Date'], format='%d/%m/%Y', errors='coerce')
        season_name = os.path.basename(file).replace('.csv', '')
        df_season['Season'] = season_name
        df_list.append(df_season)
    except Exception as e:
        print(f"Could not read {file}: {e}")

if not df_list:
    raise ValueError("No data loaded.")

df_all = pd.concat(df_list, ignore_index=True)
print(f"Total matches loaded: {len(df_all)}")

# ------------------------------
# 2. Compute Discipline Ratio (DisR)
# ------------------------------
df_all['DisR'] = (df_all['HY'] + df_all['AY'] + df_all['HR'] + df_all['AR']) / (df_all['HF'] + df_all['AF'] + 1e-6)

# ------------------------------
# 3. Assign season weights (more recent = higher weight)
# ------------------------------
seasons = sorted(df_all['Season'].unique())
# Linear weights: oldest = 1, newest = number of seasons
season_weight_map = {season: i+1 for i, season in enumerate(seasons)}
df_all['SeasonWeight'] = df_all['Season'].map(season_weight_map)

# ------------------------------
# 4. Separate home and away data
# ------------------------------
home_df = df_all[['HomeTeam', 'DisR', 'SeasonWeight']].rename(columns={'HomeTeam': 'Team'})
away_df = df_all[['AwayTeam', 'DisR', 'SeasonWeight']].rename(columns={'AwayTeam': 'Team'})

# Add a flag for home/away
home_df['IsHome'] = 1
away_df['IsHome'] = 0

all_data = pd.concat([home_df, away_df], ignore_index=True)

# ------------------------------
# 5. Compute weighted averages per team, split by home/away
# ------------------------------
def weighted_avg(df, values_col, weights_col):
    """Compute weighted average, return NaN if no weights."""
    total_weight = df[weights_col].sum()
    if total_weight == 0:
        return np.nan
    return (df[values_col] * df[weights_col]).sum() / total_weight

# Group by Team and IsHome
agg = all_data.groupby(['Team', 'IsHome']).apply(
    lambda g: pd.Series({
        'weighted_avg_DisR': weighted_avg(g, 'DisR', 'SeasonWeight'),
        'matches': len(g)
    })
).reset_index()

# Pivot to get home and away columns
pivot = agg.pivot(index='Team', columns='IsHome', values=['weighted_avg_DisR', 'matches'])
pivot.columns = ['Away_Avg', 'Home_Avg', 'Away_Matches', 'Home_Matches']
pivot = pivot.reset_index()

# Compute overall weighted average (home + away combined) for sorting
overall_agg = all_data.groupby('Team').apply(
    lambda g: weighted_avg(g, 'DisR', 'SeasonWeight')
).rename('Overall_Avg').reset_index()

# Merge
final = pd.merge(pivot, overall_agg, on='Team')
final = final[['Team', 'Home_Avg', 'Away_Avg', 'Overall_Avg', 'Home_Matches', 'Away_Matches']]

# Sort by overall aggression (or you can change to Home_Avg or Away_Avg)
final = final.sort_values('Overall_Avg', ascending=False)

# ------------------------------
# 6. Print and save results
# ------------------------------
print("\n" + "="*80)
print("TEAM EXPECTED AGGRESSION FOR 2026-2027 (Home vs Away, Weighted by Recency)")
print("(Higher value = more aggressive / more cards per foul)")
print("="*80)
print(final.to_string(index=False, float_format="%.3f"))

# Save to CSV
output_file = os.path.join(data_dir, 'team_aggression_home_away.csv')
final.to_csv(output_file, index=False)
print(f"\nTable saved to '{output_file}'")