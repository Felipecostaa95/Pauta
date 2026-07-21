"""SQLite storage. The whole point of keeping history is that a spike is only
meaningful against a baseline — day one of this system detects nothing."""
import sqlite3
import json
import os
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id           TEXT PRIMARY KEY,
    day          TEXT NOT NULL,
    source       TEXT NOT NULL,
    market       TEXT NOT NULL,
    lang         TEXT,
    title        TEXT NOT NULL,
    url          TEXT,
    author       TEXT,
    published_at TEXT,
    weight       REAL NOT NULL DEFAULT 1.0,
    extra        TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_day    ON items(day);
CREATE INDEX IF NOT EXISTS idx_items_market ON items(day, market);

CREATE TABLE IF NOT EXISTS entities (
    key        TEXT PRIMARY KEY,
    display    TEXT NOT NULL,
    first_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS item_entities (
    item_id    TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    PRIMARY KEY (item_id, entity_key)
);
CREATE INDEX IF NOT EXISTS idx_ie_entity ON item_entities(entity_key);

-- Serie temporal. Esta tabla es el corazón del sistema.
CREATE TABLE IF NOT EXISTS daily (
    day        TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    market     TEXT NOT NULL,
    source     TEXT NOT NULL,
    volume     REAL NOT NULL,
    n_items    INTEGER NOT NULL,
    PRIMARY KEY (day, entity_key, market, source)
);
CREATE INDEX IF NOT EXISTS idx_daily_lookup ON daily(entity_key, market, day);

CREATE TABLE IF NOT EXISTS spikes (
    day        TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    market     TEXT NOT NULL,
    volume     REAL NOT NULL,
    baseline   REAL NOT NULL,
    z          REAL NOT NULL,
    velocity   REAL NOT NULL,
    status     TEXT NOT NULL,
    n_days     INTEGER NOT NULL,
    value      REAL NOT NULL,
    PRIMARY KEY (day, entity_key, market)
);

CREATE TABLE IF NOT EXISTS briefs (
    day        TEXT NOT NULL,
    market     TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    topic      TEXT,
    why        TEXT,
    angle      TEXT,
    durability TEXT,
    PRIMARY KEY (day, market, entity_key)
);

CREATE TABLE IF NOT EXISTS saturation (
    day        TEXT NOT NULL,
    market     TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    n_videos   INTEGER NOT NULL,
    PRIMARY KEY (day, market, entity_key)
);
"""


@contextmanager
def connect(path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


@contextmanager
def connect_readonly(path):
    """Abre la base en modo SOLO LECTURA (URI mode=ro). SQLite nunca escribe el
    archivo — ni un byte, ni journal, ni checkpoint — así el working tree no
    queda 'sucio'.

    Esto es lo que le permite al monitor de última hora leer la pauta diaria
    (spikes/briefs) sin ensuciar data/pauta.db. Si el monitor abriera esa base
    en modo lectura/escritura, dejaría el archivo binario modificado en el
    working tree y el rebase de dos workflows corriendo a la vez chocaría —
    justo el bug que estamos evitando. En SOLO LECTURA eso es imposible.

    No commitea (no hay nada que commitear). Si el archivo no existe, sqlite3
    lanza OperationalError: el llamador decide qué hacer.

    'immutable=1': la pauta diaria guarda la base en modo WAL, y una lectura
    normal (mode=ro) crearía archivos -wal/-shm al lado para poder leerla.
    immutable le promete a SQLite que nadie va a tocar el archivo mientras lo
    leemos —cierto dentro de un checkout de CI, donde el otro workflow corre en
    su propio runner— así lee sin crear NINGÚN sidecar. El working tree queda
    prístino: ni pauta.db ni archivos nuevos que puedan chocar en el commit."""
    conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init(conn):
    conn.executescript(SCHEMA)


def upsert_items(conn, items):
    """items: lista de dicts. Devuelve cuántos eran nuevos."""
    before = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    conn.executemany(
        """INSERT OR IGNORE INTO items
           (id, day, source, market, lang, title, url, author, published_at, weight, extra)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        [(i["id"], i["day"], i["source"], i["market"], i.get("lang"), i["title"],
          i.get("url"), i.get("author"), i.get("published_at"), i.get("weight", 1.0),
          json.dumps(i.get("extra", {}), ensure_ascii=False)) for i in items],
    )
    after = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    return after - before


def items_for_day(conn, day):
    return conn.execute("SELECT * FROM items WHERE day = ?", (day,)).fetchall()


