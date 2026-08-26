"""Render de la pauta.

El elemento central es la traza: 28 días de barras con la banda de ruido
dibujada encima. Casi todos los dashboards te muestran una sparkline y un
número; acá ves de dónde se escapó el pico. Un guionista que ve la barra
saliéndose de la banda entiende el z-score sin que nadie le explique qué es
una mediana absoluta de desviaciones.

Paleta de marca UPSOMEDIA. La marca solo definió dark mode (--st-*, --accent
etc. en :root); el modo claro es una derivación nuestra, NO viene de la
marca: mismo hue por acento pero oscurecido, porque los tonos vivos que
dieron (ej. #FFC72C) dan <2:1 de contraste como texto sobre blanco — sin
oscurecerlos el modo claro sería ilegible. Ver el bloque
`@media (prefers-color-scheme: light)` / `:root[data-theme=light]` en CSS.

Los 4 colores de estado (dark mode) son los acentos secundarios de la marca;
validados con el verificador de accesibilidad del skill de dataviz contra
las superficies reales (--card #1A1A1A, --ground #000000): contraste >=4:1
los cuatro, separación CVD adyacente ΔE>=8 en la mayoría de los pares. La
excepción es naranja/magenta (PICO/TECHO), que da ΔE~12.7 (<15, el piso
"visión normal"): un usuario daltónico O con visión normal podría
confundirlos si el color viajara solo. Por eso NUNCA viaja solo — la píldora
siempre lleva el texto del estado (PICO/TECHO/NUEVO/OBSERVAR), que es la
mitigación que el propio skill exige para un par en esa banda.
"""
import html
import os
import re
from datetime import date
from statistics import median

from . import tags as tagmatch

STATUS = {
    "PICO":     ("var(--st-pico)",     "PICO"),
    "NUEVO":    ("var(--st-nuevo)",    "NUEVO"),
    "OBSERVAR": ("var(--st-observar)", "OBSERVAR"),
    "TECHO":    ("var(--st-techo)",    "TECHO"),
}
SOURCE_LABEL = {"gtrends": "búsquedas", "gnews": "prensa", "rss": "medios",
                "youtube": "video", "reddit": "foros"}


def trace_svg(history, today, color, w=140, h=32):
    """Barras + banda de ruido. La banda es mediana ± 1.4826·MAD: el territorio
    donde el tema vive normalmente. Todo lo que la perfora es señal.
    Cada barra lleva un <title>: tooltip nativo con día y volumen."""
    vals = [v for _, v in history]
    days = [d for d, _ in history]
    series = vals + [today]
    labels = days + ["hoy"]
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
            f'fill="var(--band)" opacity=".14"/>')
        y_med = h - min(h, med / top * h)
        parts.append(
            f'<line x1="0" y1="{y_med:.1f}" x2="{w}" y2="{y_med:.1f}" '
            f'stroke="var(--band)" stroke-width="1" stroke-opacity=".35"/>')

    for i, v in enumerate(series):
        bh = max(0.8, v / top * h)
        x = i * (bw + 1.2)
        last = i == n - 1
        parts.append(
            f'<rect x="{x:.1f}" y="{h - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
            f'rx=".5" fill="{color if last else "var(--bar)"}" '
            f'opacity="{1 if last else .8}">'
            f'<title>{html.escape(str(labels[i]))}: {v:.1f}</title></rect>')

    return (f'<svg class="trace" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'role="img" aria-label="Volumen de los últimos {n} días">'
            + "".join(parts) + "</svg>")


def _brief_text(topic, name, why, angle, ev):
    """El texto que se lleva el guionista con un click."""
    lines = [topic or name]
    if why:
        lines.append(why)
    if angle:
        lines.append(f"Ángulo: {angle}")
    for e in ev[:3]:
        if e["url"]:
            lines.append(e["url"])
    return "\n".join(lines)


