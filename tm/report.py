"""Render de la pauta.

El elemento central es la traza: 28 días de barras con la banda de ruido
dibujada encima. Casi todos los dashboards te muestran una sparkline y un
número; acá ves de dónde se escapó el pico. Un guionista que ve la barra
saliéndose de la banda entiende el z-score sin que nadie le explique qué es
una mediana absoluta de desviaciones.
"""
import html
import os
from datetime import date
from statistics import median

STATUS = {
    "PICO":     ("var(--cherry)",    "PICO"),
    "NUEVO":    ("var(--buff)",      "NUEVO"),
    "OBSERVAR": ("var(--goldenrod)", "OBSERVAR"),
    "TECHO":    ("var(--salmon)",    "TECHO"),
}
SOURCE_LABEL = {"gtrends": "búsquedas", "gnews": "prensa", "rss": "medios",
                "youtube": "video", "reddit": "foros"}


def trace_svg(history, today, color, w=132, h=30):
    """Barras + banda de ruido. La banda es mediana ± 1.4826·MAD: el territorio
    donde el tema vive normalmente. Todo lo que la perfora es señal."""
    vals = [v for _, v in history]
    series = vals + [today]
    top = max(series + [1.0]) * 1.12
    n = len(series)
    bw = max(1.4, (w - (n - 1) * 1.2) / n)

    parts = []
    if vals:
        med = median(vals)
        mad = median([abs(v - med) for v in vals])
        band = 1.4826 * mad if mad > 0 else max(0.75, 0.25 * max(1.0, med))
        y_hi = h - min(h, (med + band) / top * h)
        y_lo = h - min(h, max(0.0, med - band) / top * h)
        parts.append(
            f'<rect x="0" y="{y_hi:.1f}" width="{w}" height="{max(1.0, y_lo - y_hi):.1f}" '
            f'fill="var(--ghost)" opacity=".5"/>')
        y_med = h - min(h, med / top * h)
        parts.append(
            f'<line x1="0" y1="{y_med:.1f}" x2="{w}" y2="{y_med:.1f}" '
            f'stroke="var(--ghost)" stroke-width="1"/>')

    for i, v in enumerate(series):
        bh = max(0.8, v / top * h)
        x = i * (bw + 1.2)
        last = i == n - 1
        parts.append(
            f'<rect x="{x:.1f}" y="{h - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
            f'rx=".5" fill="{color if last else "var(--ghost)"}" '
            f'opacity="{1 if last else .75}"/>')

    return (f'<svg class="trace" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'role="img" aria-label="Volumen de los últimos {n} días">'
            + "".join(parts) + "</svg>")


def _row(i, r, name, brief, ev, split, rel_names=()):
    color, label = STATUS.get(r["status"], ("var(--ink-dim)", r["status"]))
    why = (brief or {}).get("why") or ""
    angle = (brief or {}).get("angle") or ""
    topic = (brief or {}).get("topic")
    dur = (brief or {}).get("durability")

    chips = "".join(
        f'<span class="chip">{SOURCE_LABEL.get(s, s)}</span>'
        for s, _ in sorted(split.items(), key=lambda kv: -kv[1])[:4])
    rel = "".join(f'<span class="rel">{html.escape(t)}</span>'
                  for t in list(rel_names)[:6])
    links = "".join(
        f'<li><a href="{html.escape(e["url"] or "#")}" target="_blank" rel="noopener">'
        f'{html.escape((e["title"] or "")[:96])}</a>'
        f'<span class="src">{html.escape(e["author"] or e["source"])}</span></li>'
        for e in ev[:3])

    # Un tema que venía en cero da un z de tres cifras. Operativamente z=50 y
    # z=114 dicen lo mismo: "esto salió de la nada". Mostrar el número exacto
    # es ruido con pinta de precisión.
    if r["status"] == "NUEVO":
        z = "—"
    elif r["z"] > 50:
        z = "50+"
    else:
        z = f'{r["z"]:.1f}'
    vel = r["velocity"]
    arrow = "▲" if vel > 0.15 else ("▼" if vel < -0.15 else "▬")

    return f"""
<article class="row">
  <div class="rank">{i:02d}</div>
  <div class="state">
    <span class="pill" style="--c:{color}">{label}</span>
    {f'<span class="dur">{html.escape(dur)}</span>' if dur else ''}
  </div>
  <div class="body">
    <h3 class="slug">{html.escape(topic or name)}</h3>
    {f'<p class="why">{html.escape(why)}</p>' if why else ''}
    {f'<p class="angle"><span>ángulo</span>{html.escape(angle)}</p>' if angle else ''}
    <ul class="ev">{links}</ul>
    {f'<div class="rels">{rel}</div>' if rel else ''}
  </div>
  <div class="viz">
    {trace_svg(r["history"], r["volume"], color)}
    <div class="chips">{chips}</div>
  </div>
  <div class="num">
    <div class="z" style="--c:{color}">{z}</div>
    <div class="zl">z-score</div>
    <div class="vel">{arrow} {vel * 100:+.0f}%</div>
  </div>
</article>"""


