"""Monitor de última hora.

Esto NO es el detector de tendencias (spike.py). Son dos preguntas distintas:

  spike.py     → "¿de esto se habla más que lo normal ESTA SEMANA?" (tendencia)
  breaking.py  → "¿esto apareció de la nada en los últimos MINUTOS?" (ruptura)

La diferencia técnica importa. Una tendencia se mide contra un baseline de 28
días. Una ruptura no tiene baseline útil — si se murió alguien hace 20 minutos,
comparar contra las últimas 4 semanas es irrelevante: la señal es que MUCHAS
fuentes distintas están cubriendo el mismo nombre AL MISMO TIEMPO, ahora, cuando
hace un rato no lo cubría nadie.

Por eso este módulo:
- Corre seguido (cada ~15 min), no una vez al día.
- Solo mira Google News y Google Trends: son las fuentes que reaccionan en
  minutos. YouTube y RSS de medios son más lentos para esto.
- No compara contra días — compara contra el estado que guardó en su ÚLTIMA
  corrida (hace 15 min). Un tema que salta de "0-1 fuentes" a "5+ fuentes" entre
  una corrida y la siguiente es la huella de algo que rompió.
- No usa lista de palabras clave ("murió", "arrestado"...). Esas listas siempre
  se quedan cortas justo con lo que no anticipaste. La señal es la velocidad de
  aparición multi-fuente, sea cual sea el tema.
"""
import time
import logging
from datetime import datetime, timezone

from . import entities as ent

log = logging.getLogger("tm.breaking")

# Cuántas fuentes DISTINTAS tienen que cubrir el mismo tema en la misma corrida
# para considerarlo una ruptura. Menos que esto es ruido de un solo medio.
MIN_SOURCES = 4

# Si un tema ya venía con esta cobertura o más en la corrida anterior, no es
# "ruptura" — ya venía pasando, lo agarra la pauta diaria. Solo alertamos lo
# que SALTÓ desde casi nada.
WAS_QUIET_MAX = 1


def _now():
    return datetime.now(timezone.utc)


BREAKING_SCHEMA = """
-- Estado de la última corrida del monitor, por tema. Se sobreescribe cada vez.
CREATE TABLE IF NOT EXISTS breaking_state (
    entity_key TEXT NOT NULL,
    market     TEXT NOT NULL,
    n_sources  INTEGER NOT NULL,
    n_items    INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (entity_key, market)
);

-- Alertas emitidas. Se conservan unas horas para mostrarlas en la web y para
-- no volver a alertar lo mismo cada 15 min (de-dupe).
CREATE TABLE IF NOT EXISTS breaking_alerts (
    entity_key  TEXT NOT NULL,
    market      TEXT NOT NULL,
    display     TEXT NOT NULL,
    n_sources   INTEGER NOT NULL,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    headline    TEXT,
    url         TEXT,
    PRIMARY KEY (entity_key, market)
);
"""


def init(conn):
    conn.executescript(BREAKING_SCHEMA)


def _current_coverage(items):
    """Por tema (entity_key + mercado): cuántas FUENTES distintas lo cubren y
    cuántos items. 'Fuentes distintas' cuenta medios/outlets diferentes, no
    la fuente-tipo (gnews/gtrends) — 5 notas de gnews de 5 medios distintos
    cuentan como 5, no como 1."""
    # entity_key -> market -> {outlets:set, items:list}
    cov = {}
    pairs, display = ent.extract(items, _entity_cfg())
    by_item = {}
    for item_id, key in pairs:
        by_item.setdefault(item_id, []).append(key)

    items_by_id = {i["id"]: i for i in items}
    for item_id, keys in by_item.items():
        it = items_by_id.get(item_id)
        if not it:
            continue
        mkt = it["market"]
        # el "outlet" real: el autor (medio) para gnews, o la fuente si no hay
        outlet = (it.get("author") or it["source"]).strip().lower()
        for key in keys:
            slot = cov.setdefault(key, {}).setdefault(
                mkt, {"outlets": set(), "items": [], "display": display.get(key, key)})
            slot["outlets"].add(outlet)
            slot["items"].append(it)
    return cov


def _entity_cfg():
    # Config mínima de entidades para el monitor. Igual que la pauta pero sin
    # depender del config.yaml completo — el monitor tiene que ser autónomo y
    # rápido. Reusa stoplist básica.
    return {
        "min_chars": 3,
        "max_doc_freq": 0.5,   # más laxo: en una ventana chica, un tema real
                               # puede ocupar buena parte de los titulares
        "auto_alias": True,
        "alias_cooc": 0.6,
        "aliases": {"eeuu": "estados unidos", "usa": "estados unidos"},
        "stoplist": ["video", "videos", "noticias", "news", "live", "en vivo",
                     "directo", "hoy", "shorts", "trailer", "oficial"],
    }


