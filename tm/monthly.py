"""Retrospectiva mensual: los 5 temas de más repercusión por mercado, con un
análisis de por qué se volvieron tendencia. A diferencia de la pauta diaria
(que mira UN día contra su baseline de 28 días), esto mira TODOS los días del
mes y se queda con el mejor rank que cada tema alcanzó en cualquier día.

Dos fuentes de datos, porque la retención de 30 días (tm/db.py:prune) podó
los items/spikes crudos de antes de fines de julio:
  - Días que siguen en la base viva: se leen de items/spikes directo.
  - Días más viejos: se parsean del HTML archivado (reports/pauta-*.html),
    que nunca se borra — el propio render ya tiene rank, estado y evidencia
    tal cual quedaron ese día.
Las dos devuelven el mismo shape de fila, así el resto del pipeline no
necesita saber de dónde vino cada una.
"""
import html as htmlmod
import json
import logging
import os
import re
from datetime import date, timedelta

from . import tags as tagmatch
from . import report

log = logging.getLogger("tm.monthly")

TOP_N = 5

_SECTION_RE = re.compile(
    r'<section class="market" id="mkt-([A-Z]+)"[^>]*>(.*?)</section>', re.S)
_ROW_RE = re.compile(
    r'<article class="row"[^>]*data-status="([^"]*)"[^>]*>(.*?)</article>', re.S)
_SLUG_RE = re.compile(r'<h3 class="slug">(.*?)</h3>', re.S)
_Z_RE = re.compile(r'<div class="z"[^>]*>([^<]*)</div>')
_EV_RE = re.compile(
    r'<li><a href="([^"]*)"[^>]*>(.*?)</a><span class="src">(.*?)</span></li>')


def _unesc(s):
    return htmlmod.unescape(s or "").strip()


def _parse_z(txt):
    txt = (txt or "").strip()
    if txt == "50+":
        return 50.0
    try:
        return float(txt)
    except ValueError:
        return 0.0  # "—" (NUEVO, sin baseline) u otro texto no numérico


def parse_archived_report(path):
    """[{market, rank, status, name, z, evidence:[{title,url,author}]}] a
    partir de un pauta-YYYY-MM-DD.html ya escrito. Lee la evidencia tal cual
    quedó guardada ese día — no reconstruye nada."""
    with open(path, encoding="utf-8") as f:
        doc = f.read()
    out = []
    for mkt, section in _SECTION_RE.findall(doc):
        for i, (status, block) in enumerate(_ROW_RE.findall(section), 1):
            slug_m = _SLUG_RE.search(block)
            if not slug_m:
                continue
            z_m = _Z_RE.search(block)
            evidence = [
                {"url": u, "title": _unesc(t), "author": _unesc(a)}
                for u, t, a in _EV_RE.findall(block)
            ]
            out.append({
                "market": mkt, "rank": i, "status": status,
                "name": _unesc(slug_m.group(1)),
                "z": _parse_z(z_m.group(1) if z_m else ""),
                "evidence": evidence,
            })
    return out


def day_candidates_from_db(conn, db, day, markets):
    """Mismo shape que parse_archived_report(), leyendo la base viva."""
    out = []
    for m in markets:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM spikes WHERE day=? AND market=? ORDER BY value DESC",
            (day, m["id"]))]
        for i, r in enumerate(rows, 1):
            ev = db.evidence(conn, r["entity_key"], r["market"], day, limit=6)
            out.append({
                "market": m["id"], "rank": i, "status": r["status"],
                "name": db.display_name(conn, r["entity_key"]), "z": r["z"],
                "evidence": [{"url": e["url"], "title": e["title"],
                             "author": e["author"] or e["source"]} for e in ev],
            })
    return out


def _norm(name):
    name = (name or "").strip().lower()
    name = re.sub(r"[’']s\b", "", name)  # "Hayden Panettiere's" -> "hayden panettiere"
    return re.sub(r"\s+", " ", name).strip()


