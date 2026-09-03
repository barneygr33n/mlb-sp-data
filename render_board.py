import html, numpy as np
def american(p): p=min(max(p,.02),.98); return f"−{round(100*p/(1-p))}" if p>=.5 else f"+{round(100*(1-p)/p)}"
def implied(price): return (100/(price+100)) if price>0 else (-price/(-price+100))
CSS="""
:root{--bg:#f7f7f5;--card:#fff;--ink:#1b1d21;--mu:#6c7178;--line:#e7e5e0;--line2:#efeee9;
--amber:#b7791f;--amber-bg:#fbf4e4;--good:#1f7a4d;--dn:#c0392b;--up:#1f7a4d;--indigo:#5a5cc0;
--head:#3a3d42;--fav:#1b1d21;--edge:#166a4d;--edge-bg:#e7f4ee}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#131417;--card:#1b1d21;--ink:#e8eaec;
--mu:#969ba2;--line:#2b2e33;--line2:#22242a;--amber:#e0a83d;--amber-bg:#241f12;--good:#4fbf82;--dn:#ff6f61;
--up:#4fbf82;--indigo:#9a9cf0;--head:#c3c8ce;--fav:#e8eaec;--edge:#5bd39a;--edge-bg:#14241d}}
:root[data-theme="dark"]{--bg:#131417;--card:#1b1d21;--ink:#e8eaec;--mu:#969ba2;--line:#2b2e33;--line2:#22242a;
--amber:#e0a83d;--amber-bg:#241f12;--good:#4fbf82;--dn:#ff6f61;--up:#4fbf82;--indigo:#9a9cf0;--head:#c3c8ce;
--fav:#e8eaec;--edge:#5bd39a;--edge-bg:#14241d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:'IBM Plex Sans',system-ui,sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:1040px;margin:0 auto;padding:26px 14px 72px}
.eyebrow{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--amber);margin:0 0 6px}
h1{font-size:23px;font-weight:600;letter-spacing:-.01em;margin:0 0 6px}
.meta{color:var(--mu);font-size:13px;font-variant-numeric:tabular-nums}.meta b{color:var(--ink);font-weight:600}
.note{font-family:'IBM Plex Mono',monospace;font-size:11.5px;color:var(--mu);background:var(--line2);border:1px solid var(--line);border-radius:7px;padding:9px 11px;margin:14px 0 20px;line-height:1.55}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 15px;display:flex;flex-direction:column;gap:11px}
.card.flag{box-shadow:inset 3px 0 0 var(--amber);border-color:var(--amber)}
.ch{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.who{min-width:0}
.name{font-weight:600;font-size:16px;display:block;letter-spacing:-.01em}
.mu{color:var(--mu);font-size:12.5px;font-variant-numeric:tabular-nums}.vs{opacity:.6}
.tags{margin-top:7px;display:flex;flex-wrap:wrap;gap:5px}
.tag,.lean{font-family:'IBM Plex Mono',monospace;font-size:10px;padding:2px 7px;border-radius:5px;border:1px solid var(--line);color:var(--mu);letter-spacing:.02em;white-space:nowrap}
.t-warn{color:var(--amber);border-color:var(--amber)}.t-good{color:var(--good);border-color:var(--good)}
.lean{font-weight:600}.lean.dn{color:var(--dn);border-color:var(--dn)}.lean.up{color:var(--up);border-color:var(--up)}
.kpis{display:grid;grid-template-columns:repeat(3,auto);gap:12px;text-align:right;flex:none}
.kpi{display:flex;flex-direction:column;gap:1px}
.kl{font-family:'IBM Plex Mono',monospace;font-size:9px;letter-spacing:.05em;text-transform:uppercase;color:var(--head)}
.kv{font-family:'IBM Plex Mono',monospace;font-size:17px;font-weight:600;font-variant-numeric:tabular-nums}
.kv.dumb{color:var(--indigo)}.kv.book{color:var(--mu);font-weight:500}.kv small{display:block;font-size:9.5px;font-weight:500;color:var(--mu);margin-top:1px}
.edge{font-family:'IBM Plex Mono',monospace;font-size:11.5px;padding:7px 9px;border-radius:7px;background:var(--line2);color:var(--mu);line-height:1.4}
.edge.hit{background:var(--edge-bg);color:var(--edge);border:1px solid var(--edge)}
.edge b{color:inherit;font-weight:600}
.alt{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
.alt th{font-family:'IBM Plex Mono',monospace;font-size:9.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--head);font-weight:600;text-align:right;padding:5px 8px;border-bottom:1px solid var(--line)}
.alt th.ln{text-align:left}.alt th .mu{text-transform:none;letter-spacing:0}
.alt td{padding:6px 8px;border-bottom:1px solid var(--line2)}.alt tr:last-child td{border-bottom:none}
.ln{font-family:'IBM Plex Mono',monospace;font-size:13px;color:var(--mu);text-align:left;font-weight:500}
.side{text-align:right;white-space:nowrap}
.side .pct{font-family:'IBM Plex Mono',monospace;font-size:14px;font-weight:600}
.side .odds{font-family:'IBM Plex Mono',monospace;font-size:11.5px;margin-left:7px}
.side.fav .pct{color:var(--fav)}.side.fav .odds{color:var(--mu)}
.side.und .pct{color:var(--mu);font-weight:500}.side.und .odds{color:var(--mu);opacity:.7}
.legend{margin-top:20px;color:var(--mu);font-size:12.5px;line-height:1.75;max-width:70ch}
.legend b{color:var(--ink)}.legend .k{color:var(--indigo);font-weight:600}.legend .a{color:var(--amber);font-weight:600}
"""
def pc(x): return f"{100*x:.0f}"
def card_html(c):
    tg="".join(f"<span class='tag t-{k}'>{html.escape(t)}</span>" for t,k in c['tags'])
    arr="▼" if c['adj']<0 else "▲"; lcls="dn" if c['adj']<0 else "up"
    lean=("UNDER" if c['adj']<0 else "OVER")
    chip=(f"<span class='lean {lcls}'>{arr} leans {lean} · {abs(c['adj']):.1f} vs avg</span>"
          if abs(c['adj'])>=0.4 else "<span class='lean'>≈ average</span>")
    b=c.get('book'); draws=c.get('draws')
    if b and draws is not None:
        L=b['line']; pu=float((np.asarray(draws)<L).mean()); po=1-pu
        edge=""
        for side,ourp,price in [("UNDER",pu,b.get('under')),("OVER",po,b.get('over'))]:
            if price is None: continue
            imp=implied(price); ev=ourp-imp
            if ev>=0.03:
                edge=(f"<div class='edge hit'><b>{side} +EV</b> · our {pc(ourp)}% vs book {pc(imp)}% "
                      f"(book {price:+d}, fair {american(ourp)})</div>"); break
        if not edge:
            edge=f"<div class='edge'>Book <b>{L}</b> ({b['book']}) o{b.get('over'):+d}/u{b.get('under'):+d} · no edge at the main line</div>"
        bookkv=f"{L}<small>{b['book']}</small>"
    else:
        edge=""; bookkv="–<small>flagged only</small>" if c['big'] else "–"
    rows=""
    for L,po in c['ladder']:
        pu=1-po; fav_o=po>=pu; oc="fav" if fav_o else "und"; uc="fav" if not fav_o else "und"
        rows+=(f"<tr><td class='ln'>{L}</td>"
               f"<td class='side {oc}'><span class='pct'>{pc(po)}%</span><span class='odds'>{american(po)}</span></td>"
               f"<td class='side {uc}'><span class='pct'>{pc(pu)}%</span><span class='odds'>{american(pu)}</span></td></tr>")
    return (f"<article class='card{' flag' if c['big'] else ''}'>"
      f"<div class='ch'><div class='who'><span class='name'>{html.escape(c['sp'])}</span>"
      f"<span class='mu'>{html.escape(c['team'])} <span class='vs'>vs</span> {html.escape(c['opp'])}</span>"
      f"<div class='tags'>{tg}{chip}</div></div>"
      f"<div class='kpis'><div class='kpi'><span class='kl'>Dumb avg</span><span class='kv dumb'>{c['dumb']:.1f}</span></div>"
      f"<div class='kpi'><span class='kl'>Model</span><span class='kv'>{c['model']:.1f}</span></div>"
      f"<div class='kpi'><span class='kl'>Book</span><span class='kv book'>{bookkv}</span></div></div></div>"
      f"{edge}"
      f"<table class='alt'><thead><tr><th class='ln'>Line</th><th>Over <span class='mu'>%/odds</span></th>"
      f"<th>Under <span class='mu'>%/odds</span></th></tr></thead><tbody>{rows}</tbody></table></article>")