CSS = """
:root{
  --ground:#151A21; --raised:#1B222C; --rule:#2B3441;
  --ink:#E7EAEF; --ink-dim:#8794A5; --ghost:#38424F;
  --cherry:#E8455F; --salmon:#F2836B; --goldenrod:#E0A82E; --buff:#D8C79E;
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
  font-family:'Archivo',system-ui,sans-serif;font-size:14px;line-height:1.45;
  -webkit-font-smoothing:antialiased}
a{color:inherit}
.wrap{max-width:1180px;margin:0 auto;padding:40px 24px 80px}

.masthead{border-bottom:2px solid var(--ink);padding-bottom:14px;margin-bottom:8px;
  display:flex;align-items:baseline;justify-content:space-between;gap:20px;flex-wrap:wrap}
.masthead h1{margin:0;font-size:34px;font-weight:800;letter-spacing:-.03em;
  text-transform:uppercase}
.masthead .date{font-family:'JetBrains Mono',monospace;font-size:13px;color:var(--ink-dim)}
.tally{font-family:'JetBrains Mono',monospace;font-size:11.5px;color:var(--ink-dim);
  margin:0 0 40px;letter-spacing:.02em}

.market{margin:44px 0 0}
.market > header{display:flex;align-items:center;gap:14px;
  padding-bottom:9px;border-bottom:1px solid var(--rule);margin-bottom:4px}
.market h2{margin:0;font-size:15px;font-weight:700;letter-spacing:.16em;text-transform:uppercase}
.market .cpm{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--ink-dim);
  border:1px solid var(--rule);border-radius:3px;padding:1px 6px}
.market .count{margin-left:auto;font-family:'JetBrains Mono',monospace;font-size:11px;
  color:var(--ink-dim)}

.row{display:grid;grid-template-columns:34px 96px 1fr 150px 76px;gap:18px;
  padding:20px 0;border-bottom:1px solid var(--rule);align-items:start}
.rank{font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--ghost);padding-top:3px}
.pill{display:inline-block;font-size:9.5px;font-weight:700;letter-spacing:.11em;
  padding:3px 7px;border-radius:2px;color:var(--ground);background:var(--c)}
.dur{display:block;margin-top:6px;font-family:'JetBrains Mono',monospace;
  font-size:10px;color:var(--ink-dim)}
.slug{margin:0;font-size:19px;font-weight:700;letter-spacing:-.02em;line-height:1.2}
.why{margin:7px 0 0;font-family:'Newsreader',Georgia,serif;font-size:15.5px;
  line-height:1.5;color:#C6CEDA}
.angle{margin:8px 0 0;font-size:12.5px;color:var(--ink-dim)}
.angle span{display:inline-block;font-size:9px;font-weight:700;letter-spacing:.12em;
  text-transform:uppercase;color:var(--ghost);margin-right:7px}
.ev{list-style:none;margin:11px 0 0;padding:0}
.ev li{font-size:12px;line-height:1.5;color:var(--ink-dim);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ev a{text-decoration:none;border-bottom:1px solid var(--rule)}
.ev a:hover{border-bottom-color:var(--ink-dim);color:var(--ink)}
.ev .src{color:var(--ghost);margin-left:7px;font-size:10.5px}
.rels{margin-top:10px;display:flex;flex-wrap:wrap;gap:5px}
.rel{font-size:10.5px;color:var(--ghost);border:1px dashed var(--rule);
  border-radius:2px;padding:1px 6px}
.viz .trace{display:block}
.chips{margin-top:8px;display:flex;flex-wrap:wrap;gap:4px}
.chip{font-family:'JetBrains Mono',monospace;font-size:9.5px;color:var(--ink-dim);
  border:1px solid var(--rule);border-radius:2px;padding:1px 5px}
.num{text-align:right}
.z{font-family:'JetBrains Mono',monospace;font-size:25px;font-weight:600;color:var(--c);
  line-height:1;letter-spacing:-.04em}
.zl{font-size:8.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--ghost);margin-top:4px}
.vel{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--ink-dim);margin-top:8px}

.legend{margin-top:56px;padding-top:20px;border-top:1px solid var(--rule);
  font-size:12px;color:var(--ink-dim);line-height:1.7}
.legend h4{margin:0 0 8px;font-size:10px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--ghost)}
.legend code{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--ink)}
.gap{margin-top:18px;padding:12px 14px;border-left:2px solid var(--goldenrod);
  background:var(--raised);border-radius:0 3px 3px 0}
.empty{padding:30px 0;color:var(--ink-dim);font-family:'Newsreader',serif;font-size:15px}

@media (max-width:820px){
  .wrap{padding:26px 16px 60px}
  .masthead h1{font-size:26px}
  .row{grid-template-columns:1fr 76px;gap:12px;row-gap:14px}
  .rank{display:none}
  .state{grid-column:1}
  .num{grid-column:2;grid-row:1;text-align:right}
  .body{grid-column:1/-1}
  .viz{grid-column:1/-1}
}
@media (prefers-reduced-motion:no-preference){
  .row{animation:in .45s cubic-bezier(.2,.7,.3,1) backwards}
}
@keyframes in{from{opacity:0;transform:translateY(5px)}}

/* ── Banda de última hora ── */
.breaking{margin:0 0 40px;border:1px solid var(--cherry);border-radius:6px;
  background:linear-gradient(180deg,rgba(232,69,95,.10),rgba(232,69,95,.02));
  padding:16px 18px 18px}
.brk-header{display:flex;align-items:baseline;gap:10px;font-size:14px;font-weight:800;
  letter-spacing:.14em;text-transform:uppercase;color:var(--cherry);margin-bottom:14px}
.brk-bolt{font-size:16px}
.brk-sub{margin-left:auto;font-family:'JetBrains Mono',monospace;font-size:10px;
  font-weight:400;letter-spacing:.02em;text-transform:none;color:var(--ink-dim)}
.brk-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px}
.brk-card{display:block;text-decoration:none;border:1px solid var(--rule);
  border-radius:4px;padding:12px;background:var(--raised);transition:border-color .15s}
.brk-card:hover{border-color:var(--cherry)}
.brk-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:7px}
.brk-mkt{font-family:'JetBrains Mono',monospace;font-size:9.5px;letter-spacing:.1em;
  text-transform:uppercase;color:var(--ink-dim)}
.brk-when{font-family:'JetBrains Mono',monospace;font-size:9.5px;color:var(--cherry)}
.brk-name{font-size:16px;font-weight:700;color:var(--ink);letter-spacing:-.01em;
  line-height:1.2;margin-bottom:5px}
.brk-head{font-family:'Newsreader',Georgia,serif;font-size:13px;line-height:1.4;
  color:#C6CEDA;margin-bottom:8px}
.brk-srcs{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--goldenrod)}
@media (prefers-reduced-motion:no-preference){
  .breaking{animation:in .4s cubic-bezier(.2,.7,.3,1) backwards}
  .brk-bolt{animation:pulse 2s ease-in-out infinite}
}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.45}}
"""


