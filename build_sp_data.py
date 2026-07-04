"""
MLB Game-Specific Starting Pitcher Data Builder — v2 (BIP extension)
=====================================================================
Runs on GitHub Actions (has normal internet access — unlike the Cowork sandbox).

v2 changes (2026-07-04):
  - SEASONS extended through 2025 (weather dataset covers 2023 - Aug 2025)
  - Adds SP K%, BB%, IP to each game row (for expected balls-in-play scaling
    of the weather model: weather affects contact, not Ks/walks)
  - Fetches a second FanGraphs stat page (type=1, "Advanced") for K%/BB% and
    merges by playerid; probes multiple JSON key spellings defensively
  - Builds team-season BULLPEN aggregates (relievers = GS==0, IP-weighted
    K%/BB%) -> team_bullpen.csv
  - All original columns preserved; run_regression.py still works unchanged

Outputs: mlb_sp_games.csv, team_bullpen.csv (committed by the workflow).
"""

import csv
import io
import json
import time
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

SEASONS = [2021, 2022, 2023, 2024, 2025]
OUT_PATH = Path(__file__).parent / "mlb_sp_games.csv"
BP_PATH = Path(__file__).parent / "team_bullpen.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

RETRO_TEAM_MAP = {
    "ARI": "ARI", "ATL": "ATL", "BAL": "BAL", "BOS": "BOS",
    "CHA": "CHW", "CHN": "CHC", "CIN": "CIN", "CLE": "CLE", "COL": "COL",
    "DET": "DET", "HOU": "HOU", "KCA": "KC", "ANA": "LAA", "LAA": "LAA",
    "LAN": "LAD", "MIA": "MIA", "MIL": "MIL", "MIN": "MIN",
    "NYN": "NYM", "NYA": "NYY", "OAK": "ATH", "ATH": "ATH",
    "PHI": "PHI", "PIT": "PIT", "SDN": "SD", "SEA": "SEA", "SFN": "SF",
    "SLN": "STL", "TBA": "TB", "TEX": "TEX", "TOR": "TOR", "WAS": "WSH",
}

