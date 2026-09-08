# dashboard.py
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ------------------------------------------------------------
# Page configuration
st.set_page_config(page_title="Premier League Player Dashboard", layout="wide")
st.title("⚽ Premier League Player Analysis Dashboard")

# ------------------------------------------------------------
# Load and clean data
@st.cache_data
def load_data():
    df = pd.read_csv("C:/Users/liam/Documents/GitHub/Footballdata/data/ENGLAND/Premier league/PLAYERS/league-players.csv", delimiter=";", decimal=".", encoding="utf-8-sig")
    df.columns = df.columns.str.strip()
    numeric_cols = [
        'apps', 'min', 'goals', 'NPG', 'a', 'xG', 'NPxG', 'xA',
        'xGChain', 'xGBuildup', 'xG90', 'NPxG90', 'xA90',
        'xG90xA90', 'NPxG90xA90', 'xGChain90', 'xGBuildup90'
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df.fillna(0, inplace=True)
    # Derived metrics
    df['goals_per90'] = (df['goals'] / df['min']) * 90
    df['assists_per90'] = (df['a'] / df['min']) * 90
    df['npg_per90'] = (df['NPG'] / df['min']) * 90
    df['xg_goals_diff'] = df['xG'] - df['goals']
    df['xG90_xA90'] = df['xG90'] + df['xA90']
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df.fillna(0, inplace=True)
    return df

df = load_data()

# ------------------------------------------------------------
# Sidebar filters
st.sidebar.header("Filters")

# Team filter
all_teams = sorted(df['team'].unique())
selected_teams = st.sidebar.multiselect(
    "Select Team(s)", all_teams, default=all_teams[:5]
)

# Minutes filter
min_minutes = st.sidebar.slider(
    "Minimum minutes played", 0, int(df['min'].max()), 0
)

# Metric selector for top table
metric_options = {
    "Goals": "goals",
    "Assists": "a",
    "Expected Goals (xG)": "xG",
    "Non-Penalty xG": "NPxG",
    "Expected Assists (xA)": "xA",
    "xG per 90": "xG90",
    "xA per 90": "xA90",
    "xG + xA per 90": "xG90_xA90",
    "Goals per 90": "goals_per90",
    "Assists per 90": "assists_per90"
}
selected_metric = st.sidebar.selectbox(
    "Metric for Top Players", list(metric_options.keys())
)

# Apply filters
filtered_df = df[df['team'].isin(selected_teams)]
filtered_df = filtered_df[filtered_df['min'] >= min_minutes]

# ------------------------------------------------------------
# Dashboard Tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📊 Top Players", "📈 Distributions", "🔍 Scatter Plots", "🏆 Team Comparison", "🔥 Correlation"]
)

# ------------------------------------------------------------
# Tab 1: Top Players Table
# Tab 1: Top Players Table
with tab1:
    st.subheader(f"Top Players by {selected_metric}")
    metric_col = metric_options[selected_metric]
    
    # Define the columns we always want to show
    base_cols = ['player', 'team', 'apps', 'min', 'goals', 'a', 'xG', 'xA', 'xG90', 'xA90']
    
    # Build display columns: include metric_col only if it's not already in base_cols
    if metric_col not in base_cols:
        display_cols = base_cols + [metric_col]
    else:
        display_cols = base_cols  # metric already present, no duplication
    
    # Get top 20 players sorted by the selected metric
    top_players = filtered_df.nlargest(20, metric_col)[display_cols]
    
    # Display the table (use width='stretch' to avoid deprecation warning)
    st.dataframe(top_players, width='stretch')
    
    # Bar chart for top 10
    fig = px.bar(
        top_players.head(10),
        x=metric_col,
        y='player',
        color='team',
        title=f"Top 10 Players – {selected_metric}",
        orientation='h',
        height=500
    )
    st.plotly_chart(fig, use_container_width=True)
