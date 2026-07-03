"""
MLB Game-Specific Starting Pitcher Data Builder
================================================
Runs on GitHub Actions (has normal internet access — unlike the Cowork sandbox,
which is blocked from Retrosheet, FanGraphs, and every other stats host we've
tried this season).

For each season in SEASONS, pulls:
  1. Retrosheet game logs (starting pitcher IDs per game, Retrosheet ID system)
  2. FanGraphs season pitching leaderboard (ERA/xFIP/SIERA/GS, FanGraphs ID system)
  3. Chadwick Bureau register (crosswalk: Retrosheet ID <-> FanGraphs ID)

Joins them into one CSV: one row per game, with each team's starting pitcher's
season ERA/xFIP/SIERA attached. This upgrades the Tier 1 totals model
(validate_tier1_model.py) from team-season averages to game-specific SP quality —
the actual BARTOLO insight (the market sets the line off that day's starter, not
the roster average).

Output: mlb_sp_games.csv, committed back to the repo by the GitHub Actions workflow.
"""

import csv
import io
import json
import time
import urllib.request
import zipfile
from pathlib import Path

SEASONS = [2021, 2022, 2023, 2024]  # matches mlb_odds_dataset.json coverage
OUT_PATH = Path(__file__).parent / "mlb_sp_games.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

# Retrosheet team codes -> standard short codes used elsewhere in this project
# (matches the TEAM_NORM / short-code convention in build_tracker.py / mlb_odds_dataset.json)
RETRO_TEAM_MAP = {
    "ARI": "ARI", "ATL": "ATL", "BAL": "BAL", "BOS": "BOS",
    "CHA": "CHW", "CHN": "CHC", "CIN": "CIN", "CLE": "CLE", "COL": "COL",
    "DET": "DET", "HOU": "HOU", "KCA": "KC", "ANA": "LAA", "LAA": "LAA",
    "LAN": "LAD", "MIA": "MIA", "MIL": "MIL", "MIN": "MIN",
    "NYN": "NYM", "NYA": "NYY", "OAK": "ATH", "ATH": "ATH",
    "PHI": "PHI", "PIT": "PIT", "SDN": "SD", "SEA": "SEA", "SFN": "SF",
    "SLN": "STL", "TBA": "TB", "TEX": "TEX", "TOR": "TOR", "WAS": "WSH",
}


def fetch(url, retries=3):
    last_err = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except Exception as e:
            last_err = e
            time.sleep(2)
    raise RuntimeError(f"Failed to fetch {url}: {last_err}")


# ── Step 1: Retrosheet game logs (starting pitcher IDs per game) ──────────────
def fetch_retrosheet_games(season):
    print(f"  Fetching Retrosheet game log {season}...")
    raw = fetch(f"https://www.retrosheet.org/gamelogs/gl{season}.zip")
    zf = zipfile.ZipFile(io.BytesIO(raw))
    txt_name = [n for n in zf.namelist() if n.upper().endswith(".TXT")][0]
    content = zf.read(txt_name).decode("utf-8", errors="replace")

    games = []
    for row in csv.reader(io.StringIO(content)):
        if len(row) < 105:
            continue
        date = row[0]  # yyyymmdd
        vteam_raw = row[3]
        hteam_raw = row[6]
        vscore = row[9]
        hscore = row[10]
        vsp_retro_id = row[101]
        hsp_retro_id = row[103]
        if not vsp_retro_id or not hsp_retro_id:
            continue
        games.append({
            "date": f"{date[:4]}-{date[4:6]}-{date[6:8]}",
            "season": season,
            "home": RETRO_TEAM_MAP.get(hteam_raw, hteam_raw),
            "away": RETRO_TEAM_MAP.get(vteam_raw, vteam_raw),
            "home_score": hscore,
            "away_score": vscore,
            "home_sp_retro_id": hsp_retro_id,
            "away_sp_retro_id": vsp_retro_id,
        })
    print(f"    {len(games)} games with SP IDs")
    return games


