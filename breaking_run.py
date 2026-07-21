#!/usr/bin/env python3
"""Monitor de última hora — corre cada ~15 min.

    python breaking_run.py

Es deliberadamente liviano: NO baja YouTube, NO usa spaCy pesado, NO recalcula
series de 28 días. Solo mira Google News + Trends (las fuentes que reaccionan
en minutos), detecta rupturas multi-fuente respecto a la corrida anterior, y
actualiza el bloque "⚡ Última hora" del reporte.

Usa su propia tabla en la misma base de datos, así que NO interfiere con la
pauta diaria (run.py) ni con su historial de tendencias.
"""
import argparse
import json
import logging
import os
import sys
from datetime import date

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tm import db, sources, breaking, report

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s  %(message)s")
log = logging.getLogger("breaking")


def collect_fast(market, day):
    """Solo las fuentes rápidas. No toca YouTube (cuota) ni RSS lento."""
    items = []
    try:
        items += sources.gnews(market, day, {"topics": ["WORLD", "NATION",
                                                          "ENTERTAINMENT"]})
    except Exception as e:
        log.warning("gnews %s: %s", market["id"], e)
    try:
        items += sources.gtrends(market, day, {})
    except Exception as e:
        log.warning("gtrends %s: %s", market["id"], e)
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))
    day = date.today().isoformat()

    with db.connect(cfg["db"]) as conn:
        db.init(conn)
        breaking.init(conn)

        all_items = []
        for m in cfg["markets"]:
            got = collect_fast(m, day)
            for it in got:
                if isinstance(it.get("extra"), str):
                    it["extra"] = json.loads(it["extra"] or "{}")
            all_items += got
            log.info("%s: %d items rápidos", m["id"], len(got))

        rupturas = breaking.detect(conn, all_items)
        breaking.record_alerts(conn, rupturas)

        if rupturas:
            log.info("%d RUPTURAS nuevas: %s", len(rupturas),
                     ", ".join(r["display"] for r in rupturas))
        else:
            log.info("sin rupturas nuevas esta vuelta")

        # Re-renderizar el reporte para reflejar el bloque de última hora.
        # Reusa lo último que calculó la pauta diaria (spikes/briefs guardados),
        # solo actualiza la banda de arriba.
        spikes = [dict(r) for r in conn.execute(
            "SELECT * FROM spikes WHERE day=? ORDER BY value DESC", (day,))]
        for s in spikes:
            s["history"] = db.series(conn, s["entity_key"], s["market"], day,
                                     cfg["spike"]["window_days"] + 1)
        alerts = breaking.active_alerts(conn)
        html = report.render(day, cfg["markets"], spikes, db.get_briefs(conn, day),
                             conn, db, {}, cfg["spike"], breaking_alerts=alerts)
        report.write(html, cfg["out_dir"], day)
        log.info("reporte actualizado con %d alertas activas", len(alerts))


if __name__ == "__main__":
    main()