def detect(conn, items):
    """Compara la cobertura actual contra el estado guardado la corrida pasada.
    Devuelve la lista de rupturas nuevas (temas que saltaron de silencio a
    cobertura multi-fuente)."""
    now = _now().isoformat()
    cov = _current_coverage(items)

    # estado anterior
    prev = {(r["entity_key"], r["market"]): r["n_sources"]
            for r in conn.execute("SELECT * FROM breaking_state")}

    # ── Arranque en frío ──────────────────────────────────────────────
    # Si no hay estado previo (primera corrida del monitor), NO alertamos nada
    # todavía — solo sembramos el estado base. Sin esto, la primera vuelta
    # marca como "ruptura" todo lo que ya venía pasando, que es justo lo que
    # NO queremos: una ruptura es algo que aparece MIENTRAS el monitor mira.
    cold_start = len(prev) == 0

    candidates = []
    new_state = []
    for key, markets in cov.items():
        for mkt, slot in markets.items():
            n_src = len(slot["outlets"])
            new_state.append((key, mkt, n_src, len(slot["items"]), now))

            before = prev.get((key, mkt), 0)
            if n_src >= MIN_SOURCES and before <= WAS_QUIET_MAX:
                top = max(slot["items"], key=lambda i: i.get("weight", 1.0))
                candidates.append({
                    "entity_key": key, "market": mkt,
                    "display": slot["display"], "n_sources": n_src,
                    "headline": top["title"], "url": top.get("url"),
                    "items": {i["id"] for i in slot["items"]},
                })

    # guardar estado nuevo (reemplaza el anterior por completo)
    conn.execute("DELETE FROM breaking_state")
    conn.executemany(
        """INSERT INTO breaking_state
           (entity_key, market, n_sources, n_items, updated_at)
           VALUES (?,?,?,?,?)""", new_state)

    if cold_start:
        log.info("arranque en frío: sembrado el estado base, sin alertas esta vuelta")
        return []

    collapsed = _collapse(candidates)

    # Segundo filtro de de-dupe: si ya emitimos una alerta activa para este tema
    # (o una entidad muy parecida) en las últimas horas, no volvemos a alertar
    # aunque la fragmentación de entidades haga aparecer una variante nueva del
    # mismo nombre. record_alerts() actualiza las existentes; acá evitamos que
    # una variante cuente como ruptura nueva.
    already = {(r["entity_key"], r["market"])
               for r in conn.execute("SELECT entity_key, market FROM breaking_alerts")}
    fresh = []
    for r in collapsed:
        # match exacto, o una entidad activa cuyo nombre esté contenido (o al
        # revés) — cubre "Famous Actor" vs "Famous Actor dies".
        dup = False
        for (ak, am) in already:
            if am != r["market"]:
                continue
            if ak == r["entity_key"] or ak in r["entity_key"] or r["entity_key"] in ak:
                dup = True
                break
        if not dup:
            fresh.append(r)
    return fresh


def _collapse(candidates, thresh=0.6):
    """Un mismo evento dispara varias entidades ("Famous Actor", "dies suddenly",
    "family confirms"). Si dos candidatos del mismo mercado comparten >60% de
    sus items, son la misma historia: se queda el de más fuentes, el resto se
    descarta. Mismo criterio que la pauta diaria."""
    out = []
    by_market = {}
    for c in candidates:
        by_market.setdefault(c["market"], []).append(c)

    for mkt, rows in by_market.items():
        rows.sort(key=lambda r: -r["n_sources"])
        heads = []
        for r in rows:
            absorbed = False
            for h in heads:
                overlap = len(r["items"] & h["items"]) / max(1, min(len(r["items"]),
                                                                    len(h["items"])))
                if overlap >= thresh:
                    absorbed = True
                    break
            if not absorbed:
                heads.append(r)
        out += heads

    for r in out:
        r.pop("items", None)
    return out


def record_alerts(conn, rupturas, ttl_hours=6):
    """Registra rupturas nuevas y refresca las existentes. De-dupe: si un tema
    ya está en alertas, actualiza last_seen en vez de duplicar. Limpia las
    viejas (más de ttl_hours sin actualizarse)."""
    now = _now()
    now_s = now.isoformat()

    for r in rupturas:
        existing = conn.execute(
            "SELECT first_seen FROM breaking_alerts WHERE entity_key=? AND market=?",
            (r["entity_key"], r["market"])).fetchone()
        if existing:
            conn.execute(
                """UPDATE breaking_alerts
                   SET last_seen=?, n_sources=?, headline=?, url=?
                   WHERE entity_key=? AND market=?""",
                (now_s, r["n_sources"], r["headline"], r.get("url"),
                 r["entity_key"], r["market"]))
        else:
            conn.execute(
                """INSERT INTO breaking_alerts
                   (entity_key, market, display, n_sources, first_seen, last_seen,
                    headline, url)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (r["entity_key"], r["market"], r["display"], r["n_sources"],
                 now_s, now_s, r["headline"], r.get("url")))

    # limpiar viejas
    cutoff = now.timestamp() - ttl_hours * 3600
    for row in conn.execute("SELECT entity_key, market, last_seen FROM breaking_alerts"):
        try:
            seen = datetime.fromisoformat(row["last_seen"]).timestamp()
        except (ValueError, TypeError):
            continue
        if seen < cutoff:
            conn.execute("DELETE FROM breaking_alerts WHERE entity_key=? AND market=?",
                         (row["entity_key"], row["market"]))


def active_alerts(conn):
    """Alertas vigentes, más recientes primero, para mostrar en la web."""
    rows = conn.execute(
        """SELECT * FROM breaking_alerts ORDER BY first_seen DESC""").fetchall()
    return [dict(r) for r in rows]