def _collapse_month(cands, thresh=0.3):
    """El mismo hecho puede picar en días distintos bajo entidades distintas
    ("Hayden Panettiere" un día, "Hayden Panettiere's" otro) — spike.py ya
    colapsa esto DENTRO de un día (collapse_stories), pero acá cruzamos
    varios días con dos fuentes de datos, así que hace falta de nuevo.
    Mismo criterio: si comparten evidencia (URLs) o un nombre contiene al
    otro, es la misma historia — se queda la de mejor rank."""
    cands = sorted(cands, key=lambda c: (c["rank"], -c["z"]))
    heads = []
    for c in cands:
        urls = {e["url"] for e in c["evidence"] if e.get("url")}
        n = _norm(c["display"])
        absorbed = False
        for h in heads:
            h_urls = {e["url"] for e in h["evidence"] if e.get("url")}
            h_n = _norm(h["display"])
            overlap = len(urls & h_urls) / max(1, min(len(urls), len(h_urls)))
            same_name = n and h_n and (n in h_n or h_n in n)
            if overlap >= thresh or same_name:
                absorbed = True
                break
        if not absorbed:
            heads.append(c)
    return heads


def _daterange(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def collect_month(conn, db, out_dir, year, month, markets, excluir_cfg):
    """{market_id: [hasta TOP_N filas]}, ordenadas por mejor rank alcanzado
    en el mes (empate: mayor z). Filtra gaming/conflicto igual que la pauta
    diaria (tagmatch.excluded_categories, context='pauta_diaria') — un tema
    que no entraría hoy tampoco debería aparecer en el resumen del mes."""
    start = date(year, month, 1)
    end = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    end = min(end, date.today())
    if start > end:
        return {m["id"]: [] for m in markets}

    row = conn.execute("SELECT MIN(day) AS d FROM items").fetchone()
    db_min = date.fromisoformat(row["d"]) if row and row["d"] else None

    best = {}  # (market, nombre normalizado) -> fila ganadora
    days_seen = 0
    for d in _daterange(start, end):
        day_s = d.isoformat()
        if db_min and d >= db_min:
            rows = day_candidates_from_db(conn, db, day_s, markets)
        else:
            path = os.path.join(out_dir, f"pauta-{day_s}.html")
            if not os.path.exists(path):
                continue
            rows = parse_archived_report(path)
        if rows:
            days_seen += 1
        for r in rows:
            # Por NOTA individual, no por tema completo (mismo criterio que
            # run.py/tags.filter_excluded_items para la pauta diaria): un
            # tema real con una sola nota incidental de gaming (ej. "Nvidia"
            # con un hashtag #pcgaming perdido en una de tres notas) no debe
            # desaparecer entero — se saca esa nota y listo.
            if tagmatch.excluded_categories(r["name"], excluir_cfg, "pauta_diaria"):
                continue  # el nombre del tema EN SÍ matchea -> afuera
            # Título Y canal/autor: un video de gaming a veces no dice
            # "gaming" en el título, pero sí en el nombre del canal (ej.
            # "CaseOh", streamer, ninguna de sus notas lo menciona en texto).
            clean_ev = [e for e in r["evidence"]
                       if not tagmatch.excluded_categories(
                           f"{e['title']} {e.get('author', '')}", excluir_cfg, "pauta_diaria")]
            if not clean_ev:
                continue  # se quedó sin ninguna nota limpia
            r = {**r, "evidence": clean_ev}
            key = (r["market"], _norm(r["name"]))
            cur = best.get(key)
            better = cur is None or r["rank"] < cur["rank"] or \
                (r["rank"] == cur["rank"] and r["z"] > cur["z"])
            if better:
                best[key] = {**r, "day": day_s, "display": r["name"]}

    log.info("%s-%02d: %d días con datos, %d temas únicos", year, month, days_seen, len(best))

    top = {}
    for m in markets:
        cands = [v for (mkt, _), v in best.items() if mkt == m["id"]]
        cands = _collapse_month(cands)
        top[m["id"]] = cands[:TOP_N]
    return top


MONTHLY_SYSTEM = """Sos el editor de la retrospectiva mensual de una operación de video corto \
que publica en tres mercados (Estados Unidos/inglés, Francia/francés, México/español).

Te paso, por mercado, los temas que más repercusión tuvieron durante todo el mes, con la \
evidencia cruda del día en que llegaron más arriba: titulares y fuente.

Reglas:
- El análisis sale SOLO de la evidencia que te doy. Si no alcanza para explicar por qué se \
volvió tendencia, escribí exactamente: "No está claro en la evidencia." No inventes contexto \
que no esté en los titulares.
- "topic": nombre limpio y legible del tema, 2-6 palabras. La evidencia trae nombres de \
entidad extraídos automáticamente — a veces vienen fragmentados o en mayúsculas sueltas; \
arreglalo vos.
- "why": 2-3 frases, mirando el mes completo — qué pasó y por qué explotó, no solo el día \
del pico.
- Escribí en español rioplatense neutro, seco, sin adjetivos de relleno.

Devolvé SOLO un array JSON, sin markdown ni texto alrededor:
[{"rank": 1, "topic": "...", "why": "..."}]"""


def _parse_json_array(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    log.warning("monthly: respuesta no parseable del modelo")
    return []


def generate_analysis(top, markets, model, api_key):
    """Completa cada fila de `top` con topic/why, mutando in-place. Sin
    ANTHROPIC_API_KEY, el mensual sale igual pero sin el análisis (mismo
    criterio que tm/explain.py para la pauta diaria)."""
    if not api_key:
        log.info("monthly: sin ANTHROPIC_API_KEY, sale sin análisis")
        return
    try:
        import anthropic
    except ImportError:
        log.warning("monthly: falta `pip install anthropic`")
        return

    client = anthropic.Anthropic(api_key=api_key)
    names = {m["id"]: m["name"] for m in markets}
    for mkt, cands in top.items():
        if not cands:
            continue
        payload = "\n\n".join(
            f"  rank {i}: {c['display']}\n" +
            "\n".join(f"    - [{e['author']}] {e['title']}" for e in c["evidence"][:5])
            for i, c in enumerate(cands, 1))
        prompt = f"Mercado: {names.get(mkt, mkt)} ({mkt})\n\nTemas del mes:\n\n{payload}"
        try:
            resp = client.messages.create(
                model=model, max_tokens=1500,
                system=MONTHLY_SYSTEM,
                messages=[{"role": "user", "content": prompt}])
            text = "".join(b.text for b in resp.content if b.type == "text")
        except Exception as e:
            log.error("monthly explain %s: %s", mkt, e)
            continue
        for item in _parse_json_array(text):
            r = item.get("rank")
            if isinstance(r, int) and 1 <= r <= len(cands):
                cands[r - 1]["topic"] = item.get("topic") or cands[r - 1]["display"]
                cands[r - 1]["why"] = item.get("why") or ""


def apply_analysis(top, analysis):
    """Alternativa a generate_analysis() que no llama a Claude: aplica un
    topic/why ya escrito, indexado por mercado -> nombre del tema (tal cual
    aparece en `display`, sin normalizar — se normaliza acá adentro para que
    no haga falta que coincida carácter por carácter). Pensado para cuando no
    hay ANTHROPIC_API_KEY pero el análisis se escribió a mano con la misma
    evidencia que hubiera visto el modelo."""
    for mkt, cands in top.items():
        by_name = {_norm(k): v for k, v in (analysis.get(mkt) or {}).items()}
        for c in cands:
            a = by_name.get(_norm(c["display"]))
            if a:
                c["topic"] = a.get("topic") or c["display"]
                c["why"] = a.get("why") or ""


# ── Render ────────────────────────────────────────────────────────────────
MONTH_NAMES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio",
               "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

_MONTH_RE = re.compile(r"mensual-(\d{4})-(\d{2})\.html$")


def _card(i, c, market_id):
    topic = c.get("topic") or c["display"]
    why = c.get("why") or ""
    day_fmt = date.fromisoformat(c["day"]).strftime("%d/%m")
    z = c["z"]
    zfmt = "50+" if z >= 50 else f"{z:.1f}"
    ev = "".join(
        f'<li><a href="{htmlmod.escape(e["url"] or "#")}" target="_blank" rel="noopener">'
        f'{htmlmod.escape((e["title"] or "")[:96])}</a>'
        f'<span class="src">{htmlmod.escape(e["author"])}</span></li>'
        for e in c["evidence"][:3])
    why_html = (f'<p class="why">{htmlmod.escape(why)}</p>' if why
                else '<p class="mnoanalysis">Sin análisis — no está claro en la evidencia.</p>')
    row_class = "row mrow lead" if i == 1 else "row mrow"
    return f"""
<article class="{row_class}" style="--c:var(--accent)">
  <div class="rank">{i:02d}</div>
  <div class="body">
    <h3 class="slug">{htmlmod.escape(topic)}</h3>
    {why_html}
    <ul class="ev">{ev}</ul>
    <div class="mmeta">pico el {day_fmt} · z {zfmt}</div>
  </div>
</article>"""


def _available_months(out_dir):
    """[(year, month, filename)] de todos los mensual-YYYY-MM.html en out_dir,
    más nuevo primero."""
    if not os.path.isdir(out_dir):
        return []
    out = []
    for name in os.listdir(out_dir):
        m = _MONTH_RE.match(name)
        if m:
            out.append((int(m.group(1)), int(m.group(2)), name))
    return sorted(out, reverse=True)


def _month_selector(out_dir, current_year, current_month):
    months = _available_months(out_dir)
    key = (current_year, current_month)
    if key not in {(y, m) for y, m, _ in months}:
        months = sorted(months + [(current_year, current_month,
                        f"mensual-{current_year}-{current_month:02d}.html")], reverse=True)
    pills = []
    for y, m, fname in months:
        on = " on" if (y, m) == key else ""
        pills.append(f'<a class="tab{on}" href="{fname}">{MONTH_NAMES[m]} {y}</a>')
    return "".join(pills)


def render(year, month, top, markets, out_dir):
    month_name = MONTH_NAMES[month]
    sections = []
    for m in markets:
        cands = top.get(m["id"], [])
        cards = "".join(_card(i, c, m["id"]) for i, c in enumerate(cands, 1))
        if not cands:
            cards = ('<p class="empty">Sin temas para este mercado este mes '
                     '(o todos filtrados por gaming/conflicto).</p>')
        sections.append(
            f'<section class="market" id="mkt-{m["id"]}">'
            f'<header><h2>{htmlmod.escape(m["name"])}</h2>'
            f'<span class="count">top {len(cands)}</span></header>{cards}</section>')

    selector = _month_selector(out_dir, year, month)

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#000000" media="(prefers-color-scheme: dark)">
<meta name="theme-color" content="#F5F5F4" media="(prefers-color-scheme: light)">
<title>Lo mejor de {month_name} — Pauta Upsomedia</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%23000000'/%3E%3Ccircle cx='16' cy='16' r='7' fill='%23FFC72C'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;700;800&family=Newsreader:opsz,wght@6..72,400;6..72,500&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>{report.CSS}</style>
<script>try{{var t=localStorage.getItem('pauta-theme');
if(t)document.documentElement.dataset.theme=t}}catch(e){{}}</script>
</head>
<body>
<nav class="topbar"><div class="in">
  <span class="brand">Upsomedia · Lo mejor del mes</span>
  <div class="tabs">{selector}<a class="tab" href="index.html">pauta diaria →</a></div>
  <button class="theme" id="theme" type="button" title="Cambiar tema"
    aria-label="Cambiar entre tema claro y oscuro">◐</button>
</div></nav>
<div class="wrap">
<p class="mintro">Los 5 temas de más repercusión de {month_name} de {year} en cada
mercado — el mejor rank que alcanzaron en cualquier día del mes, con un análisis
de por qué se volvieron tendencia.</p>
{"".join(sections)}
</div>
<script>{report.JS}</script>
</body></html>"""


def write(html_str, out_dir, year, month):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"mensual-{year}-{month:02d}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_str)
    return path


_SELECTOR_RE = re.compile(r'<div class="tabs">.*?</div>', re.S)


def sync_selector(out_dir):
    """Reescribe el selector de mes en TODOS los mensual-*.html existentes,
    para que cada uno liste el conjunto completo de meses disponibles — mismo
    criterio que report.sync_archive() para el dropdown de días."""
    months = _available_months(out_dir)
    touched = []
    for y, m, fname in months:
        path = os.path.join(out_dir, fname)
        with open(path, encoding="utf-8") as f:
            doc = f.read()
        selector = _month_selector(out_dir, y, m)
        new_tabs = (f'<div class="tabs">{selector}'
                    f'<a class="tab" href="index.html">pauta diaria →</a></div>')
        new_doc, n = _SELECTOR_RE.subn(lambda _m: new_tabs, doc, count=1)
        if n and new_doc != doc:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_doc)
            touched.append(fname)
    return touched