def _sat_badge(n):
    """Cuántos videos del tema ya hay arriba. Menos de 10 es ventana abierta;
    más de 50 es llegar a la fila."""
    if n is None:
        return ""
    if n < 10:
        level, hint = "baja", "ventana abierta"
    elif n <= 50:
        level, hint = "media", "competido"
    else:
        level, hint = "alta", "saturado"
    # totalResults es una estimación y para términos genéricos devuelve
    # millones; arriba de 500 el número exacto ya no agrega nada.
    shown = "500+" if n > 500 else str(n)
    return (f'<p class="sat"><span>saturación</span><b>{level}</b> — '
            f'~{shown} videos en 24 h ({hint})</p>')


def _tag_badges(name, ev, categorias):
    """Badges de categoría destacada (celebridad, rescate, policial, viral,
    boda viral). Se recalculan acá con el mismo texto (nombre + titulares de
    evidencia) y el mismo matching que usó spike.py para el boost — así el
    monitor de última hora, que re-renderiza leyendo los spikes ya guardados
    (sin el campo de boost), muestra exactamente los mismos badges."""
    if not categorias:
        return ""
    text = " ".join([name] + [e["title"] for e in ev])
    names = tagmatch.matched_tags(text, categorias)
    if not names:
        return ""
    chips = "".join(
        f'<span class="chip tag">{emoji} {html.escape(label)}</span>'
        for emoji, label in (tagmatch.BADGES[n] for n in names if n in tagmatch.BADGES))
    return chips