# ------------------------------------------------------------
# Tab 2: Distributions
with tab2:
    st.subheader("Distribution of Key Metrics")
    col1, col2 = st.columns(2)
    with col1:
        fig_hist_goals = px.histogram(
            filtered_df, x='goals', nbins=20,
            title="Goals Distribution", labels={'goals': 'Goals'}
        )
        st.plotly_chart(fig_hist_goals, use_container_width=True)
    with col2:
        fig_hist_xg = px.histogram(
            filtered_df, x='xG', nbins=20,
            title="Expected Goals (xG) Distribution", labels={'xG': 'xG'}
        )
        st.plotly_chart(fig_hist_xg, use_container_width=True)

    col3, col4 = st.columns(2)
    with col3:
        fig_hist_assists = px.histogram(
            filtered_df, x='a', nbins=20,
            title="Assists Distribution", labels={'a': 'Assists'}
        )
        st.plotly_chart(fig_hist_assists, use_container_width=True)
    with col4:
        fig_hist_xa = px.histogram(
            filtered_df, x='xA', nbins=20,
            title="Expected Assists (xA) Distribution", labels={'xA': 'xA'}
        )
        st.plotly_chart(fig_hist_xa, use_container_width=True)

# ------------------------------------------------------------
# Tab 3: Scatter Plots
with tab3:
    st.subheader("Relationship Between Metrics")
    col1, col2 = st.columns(2)
    with col1:
        fig_scatter1 = px.scatter(
            filtered_df,
            x='xG', y='goals',
            color='team',
            hover_data=['player'],
            title="xG vs Goals (over/underperformance)",
            labels={'xG': 'Expected Goals', 'goals': 'Actual Goals'}
        )
        # Add identity line
        max_val = max(filtered_df['xG'].max(), filtered_df['goals'].max())
        fig_scatter1.add_shape(
            type='line', x0=0, y0=0, x1=max_val, y1=max_val,
            line=dict(dash='dash', color='gray')
        )
        st.plotly_chart(fig_scatter1, use_container_width=True)

    with col2:
        fig_scatter2 = px.scatter(
            filtered_df,
            x='xG90', y='xA90',
            color='team',
            hover_data=['player'],
            title="Threat (xG90) vs Creativity (xA90)",
            labels={'xG90': 'xG per 90', 'xA90': 'xA per 90'}
        )
        st.plotly_chart(fig_scatter2, use_container_width=True)

# ------------------------------------------------------------
# Tab 4: Team Comparison
with tab4:
    st.subheader("Team Averages and Aggregates")
    # Aggregate by team
    team_stats = filtered_df.groupby('team').agg(
        avg_goals=('goals', 'mean'),
        avg_xG=('xG', 'mean'),
        avg_xA=('xA', 'mean'),
        total_goals=('goals', 'sum'),
        total_xG=('xG', 'sum'),
        total_xA=('xA', 'sum'),
        avg_xG90=('xG90', 'mean'),
        avg_xA90=('xA90', 'mean'),
        players=('player', 'count')
    ).reset_index()

    # Show top teams by average xG90
    top_teams = team_stats.nlargest(10, 'avg_xG90')
    fig_team = px.bar(
        top_teams,
        x='avg_xG90',
        y='team',
        color='team',
        title="Top 10 Teams by Average xG per 90",
        orientation='h',
        labels={'avg_xG90': 'Average xG90'}
    )
    st.plotly_chart(fig_team, use_container_width=True)

    # Boxplot of goals by team (for teams with at least 2 players)
    team_counts = filtered_df['team'].value_counts()
    teams_with_enough = team_counts[team_counts >= 2].index.tolist()
    if teams_with_enough:
        box_df = filtered_df[filtered_df['team'].isin(teams_with_enough)]
        fig_box = px.box(
            box_df,
            x='team',
            y='goals',
            color='team',
            title="Goals Distribution by Team",
            labels={'goals': 'Goals'}
        )
        st.plotly_chart(fig_box, use_container_width=True)

# ------------------------------------------------------------
# Tab 5: Correlation Heatmap
with tab5:
    st.subheader("Correlation Matrix of Key Metrics")
    corr_cols = ['goals', 'a', 'xG', 'NPxG', 'xA', 'xG90', 'xA90',
                 'xGChain90', 'xGBuildup90', 'goals_per90', 'assists_per90']
    corr = filtered_df[corr_cols].corr()
    fig_corr = go.Figure(data=go.Heatmap(
        z=corr.values,
        x=corr.columns,
        y=corr.columns,
        colorscale='RdBu_r',
        zmid=0,
        text=corr.values.round(2),
        texttemplate='%{text}',
        textfont={"size": 10},
        hoverongaps=False
    ))
    fig_corr.update_layout(
        title="Correlation Matrix",
        width=800,
        height=700
    )
    st.plotly_chart(fig_corr, use_container_width=True)

# ------------------------------------------------------------
# Footer
st.sidebar.markdown("---")
st.sidebar.info("Dashboard built with Streamlit & Plotly.")