import pandas as pd
import numpy as np

# Load the CSV file (adjust file path as needed)
df = pd.read_csv(r'C:\Users\liam\Documents\GitHub\Footballdata\data\top5combined\top5leaguesdata-playerdata2026.csv', encoding='utf-8-sig')
# The skiprows list removes the repeated header rows that appear every 25 rows.

# 2. Clean column names (strip spaces)
df.columns = df.columns.str.strip()

# 3. Find the player column (case-insensitive)
player_col = None
for col in df.columns:
    if 'player' in col.lower():
        player_col = col
        break
if player_col is None:
    raise KeyError("No column with 'Player' found. Columns: " + str(df.columns.tolist()))

# 4. Remove repeated header rows (where player column equals 'Player')
df = df[df[player_col] != 'Player'].copy()

# 5. Define all columns that should be numeric
numeric_columns = [
    'MP', 'Starts', 'Min', '90s', 'Gls', 'Ast', 'G+A',
    'G-PK', 'PK', 'PKatt', 'CrdY', 'CrdR', 'Age'
]

# 6. Convert each to numeric (coerce errors to NaN)
for col in numeric_columns:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce')

# 7. Drop rows where essential stats are missing (we need Min, 90s, Gls, Ast, Age)
df = df.dropna(subset=['Min', '90s', 'Gls', 'Ast', 'Age'])

# 8. Compute per-90 stats
df['Gls_per90'] = df['Gls'] / df['90s'].replace(0, np.nan)
df['Ast_per90'] = df['Ast'] / df['90s'].replace(0, np.nan)
df['G+A_per90'] = df['Gls_per90'] + df['Ast_per90']
df[['Gls_per90', 'Ast_per90', 'G+A_per90']] = df[['Gls_per90', 'Ast_per90', 'G+A_per90']].fillna(0)

# 9. Position multiplier
def position_multiplier(pos):
    if pd.isna(pos):
        return 1.0
    pos = str(pos)
    if 'FW' in pos:
        return 1.5
    elif 'MF' in pos:
        return 1.0
    elif 'DF' in pos:
        return 0.7
    elif 'GK' in pos:
        return 0.3
    else:
        return 1.0
df['PosMultiplier'] = df['Pos'].apply(position_multiplier)

# 10. Age factor (now Age is numeric)
def age_factor(age):
    if pd.isna(age):
        return 1.0
    if age < 23:
        return 1.3
    elif age < 28:
        return 1.0
    elif age < 32:
        return 0.8
    else:
        return 0.6
df['AgeFactor'] = df['Age'].apply(age_factor)

# 11. Minutes factor (full season ~2700 min)
df['MinFactor'] = df['Min'] / 2700
df['MinFactor'] = df['MinFactor'].clip(upper=1.0)

# 12. Card penalty
df['CardPenalty'] = 1 - (df['CrdY'] * 0.01 + df['CrdR'] * 0.03)
df['CardPenalty'] = df['CardPenalty'].clip(lower=0.5)

# 13. Base value (15 million per G+A per 90)
df['BaseValue'] = df['G+A_per90'] * 15

# 14. Final estimated market value (in million €)
df['MarketValue_est'] = (df['BaseValue'] * df['PosMultiplier'] * 
                         df['AgeFactor'] * df['MinFactor'] * df['CardPenalty']).round(2)
df['MarketValue_est'] = df['MarketValue_est'].clip(upper=150)

# 15. Show top 10
print("\nTop 10 players by estimated market value:")
print(df[['Player', 'Squad', 'Comp', 'Pos', 'G+A_per90', 'Age', 'MarketValue_est']]
      .sort_values('MarketValue_est', ascending=False).head(10))