def _row(i, r, name, brief, ev, split, rel_names=(), sat=None, categorias=None):
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

    brief_txt = html.escape(_brief_text(topic, name, why, angle, ev), quote=True)
    tag_badges = _tag_badges(name, ev, categorias)

    # La fila #1 de cada mercado lleva un tratamiento propio (regla craft
    # R4: mata la monotonía) — si no, 36 filas idénticas leen como una
    # planilla generada, no como una pauta editada. Ver .row.lead en CSS.
    row_class = "row lead" if i == 1 else "row"

    return f"""
<article class="{row_class}" data-status="{html.escape(r["status"])}" style="--c:{color}">
  <div class="rank">{i:02d}</div>
  <div class="state">
    <span class="pill" style="--c:{color}">{label}</span>
    {f'<span class="dur">{html.escape(dur)}</span>' if dur else ''}
  </div>
  <div class="body">
    <h3 class="slug">{html.escape(topic or name)}</h3>
    {f'<p class="why">{html.escape(why)}</p>' if why else ''}
    {f'<p class="angle"><span>ángulo</span>{html.escape(angle)}</p>' if angle else ''}
    {_sat_badge(sat)}
    {f'<div class="tags">{tag_badges}</div>' if tag_badges else ''}
    <ul class="ev">{links}</ul>
    {f'<div class="rels">{rel}</div>' if rel else ''}
    <button class="copy" type="button" data-brief="{brief_txt}">Copiar brief</button>
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
  --ground:#000000; --surface:#111111; --card:#1A1A1A; --raised:#202020; --rule:#262626;
  --ink:#FFFFFF; --ink-dim:#E5E5E5; --ghost:#888888;
  --bar:#262626; --band:#E5E5E5; --pill-ink:#111111;
  --st-pico:#FF5722; --st-observar:#00A8FF; --st-nuevo:#2ECC71; --st-techo:#E91E63;
  --accent:#FFC72C;
  color-scheme:dark;
}
/* Modo claro: la marca solo definió dark mode, así que estos son shades más
   oscuros (mismo hue) de los 5 acentos — los originales vivos (#FF5722 etc.)
   dan <2:1 de contraste como texto sobre blanco (validado, no a ojo). Acá SÍ
   pasan >=4.5:1 sobre #FFFFFF. Los pills usan estos mismos tokens de fondo,
   por eso --pill-ink pasa a blanco en claro (los originales vivos solo leían
   bien con texto oscuro; estos oscurecidos leen bien con texto claro). */
@media (prefers-color-scheme: light){
  :root:not([data-theme=dark]){
    --ground:#F5F5F4; --surface:#FFFFFF; --card:#FFFFFF; --raised:#EFEFED; --rule:#E3E3E1;
    --ink:#0A0A0A; --ink-dim:#3A3A3A; --ghost:#6B6B6B;
    --bar:#E3E3E1; --band:#3A3A3A; --pill-ink:#FFFFFF;
    --st-pico:#DF3500; --st-observar:#007CBD; --st-nuevo:#1E854A; --st-techo:#E6175D;
    --accent:#976F00;
    color-scheme:light;
  }
}
:root[data-theme=light]{
  --ground:#F5F5F4; --surface:#FFFFFF; --card:#FFFFFF; --raised:#EFEFED; --rule:#E3E3E1;
  --ink:#0A0A0A; --ink-dim:#3A3A3A; --ghost:#6B6B6B;
  --bar:#E3E3E1; --band:#3A3A3A; --pill-ink:#FFFFFF;
  --st-pico:#DF3500; --st-observar:#007CBD; --st-nuevo:#1E854A; --st-techo:#E6175D;
  --accent:#976F00;
  color-scheme:light;
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
  font-family:'Archivo',system-ui,sans-serif;font-size:14px;line-height:1.45;
  -webkit-font-smoothing:antialiased}
a{color:inherit}
button{font:inherit;color:inherit}
.wrap{max-width:1180px;margin:0 auto;padding:0 24px 80px}

.topbar{position:sticky;top:0;z-index:10;background:var(--surface);
  border-bottom:2px solid var(--accent)}
.topbar .in{max-width:1180px;margin:0 auto;padding:12px 24px;
  display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.brand{font-size:19px;font-weight:800;letter-spacing:-.02em;text-transform:uppercase;
  margin-right:2px;display:inline-flex;align-items:center;gap:9px}
.brand::before{content:"";width:9px;height:9px;border-radius:2px;background:var(--accent)}
.topbar .date{font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--ghost)}
.tabs{display:flex;gap:6px;margin-left:auto}
.tab{font-size:12px;font-weight:600;letter-spacing:.06em;text-decoration:none;
  padding:5px 11px;border:1px solid var(--rule);border-radius:99px;color:var(--ghost)}
.tab:hover{color:var(--ink);border-color:var(--accent)}
.tab b{color:var(--ink);font-weight:700}
.theme{background:none;border:1px solid var(--rule);border-radius:99px;
  width:30px;height:30px;cursor:pointer;color:var(--ghost);font-size:14px;line-height:1}
.theme:hover{color:var(--ink);border-color:var(--accent)}

.hero{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;
  margin:28px 0 8px}
.tile{background:var(--card);border:1px solid var(--rule);border-radius:10px;
  padding:14px 16px;min-width:0}
.tile .v{font-size:27px;font-weight:800;letter-spacing:-.03em;line-height:1.1}
.tile .l{font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--ghost);margin-top:5px}
.tally{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--ghost);
  margin:10px 2px 26px;letter-spacing:.02em}
.tally abbr{text-decoration:underline dotted;text-decoration-color:var(--rule);
  cursor:help}

.filters{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 6px}
.filter{background:none;border:1px solid var(--rule);border-radius:99px;
  padding:5px 12px;font-size:11.5px;font-weight:600;letter-spacing:.05em;
  color:var(--ghost);cursor:pointer;display:inline-flex;align-items:center;gap:7px}
.filter .dot{width:8px;height:8px;border-radius:99px;background:var(--c,var(--ghost))}
.filter:hover{color:var(--ink)}
.filter.on{color:var(--ink);border-color:var(--ink-dim);background:var(--raised)}
.filter .n{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--ghost)}

.market{margin:34px 0 0;scroll-margin-top:64px}
.market > header{display:flex;align-items:center;gap:14px;
  padding:0 2px 10px}
.market h2{margin:0;font-size:15px;font-weight:700;letter-spacing:.16em;text-transform:uppercase}
.market .cpm{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--ghost);
  border:1px solid var(--rule);border-radius:99px;padding:1px 8px}
.market .count{margin-left:auto;font-family:'JetBrains Mono',monospace;font-size:11px;
  color:var(--ghost)}

.row{display:grid;grid-template-columns:34px 96px 1fr 156px 80px;gap:18px;
  background:var(--card);border:1px solid var(--rule);border-radius:12px;
  padding:18px 20px;margin-bottom:10px;align-items:start;
  transition:border-color .15s}
.row:hover{border-color:var(--ghost)}
.row.hide{display:none}
.row.lead{border-left:4px solid var(--c);padding-left:16px}
.row.lead .slug{font-size:27px}
.rank{font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:600;
  color:var(--ink-dim);padding-top:3px}
.pill{display:inline-block;font-size:9.5px;font-weight:700;letter-spacing:.11em;
  padding:3px 8px;border-radius:99px;color:var(--pill-ink);background:var(--c)}
.dur{display:block;margin-top:6px;font-family:'JetBrains Mono',monospace;
  font-size:10px;color:var(--ink-dim)}
.slug{margin:0;font-size:19px;font-weight:700;letter-spacing:-.02em;line-height:1.2}
.why{margin:7px 0 0;font-family:'Newsreader',Georgia,serif;font-size:15.5px;
  line-height:1.5;color:var(--ink-dim)}
.angle{margin:8px 0 0;font-size:12.5px;color:var(--ink-dim)}
.angle span{display:inline-block;font-size:9px;font-weight:700;letter-spacing:.12em;
  text-transform:uppercase;color:var(--ghost);margin-right:7px}
.sat{margin:8px 0 0;font-size:12.5px;color:var(--ink-dim)}
.sat span{display:inline-block;font-size:9px;font-weight:700;letter-spacing:.12em;
  text-transform:uppercase;color:var(--ghost);margin-right:7px}
.sat b{font-weight:700;color:var(--ink)}
.ev{list-style:none;margin:11px 0 0;padding:0}
.ev li{font-size:12px;line-height:1.55;color:var(--ink-dim);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ev a{text-decoration:none;border-bottom:1px solid var(--rule)}
.ev a:hover{border-bottom-color:var(--ink-dim);color:var(--ink)}
.ev .src{color:var(--ghost);margin-left:7px;font-size:10.5px}
.rels{margin-top:10px;display:flex;flex-wrap:wrap;gap:5px}
.rel{font-size:10.5px;color:var(--ghost);border:1px dashed var(--rule);
  border-radius:99px;padding:1px 8px}
.copy{margin-top:12px;background:none;border:1px solid var(--accent);border-radius:7px;
  padding:5px 11px;font-size:11px;font-weight:700;color:var(--accent);cursor:pointer;
  transition:background-color .15s,color .15s}
.copy:hover{background:var(--accent);color:var(--pill-ink)}
.viz .trace{display:block}
.chips{margin-top:8px;display:flex;flex-wrap:wrap;gap:4px}
.chip{font-family:'JetBrains Mono',monospace;font-size:9.5px;color:var(--ghost);
  border:1px solid var(--rule);border-radius:99px;padding:1px 7px}
.tags{margin-top:8px;display:flex;flex-wrap:wrap;gap:5px}
.chip.tag{font-family:'Archivo',system-ui,sans-serif;font-size:10.5px;font-weight:600;
  color:var(--ink);background:var(--raised);border-color:var(--ghost);padding:2px 9px}
.num{text-align:right}
.z{font-family:'JetBrains Mono',monospace;font-size:25px;font-weight:600;color:var(--c);
  line-height:1;letter-spacing:-.04em}
.zl{font-size:8.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--ghost);margin-top:4px}
.vel{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--ink-dim);margin-top:8px}

.legend{margin-top:56px;padding-top:20px;border-top:1px solid var(--rule);
  font-size:12px;color:var(--ghost);line-height:1.7}
.legend h4{margin:0 0 8px;font-size:10px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--ghost)}
.legend code{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--ink-dim)}
.legend .pill{margin-right:2px}
.gap{margin-top:18px;padding:12px 14px;border-left:2px solid var(--accent);
  background:var(--card);border-radius:0 8px 8px 0}
.empty{padding:26px 20px;color:var(--ink-dim);font-family:'Newsreader',serif;font-size:15px;
  background:var(--card);border:1px dashed var(--rule);border-radius:12px}

/* ── Banda de última hora ── */
.breaking{margin:22px 0 8px;border:1px solid var(--accent);border-radius:12px;
  background:linear-gradient(180deg,rgba(255,199,44,.12),rgba(255,199,44,.02));
  padding:16px 18px 18px}
.brk-header{display:flex;align-items:baseline;gap:10px;font-size:14px;font-weight:800;
  letter-spacing:.14em;text-transform:uppercase;color:var(--accent);margin-bottom:14px}
.brk-bolt{font-size:16px}
.brk-sub{margin-left:auto;font-family:'JetBrains Mono',monospace;font-size:10px;
  font-weight:400;letter-spacing:.02em;text-transform:none;color:var(--ghost)}
.brk-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px}
.brk-card{display:block;text-decoration:none;border:1px solid var(--rule);
  border-radius:10px;padding:12px;background:var(--card);transition:border-color .15s}
.brk-card:hover{border-color:var(--accent)}
.brk-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:7px}
.brk-mkt{font-family:'JetBrains Mono',monospace;font-size:9.5px;letter-spacing:.1em;
  text-transform:uppercase;color:var(--ghost)}
.brk-when{font-family:'JetBrains Mono',monospace;font-size:9.5px;color:var(--accent)}
.brk-name{font-size:16px;font-weight:700;color:var(--ink);letter-spacing:-.01em;
  line-height:1.2;margin-bottom:5px}
.brk-head{font-family:'Newsreader',Georgia,serif;font-size:13px;line-height:1.4;
  color:var(--ink-dim);margin-bottom:8px}
.brk-srcs{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--ink-dim)}

/* ── Foco de teclado ── el navegador da un outline por default que no está
   pensado para superficies negras/blancas puras; acá lo reemplazamos por
   uno propio, en el amarillo de marca, en todo lo interactivo. Nunca
   outline:none sin este reemplazo (regla craft R11). */
a:focus-visible, button:focus-visible, summary:focus-visible,
.tab:focus-visible, .filter:focus-visible, .theme:focus-visible,
.copy:focus-visible, .brk-card:focus-visible, .ev a:focus-visible{
  outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}

@media (max-width:820px){
  .wrap{padding:0 14px 60px}
  .topbar .in{padding:10px 14px}
  .tabs{margin-left:0;width:100%;order:3}
  .row{grid-template-columns:1fr 80px;gap:12px;row-gap:14px;padding:15px 15px}
  .rank{display:none}
  .state{grid-column:1}
  .num{grid-column:2;grid-row:1;text-align:right}
  .body{grid-column:1/-1}
  .viz{grid-column:1/-1}
}
@media (prefers-reduced-motion:no-preference){
  .row{animation:in .45s cubic-bezier(.2,.7,.3,1) backwards}
  .breaking{animation:in .4s cubic-bezier(.2,.7,.3,1) backwards}
  .brk-bolt{animation:pulse 2s ease-in-out infinite}
}
@keyframes in{from{opacity:0;transform:translateY(5px)}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.45}}
"""