def register_entities(conn, ents, day):
    """ents: dict key -> display"""
    conn.executemany(
        "INSERT OR IGNORE INTO entities (key, display, first_seen) VALUES (?,?,?)",
        [(k, v, day) for k, v in ents.items()],
    )


def link_items(conn, pairs):
    conn.executemany(
        "INSERT OR IGNORE INTO item_entities (item_id, entity_key) VALUES (?,?)", pairs
    )


def rebuild_daily(conn, day):
    """Recalcula los agregados del día desde items + item_entities.
    Idempotente: podés correr el pipeline dos veces el mismo día sin duplicar."""
    conn.execute("DELETE FROM daily WHERE day = ?", (day,))
    conn.execute(
        """INSERT INTO daily (day, entity_key, market, source, volume, n_items)
           SELECT i.day, ie.entity_key, i.market, i.source, SUM(i.weight), COUNT(*)
           FROM items i JOIN item_entities ie ON ie.item_id = i.id
           WHERE i.day = ?
           GROUP BY i.day, ie.entity_key, i.market, i.source""",
        (day,),
    )


def series(conn, entity_key, market, upto_day, days):
    """Volumen total por día (todas las fuentes sumadas), ordenado asc."""
    rows = conn.execute(
        """SELECT day, SUM(volume) AS v FROM daily
           WHERE entity_key = ? AND market = ? AND day <= ?
           GROUP BY day ORDER BY day DESC LIMIT ?""",
        (entity_key, market, upto_day, days),
    ).fetchall()
    return [(r["day"], r["v"]) for r in reversed(rows)]


def today_candidates(conn, day, min_volume):
    rows = conn.execute(
        """SELECT entity_key, market, SUM(volume) AS v, SUM(n_items) AS n
           FROM daily WHERE day = ?
           GROUP BY entity_key, market
           HAVING v >= ?""",
        (day, min_volume),
    ).fetchall()
    return [dict(r) for r in rows]


def save_spikes(conn, day, rows):
    conn.execute("DELETE FROM spikes WHERE day = ?", (day,))
    conn.executemany(
        """INSERT INTO spikes
           (day, entity_key, market, volume, baseline, z, velocity, status, n_days, value)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        [(day, r["entity_key"], r["market"], r["volume"], r["baseline"], r["z"],
          r["velocity"], r["status"], r["n_days"], r["value"]) for r in rows],
    )


def evidence(conn, entity_key, market, day, limit=6):
    return [dict(r) for r in conn.execute(
        """SELECT i.title, i.url, i.source, i.author, i.weight
           FROM items i JOIN item_entities ie ON ie.item_id = i.id
           WHERE ie.entity_key = ? AND i.market = ? AND i.day = ?
           ORDER BY i.weight DESC LIMIT ?""",
        (entity_key, market, day, limit),
    ).fetchall()]


def source_split(conn, entity_key, market, day):
    return {r["source"]: r["volume"] for r in conn.execute(
        "SELECT source, volume FROM daily WHERE entity_key=? AND market=? AND day=?",
        (entity_key, market, day))}


def display_name(conn, key):
    r = conn.execute("SELECT display FROM entities WHERE key = ?", (key,)).fetchone()
    return r["display"] if r else key


def save_briefs(conn, day, rows):
    conn.execute("DELETE FROM briefs WHERE day = ?", (day,))
    conn.executemany(
        """INSERT OR REPLACE INTO briefs
           (day, market, entity_key, topic, why, angle, durability) VALUES (?,?,?,?,?,?,?)""",
        [(day, r["market"], r["entity_key"], r.get("topic"), r.get("why"),
          r.get("angle"), r.get("durability")) for r in rows],
    )


def get_briefs(conn, day):
    return {(r["market"], r["entity_key"]): dict(r)
            for r in conn.execute("SELECT * FROM briefs WHERE day = ?", (day,))}


def save_saturation(conn, day, rows):
    # OR REPLACE sin DELETE: con varias corridas al día, una medición de la
    # mañana sobrevive aunque el tema ya no sea PICO a la tarde.
    conn.executemany(
        """INSERT OR REPLACE INTO saturation (day, market, entity_key, n_videos)
           VALUES (?,?,?,?)""",
        [(day, r["market"], r["entity_key"], r["n_videos"]) for r in rows],
    )


def get_saturation(conn, day):
    return {(r["market"], r["entity_key"]): r["n_videos"]
            for r in conn.execute(
                "SELECT market, entity_key, n_videos FROM saturation WHERE day = ?",
                (day,))}
