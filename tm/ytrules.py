"""Reglas de admisión del video (YouTube y agencias de video viral).

Por qué existe este módulo: `chart=mostPopular` mide AUDIENCIA (lo más visto),
y este monitor tiene que detectar PICOS de actividad y discusión — noticias,
celebridades, deportes, virales noticiosos tipo Newsflare. Mientras el video
generó temas por sí solo, la pauta se llenó de videoclips y vlogs: eran lo más
visto del día, no algo que estuviera pasando.

Así que el video dejó de ser una fuente que genera temas y pasa a cumplir dos
roles, y nada más:

  1. CORROBORAR temas que ya están picando en otra fuente (prensa, búsquedas,
     Wikipedia).
  2. APORTAR shorts virales noticiosos que pasen filtros estrictos.

Las reglas son POR VIDEO, no por tema, y se aplican DESPUÉS de la exclusión
dura de tags.filter_excluded_items() — o sea, cuando un video llega acá ya se
sabe que no es gaming, ni baile, ni contenido hecho con IA (esas tres tienen
scope `todo` en config.yaml). La música se saca antes todavía, en la
recolección: categoría 10 descartada y clasificación `videoclip`.

Consecuencia deliberada: un tema cuya ÚNICA evidencia del día es video sin
corroborar se queda sin evidencia y desaparece solo de la pauta, igual que
pasa con la exclusión dura — rebuild_daily() no le encuentra volumen. No hace
falta un chequeo aparte.
"""
import logging
from collections import Counter, defaultdict
from statistics import quantiles

from . import tags as tagmatch

log = logging.getLogger("tm.ytrules")

# Fuentes que pasan por estas reglas. El resto (prensa, búsquedas, Wikipedia)
# no se toca: son justamente las que CORROBORAN.
VIDEO_SOURCES = ("youtube", "agencias_video")

# Motivo de descarte -> etiqueta para la línea de transparencia del reporte.
MOTIVOS = {
    "videoclip": "videoclips",
    "largo_sin_corroborar": "videos largos sin corroborar",
    "short_sin_senal": "shorts sin señal viral",
}

# Categorías destacadas (config.yaml) que habilitan a un short a entrar SIN
# corroboración, si además tiene señal viral fuerte. Son las que el usuario
# quiere ver: el rescate, el arresto, el animal, el golazo, la boda que se
# descontrola, el chico, la celebridad, la pareja. Deja afuera cualquier
# categoría futura que no sea noticiosa: agregar una a config.yaml no la
# vuelve automáticamente un pasaporte para shorts sin corroborar.
CATEGORIAS_SHORT = frozenset({
    "rescate", "policial", "animales", "deporte_viral",
    "boda_viral", "viral_ninos", "celebridades", "parejas",
})

# Cuántos shorts hacen falta en un mercado para que el cuartil signifique
# algo. Con 3 shorts, "el cuartil superior" es un solo video elegido casi al
# azar. Por debajo de esto ningún short entra por señal viral — los
# corroborados siguen entrando igual, que es el camino principal.
MIN_MUESTRA_CUARTIL = 4


def _p75(valores):
    """Corte del cuartil superior. `quantiles` necesita 2 puntos como mínimo;
    MIN_MUESTRA_CUARTIL ya garantiza 4."""
    return quantiles(valores, n=4)[2]


def viral_thresholds(items):
    """Cortes de velocidad y discusión por (mercado, fuente), calculados sobre
    los shorts recolectados HOY.

    Relativo y no absoluto a propósito: 5.000 vistas/hora es enorme para FR y
    normal para US, y lo que es "mucho" cambia con el día. El cuartil se
    recalibra solo.

    Por FUENTE y no solo por mercado, y esto se midió contra datos reales del
    2026-09-24 antes de dejarlo así: los shorts de `chart=mostPopular` en US
    corren a decenas de miles de vistas/hora (corte del cuartil: 36.906 v/h) y
    los de las agencias de video viral, a decenas (corte: 122 v/h). En un solo
    pool, NINGÚN clip de agencia pasa jamás — que es justo la fuente más
    parecida a lo que la pauta busca en video. La diferencia de escala es el
    tamaño de la audiencia del canal, no la señal: dentro de su propia fuente,
    un clip a 737 v/h con 0,10% de comentarios sí está reventando. Separadas,
    el mismo día entra "Feisty Kitten Sneak Attack || ViralHog" y no entran los
    otros 57 clips de agencia.

    Devuelve {(market, source): (corte_velocidad, corte_discusion)}. Una
    combinación sin muestra suficiente no aparece en el dict."""
    grupos = defaultdict(lambda: ([], []))
    for it in items:
        if it["source"] not in VIDEO_SOURCES:
            continue
        ex = it.get("extra") or {}
        if ex.get("yt_kind") != "short":
            continue
        vph, disc = ex.get("vph"), ex.get("disc")
        if vph is None or disc is None:
            continue
        vs, ds = grupos[(it["market"], it["source"])]
        vs.append(vph)
        ds.append(disc)

    cortes = {}
    for clave, (vs, ds) in grupos.items():
        if len(vs) < MIN_MUESTRA_CUARTIL:
            log.info("ytrules %s/%s: solo %d shorts, sin cuartil (ninguno entra "
                     "por señal viral)", clave[0], clave[1], len(vs))
            continue
        cortes[clave] = (_p75(vs), _p75(ds))
        log.info("ytrules %s/%s: %d shorts, corte %.0f vistas/h y %.3f%% de "
                 "comentarios", clave[0], clave[1], len(vs),
                 cortes[clave][0], cortes[clave][1] * 100)
    return cortes