JS = """
document.querySelectorAll('.filter').forEach(function(b){
  b.addEventListener('click',function(){
    document.querySelectorAll('.filter').forEach(function(x){
      x.classList.toggle('on',x===b)});
    var st=b.dataset.status;
    document.querySelectorAll('.row').forEach(function(r){
      r.classList.toggle('hide',st!=='ALL'&&r.dataset.status!==st)});
  });
});
document.querySelectorAll('.copy').forEach(function(b){
  b.addEventListener('click',function(){
    navigator.clipboard.writeText(b.dataset.brief).then(function(){
      b.textContent='Copiado ✓';
      setTimeout(function(){b.textContent='Copiar brief'},1600);
    });
  });
});
document.getElementById('theme').addEventListener('click',function(){
  var root=document.documentElement;
  var cur=root.dataset.theme||
    (matchMedia('(prefers-color-scheme: light)').matches?'light':'dark');
  var next=cur==='dark'?'light':'dark';
  root.dataset.theme=next;
  try{localStorage.setItem('pauta-theme',next)}catch(e){}
});
"""


# Estilo del selector de archivo. Va EMBEBIDO dentro del propio control (no en
# el CSS global) para que sync_archive() pueda inyectar el dropdown completo en
# reportes viejos sin depender del CSS con que se generaron. Usa las variables
# de tema (--ground, --rule…) que todos los reportes ya definen.
ARCH_CSS = """
details.arch{position:relative;display:inline-block;border:0;padding:0;margin:0;background:none}
details.arch>summary{list-style:none;cursor:pointer;user-select:none;
  font-family:'JetBrains Mono',monospace;font-size:11.5px;color:var(--ghost);
  background:var(--ground);border:1px solid var(--rule);border-radius:7px;
  padding:4px 8px;display:inline-flex;align-items:center;gap:6px}
details.arch>summary::-webkit-details-marker{display:none}
details.arch>summary::marker{content:""}
details.arch>summary:hover{color:var(--ink);border-color:var(--accent)}
details.arch .arch-caret{font-size:9px;transition:transform .15s}
details.arch[open]>summary .arch-caret{transform:rotate(180deg)}
details.arch>ul{position:absolute;top:calc(100% + 5px);left:0;z-index:30;
  margin:0;padding:4px;list-style:none;min-width:150px;
  background:var(--card);border:1px solid var(--rule);border-radius:8px;
  box-shadow:0 10px 28px rgba(0,0,0,.6);
  max-height:322px;overflow-y:auto;overscroll-behavior:contain}
details.arch>ul li{margin:0}
details.arch>ul a{display:block;text-decoration:none;border-radius:5px;
  font-family:'JetBrains Mono',monospace;font-size:11.5px;color:var(--ghost);
  padding:6px 9px;white-space:nowrap}
details.arch>ul a:hover{background:var(--raised);color:var(--ink)}
details.arch>ul a.on{color:var(--accent);background:var(--raised)}
"""