# ── Step 2: FanGraphs pitcher season stats ─────────────────────────────────────
def fetch_fg_pitcher_stats(season):
    print(f"  Fetching FanGraphs pitcher stats {season}...")
    url = (
        "https://www.fangraphs.com/api/leaders/major-league/data"
        f"?age=&pos=all&stats=pit&lg=all&season={season}&season1={season}"
        "&ind=0&qual=0&type=4&pagenum=1&pageitems=3000"
    )
    raw = fetch(url)
    data = json.loads(raw)
    rows = data.get("data", data) if isinstance(data, dict) else data
    stats = {}
    for r in rows:
        fg_id = r.get("playerid")
        if fg_id is None:
            continue
        stats[str(fg_id)] = {
            "name": r.get("PlayerName"),
            "era": r.get("ERA"),
            "xfip": r.get("xFIP"),
            "siera": r.get("SIERA"),
            "gs": r.get("GS"),
        }
    print(f"    {len(stats)} pitchers")
    return stats


# ── Step 3: Chadwick Bureau register (Retrosheet ID <-> FanGraphs ID) ─────────
def fetch_chadwick_crosswalk():
    print("  Fetching Chadwick Bureau register (id crosswalk)...")
    crosswalk = {}
    for hexchar in "0123456789abcdef":
        url = f"https://raw.githubusercontent.com/chadwickbureau/register/master/data/people-{hexchar}.csv"
        try:
            raw = fetch(url, retries=2)
        except Exception as e:
            print(f"    WARNING: people-{hexchar}.csv failed: {e}")
            continue
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8", errors="replace")))
        for row in reader:
            retro_id = row.get("key_retro")
            fg_id = row.get("key_fangraphs")
            if retro_id and fg_id:
                crosswalk[retro_id] = fg_id
    print(f"    {len(crosswalk)} retro->fangraphs id mappings")
    return crosswalk


def main():
    print("=" * 60)
    print("MLB Game-Specific SP Data Builder")
    print("=" * 60)

    crosswalk = fetch_chadwick_crosswalk()

    all_games = []
    fg_stats_by_season = {}
    for season in SEASONS:
        games = fetch_retrosheet_games(season)
        all_games.extend(games)
        fg_stats_by_season[season] = fetch_fg_pitcher_stats(season)
        time.sleep(1)

    print(f"\nTotal games: {len(all_games)}")

    matched = 0
    rows_out = []
    for g in all_games:
        season_stats = fg_stats_by_season[g["season"]]
        home_fg_id = crosswalk.get(g["home_sp_retro_id"])
        away_fg_id = crosswalk.get(g["away_sp_retro_id"])
        home_stats = season_stats.get(home_fg_id, {}) if home_fg_id else {}
        away_stats = season_stats.get(away_fg_id, {}) if away_fg_id else {}

        row = {
            "date": g["date"],
            "season": g["season"],
            "home": g["home"],
            "away": g["away"],
            "home_score": g["home_score"],
            "away_score": g["away_score"],
            "home_sp_name": home_stats.get("name", ""),
            "home_sp_era": home_stats.get("era", ""),
            "home_sp_xfip": home_stats.get("xfip", ""),
            "home_sp_siera": home_stats.get("siera", ""),
            "home_sp_gs": home_stats.get("gs", ""),
            "away_sp_name": away_stats.get("name", ""),
            "away_sp_era": away_stats.get("era", ""),
            "away_sp_xfip": away_stats.get("xfip", ""),
            "away_sp_siera": away_stats.get("siera", ""),
            "away_sp_gs": away_stats.get("gs", ""),
        }
        if home_stats.get("era") not in (None, "") and away_stats.get("era") not in (None, ""):
            matched += 1
        rows_out.append(row)

    print(f"Games with both SP stats matched: {matched} / {len(rows_out)}")

    fieldnames = list(rows_out[0].keys()) if rows_out else []
    with open(OUT_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_out)

    print(f"\n✓ Wrote {OUT_PATH} ({len(rows_out)} rows)")


if __name__ == "__main__":
    main()
