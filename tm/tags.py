"""Matching de términos para exclusión dura y categorías destacadas.

Un solo lugar para la lógica de "¿este tema matchea esta lista de términos?":
la usan spike.py y breaking.py (para descartar/boostear) y report.py (para
pintar el badge). Mismo texto, mismo matching en todos — así el ranking, lo
que se filtra y lo que se ve en pantalla nunca divergen.
"""
import re

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
