#!/usr/bin/env python3
"""
MLB Pitcher Total Outs — live daily tool.  Runs on GitHub Actions (statsapi + The Odds API).
today's probables -> each SP recent starts + days rest -> opponent trailing P/PA (from
outs_build_data.csv) -> engine v2 projection + alt ladder -> Odds API MAIN pitcher_outs line for
FLAGGED games only (free-tier quota-safe) -> docs/index.html + docs/outs_lines_log.csv.
Env: ODDS_API_KEY. Local test: `python daily_outs_tool.py --mock YYYY-MM-DD` (renders a past slate
from the CSV, no network).
"""
import os, sys, csv, json, time, html, datetime, urllib.request
import numpy as np
from pathlib import Path
HERE=Path(__file__).parent; DATA=HERE/"outs_build_data.csv"; DOCS=HERE/"docs"; DOCS.mkdir(exist_ok=True)
BASE="https://statsapi.mlb.com/api/v1"; ODDS_KEY=os.environ.get("ODDS_API_KEY","")
HEADERS={"User-Agent":"Mozilla/5.0 (research)"}; K_OPP=0.7; HALFLIFE=4.0; FLAG=1.0
def get(url,retries=3,timeout=20):
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=HEADERS),timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            if i==retries-1: print("  FAIL",url[:70],e); return None
            time.sleep(1.5*(i+1))
# ---------- engine v2 ----------
def layoff_delta(d): return 1.5 if (d is not None and d>=14) else (0.3 if (d is not None and d>=8) else 0.0)
def project(prior_outs, opp_ppa, lg, days_rest, n=8000, seed=0):
    O=np.asarray([o for o in prior_outs if o is not None],float)
    if len(O)<5: return None
    rng=np.random.default_rng(seed); wr=0.5**(np.arange(len(O))[::-1]/HALFLIFE)
    gd=((opp_ppa-lg)/lg) if opp_ppa else 0.0
    w=wr*np.exp(-K_OPP*gd*(O-O.mean())); w/=w.sum()
    d=np.clip(rng.choice(O,n,p=w)-layoff_delta(days_rest),0,27)
    base=int(round(d.mean())); lines=[max(3.5,base-2.5+i) for i in range(6)]
    return dict(model=float(d.mean()),dumb=float(O[-10:].mean()),draws=d,
                ladder=[(L,float((d>L).mean())) for L in lines])
def american(p): p=min(max(p,.02),.98); return f"−{round(100*p/(1-p))}" if p>=.5 else f"+{round(100*(1-p)/p)}"
def implied(price): return (100/(price+100)) if price>0 else (-price/(-price+100))
# ---------- opponent trailing P/PA from CSV ----------
def load_opp_ppa(win=20):
    rows=list(csv.DictReader(open(DATA)))
    for r in rows: r['off_ppa']=float(r['off_pitches'])/float(r['off_bf'])
    rows.sort(key=lambda r:r['date']); hist={}
    for r in rows: hist.setdefault(r['team_id'],[]).append(r['off_ppa'])
    lg=float(np.mean([r['off_ppa'] for r in rows]))
    return {t:float(np.mean(v[-win:])) for t,v in hist.items()}, lg
# ---------- statsapi ----------
def todays_games(date):
    d=get(f"{BASE}/schedule?sportId=1&date={date}&hydrate=probablePitcher"); games=[]
    for day in (d or {}).get("dates",[]):
        for g in day.get("games",[]):
            h,a=g["teams"]["home"],g["teams"]["away"]
            games.append(dict(home_id=str(h["team"]["id"]),home=h["team"]["name"],
                away_id=str(a["team"]["id"]),away=a["team"]["name"],
                home_sp=h.get("probablePitcher"),away_sp=a.get("probablePitcher")))
    return games
def sp_recent(pid,season):
    d=get(f"{BASE}/people/{pid}/stats?stats=gameLog&group=pitching&season={season}")
    outs=[]; last=None
    for s in (d or {}).get("stats",[]):
        for sp in reversed(s.get("splits",[])):  # gameLog newest-first; reverse to oldest..newest
            st=sp.get("stat",{})
            if str(st.get("gamesStarted",0)) in ("1",):
                ip=st.get("inningsPitched")
                if ip: w,_,f=str(ip).partition("."); outs.append(int(w)*3+(int(f) if f else 0))
                if last is None or sp.get("date",'')>last: last=sp.get("date")
    return outs,last
