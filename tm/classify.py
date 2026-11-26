"""Clasificador LLM: segunda pasada sobre los filtros de palabras (config.yaml -> excluir).

Las listas de términos (tags.py) son rápidas y baratas pero ciegas al contexto:
"infinity war" y Biden/Obama caían como conflicto, y `box`/`ring` pueden colar
guerra como deporte. Un modelo lee el tema con sus titulares y decide si de eso
TRATA, no si una palabra coincide.

Dos usos, ambos sobre pocos candidatos (no sobre todo lo recolectado):

  etiquetar_picos()     picos ya detectados -> etiquetas por tema. Ve lo que las
                        listas DEJARON PASAR (gaming/guerra/IA/baile que se coló).
  revisar_excluidos()   temas que las listas DESCARTARON -> rescata los que el
                        modelo dice que estaban bien (falsos positivos).
                        Sin esto el filtro es una caja negra: lo descartado nunca
                        llega a ningún reporte y nadie ve qué se perdió.

Modos (config.yaml -> clasificador.mode):
  shadow    solo registra y loguea. No cambia la pauta. Es el modo de arranque.
  enforce   además descarta los picos que el modelo etiqueta con alta confianza.

Alcance: esto corre SOLO en la pauta diaria (run.py). Conflicto bélico sigue
fuera del alcance del monitor de 15 min, igual que tags.excluded_categories():
`categorias(excluir, "monitor")` ya respeta scope='solo_pauta_diaria'.

Sin ANTHROPIC_API_KEY o ante cualquier error devuelve {}: la pauta sale igual con
los filtros de palabras de siempre. Nunca puede tumbar la corrida.
"""
import json
import logging
import os
from collections import defaultdict

from .explain import _parse

log = logging.getLogger("tm.classify")

# Definición de cada categoría de `excluir`. Una categoría nueva sin entrada acá
# se le pasa al modelo solo con su nombre.
DEFINICIONES = {
    "gaming": "videojuegos, gameplays, streamers de juegos, esports, consolas, "
              "lanzamientos y noticias de la industria del videojuego",
    "bailes": "retos, tendencias o videos de baile y coreografía como contenido",
    "contenido_ia": "videos, imágenes o audios generados con inteligencia artificial, deepfakes",
    "conflicto": "guerra o conflicto armado real: ataques, bombardeos, tropas, "
                 "cese del fuego, ofensivas militares",
}

SYSTEM = """Sos un clasificador editorial para una pauta de video corto. Recibís temas \
con sus titulares de evidencia y decidís a cuáles de estas categorías pertenece cada uno:

{cats}

Reglas:
- Una categoría aplica SOLO si de eso trata el tema en sí. Una palabra suelta no alcanza.
- Deportes, boxeo, películas, series, libros, juegos de mesa y política interna NO son \
conflicto bélico aunque usen "guerra", "war", "ataque" u "ofensiva".
- Basate solo en lo que te doy. No completes con lo que creas saber.
- Ante la duda, labels vacío. Es peor descartar contenido bueno que dejar pasar uno dudoso.
- confianza: de 0 a 1, qué tan seguro estás de tu respuesta (también cuando labels está vacío).
- motivo: una frase corta.

Devolvé SOLO un array JSON, sin markdown: \
[{"i": 0, "labels": ["gaming"], "confianza": 0.9, "motivo": "..."}]"""


def _cliente():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    return anthropic.Anthropic(api_key=key)


def categorias(excluir, context="pauta_diaria"):
    """{nombre: definición} de las categorías de `excluir` que aplican en este
    contexto. Mismo criterio de scope que tags.excluded_categories()."""
    out = {}
    for name, spec in (excluir or {}).items():
        if (spec or {}).get("scope", "todo") == "solo_pauta_diaria" and context != "pauta_diaria":
            continue
        out[name] = DEFINICIONES.get(name, name)
    return out


def _id(market, key):
    return f"{market}|{key}"


