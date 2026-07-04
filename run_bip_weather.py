"""
BIP-Scaled Weather Interaction Test
====================================
Runs on GitHub Actions after build_sp_data.py (v2).

Hypothesis (Ben, 2026-07-04): weather affects balls in play, not Ks/walks.
So the weather impact on a game's total should scale with the expected number
of balls in play — a high-K pitching matchup should mute weather effects, a
pitch-to-contact matchup should amplify them. Nobody prices this.

Method:
  1. Join mlb_sp_games.csv (SP K%/BB%/IP/GS) + team_bullpen.csv (bullpen
     K%/BB%) + weather_opening_extract.csv (temp/relh/eff_wind + opening/
     closing totals, outdoor games with humidity, 2023 - Aug 2025).
  2. Expected contact index per game:
       sp_contact  = 1 - K% - BB%          (per side)
       exp_ip      = clamp(season IP/GS, 4.0, 7.0)
       side_index  = (exp_ip*sp_contact + (9-exp_ip)*bp_contact) / 9
       bip_index   = mean of both sides, then z-scored across the sample
  3. Tests (target: gap_open = actual runs - OPENING total):
       A. Global OLS with interactions:
          gap_open ~ temp + relh + eff_wind + bip_z + temp*bip_z + wind*bip_z
          -> positive interaction t-stats = weather matters more when more
             balls are in play. THE key test.
       B. Same, vs closing line (does the refinement survive to the close?)
       C. Tercile split: temp/wind betas in low-contact vs high-contact games
          (readable version of A).
       D. Pooled confirmed-humidity-park test: signed humidity signal
          (park-specific direction from weather_market_residual.py, 2026-07-04)
          interacted with bip_z.

Prints results only — no large files move back out.
"""

import csv
import numpy as np
from pathlib import Path

HERE = Path(__file__).parent
SP_PATH = HERE / "mlb_sp_games.csv"
BP_PATH = HERE / "team_bullpen.csv"
WX_PATH = HERE / "weather_opening_extract.csv"

MIN_GS = 5

# Confirmed humidity parks and signal direction (sign of relh beta on gap_open,
# from weather_market_residual.py run 2026-07-04 on 5,393 games):
#   +1 => higher humidity -> more runs vs line (dry -> Under)
#   -1 => higher humidity -> fewer runs vs line (humid -> Under / dry -> Over)
HUMIDITY_PARKS = {
    "Target Field": +1,        # t=+2.23
    "Kauffman Stadium": +1,    # t=+1.56
    "Fenway Park": -1,         # t=-2.45
    "Citi Field": -1,          # t=-2.17
    "Oracle Park": -1,         # t=-1.62
}