def _breaking_band(alerts, market_names):
    """La banda ⚡ Última hora. Solo se dibuja si hay alertas activas — cuando
    no hay nada rompiendo, no ocupa espacio."""
    if not alerts:
        return ""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    cards = []
    for a in alerts:
        try:
            first = datetime.fromisoformat(a["first_seen"])
            mins = int((now - first).total_seconds() / 60)
            when = "ahora" if mins < 2 else (f"hace {mins} min" if mins < 60
                                             else f"hace {mins // 60}h {mins % 60}min")
        except (ValueError, TypeError, KeyError):
            when = ""
        mkt = market_names.get(a["market"], a["market"])
        cards.append(
            f'<a class="brk-card" href="{html.escape(a.get("url") or "#")}" '
            f'target="_blank" rel="noopener">'
            f'<div class="brk-top"><span class="brk-mkt">{html.escape(mkt)}</span>'
            f'<span class="brk-when">{when}</span></div>'
            f'<div class="brk-name">{html.escape(a["display"])}</div>'
            f'<div class="brk-head">{html.escape((a.get("headline") or "")[:120])}</div>'
            f'<div class="brk-srcs">{a["n_sources"]} fuentes cubriéndolo</div></a>')
    return (f'<section class="breaking"><header class="brk-header">'
            f'<span class="brk-bolt">⚡</span> Última hora'
            f'<span class="brk-sub">rupturas de los últimos minutos · se actualiza cada 15 min</span>'
            f'</header><div class="brk-grid">{"".join(cards)}</div></section>')