def _archive_control(days, selected):
    """El selector de archivo. Lista SIEMPRE todas las fechas con reporte, de
    más nueva a más vieja; la que está abierta solo se resalta, nunca altera la
    lista. Es <details> puro (sin JS) y trae su propio <style>, así el mismo
    bloque sirve tanto al render de hoy como a sync_archive() reescribiendo
    reportes viejos. La caja tiene alto máximo (~10 fechas) con scroll contenido
    en lugar de crecer sin límite."""
    days = sorted(set(days), reverse=True)
    if len(days) <= 1:
        return f'<span class="date" id="arch">{html.escape(selected)}</span>'
    items = []
    for d in days:
        on = ' class="on"' if d == selected else ''
        items.append(
            f'<li><a{on} href="pauta-{html.escape(d)}.html">{html.escape(d)}</a></li>')
    return (
        '<details class="arch" id="arch">'
        f'<summary>{html.escape(selected)}<span class="arch-caret">▾</span></summary>'
        f'<ul>{"".join(items)}</ul>'
        f'<style>{ARCH_CSS}</style>'
        '</details>')


# Localiza el control de archivo dentro de un reporte ya escrito: el <details>
# nuevo, el <select> viejo, o el <span class="date"> de un reporte de un solo
# día. Se reemplaza SOLO la primera coincidencia (el control vive en la topbar,
# antes que cualquier contenido).
_ARCH_RE = re.compile(
    r'<details class="arch" id="arch">.*?</details>'
    r'|<select class="arch" id="arch"[^>]*>.*?</select>'
    r'|<span class="date"[^>]*>[^<]*</span>',
    re.DOTALL)
