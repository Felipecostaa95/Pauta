"""Matching de términos para down-weight y categorías destacadas.

Un solo lugar para la lógica de "¿este tema matchea esta lista de términos?":
la usan spike.py (para bajar/subir el score) y report.py (para pintar el
badge). Mismo texto, mismo matching en los dos — así el ranking y lo que se
ve en pantalla nunca divergen.
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


def down_weight_factor(text, down_weight_cfg):
    """Producto de los factores de las categorías de down-weight que matcheen
    (p.ej. 'conflicto' -> 0.3). Sin coincidencias, devuelve 1.0."""
    text = (text or "").lower()
    factor = 1.0
    for spec in (down_weight_cfg or {}).values():
        terms = (spec or {}).get("terms", [])
        if any(_has_term(text, t) for t in terms):
            factor *= (spec or {}).get("factor", 1.0)
    return factor


def score_factor(text, down_weight_cfg, categorias_cfg):
    """Factor combinado que multiplica el score de un tema: down-weight de
    conflicto (si matchea) por boost de categoría destacada (si matchea,
    aplicado UNA sola vez aunque el tema matchee varias categorías). Si un
    tema matchea ambos (ej. un rescate en zona de guerra), los dos factores se
    multiplican — no se cancelan entre sí, el resultado queda predecible."""
    factor = down_weight_factor(text, down_weight_cfg)
    if matched_tags(text, categorias_cfg):
        factor *= BOOST_FACTOR
    return factor