def render(day, markets, spikes, briefs, conn, db, coverage, cfg, breaking_alerts=None):
    names = {m["id"]: m for m in markets}
    sections = []

    for m in markets:
        rows = [r for r in spikes if r["market"] == m["id"]][:cfg["top_per_market"]]
        head = (f'<header><h2>{html.escape(m["name"])}</h2>'
                f'<span class="cpm">CPM ×{m.get("cpm_index", 1.0)}</span>'
                f'<span class="count">{len(rows)} temas</span></header>')
        if not rows:
            body = ('<p class="empty">Nada perforó el umbral hoy. Con pocos días de '
                    'historia esto es normal: el sistema todavía está aprendiendo el '
                    'ruido de fondo.</p>')
        else:
            body = "".join(
                _row(i, r, db.display_name(conn, r["entity_key"]),
                     briefs.get((r["market"], r["entity_key"])),
                     db.evidence(conn, r["entity_key"], r["market"], day),
                     db.source_split(conn, r["entity_key"], r["market"], day),
                     [db.display_name(conn, k) for k in (r.get("related") or [])])
                for i, r in enumerate(rows, 1))
        sections.append(f'<section class="market">{head}{body}</section>')

    tally = " · ".join(
        f"{mid}: " + ", ".join(f"{s} {n}" for s, n in rep.items())
        for mid, rep in coverage.items())
    n_items = conn.execute("SELECT COUNT(*) c FROM items WHERE day=?", (day,)).fetchone()["c"]
    hist = conn.execute("SELECT COUNT(DISTINCT day) c FROM items").fetchone()["c"]

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pauta del día — {day}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;700;800&family=Newsreader:opsz,wght@6..72,400;6..72,500&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>{CSS}</style></head>
<body><div class="wrap">
<div class="masthead"><h1>Pauta del día</h1><span class="date">{day}</span></div>
<p class="tally">{html.escape(str(n_items))} items nuevos · {hist} días de historia acumulada · {html.escape(tally)}</p>
{_breaking_band(breaking_alerts or [], {m["id"]: m["name"] for m in markets})}
{"".join(sections)}
<div class="legend">
  <h4>Cómo leer esto</h4>
  <p><code>PICO</code> el tema perforó su ruido de fondo y sigue subiendo — es lo que hay que producir hoy.
  <code>TECHO</code> perforó pero ya viene bajando: llegaste tarde, evaluá si vale.
  <code>NUEVO</code> no tiene historia suficiente para comparar; el z no significa nada todavía.
  <code>OBSERVAR</code> se mueve, no explota.</p>
  <p>La banda gris de la traza es el territorio normal del tema (mediana ± ruido). La barra
  de color es hoy. Si la barra se sale de la banda, pasó algo.</p>
  <div class="gap"><strong>Hueco conocido:</strong> TikTok e Instagram no tienen API pública de
  tendencias. Esta pauta no los cubre — hay que mirarlos a mano o pagar un scraper.
  Ver README.</div>
</div>
</div></body></html>"""


def write(html_str, out_dir, day):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"pauta-{day}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_str)
    latest = os.path.join(out_dir, "index.html")
    with open(latest, "w", encoding="utf-8") as f:
        f.write(html_str)
    return path