_TITLE_DAY_RE = re.compile(r'<title>[^<]*?(\d{4}-\d{2}-\d{2})[^<]*</title>')


def sync_archive(out_dir):
    """Reescribe el selector de archivo en TODOS los pauta-*.html (e index.html)
    para que cada uno liste el conjunto COMPLETO de fechas disponibles.

    Cada reporte es un archivo estático generado en su día: sin esto, un reporte
    viejo conserva el dropdown corto que tenía al generarse y, al abrirlo, las
    fechas más nuevas 'desaparecen'. Acá igualamos la lista en todos, resaltando
    en cada uno su propia fecha. Idempotente. Devuelve los archivos tocados."""
    if not os.path.isdir(out_dir):
        return []
    files = sorted(f for f in os.listdir(out_dir)
                   if f.startswith("pauta-") and f.endswith(".html"))
    days = sorted((f[len("pauta-"):-len(".html")] for f in files), reverse=True)
    if not days:
        return []
    targets = list(files)
    if os.path.exists(os.path.join(out_dir, "index.html")):
        targets.append("index.html")

    touched = []
    for name in targets:
        path = os.path.join(out_dir, name)
        with open(path, encoding="utf-8") as fh:
            doc = fh.read()
        m = _TITLE_DAY_RE.search(doc)
        selected = m.group(1) if m else days[0]
        control = _archive_control(days, selected)
        new_doc, n = _ARCH_RE.subn(lambda _m: control, doc, count=1)
        if n and new_doc != doc:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new_doc)
            touched.append(name)
    return touched


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


