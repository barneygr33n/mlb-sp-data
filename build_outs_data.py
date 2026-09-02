#!/usr/bin/env python3
"""
Historical data for the Pitcher Total Outs origination tool  (Phase 1 validation)
=================================================================================
Runs on GitHub Actions (the Cowork sandbox can't reach statsapi.mlb.com).

For every regular-season FINAL game 2021-2026(to date), pulls the boxscore and
emits ONE ROW PER SIDE (home/away) capturing, walk-forward-friendly, everything
the outs sim + backtest needs:

  Starter line (the outs target + the pitch-count basis):
    outs, pitches, bf, h, r, er, k, bb, hr
  This team's OFFENSE that game (the opponent-grind feature, P/PA):
    off_pitches = total pitches the OPPOSING staff threw  (= pitches this
                  team's hitters saw)
    off_bf      = total batters the OPPOSING staff faced  (= this team's PA)
    -> a team's pitches-per-PA on offense = off_pitches / off_bf, and the
       backtest builds each opponent's TRAILING P/PA from these rows.

Output: outs_build_data.csv  (~24k rows, 2 per game) — committed by the workflow.

Why one row per side: for an SP start on side S vs opponent O, the backtest looks
up O's trailing offensive P/PA from O's own rows (the games where O was hitting).
Days rest / leash / blow-up-frequency features are derived in the backtest from
the per-start sequence, so this builder stays a clean single pass.

Runtime: ~12k boxscore calls x 0.15s ~ 35 min. Fits Actions limits.
"""
import csv, json, time, urllib.request
from pathlib import Path

SEASONS = [2021, 2022, 2023, 2024, 2025, 2026]
OUT = Path(__file__).parent / "outs_build_data.csv"
BASE = "https://statsapi.mlb.com/api/v1"
HEADERS = {"User-Agent": "Mozilla/5.0 (research; contact via github)"}

def get(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            if i == retries - 1:
                print(f"  FAIL {url}: {e}")
                return None
            time.sleep(2 * (i + 1))

def outs_from_ip(ip_str):
    """'5.2' -> 17 outs."""
    if ip_str is None or ip_str == "":
        return None
    try:
        whole, _, frac = str(ip_str).partition(".")
        return int(whole) * 3 + (int(frac) if frac else 0)
    except ValueError:
        return None

def num(v):
    try:
        return int(v)
    except (ValueError, TypeError):
        return None

def staff_totals(team_box):
    """Sum pitches + batters-faced across every pitcher on a side (the full staff)."""
    tot_p = tot_bf = 0
    have_p = False
    players = team_box.get("players", {})
    for pid in team_box.get("pitchers", []):
        st = players.get(f"ID{pid}", {}).get("stats", {}).get("pitching", {})
        p = st.get("pitchesThrown")
        if p is None:
            p = st.get("numberOfPitches")
        bf = st.get("battersFaced")
        if p is not None:
            tot_p += int(p); have_p = True
        if bf is not None:
            tot_bf += int(bf)
    return (tot_p if have_p else None), (tot_bf if tot_bf else None)

def main():
    rows = []
    n_pitch_missing = 0
    for season in SEASONS:
        sched = get(f"{BASE}/schedule?sportId=1&season={season}"
                    f"&gameType=R&fields=dates,date,games,gamePk,status,codedGameState")
        if not sched:
            continue
        pks = [(d["date"], g["gamePk"])
               for d in sched.get("dates", [])
               for g in d.get("games", [])
               if g.get("status", {}).get("codedGameState") == "F"]
        print(f"{season}: {len(pks)} final games")
        for i, (date, pk) in enumerate(pks):
            box = get(f"{BASE}/game/{pk}/boxscore")
            if not box:
                continue
            teams = box.get("teams", {})
            home, away = teams.get("home", {}), teams.get("away", {})
            # staff totals per side (used as the OPPOSING offense's pitches-seen/PA)
            home_staff_p, home_staff_bf = staff_totals(home)
            away_staff_p, away_staff_bf = staff_totals(away)
            meta = {
                "home": {"box": home, "team": home,
                         "off_pitches": away_staff_p, "off_bf": away_staff_bf},
                "away": {"box": away, "team": away,
                         "off_pitches": home_staff_p, "off_bf": home_staff_bf},
            }
            for side in ("home", "away"):
                t = teams.get(side, {})
                pids = t.get("pitchers", [])
                if not pids:
                    continue
                sp_id = pids[0]
                p = t.get("players", {}).get(f"ID{sp_id}", {})
                st = p.get("stats", {}).get("pitching", {})
                if not st:
                    continue
                opp = "away" if side == "home" else "home"
                sp_pitches = st.get("pitchesThrown") or st.get("numberOfPitches")
                if sp_pitches is None:
                    n_pitch_missing += 1
                rows.append({
                    "date": date, "season": season, "game_pk": pk, "side": side,
                    "team_id": t.get("team", {}).get("id"),
                    "team": t.get("team", {}).get("name", ""),
                    "opp_id": teams.get(opp, {}).get("team", {}).get("id"),
                    "opp": teams.get(opp, {}).get("team", {}).get("name", ""),
                    "sp_id": sp_id,
                    "sp_name": p.get("person", {}).get("fullName", ""),
                    "outs": outs_from_ip(st.get("inningsPitched")),
                    "pitches": num(sp_pitches),
                    "bf": num(st.get("battersFaced")),
                    "h": num(st.get("hits")), "r": num(st.get("runs")),
                    "er": num(st.get("earnedRuns")),
                    "k": num(st.get("strikeOuts")), "bb": num(st.get("baseOnBalls")),
                    "hr": num(st.get("homeRuns")),
                    # this team's offense that game (from the opposing staff totals):
                    "off_pitches": meta[side]["off_pitches"],
                    "off_bf": meta[side]["off_bf"],
                })
            if i % 300 == 0:
                print(f"  {season}: {i}/{len(pks)} ({len(rows)} rows)")
            time.sleep(0.15)

    if not rows:
        print("NO ROWS — aborting"); return
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    # coverage summary (pitches can be sparse in older seasons)
    with_pitch = sum(1 for r in rows if r["pitches"] is not None)
    with_off = sum(1 for r in rows if r["off_pitches"] and r["off_bf"])
    print(f"\n Wrote {OUT} ({len(rows)} rows)")
    print(f"  SP pitches present : {with_pitch}/{len(rows)} ({100*with_pitch/len(rows):.1f}%)")
    print(f"  offense P/PA present: {with_off}/{len(rows)} ({100*with_off/len(rows):.1f}%)")
    by_season = {}
    for r in rows:
        s = r["season"]; d = by_season.setdefault(s, [0, 0])
        d[0] += 1; d[1] += (r["pitches"] is not None)
    for s in sorted(by_season):
        tot, wp = by_season[s]
        print(f"    {s}: {tot} rows, pitches {100*wp/tot:.0f}%")

if __name__ == "__main__":
    main()
