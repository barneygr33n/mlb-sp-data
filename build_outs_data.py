#!/usr/bin/env python3
"""
Historical data for the Pitcher Total Outs origination tool  (v2: + HP umpire)
=============================================================================
Runs on GitHub Actions (sandbox can't reach statsapi.mlb.com).
One row per side per FINAL game 2021-2026 with the starter's line, the team's
offensive pitches/PA, AND the home-plate umpire (name+id) for umpire-tendency work.
Output: outs_build_data.csv. Runtime ~80 min (~13k boxscore calls).
"""
import csv, json, time, urllib.request, sys, functools
from pathlib import Path
print = functools.partial(print, flush=True)   # -u: stream progress in Actions log

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
                print(f"  FAIL {url}: {e}"); return None
            time.sleep(2 * (i + 1))

def outs_from_ip(ip_str):
    if ip_str is None or ip_str == "": return None
    try:
        whole, _, frac = str(ip_str).partition(".")
        return int(whole) * 3 + (int(frac) if frac else 0)
    except ValueError:
        return None

def num(v):
    try: return int(v)
    except (ValueError, TypeError): return None

def staff_totals(team_box):
    tot_p = tot_bf = 0; have_p = False
    players = team_box.get("players", {})
    for pid in team_box.get("pitchers", []):
        st = players.get(f"ID{pid}", {}).get("stats", {}).get("pitching", {})
        p = st.get("pitchesThrown") or st.get("numberOfPitches")
        bf = st.get("battersFaced")
        if p is not None: tot_p += int(p); have_p = True
        if bf is not None: tot_bf += int(bf)
    return (tot_p if have_p else None), (tot_bf if tot_bf else None)

def hp_umpire(box):
    for o in box.get("officials", []):
        if o.get("officialType") == "Home Plate":
            off = o.get("official", {})
            return off.get("id"), off.get("fullName")
    return None, None

def main():
    rows = []
    for season in SEASONS:
        sched = get(f"{BASE}/schedule?sportId=1&season={season}"
                    f"&gameType=R&fields=dates,date,games,gamePk,status,codedGameState")
        if not sched: continue
        pks = [(d["date"], g["gamePk"]) for d in sched.get("dates", [])
               for g in d.get("games", []) if g.get("status", {}).get("codedGameState") == "F"]
        print(f"{season}: {len(pks)} final games")
        for i, (date, pk) in enumerate(pks):
            box = get(f"{BASE}/game/{pk}/boxscore")
            if not box: continue
            teams = box.get("teams", {})
            home, away = teams.get("home", {}), teams.get("away", {})
            hp_id, hp_name = hp_umpire(box)
            home_sp, home_sbf = staff_totals(home); away_sp, away_sbf = staff_totals(away)
            meta = {"home": {"off_pitches": away_sp, "off_bf": away_sbf},
                    "away": {"off_pitches": home_sp, "off_bf": home_sbf}}
            for side in ("home", "away"):
                t = teams.get(side, {}); pids = t.get("pitchers", [])
                if not pids: continue
                sp_id = pids[0]
                p = t.get("players", {}).get(f"ID{sp_id}", {})
                st = p.get("stats", {}).get("pitching", {})
                if not st: continue
                opp = "away" if side == "home" else "home"
                sp_pitches = st.get("pitchesThrown") or st.get("numberOfPitches")
                rows.append({
                    "date": date, "season": season, "game_pk": pk, "side": side,
                    "team_id": t.get("team", {}).get("id"), "team": t.get("team", {}).get("name", ""),
                    "opp_id": teams.get(opp, {}).get("team", {}).get("id"),
                    "opp": teams.get(opp, {}).get("team", {}).get("name", ""),
                    "sp_id": sp_id, "sp_name": p.get("person", {}).get("fullName", ""),
                    "outs": outs_from_ip(st.get("inningsPitched")), "pitches": num(sp_pitches),
                    "bf": num(st.get("battersFaced")), "h": num(st.get("hits")), "r": num(st.get("runs")),
                    "er": num(st.get("earnedRuns")), "k": num(st.get("strikeOuts")),
                    "bb": num(st.get("baseOnBalls")), "hr": num(st.get("homeRuns")),
                    "off_pitches": meta[side]["off_pitches"], "off_bf": meta[side]["off_bf"],
                    "hp_ump_id": hp_id, "hp_ump": hp_name,
                })
            if i % 300 == 0: print(f"  {season}: {i}/{len(pks)} ({len(rows)} rows)")
            time.sleep(0.15)
    if not rows: print("NO ROWS"); return
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    with_ump = sum(1 for r in rows if r["hp_ump_id"] is not None)
    with_pitch = sum(1 for r in rows if r["pitches"] is not None)
    print(f"\n Wrote {OUT} ({len(rows)} rows)")
    print(f"  SP pitches present: {with_pitch}/{len(rows)} ({100*with_pitch/len(rows):.1f}%)")
    print(f"  HP umpire present : {with_ump}/{len(rows)} ({100*with_ump/len(rows):.1f}%)")

if __name__ == "__main__": main()
