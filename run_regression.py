"""
Tier 1 Model: Game-Specific SP Regression
==========================================
Runs on GitHub Actions after build_sp_data.py has produced mlb_sp_games.csv.
Joins it to odds_extract.csv (a compact date/home/away/opening_total extract
of Ben's local mlb_odds_dataset.json, uploaded separately since the full 77MB
file can't reasonably move through this pipeline) and reruns the Tier 1
regression from validate_tier1_model.py, swapping team-season ERA/xFIP for
game-specific starting pitcher ERA/xFIP/SIERA.

Only prints results (R² numbers) — does not need to move any large file back
out. That's the point: keep the round-trip small.
"""

import csv
import numpy as np
from pathlib import Path

SP_PATH = Path(__file__).parent / "mlb_sp_games.csv"
ODDS_PATH = Path(__file__).parent / "odds_extract.csv"

PARK_FACTORS = {
    "COL": 1.200, "BOS": 1.055, "CIN": 1.045, "PHI": 1.040, "TEX": 1.035,
    "LAD": 1.030, "NYY": 1.025, "MIL": 1.020, "ATL": 1.015, "HOU": 1.010,
    "STL": 1.005, "CHC": 1.005, "TOR": 1.000, "DET": 1.000, "ARI": 0.995,
    "CLE": 0.995, "NYM": 0.990, "LAA": 0.985, "MIN": 0.985, "BAL": 0.985,
    "MIA": 0.980, "TB": 0.975, "KC": 0.975,
    "SEA": 0.970, "OAK": 0.970, "ATH": 0.970, "SD": 0.965, "SF": 0.960,
    "WSH": 0.965, "CHW": 0.995, "PIT": 0.985,
}


def to_float(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def ols_r2(X, y):
    X = np.column_stack([np.ones(len(y)), X])
    coefs, *_ = np.linalg.lstsq(X, y, rcond=None)
    preds = X @ coefs
    ss_res = np.sum((y - preds) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    return 1 - ss_res / ss_tot


def main():
    print("Loading odds extract...")
    odds = {}
    with open(ODDS_PATH) as f:
        for row in csv.DictReader(f):
            key = (row["date"], row["away"], row["home"])
            odds[key] = to_float(row["opening_total"])
    print(f"  {len(odds)} games with opening totals")

    print("Loading SP games...")
    rows = []
    with open(SP_PATH) as f:
        for row in csv.DictReader(f):
            key = (row["date"], row["away"], row["home"])
            ot = odds.get(key)
            if ot is None:
                continue
            row["opening_total"] = ot
            rows.append(row)
    print(f"  {len(rows)} games matched to opening totals")

    # Filter to rows with complete SP stats
    clean = []
    for r in rows:
        h_era = to_float(r["home_sp_era"])
        a_era = to_float(r["away_sp_era"])
        h_xfip = to_float(r["home_sp_xfip"])
        a_xfip = to_float(r["away_sp_xfip"])
        h_siera = to_float(r["home_sp_siera"])
        a_siera = to_float(r["away_sp_siera"])
        park = PARK_FACTORS.get(r["home"], 1.0)
        if None in (h_era, a_era):
            continue
        clean.append({
            "opening_total": r["opening_total"],
            "home_era": h_era, "away_era": a_era,
            "home_xfip": h_xfip, "away_xfip": a_xfip,
            "home_siera": h_siera, "away_siera": a_siera,
            "park": park,
        })
    print(f"  {len(clean)} games with complete game-specific SP ERA")

    y = np.array([c["opening_total"] for c in clean])

    print("\n" + "=" * 60)
    print("GAME-SPECIFIC SP REGRESSION RESULTS")
    print("=" * 60)
    print("Baseline (team-season ERA+wRC+park, 2026-06-23): R²=0.481")
    print()

    # Model E: game-specific SP ERA (home + away) + park factor
    X = np.column_stack([
        [c["home_era"] for c in clean],
        [c["away_era"] for c in clean],
        [c["park"] for c in clean],
    ])
    r2 = ols_r2(X, y)
    print(f"Model E — Game SP ERA + park factor:              R²={r2:.3f}  (n={len(clean)})")

    # Model F: game-specific SP xFIP (where available) + park
    clean_x = [c for c in clean if c["home_xfip"] is not None and c["away_xfip"] is not None]
    if clean_x:
        yx = np.array([c["opening_total"] for c in clean_x])
        Xx = np.column_stack([
            [c["home_xfip"] for c in clean_x],
            [c["away_xfip"] for c in clean_x],
            [c["park"] for c in clean_x],
        ])
        r2x = ols_r2(Xx, yx)
        print(f"Model F — Game SP xFIP + park factor:             R²={r2x:.3f}  (n={len(clean_x)})")

    # Model G: game-specific SP SIERA (where available) + park
    clean_s = [c for c in clean if c["home_siera"] is not None and c["away_siera"] is not None]
    if clean_s:
        ys = np.array([c["opening_total"] for c in clean_s])
        Xs = np.column_stack([
            [c["home_siera"] for c in clean_s],
            [c["away_siera"] for c in clean_s],
            [c["park"] for c in clean_s],
        ])
        r2s = ols_r2(Xs, ys)
        print(f"Model G — Game SP SIERA + park factor:            R²={r2s:.3f}  (n={len(clean_s)})")

    # Model H: ERA + xFIP + SIERA combined (where all available) + park
    clean_all = [c for c in clean if None not in (c["home_xfip"], c["away_xfip"], c["home_siera"], c["away_siera"])]
    if clean_all:
        ya = np.array([c["opening_total"] for c in clean_all])
        Xa = np.column_stack([
            [c["home_era"] for c in clean_all], [c["away_era"] for c in clean_all],
            [c["home_xfip"] for c in clean_all], [c["away_xfip"] for c in clean_all],
            [c["home_siera"] for c in clean_all], [c["away_siera"] for c in clean_all],
            [c["park"] for c in clean_all],
        ])
        r2a = ols_r2(Xa, ya)
        print(f"Model H — ERA+xFIP+SIERA (all 3) + park:          R²={r2a:.3f}  (n={len(clean_all)})")

    print()
    print("[Interpretation]")
    print(f"  Lift over team-season baseline (0.481): +{r2 - 0.481:.3f} R² (Model E)")
    if r2 >= 0.60:
        print("  Target reached — game-specific SP confirmed as the key upgrade.")
    elif r2 > 0.481:
        print("  Improvement confirmed but below 0.60 target — may need weighting or more recent-form data.")
    else:
        print("  No improvement over team-season baseline — investigate data quality.")


if __name__ == "__main__":
    main()