# ---------- Odds API main line (flagged only) ----------
def odds_events():
    if not ODDS_KEY: return {}
    d=get(f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events?apiKey={ODDS_KEY}&dateFormat=iso")
    return {(e["home_team"],e["away_team"]):e["id"] for e in (d or [])}
def main_line(eid,sp_name):
    if not (ODDS_KEY and eid): return None
    d=get(f"https://api.the-odds-api.com/v4/sports/baseball_mlb/events/{eid}/odds?apiKey={ODDS_KEY}&regions=us&markets=pitcher_outs&oddsFormat=american")
    nm=sp_name.lower()
    for bm in (d or {}).get("bookmakers",[]):
        ov=un=pt=None
        for o in bm.get("markets",[{}])[0].get("outcomes",[]) if bm.get("markets") else []:
            if (o.get("description","") or "").lower()!=nm: continue
            if o.get("name")=="Over": ov=o.get("price"); pt=o.get("point")
            elif o.get("name")=="Under": un=o.get("price")
        if pt is not None: return {"book":bm["key"],"line":pt,"over":ov,"under":un}
    return None
# ---------- build cards ----------
def build_live(date):
    season=int(date[:4]); opp_ppa,lg=load_opp_ppa(); games=todays_games(date); omap=odds_events()
    cards=[]
    for g in games:
        for spinfo,team,opp,opp_id in [(g.get("home_sp"),g["home"],g["away"],g["away_id"]),
                                       (g.get("away_sp"),g["away"],g["home"],g["home_id"])]:
            if not spinfo: continue
            outs,last=sp_recent(spinfo["id"],season)
            if len(outs)<5: continue
            dr=None
            if last:
                try: dr=(datetime.date.fromisoformat(date)-datetime.date.fromisoformat(last)).days
                except: pass
            pr=project(outs,opp_ppa.get(opp_id),lg,dr,seed=spinfo["id"])
            if not pr: continue
            adj=pr["model"]-pr["dumb"]; big=abs(adj)>=FLAG; book=None
            if big: book=main_line(omap.get((g["home"],g["away"])),spinfo["fullName"])
            cards.append(mkcard(spinfo["fullName"],team,opp,pr,adj,dr,opp_ppa.get(opp_id),lg,big,book))
            time.sleep(0.1)
    cards.sort(key=lambda c:-abs(c["adj"])); return cards,date
def mkcard(name,team,opp,pr,adj,dr,oppa,lg,big,book):
    tags=[]
    if oppa:
        g=oppa-lg
        if g>0.06: tags.append(("grindy opp","warn"))
        elif g<-0.06: tags.append(("free-swing opp","good"))
    if dr is not None and dr>=14: tags.append(("IL return","warn"))
    elif dr is not None and dr>=8: tags.append(("long rest","mut"))
    return dict(sp=name,team=team,opp=opp,dumb=pr["dumb"],model=pr["model"],adj=adj,draws=pr["draws"],
                ladder=pr["ladder"],tags=tags,big=big,book=book)
# ---------- mock (from CSV, no network) ----------
def build_mock(date):
    import pandas as pd
    df=pd.read_csv(DATA); df['date']=pd.to_datetime(df['date']); df['off_ppa']=df['off_pitches']/df['off_bf']
    df=df.sort_values('date').reset_index(drop=True); S=pd.Timestamp(date)
    th={}; opp=np.full(len(df),np.nan)
    for i,r in enumerate(df.itertuples()):
        h=th.get(r.opp_id,[])
        if len(h)>=8: opp[i]=np.mean(h[-20:])
        th.setdefault(r.team_id,[]).append(r.off_ppa)
    df['opp_ppa']=opp; lg=np.nanmean(df['opp_ppa'])
    sp={}; pool=[None]*len(df); dr=np.full(len(df),np.nan)
    for i,r in enumerate(df.itertuples()):
        h=sp.get(r.sp_id,[])
        if h: dr[i]=(r.date-h[-1][0])/np.timedelta64(1,'D')
        if len(h)>=5: pool[i]=[o for _,o in h[-15:]]
        sp.setdefault(r.sp_id,[]).append((r.date,r.outs))
    sl=df[(df['date']==S)&pd.notna(df['opp_ppa'])]; cards=[]
    for r in sl.itertuples():
        if pool[r.Index] is None: continue
        pr=project(pool[r.Index],df['opp_ppa'].values[r.Index],lg,dr[r.Index],seed=r.sp_id)
        if not pr: continue
        adj=pr["model"]-pr["dumb"]
        cards.append(mkcard(r.sp_name,r.team,r.opp,pr,adj,dr[r.Index],df['opp_ppa'].values[r.Index],lg,abs(adj)>=FLAG,None))
    cards.sort(key=lambda c:-abs(c["adj"])); return cards,date
# render in separate module part
from render_board import render
if __name__=="__main__":
    if len(sys.argv)>2 and sys.argv[1]=="--mock":
        cards,date=build_mock(sys.argv[2]); live=False
    else:
        date=datetime.date.today().isoformat(); cards,date=build_live(date); live=True
    if live:
        import csv as _csv
        logp=DOCS/"outs_lines_log.csv"; new=not logp.exists()
        with open(logp,"a",newline="") as f:
            w=_csv.writer(f)
            if new: w.writerow(["pulled_date","game_date","pitcher","book","line","over","under","our_model","our_dumb"])
            for c in cards:
                b=c.get("book")
                if b: w.writerow([datetime.date.today().isoformat(),date,c["sp"],b["book"],b["line"],b.get("over"),b.get("under"),round(c["model"],2),round(c["dumb"],2)])
    html_out=render(cards,date,live=live)
    (DOCS/"index.html").write_text(html_out)
    print(f"wrote docs/index.html — {len(cards)} pitchers, {sum(c['big'] for c in cards)} flagged")