def senal_viral_fuerte(item, cortes):
    """El short está en el cuartil superior de velocidad Y de discusión entre
    los shorts de su mercado y su fuente. Los dos a la vez, no uno u otro:
    mucha velocidad sola es audiencia (lo que ya sabíamos medir y no sirve), y
    mucha discusión sola con pocas vistas es un comentario de nicho."""
    corte = cortes.get((item["market"], item["source"]))
    if corte is None:
        return False
    ex = item.get("extra") or {}
    vph, disc = ex.get("vph"), ex.get("disc")
    if vph is None or disc is None:
        return False
    corte_v, corte_d = corte
    return vph >= corte_v and disc >= corte_d


def categoria_destacada(item, categorias_cfg):
    """El short matchea una categoría destacada noticiosa (CATEGORIAS_SHORT).

    Solo sobre el TÍTULO: los tags de YouTube son palabras SEO y casi
    cualquier video trae 'animals' o 'viral' entre sus quince etiquetas — con
    tags esta puerta se abre para todo."""
    if not categorias_cfg:
        return False
    nombres = tagmatch.matched_tags(item.get("title") or "", categorias_cfg)
    return bool(CATEGORIAS_SHORT.intersection(nombres))


def _admite(item, corroborado, cortes, categorias_cfg):
    """(admitido, motivo_si_no). Una sola función con las tres reglas juntas,
    para que se lean en orden."""
    kind = (item.get("extra") or {}).get("yt_kind") or "largo"

    # Videoclip: nunca es evidencia. Si el artista está en tendencia, el tema
    # entra igual por las noticias, Wikipedia o Trends, y la fila muestra esas
    # notas — no el clip.
    if kind == "videoclip":
        return False, "videoclip"

    # Largo (vlog, programa, resumen): solo si otra fuente confirma el tema
    # hoy. Si un vlogger está en tendencia por algo, la noticia explica el
    # porqué y su video acompaña; si es solo un video con muchas vistas, no.
    if kind == "largo":
        return (True, None) if corroborado else (False, "largo_sin_corroborar")

    # Short: corroborado entra derecho. Si no, tiene que ganárselo con señal
    # viral fuerte Y una categoría noticiosa — las dos, no una.
    if corroborado:
        return True, None
    if (senal_viral_fuerte(item, cortes)
            and categoria_destacada(item, categorias_cfg)):
        return True, None
    return False, "short_sin_senal"


def filter_video_items(pairs, items_by_id, categorias_cfg):
    """Filtra `pairs` [(item_id, entity_key)] aplicando las reglas de admisión
    a los items de video. Los items que no son de video pasan intactos.

    La corroboración se mide por (tema, mercado): el tema tiene hoy al menos
    una nota de una fuente que NO es video y que sobrevivió a la exclusión
    dura. Se calcula sobre los `pairs` que entran, así que una nota de prensa
    descartada por gaming/conflicto tampoco corrobora nada.

    Devuelve (pairs_sobrevivientes, motivos), con `motivos` = Counter
    {motivo: n_videos}. Un video se cuenta como descartado una sola vez y solo
    si NINGUNA de sus entidades lo admitió: el mismo clip puede corroborar un
    tema y sobrar en otro, y ahí no se filtró nada."""
    corroborado = set()
    for item_id, key in pairs:
        it = items_by_id.get(item_id)
        if it is not None and it["source"] not in VIDEO_SOURCES:
            corroborado.add((key, it["market"]))

    cortes = viral_thresholds(items_by_id.values())

    kept = []
    admitido = defaultdict(bool)      # item_id -> entró en alguna entidad
    motivo_de = {}                    # item_id -> primer motivo de rechazo
    for item_id, key in pairs:
        it = items_by_id.get(item_id)
        if it is None:
            continue
        if it["source"] not in VIDEO_SOURCES:
            kept.append((item_id, key))
            continue
        ok, motivo = _admite(it, (key, it["market"]) in corroborado,
                             cortes, categorias_cfg)
        if ok:
            kept.append((item_id, key))
            admitido[item_id] = True
        else:
            motivo_de.setdefault(item_id, motivo)

    motivos = Counter(m for item_id, m in motivo_de.items()
                      if not admitido[item_id])
    return kept, motivos


def admitted_shorts(pairs, items_by_id, categorias_cfg):
    """Los shorts que quedaron en `pairs`, con sus señales, para revisarlos a
    mano (run.py los loguea). Ver que sean noticiosos y no nichos es el único
    control de calidad real que tiene la regla 3b.

    Devuelve [{title, market, agencia, vph, disc, corroborado, categorias}],
    de mayor a menor velocidad, sin repetir un video por cada entidad."""
    corroborado = set()
    for item_id, key in pairs:
        it = items_by_id.get(item_id)
        if it is not None and it["source"] not in VIDEO_SOURCES:
            corroborado.add((key, it["market"]))

    # Agrupado por video, no por par: un short colgado de tres entidades es UN
    # short, y basta con que UNA de ellas esté corroborada para que lo esté.
    keys_de = defaultdict(set)
    for item_id, key in pairs:
        keys_de[item_id].add(key)

    out = []
    for item_id, keys in keys_de.items():
        it = items_by_id.get(item_id)
        if it is None or it["source"] not in VIDEO_SOURCES:
            continue
        ex = it.get("extra") or {}
        if ex.get("yt_kind") != "short":
            continue
        out.append({
            "title": it["title"], "market": it["market"],
            "agencia": ex.get("agencia"),
            "vph": ex.get("vph"), "disc": ex.get("disc"),
            "corroborado": any((k, it["market"]) in corroborado for k in keys),
            "categorias": tagmatch.matched_tags(it["title"] or "", categorias_cfg),
        })
    out.sort(key=lambda r: -(r["vph"] or 0))
    return out
