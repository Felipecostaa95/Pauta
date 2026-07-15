"""Detección de picos.

Tres decisiones que importan:

1. Mediana + MAD en vez de media + desviación estándar. El pico de la semana
   pasada contamina la media y sube la vara: el sistema se vuelve ciego justo
   con los temas que más te importan. La mediana lo ignora.

2. Baseline consciente del día de semana. El volumen de noticias se desploma
   sábado y domingo. Sin esto, todo lunes parece un pico.

3. Los días sin datos son CERO solo si el sistema estaba corriendo. Antes de
   la primera corrida son DESCONOCIDO, no cero. Confundirlos hace que las
   primeras semanas todo parezca explotar.
"""
import math
from datetime import date, timedelta
from statistics import median


def _d(s):
    return date.fromisoformat(s)


def dense_history(rows, upto, window, system_start):
    """Serie diaria completa (con ceros) hasta el día ANTERIOR a `upto`,
    recortada al día en que el sistema empezó a recolectar."""
    m = dict(rows)
    end = _d(upto) - timedelta(days=1)
    start = max(_d(upto) - timedelta(days=window), _d(system_start))
    if start > end:
        return []
    days, cur = [], start
    while cur <= end:
        days.append(cur)
        cur += timedelta(days=1)
    return [(d, m.get(d.isoformat(), 0.0)) for d in days]


def robust_z(hist_values, today, center):
    """z robusto. 1.4826*MAD ≈ sigma para una normal."""
    if not hist_values:
        return 0.0
    med = median(hist_values)
    mad = median([abs(x - med) for x in hist_values])
    if mad > 0:
        scale = 1.4826 * mad
    else:
        # Caso frecuentísimo: casi todo cero. Sin piso, una sola mención da z=inf.
        scale = max(0.75, 0.25 * max(1.0, center))
    return (today - center) / scale


def baseline_center(hist, upto):
    """Mediana de la ventana vs mediana del mismo día de semana. Tomamos la
    mayor: preferimos perder un pico dudoso antes que pautar un falso positivo."""
    vals = [v for _, v in hist]
    if not vals:
        return 0.0
    overall = median(vals)
    dow = _d(upto).weekday()
    same = [v for d, v in hist if d.weekday() == dow]
    return max(overall, median(same)) if len(same) >= 2 else overall


def velocity(hist, today):
    """Cambio relativo respecto a ayer. Un tema alto pero plano no es noticia;
    un tema que se duplica sí."""
    if not hist:
        return 1.0
    yesterday = hist[-1][1]
    return (today - yesterday) / max(1.0, yesterday)


def classify(z, vel, n_days, cfg):
    if n_days < cfg["min_history"]:
        return "NUEVO"
    if z >= cfg["z_spike"]:
        return "PICO" if vel > 0.15 else "TECHO"
    if z >= cfg["z_watch"]:
        return "OBSERVAR"
    return None


def score(z, cpm_index):
    """Prioridad = magnitud del pico ponderada por lo que vale ese mercado.
    Un z=4 en US no vale lo mismo que un z=4 en MX cuando el CPM es 8x.
    El log evita que US se coma la pauta entera."""
    return z * math.log10(1 + cpm_index * 10)


def collapse_stories(conn, day, spikes, thresh=0.6):
    """Un solo hecho dispara muchas entidades a la vez. "Sydney Sweeney",
    "leaked contract", "statement" y "addresses" son el MISMO evento y llenaban
    cuatro filas de la pauta.

    No es un problema de alias — son entidades distintas. Es que aparecen en el
    mismo conjunto de notas. Si dos entidades comparten el 60% de sus items, son
    una sola historia: se queda la de mayor score y las demás pasan a ser
    términos relacionados.
    """
    sets = {}
    for r in conn.execute(
            """SELECT ie.entity_key AS k, i.market AS m, i.id AS iid
               FROM item_entities ie JOIN items i ON i.id = ie.item_id
               WHERE i.day = ?""", (day,)):
        sets.setdefault((r["m"], r["k"]), set()).add(r["iid"])

    out = []
    for market in {r["market"] for r in spikes}:
        rows = sorted([r for r in spikes if r["market"] == market],
                      key=lambda r: -r["value"])
        heads = []
        for r in rows:
            mine = sets.get((market, r["entity_key"]), set())
            absorbed = False
            for h in heads:
                theirs = sets.get((market, h["entity_key"]), set())
                overlap = len(mine & theirs) / max(1, min(len(mine), len(theirs)))
                if overlap >= thresh:
                    h.setdefault("related", []).append(r["entity_key"])
                    absorbed = True
                    break
            if not absorbed:
                heads.append(r)
        out += heads

    out.sort(key=lambda r: -r["value"])
    return out


def detect(conn, day, cfg, markets, db):
    row = conn.execute("SELECT MIN(day) AS d FROM items").fetchone()
    system_start = row["d"] or day
    cpm = {m["id"]: m.get("cpm_index", 1.0) for m in markets}

    out = []
    for cand in db.today_candidates(conn, day, cfg["min_volume"]):
        key, mkt, vol = cand["entity_key"], cand["market"], cand["v"]
        rows = db.series(conn, key, mkt, day, cfg["window_days"] + 1)
        rows = [(d, v) for d, v in rows if d < day]
        hist = dense_history(rows, day, cfg["window_days"], system_start)
        vals = [v for _, v in hist]

        center = baseline_center(hist, day)
        z = robust_z(vals, vol, center)
        vel = velocity(hist, vol)
        status = classify(z, vel, len(hist), cfg)
        if status is None:
            continue

        out.append({
            "entity_key": key, "market": mkt, "volume": vol,
            "baseline": center, "z": z, "velocity": vel,
            "status": status, "n_days": len(hist),
            "value": score(z, cpm.get(mkt, 1.0)),
            "history": hist,
        })

    out.sort(key=lambda r: -r["value"])
    return collapse_stories(conn, day, out, cfg.get("collapse", 0.6))