def render(day, markets, spikes, briefs, conn, db, coverage, cfg,
           saturation=None, archive=(), breaking_alerts=None, categorias=None,
           excluded_counts=None):
    saturation = saturation or {}
    sections = []
    tabs = []
    status_count = {}
    total = 0

    for m in markets:
        rows = [r for r in spikes if r["market"] == m["id"]][:cfg["top_per_market"]]
        total += len(rows)
        for r in rows:
            status_count[r["status"]] = status_count.get(r["status"], 0) + 1
        tabs.append(f'<a class="tab" href="#mkt-{m["id"]}">'
                    f'{html.escape(m["id"])} <b>{len(rows)}</b></a>')
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
                     [db.display_name(conn, k) for k in (r.get("related") or [])],
                     sat=saturation.get((r["market"], r["entity_key"])),
                     categorias=categorias)
                for i, r in enumerate(rows, 1))
        sections.append(
            f'<section class="market" id="mkt-{m["id"]}">{head}{body}</section>')

    filters = ['<button class="filter on" type="button" data-status="ALL">'
               f'Todos <span class="n">{total}</span></button>']
    for st, (color, label) in STATUS.items():
        n = status_count.get(st, 0)
        if n:
            filters.append(
                f'<button class="filter" type="button" data-status="{st}" '
                f'style="--c:{color}"><span class="dot"></span>{label} '
                f'<span class="n">{n}</span></button>')

    def _cov_piece(source, n):
        # sources.collect() guarda "ERROR: <excepción>" cuando una fuente
        # falla (ej. Google News caído). Mostrar esa excepción cruda en la
        # UI (URLs, códigos HTTP) lee como una app rota, no como un dato.
        # El detalle técnico completo queda en el title="" (tooltip); lo que
        # se lee de entrada es una frase corta.
        if isinstance(n, str) and n.upper().startswith("ERROR"):
            return (f'<abbr title="{html.escape(n)}">'
                    f'{html.escape(source)} no disponible</abbr>')
        return f"{html.escape(str(source))} {n}"

    tally = " · ".join(
        f"{html.escape(mid)}: " + ", ".join(_cov_piece(s, n) for s, n in rep.items())
        for mid, rep in coverage.items())
    n_items = conn.execute("SELECT COUNT(*) c FROM items WHERE day=?", (day,)).fetchone()["c"]
    hist = conn.execute("SELECT COUNT(DISTINCT day) c FROM items").fetchone()["c"]
    picos = status_count.get("PICO", 0)

    archive_html = _archive_control(set(archive) | {day}, day)

    hero = (f'<div class="hero">'
            f'<div class="tile"><div class="v">{total}</div><div class="l">temas en pauta</div></div>'
            f'<div class="tile"><div class="v" style="color:var(--st-pico)">{picos}</div>'
            f'<div class="l">picos — producir hoy</div></div>'
            f'<div class="tile"><div class="v">{n_items}</div><div class="l">items nuevos</div></div>'
            f'<div class="tile"><div class="v">{hist}</div><div class="l">días de historia</div></div>'
            f'</div>')

    breaking = _breaking_band(breaking_alerts or [],
                              {m["id"]: m["name"] for m in markets})

    excluded_line = ""
    if excluded_counts is not None:
        n_gaming = excluded_counts.get("gaming", 0)
        n_conflicto = excluded_counts.get("conflicto", 0)
        excluded_line = (
            f'<div class="gap"><strong>Filtrados de esta pauta:</strong> '
            f'{n_gaming} tema{"s" if n_gaming != 1 else ""} de gaming, '
            f'{n_conflicto} de conflicto bélico. Los de conflicto siguen '
            f'activos en el monitor de última hora.</div>')

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#000000" media="(prefers-color-scheme: dark)">
<meta name="theme-color" content="#F5F5F4" media="(prefers-color-scheme: light)">
<title>Pauta del día — {day}</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%23000000'/%3E%3Ccircle cx='16' cy='16' r='7' fill='%23FFC72C'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;600;700;800&family=Newsreader:opsz,wght@6..72,400;6..72,500&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>{CSS}</style>
<script>try{{var t=localStorage.getItem('pauta-theme');
if(t)document.documentElement.dataset.theme=t}}catch(e){{}}</script>
</head>
<body>
<nav class="topbar"><div class="in">
  <span class="brand">Pauta del día Upsomedia</span>
  {archive_html}
  <div class="tabs">{"".join(tabs)}</div>
  <button class="theme" id="theme" type="button" title="Cambiar tema"
    aria-label="Cambiar entre tema claro y oscuro">◐</button>
