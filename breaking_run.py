#!/usr/bin/env python3
"""Monitor de última hora — corre cada ~15 min.

    python breaking_run.py

Es deliberadamente liviano: NO baja YouTube, NO usa spaCy pesado, NO recalcula
series de 28 días. Solo mira Google News + Trends (las fuentes que reaccionan
en minutos), detecta rupturas multi-fuente respecto a la corrida anterior, y
actualiza el bloque "⚡ Última hora" del reporte.

Usa su PROPIA base de datos (data/breaking.db), separada de la pauta diaria
(data/pauta.db). Esto no es un detalle: los dos workflows corren en paralelo y
si escribieran el mismo archivo binario, git no puede fusionarlo y el rebase
revienta ("Cannot merge binary files"). Cada uno con su .db => nunca chocan.
Para re-renderizar el reporte el monitor SÍ necesita los spikes/briefs de la
pauta diaria, pero los lee en modo SOLO LECTURA: jamás escribe data/pauta.db.
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


def breaking_db_path(cfg):
    """La base propia del monitor. Por defecto data/breaking.db (junto a la
    pauta diaria), o cfg['breaking_db'] si se define. Separada a propósito de
    cfg['db']: ver el docstring del módulo."""
    explicit = cfg.get("breaking_db")
    if explicit:
        return explicit
    data_dir = os.path.dirname(cfg["db"]) or "."
    return os.path.join(data_dir, "breaking.db")


def render_report(pauta_db, cfg, day, alerts):
    """Re-renderiza el reporte con la banda de última hora encima.

    Los spikes/briefs los pone la pauta diaria en data/pauta.db; acá los leemos
    en modo SOLO LECTURA (nunca escribimos ese archivo) y regeneramos el HTML
    completo. Si la pauta diaria todavía no corrió y no existe la base, no hay
    nada que re-renderizar — el próximo monitor lo levantará cuando exista."""
    if not os.path.exists(pauta_db):
        log.warning("%s no existe aún; sin pauta diaria que re-renderizar "
                    "(igual quedó registrado el estado del monitor)", pauta_db)
        return
    # El archivo de días previos sale de los pauta-*.html ya generados, igual
    # que en la pauta diaria: así el dropdown de otros días no desaparece al
    # re-renderizar desde el monitor.
    archive = sorted(
        f[len("pauta-"):-len(".html")] for f in os.listdir(cfg["out_dir"])
        if f.startswith("pauta-") and f.endswith(".html")
    ) if os.path.isdir(cfg["out_dir"]) else []
    if day not in archive:
        archive.append(day)

    with db.connect_readonly(pauta_db) as pconn:
        spikes = [dict(r) for r in pconn.execute(
            "SELECT * FROM spikes WHERE day=? ORDER BY value DESC", (day,))]
        for s in spikes:
            s["history"] = db.series(pconn, s["entity_key"], s["market"], day,
                                     cfg["spike"]["window_days"] + 1)
        # Pasamos saturación y archivo (leídos en solo-lectura) para que el
        # reporte del monitor sea idéntico al de la pauta diaria + la banda de
        # última hora encima, sin perder las badges de saturación.
        html = report.render(day, cfg["markets"], spikes, db.get_briefs(pconn, day),
                             pconn, db, {}, cfg["spike"],
                             saturation=db.get_saturation(pconn, day),
                             archive=archive, breaking_alerts=alerts)
        report.write(html, cfg["out_dir"], day)
    log.info("reporte actualizado con %d alertas activas", len(alerts))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))
    day = date.today().isoformat()
    brk_db = breaking_db_path(cfg)

    # ── 1. Detección de rupturas ────────────────────────────────────────
    # El estado del monitor y sus alertas viven en SU base (brk_db), nunca en
    # la pauta diaria. Este es el único archivo que el monitor escribe.
    with db.connect(brk_db) as bconn:
        breaking.init(bconn)

        all_items = []
        for m in cfg["markets"]:
            got = collect_fast(m, day)
            for it in got:
                if isinstance(it.get("extra"), str):
                    it["extra"] = json.loads(it["extra"] or "{}")
            all_items += got
            log.info("%s: %d items rápidos", m["id"], len(got))

        rupturas = breaking.detect(bconn, all_items)
        breaking.record_alerts(bconn, rupturas)
        alerts = breaking.active_alerts(bconn)

        if rupturas:
            log.info("%d RUPTURAS nuevas: %s", len(rupturas),
                     ", ".join(r["display"] for r in rupturas))
        else:
            log.info("sin rupturas nuevas esta vuelta")

    # ── 2. Re-render del reporte (lee la pauta diaria en SOLO LECTURA) ───
    render_report(cfg["db"], cfg, day, alerts)


if __name__ == "__main__":
    main()