def to_float(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def ols(X_cols, y):
    """X_cols: list of 1-D arrays. Returns beta, t, n, r2 (with intercept)."""
    n = len(y)
    X = np.column_stack([np.ones(n)] + list(X_cols))
    y = np.asarray(y, dtype=float)
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    resid = y - X @ beta
    dof = n - X.shape[1]
    s2 = (resid @ resid) / dof
    se = np.sqrt(np.maximum(np.diag(XtX_inv) * s2, 1e-12))
    t = beta / se
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - (resid @ resid) / ss_tot if ss_tot > 0 else 0.0
    return beta, t, n, r2


def sig(t):
    at = abs(t)
    return "***" if at >= 2.0 else "** " if at >= 1.5 else "*  " if at >= 1.0 else "   "


def main():
    # ── Load bullpen ──────────────────────────────────────────────────────────
    bullpen = {}
    with open(BP_PATH) as f:
        for r in csv.DictReader(f):
            k, bb = to_float(r["bp_kpct"]), to_float(r["bp_bbpct"])
            if k is not None and bb is not None:
                bullpen[(r["season"], r["team"])] = 1.0 - k - bb
    print(f"Bullpen aggregates: {len(bullpen)} team-seasons")

    # ── Load SP games, keyed by (date, away, home) ────────────────────────────
    sp = {}
    with open(SP_PATH) as f:
        for r in csv.DictReader(f):
            sp[(r["date"], r["away"], r["home"])] = r
    print(f"SP games: {len(sp)}")

    # ── Join with weather extract, build features ─────────────────────────────
    rows = []
    n_wx = n_nosp = n_nostats = n_nobp = 0
    for r in csv.DictReader(open(WX_PATH)):
        n_wx += 1
        key = (r["date"], r["away"], r["home"])
        g = sp.get(key)
        if g is None:
            n_nosp += 1
            continue
        season = g["season"]

        side_indexes = []
        ok = True
        for side, team_key in (("home", "home"), ("away", "away")):
            k = to_float(g[f"{side}_sp_kpct"])
            bb = to_float(g[f"{side}_sp_bbpct"])
            ip = to_float(g[f"{side}_sp_ip"])
            gs = to_float(g[f"{side}_sp_gs"])
            if None in (k, bb, ip, gs) or gs < MIN_GS:
                ok = False
                break
            bp_contact = bullpen.get((season, g[team_key]))
            if bp_contact is None:
                ok = False
                n_nobp += 1
                break
            sp_contact = 1.0 - k - bb
            exp_ip = min(max(ip / gs, 4.0), 7.0)
            side_indexes.append((exp_ip * sp_contact + (9.0 - exp_ip) * bp_contact) / 9.0)
        if not ok:
            n_nostats += 1
            continue

        runs = to_float(r["total_runs"])
        rows.append({
            "venue": r["venue"],
            "gap_open": runs - to_float(r["opening_total"]),
            "gap_close": runs - to_float(r["closing_total"]),
            "temp": to_float(r["temp"]),
            "relh": to_float(r["relh"]),
            "eff_wind": to_float(r["eff_wind"]),
            "bip": (side_indexes[0] + side_indexes[1]) / 2.0,
        })

    print(f"Weather rows: {n_wx} | no SP match: {n_nosp} | "
          f"incomplete stats/GS<{MIN_GS}: {n_nostats} | final n: {len(rows)}")
    if len(rows) < 500:
        print("SAMPLE TOO SMALL — check join keys / team codes above")
        return

    bip = np.array([r["bip"] for r in rows])
    print(f"\nBIP contact index: mean={bip.mean():.4f} sd={bip.std():.4f} "
          f"min={bip.min():.4f} max={bip.max():.4f}")
    bip_z = (bip - bip.mean()) / bip.std()

    temp = np.array([r["temp"] for r in rows])
    relh = np.array([r["relh"] for r in rows])
    wind = np.array([r["eff_wind"] for r in rows])
    # Center weather vars so interaction terms are interpretable
    temp_c = temp - temp.mean()
    relh_c = relh - relh.mean()

    labels = ["temp", "relh", "eff_wind", "bip_z", "temp x bip", "wind x bip"]
    X = [temp_c, relh_c, wind, bip_z, temp_c * bip_z, wind * bip_z]

    for tgt_name in ("gap_open", "gap_close"):
        y = [r[tgt_name] for r in rows]
        beta, t, n, r2 = ols(X, y)
        print("\n" + "=" * 64)
        print(f"TEST {'A' if tgt_name == 'gap_open' else 'B'}: {tgt_name} ~ "
              f"weather + bip + interactions   (n={n}, R2={r2:.4f})")
        print("=" * 64)
        for i, lbl in enumerate(labels):
            print(f"  {lbl:<12} b={beta[i+1]:+.4f}  t={t[i+1]:+.2f}{sig(t[i+1])}")

    # ── Test C: tercile split ─────────────────────────────────────────────────
    print("\n" + "=" * 64)
    print("TEST C: temp/wind betas vs OPENER, by contact tercile")
    print("=" * 64)
    order = np.argsort(bip)
    terc = len(rows) // 3
    names = ["LOW contact (high-K matchups)", "MID", "HIGH contact (pitch-to-contact)"]
    for i, nm in enumerate(names):
        idx = order[i * terc:(i + 1) * terc] if i < 2 else order[2 * terc:]
        yy = np.array([rows[j]["gap_open"] for j in idx])
        beta, t, n, _ = ols([temp_c[idx], relh_c[idx], wind[idx]], yy)
        print(f"  {nm:<34} n={n:>5}  temp b={beta[1]:+.4f} t={t[1]:+.2f}{sig(t[1])}"
              f"  wind b={beta[3]:+.4f} t={t[3]:+.2f}{sig(t[3])}")

    # ── Test D: pooled confirmed-humidity-park interaction ────────────────────
    print("\n" + "=" * 64)
    print("TEST D: confirmed humidity parks — signed signal x BIP (vs OPENER)")
    print("=" * 64)
    park_mean_relh = {}
    for p in HUMIDITY_PARKS:
        vals = [r["relh"] for r in rows if r["venue"] == p]
        if vals:
            park_mean_relh[p] = float(np.mean(vals))
    sub = [(j, r) for j, r in enumerate(rows) if r["venue"] in park_mean_relh]
    if len(sub) >= 300:
        idx = np.array([j for j, _ in sub])
        signal = np.array([HUMIDITY_PARKS[r["venue"]] * (r["relh"] - park_mean_relh[r["venue"]])
                           for _, r in sub])
        yy = np.array([r["gap_open"] for _, r in sub])
        bz = bip_z[idx]
        beta, t, n, r2 = ols([signal, bz, signal * bz], yy)
        print(f"  n={n} across {len(park_mean_relh)} parks  R2={r2:.4f}")
        print(f"  signed humidity signal   b={beta[1]:+.4f}  t={t[1]:+.2f}{sig(t[1])}"
              f"   <- should be + if signals real")
        print(f"  bip_z                    b={beta[2]:+.4f}  t={t[2]:+.2f}{sig(t[2])}")
        print(f"  signal x bip             b={beta[3]:+.4f}  t={t[3]:+.2f}{sig(t[3])}"
              f"   <- + = BIP amplifies humidity edge")
    else:
        print(f"  Only {len(sub)} games at confirmed parks — skipping")

    print("\n[Interpretation]")
    print("  Positive 'temp x bip' / 'wind x bip' t >= 1.5: Ben's BIP-scaling")
    print("  hypothesis is supported — weather coefficients should be scaled by")
    print("  expected contact rate in the origination tool. If interactions are")
    print("  flat, use unscaled per-park weather betas and revisit with per-game")
    print("  (not season-average) expected BIP later.")


if __name__ == "__main__":
    main()