</div></nav>
<div class="wrap">
{hero}
<p class="tally">{tally}</p>
{breaking}
<div class="filters">{"".join(filters)}</div>
{"".join(sections)}
<div class="legend">
  <h4>Cómo leer esto</h4>
  <p><span class="pill" style="--c:var(--st-pico)">PICO</span> el tema perforó su ruido de fondo y sigue subiendo — es lo que hay que producir hoy.
  <span class="pill" style="--c:var(--st-techo)">TECHO</span> perforó pero ya viene bajando: llegaste tarde, evaluá si vale.
  <span class="pill" style="--c:var(--st-nuevo)">NUEVO</span> no tiene historia suficiente para comparar; el z no significa nada todavía.
  <span class="pill" style="--c:var(--st-observar)">OBSERVAR</span> se mueve, no explota.</p>
  <p>La banda clara de la traza es el territorio normal del tema (mediana ± ruido). La barra
  de color es hoy. Si la barra se sale de la banda, pasó algo. Pasá el mouse por las barras
  para ver el volumen de cada día.</p>
  <div class="gap"><strong>Hueco conocido:</strong> TikTok e Instagram no tienen API pública de
  tendencias. Esta pauta no los cubre — hay que mirarlos a mano o pagar un scraper.
  Ver README.</div>
  {excluded_line}
</div>
</div>
<script>{JS}</script>
</body></html>"""


def write(html_str, out_dir, day):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"pauta-{day}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_str)
    latest = os.path.join(out_dir, "index.html")
    with open(latest, "w", encoding="utf-8") as f:
        f.write(html_str)
    return path
