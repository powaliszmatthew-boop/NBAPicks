# Save this file as nba_model.py
import os
import pandas as pd
import requests
# Using the official, open-source NBA API package
from nba_api.stats.endpoints import leaguegamefinder
from nba_api.stats.static import teams

# ---------------------------------------------------------
# CONSTANTS & CONFIGURATION
# ---------------------------------------------------------
# To run this seamlessly, get a free API key from https://the-odds-api.com
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "YOUR_FREE_ODDS_API_KEY")
SPORT_KEY = "basketball_nba"
REGIONS = "us"
MARKETS = "spreads"

# Ensure output directory exists
os.makedirs("generated", exist_ok=True)

print("🏀 Fetching current NBA team list and historical game data...")

# 1. Fetch historical NBA games to calculate fundamental team strengths
nba_teams = teams.get_teams()
# Map TEAM_ID -> full name so names match The Odds API (e.g. "Los Angeles Clippers", not "LA Clippers")
team_id_to_name = {t['id']: t['full_name'] for t in nba_teams}

game_finder = leaguegamefinder.LeagueGameFinder(
    league_id_nullable='00',
    season_type_nullable='Regular Season',
)
games_df = game_finder.get_data_frames()[0]

# Filter for recent seasons (e.g., current 2026 or late 2025 data)
games_df['GAME_DATE'] = pd.to_datetime(games_df['GAME_DATE'])
recent_games = games_df[games_df['GAME_DATE'] >= '2025-10-01'].copy()
recent_games = recent_games[recent_games['TEAM_ID'].isin(team_id_to_name)]
recent_games['TEAM_NAME'] = recent_games['TEAM_ID'].map(team_id_to_name)

print(f"📊 Analyzing {len(recent_games)} recent team game profiles...")

# 2. Compute team strength: average point differential per game
# PLUS_MINUS is the team's point differential for that game
recent_games['DIFF'] = recent_games['PLUS_MINUS']

team_stats = recent_games.groupby('TEAM_NAME').agg(
    Games=('GAME_ID', 'count'),
    Avg_Margin=('DIFF', 'mean'),
    Avg_Pts_For=('PTS', 'mean')
).reset_index()

# 3. Pull Current Live Odds from The Odds API
print("🔌 Fetching live consensus marketplace lines...")
odds_url = f"https://api.the-odds-api.com/v4/sports/{SPORT_KEY}/odds/"
params = {"apiKey": ODDS_API_KEY, "regions": REGIONS, "markets": MARKETS, "oddsFormat": "american"}
response = requests.get(odds_url, params=params, timeout=30)

edges_discovered = []

if response.status_code == 200:
    odds_data = response.json()

    for game in odds_data:
        home_team = game['home_team']
        away_team = game['away_team']

        # Extract the point spread line
        bookmaker_line = None
        for book in game.get('bookmakers', []):
            # Use the first US bookmaker that has a spreads market (e.g., DraftKings, FanDuel)
            market = next((m for m in book['markets'] if m['key'] == 'spreads'), None)
            if market is None:
                continue
            for outcome in market['outcomes']:
                if outcome['name'] == home_team:
                    bookmaker_line = outcome['point']  # Home spread line
            if bookmaker_line is not None:
                break

        if bookmaker_line is None:
            continue

        # Match teams with our analytical dataset
        home_metrics = team_stats[team_stats['TEAM_NAME'] == home_team]
        away_metrics = team_stats[team_stats['TEAM_NAME'] == away_team]

        if not home_metrics.empty and not away_metrics.empty:
            home_margin = home_metrics['Avg_Margin'].values[0]
            away_margin = away_metrics['Avg_Margin'].values[0]

            # Standard NBA baseline: Add 2.5 points for home court advantage
            # Negative spread = home team favored
            predicted_home_spread = (away_margin - home_margin) - 2.5

            # Identify line discrepancy
            edge = predicted_home_spread - bookmaker_line

            edges_discovered.append({
                "Game Date": game['commence_time'],
                "Home Team": home_team,
                "Away Team": away_team,
                "Market Spread (Home)": bookmaker_line,
                "Model Predicted Spread (Home)": round(predicted_home_spread, 2),
                "Raw Line Edge": round(edge, 2),
                "Bet Recommendation": "PLAY HOME" if edge < -1.5 else ("PLAY AWAY" if edge > 1.5 else "PASS")
            })

    # Save findings
    output_df = pd.DataFrame(edges_discovered)
    output_file_path = "generated/nba_betting_edges.csv"
    output_df.to_csv(output_file_path, index=False)
    print(f"✅ Success! {len(edges_discovered)} games analyzed, saved to: {output_file_path}")
else:
    print(f"❌ Failed to fetch odds data. Status Code: {response.status_code}. Verify your ODDS_API_KEY environment variable.")