# FanGraphs team abbreviations -> project short codes
FG_TEAM_MAP = {
    "ARI": "ARI", "ATL": "ATL", "BAL": "BAL", "BOS": "BOS",
    "CHC": "CHC", "CHW": "CHW", "CIN": "CIN", "CLE": "CLE", "COL": "COL",
    "DET": "DET", "HOU": "HOU", "KCR": "KC", "KC": "KC",
    "LAA": "LAA", "LAD": "LAD", "MIA": "MIA", "MIL": "MIL", "MIN": "MIN",
    "NYM": "NYM", "NYY": "NYY", "OAK": "ATH", "ATH": "ATH",
    "PHI": "PHI", "PIT": "PIT", "SDP": "SD", "SD": "SD",
    "SEA": "SEA", "SFG": "SF", "SF": "SF", "STL": "STL",
    "TBR": "TB", "TB": "TB", "TEX": "TEX", "TOR": "TOR",
    "WSN": "WSH", "WSH": "WSH",
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


def probe(row, *keys):
    """Return the first non-empty value among candidate JSON key spellings."""
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            return v
    return None


def to_float(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


# ── Step 1: Retrosheet game logs ──────────────────────────────────────────────
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
        date = row[0]
        vteam_raw, hteam_raw = row[3], row[6]
        vscore, hscore = row[9], row[10]
        vsp_retro_id, hsp_retro_id = row[101], row[103]
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


# ── Step 2: FanGraphs pitcher season stats (two stat pages, merged) ──────────
def fetch_fg_page(season, stat_type):
    url = (
        "https://www.fangraphs.com/api/leaders/major-league/data"
        f"?age=&pos=all&stats=pit&lg=all&season={season}&season1={season}"
        f"&ind=0&qual=0&type={stat_type}&pagenum=1&pageitems=3000"
    )
    raw = fetch(url)
    data = json.loads(raw)
    return data.get("data", data) if isinstance(data, dict) else data


def fetch_fg_pitcher_stats(season):
    print(f"  Fetching FanGraphs pitcher stats {season} (type=4)...")
    rows4 = fetch_fg_page(season, 4)
    print(f"    {len(rows4)} rows (type=4)")
    time.sleep(1)
    print(f"  Fetching FanGraphs pitcher stats {season} (type=1, advanced)...")
    rows1 = fetch_fg_page(season, 1)
    print(f"    {len(rows1)} rows (type=1)")

    # Diagnostic: show available keys once so future sessions can see the schema
    if season == SEASONS[0] and rows4:
        print(f"    type=4 sample keys: {sorted(list(rows4[0].keys()))[:40]}")
        if rows1:
            print(f"    type=1 sample keys: {sorted(list(rows1[0].keys()))[:40]}")

    adv = {}
    for r in rows1:
        fg_id = r.get("playerid")
        if fg_id is None:
            continue
        adv[str(fg_id)] = r

    stats = {}
    kpct_found = 0
    for r in rows4:
        fg_id = r.get("playerid")
        if fg_id is None:
            continue
        fg_id = str(fg_id)
        a = adv.get(fg_id, {})

        # K% / BB%: prefer type=1 keys, then type=4, then compute from SO/BB/TBF
        kpct = probe(a, "K%", "KPct", "kPct") or probe(r, "K%", "KPct", "kPct")
        bbpct = probe(a, "BB%", "BBPct", "bbPct") or probe(r, "BB%", "BBPct", "bbPct")
        if kpct is None:
            so = to_float(probe(r, "SO", "K") or probe(a, "SO", "K"))
            tbf = to_float(probe(r, "TBF") or probe(a, "TBF"))
            if so is not None and tbf:
                kpct = so / tbf
        if bbpct is None:
            bb = to_float(probe(r, "BB") or probe(a, "BB"))
            tbf = to_float(probe(r, "TBF") or probe(a, "TBF"))
            if bb is not None and tbf:
                bbpct = bb / tbf
        # FanGraphs sometimes returns percentages as 0.243, sometimes 24.3
        kpct = to_float(kpct)
        bbpct = to_float(bbpct)
        if kpct is not None and kpct > 1:
            kpct /= 100.0
        if bbpct is not None and bbpct > 1:
            bbpct /= 100.0
        if kpct is not None:
            kpct_found += 1

        team_raw = probe(r, "TeamName", "Team", "AbbName", "teamName", "team") or \
                   probe(a, "TeamName", "Team", "AbbName", "teamName", "team")
        team = FG_TEAM_MAP.get(str(team_raw).strip(), None) if team_raw else None

        stats[fg_id] = {
            "name": r.get("PlayerName"),
            "era": r.get("ERA"),
            "xfip": r.get("xFIP"),
            "siera": r.get("SIERA"),
            "gs": r.get("GS"),
            "ip": to_float(probe(r, "IP") or probe(a, "IP")),
            "kpct": kpct,
            "bbpct": bbpct,
            "team": team,
        }
    print(f"    {len(stats)} pitchers, K% resolved for {kpct_found}")
    return stats


# ── Step 2b: team-season bullpen aggregates ───────────────────────────────────
def build_bullpen_aggregates(season, stats):
    """Relievers = GS == 0. IP-weighted K% and BB% per team."""
    agg = defaultdict(lambda: {"ip": 0.0, "k": 0.0, "bb": 0.0})
    skipped_no_team = 0
    for s in stats.values():
        gs = to_float(s["gs"])
        ip = s["ip"]
        if gs is None or gs > 0 or not ip or ip < 5:
            continue
        if not s["team"]:  # traded players ("- - -") lack a single team
            skipped_no_team += 1
            continue
        if s["kpct"] is None or s["bbpct"] is None:
            continue
        a = agg[s["team"]]
        a["ip"] += ip
        a["k"] += s["kpct"] * ip
        a["bb"] += s["bbpct"] * ip
    out = {}
    for team, a in agg.items():
        if a["ip"] > 0:
            out[team] = {
                "bp_kpct": round(a["k"] / a["ip"], 4),
                "bp_bbpct": round(a["bb"] / a["ip"], 4),
                "bp_ip": round(a["ip"], 1),
            }
    print(f"    bullpen aggregates: {len(out)} teams "
          f"({skipped_no_team} traded relievers skipped)")
    return out


# ── Step 3: Chadwick crosswalk ────────────────────────────────────────────────
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
    print("MLB Game-Specific SP Data Builder — v2 (BIP extension)")
    print("=" * 60)

    crosswalk = fetch_chadwick_crosswalk()

    all_games = []
    fg_stats_by_season = {}
    bullpen_by_season = {}
    for season in SEASONS:
        try:
            games = fetch_retrosheet_games(season)
        except Exception as e:
            print(f"  WARNING: Retrosheet {season} failed ({e}) — skipping season")
            continue
        all_games.extend(games)
        stats = fetch_fg_pitcher_stats(season)
        fg_stats_by_season[season] = stats
        bullpen_by_season[season] = build_bullpen_aggregates(season, stats)
        time.sleep(1)

    print(f"\nTotal games: {len(all_games)}")

    matched = 0
    rows_out = []
    for g in all_games:
        season_stats = fg_stats_by_season.get(g["season"], {})
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
            # v2 additions
            "home_sp_kpct": home_stats.get("kpct", ""),
            "home_sp_bbpct": home_stats.get("bbpct", ""),
            "home_sp_ip": home_stats.get("ip", ""),
            "away_sp_kpct": away_stats.get("kpct", ""),
            "away_sp_bbpct": away_stats.get("bbpct", ""),
            "away_sp_ip": away_stats.get("ip", ""),
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
    print(f"✓ Wrote {OUT_PATH} ({len(rows_out)} rows)")

    with open(BP_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["season", "team", "bp_kpct", "bp_bbpct", "bp_ip"])
        for season, teams in bullpen_by_season.items():
            for team, a in sorted(teams.items()):
                writer.writerow([season, team, a["bp_kpct"], a["bp_bbpct"], a["bp_ip"]])
    print(f"✓ Wrote {BP_PATH}")


if __name__ == "__main__":
    main()