def render(cards,date,live=True):
    nflag=sum(c['big'] for c in cards)
    note=("Live slate. Book lines are pulled for flagged games only (free-tier quota); each card gives "
          "our fair odds at every alt line — shop those in your book app. <b>Green</b> = the book's main "
          "line pays longer than our fair number (a +EV bet)."
          if live else
          "PROTOTYPE — historical slate, walk-forward. Book column empty (live only). Alt lines centered on "
          "our projection; each shows Over/Under with our % and fair American odds; brighter = our side.")
    grid="".join(card_html(c) for c in cards)
    return (f"<title>Pitcher Outs Board</title>"
      f"<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
      f"<link rel='stylesheet' href='https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap'>"
      f"<style>{CSS}</style><div class='wrap'>"
      f"<p class='eyebrow'>Origination model · MLB starting pitchers</p><h1>Pitcher Total Outs Board</h1>"
      f"<div class='meta'>Slate <b>{date}</b> &nbsp;·&nbsp; <b>{len(cards)}</b> starters &nbsp;·&nbsp; <b>{nflag}</b> flagged &nbsp;·&nbsp; ordered by our edge vs the naive average</div>"
      f"<div class='note'>{note}</div><div class='grid'>{grid}</div>"
      f"<div class='legend'><b>Read a card.</b> <span class='k'>Dumb avg</span> = the pitcher's plain recent "
      f"average outs; <b>Model</b> = our projection; the chip says our lean. The ladder gives Over/Under with "
      f"our % and fair odds, centered on our number. <span class='a'>Amber</span> = we differ ≥1.0 from the "
      f"average — the likeliest mispricings, and the games we pull a book line for.</div></div>")
