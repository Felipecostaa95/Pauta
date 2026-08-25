"""Matching de términos para exclusión dura y categorías destacadas.

Un solo lugar para la lógica de "¿este tema matchea esta lista de términos?":
la usan spike.py y breaking.py (para descartar/boostear) y report.py (para
pintar el badge). Mismo texto, mismo matching en todos — así el ranking, lo
que se filtra y lo que se ve en pantalla nunca divergen.
"""
import re
from collections import defaultdict

BOOST_FACTOR = 1.3

# emoji + etiqueta visible para cada categoría destacada (3b/3c).
BADGES = {
    "celebridades": ("⭐", "celebridad"),
    "rescate":      ("🐾", "rescate"),
    "policial":     ("🚔", "policial"),
    "viral_ninos":  ("👶", "viral"),
    "boda_viral":   ("💍", "boda viral"),
}


def _has_term(text, term):
    return re.search(r"\b" + re.escape(term.lower()) + r"\b", text) is not None


def matched_tags(text, categorias_cfg):
    """Categorías (nombres) que matchean el texto. Match simple: cualquier
    término de la lista alcanza. 'boda_viral' es la excepción: necesita un
    término de grupo_boda Y uno de grupo_gancho en el mismo tema — "boda" sola
    trae demasiado ruido (bodas de famosos, moda, consejos)."""
    text = (text or "").lower()
    tags = []
    for name, spec in (categorias_cfg or {}).items():
        if name == "boda_viral":
            if not isinstance(spec, dict):
                continue
            boda = any(_has_term(text, t) for t in spec.get("grupo_boda", []))
            gancho = any(_has_term(text, t) for t in spec.get("grupo_gancho", []))
            if boda and gancho:
                tags.append(name)
        elif any(_has_term(text, t) for t in (spec or [])):
            tags.append(name)
    return tags


def boost_factor(text, categorias_cfg):
    """Factor que multiplica el score de un tema si matchea alguna categoría
    destacada (BOOST_FACTOR, aplicado UNA sola vez aunque matchee varias).
    Sin coincidencias, devuelve 1.0."""
    return BOOST_FACTOR if matched_tags(text, categorias_cfg) else 1.0


def item_text(item):
    """Texto contra el que se matchea UNA nota: título + tags de YouTube. Sin
    los tags, un video etiquetado 'Roblox' pero titulado con puro clickbait
    ('Nueva actualización bate récord de jugadores') pasa de largo el filtro
    de gaming — el tag es la señal, no el título."""
    tags = (item.get("extra") or {}).get("tags") or []
    return " ".join([item.get("title") or ""] + list(tags))


def excluded_categories(text, excluir_cfg, context):
    """Categorías de `excluir` (config.yaml) que matchean el texto Y aplican
    en este contexto. `context` es 'pauta_diaria' o 'monitor'.

    scope='todo' aplica en los dos contextos. scope='solo_pauta_diaria' SOLO
    cuenta cuando context == 'pauta_diaria' — así breaking_run.py filtra
    gaming pero NUNCA conflicto, a propósito: el usuario quiere enterarse en
    tiempo real si estalla una guerra grande, aunque no la quiera en la pauta
    diaria. No unificar este chequeo aunque parezca redundante."""
    text = (text or "").lower()
    matched = []
    for name, spec in (excluir_cfg or {}).items():
        scope = (spec or {}).get("scope", "todo")
        if scope == "solo_pauta_diaria" and context != "pauta_diaria":
            continue
        terms = (spec or {}).get("terms", [])
        if any(_has_term(text, t) for t in terms):
            matched.append(name)
    return matched


def filter_excluded_items(pairs, items_by_id, display, excluir_cfg, context):
    """Filtra `pairs` [(item_id, entity_key)] por NOTA individual, no por tema
    completo: si un tema tiene 5 notas y una sola matchea `excluir`, se
    descarta esa nota y las otras 4 quedan armando el tema igual (con menos
    volumen). El chequeo mira el título + tags de CADA item (ver item_text),
    no el nombre del tema — así "infinity war" (la película) no se descarta
    solo porque su nombre contenga "war"; lo que importa es si la nota en sí
    habla de guerra.

    Devuelve (pairs_sobrevivientes, temas_descartados). Un tema entra en
    `temas_descartados` únicamente si TODAS sus notas de hoy matchearon
    `excluir` — ahí sí desaparece del todo (con las categorías que lo
    vaciaron, para la línea de transparencia del reporte). Si le queda aunque
    sea una nota limpia, sigue en pauta."""
    kept = []
    reasons = defaultdict(set)   # (entity_key, market) -> categorías que le sacaron notas
    before, after = set(), set()
    for item_id, key in pairs:
        it = items_by_id.get(item_id)
        if it is None:
            continue
        mkt = it["market"]
        before.add((key, mkt))
        cats = excluded_categories(item_text(it), excluir_cfg, context)
        if cats:
            reasons[(key, mkt)].update(cats)
            continue
        kept.append((item_id, key))
        after.add((key, mkt))

    discarded = [
        {"category": cat, "entity_key": key, "market": mkt, "display": display.get(key, key)}
        for (key, mkt) in (before - after)
        for cat in reasons[(key, mkt)]
    ]
    return kept, discarded