def clasificar(cands, cats, cfg, client=None):
    """cands: [{"id", "name", "titles"}] -> {id: {"labels", "conf", "motivo"}}.
    Un lote por llamada; si un lote falla, los demás siguen."""
    client = client or _cliente()
    if client is None or not cands or not cats:
        return {}
    system = SYSTEM.replace("{cats}", "\n".join(f"- {k}: {v}" for k, v in cats.items()))
    size = cfg.get("batch", 30)
    out = {}
    for s in range(0, len(cands), size):
        lote = cands[s:s + size]
        user = "\n\n".join(
            f"[{n}] {c['name']}\n" + "\n".join(f"  - {t}" for t in c["titles"])
            for n, c in enumerate(lote))
        try:
            # Sin `temperature`: los modelos nuevos la rechazan con un 400 (ver explain.py).
            resp = client.messages.create(
                model=cfg.get("model", "claude-haiku-5-5"), max_tokens=3000,
                system=system, messages=[{"role": "user", "content": user}])
            text = "".join(b.text for b in resp.content if b.type == "text")
        except Exception as e:
            log.error("clasificador: lote falló (%s)", e)
            continue
        for r in _parse(text):
            if not isinstance(r, dict):
                continue
            n = r.get("i")
            if isinstance(n, int) and 0 <= n < len(lote):
                try:
                    conf = float(r.get("confianza", 0))
                except (TypeError, ValueError):
                    conf = 0.0
                out[lote[n]["id"]] = {
                    "labels": [l for l in r.get("labels", []) if l in cats],
                    "conf": conf, "motivo": r.get("motivo", "")}
    return out


def etiquetar_picos(conn, db, day, spikes, cfg, excluir, markets, client=None):
    """Etiqueta el top de cada mercado. Devuelve {"MKT|clave": {...}}."""
    cands = []
    for m in markets:
        rows = [r for r in spikes if r["market"] == m["id"]][:cfg.get("max_per_market", 25)]
        for r in rows:
            ev = db.evidence(conn, r["entity_key"], r["market"], day, limit=5)
            cands.append({"id": _id(r["market"], r["entity_key"]),
                          "name": db.display_name(conn, r["entity_key"]),
                          "titles": [e["title"] for e in ev]})
    return clasificar(cands, categorias(excluir), cfg, client)


def revisar_excluidos(excluded, pairs_pre, items_by_id, cfg, excluir, client=None):
    """Falsos positivos de las listas. `excluded` y `pairs_pre` son lo que
    produce run.py justo antes y después de tags.filter_excluded_items().
    Devuelve los temas descartados que el modelo dice que NO pertenecían a la
    categoría por la que cayeron (con confianza suficiente)."""
    titulos = defaultdict(list)
    for iid, key in pairs_pre:
        it = items_by_id.get(iid)
        if it:
            titulos[(key, it["market"])].append(it["title"])
    vistos = {}
    for e in excluded:
        v = vistos.setdefault((e["entity_key"], e["market"]),
                              {"cats": set(), "display": e["display"]})
        v["cats"].add(e["category"])
    # Una misma historia cae como varias entidades ("cumple ocho años", "ocho años",
    # "War"...) con las mismas notas. Se deja una sola por conjunto de titulares
    # (la de nombre más largo) para no repetir la fila ni gastar tokens.
    mejor = {}
    for k in sorted(vistos, key=lambda k: -len(titulos[k])):
        firma = (k[1], tuple(sorted(set(titulos[k]))))
        if firma not in mejor or len(vistos[k]["display"]) > len(vistos[mejor[firma]]["display"]):
            mejor[firma] = k
    unicos = set(mejor.values())
    orden = [k for k in sorted(vistos, key=lambda k: -len(titulos[k]))
             if k in unicos][:cfg.get("revisar_excluidos", 40)]
    cands = [{"id": _id(m, k), "name": vistos[(k, m)]["display"],
              "titles": titulos[(k, m)][:5]} for (k, m) in orden]
    res = clasificar(cands, categorias(excluir), cfg, client)

    min_conf = cfg.get("min_confianza", 0.8)
    rescatables = []
    for (k, m) in orden:
        r = res.get(_id(m, k))
        if r and r["conf"] >= min_conf and not (set(r["labels"]) & vistos[(k, m)]["cats"]):
            rescatables.append({"market": m, "tema": vistos[(k, m)]["display"],
                                "cayo_por": sorted(vistos[(k, m)]["cats"]),
                                "motivo": r["motivo"], "ejemplo": titulos[(k, m)][:2]})
    return rescatables


def sacaria(spikes, etiquetas, min_conf):
    """Picos que el modelo descartaría: (pico, etiquetas, motivo)."""
    out = []
    for r in spikes:
        e = etiquetas.get(_id(r["market"], r["entity_key"]))
        if e and e["labels"] and e["conf"] >= min_conf:
            out.append((r, e["labels"], e["motivo"]))
    return out


def aplicar(spikes, etiquetas, min_conf):
    """Modo enforce: (picos_que_quedan, descartados[(pico, labels, motivo)])."""
    caen = {_id(r["market"], r["entity_key"]) for r, _, _ in sacaria(spikes, etiquetas, min_conf)}
    kept = [r for r in spikes if _id(r["market"], r["entity_key"]) not in caen]
    return kept, sacaria(spikes, etiquetas, min_conf)


# ── persistencia (para que --report-only reproduzca el mismo resultado) ──
def guardar(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def cargar(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}
