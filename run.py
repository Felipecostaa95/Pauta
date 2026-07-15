#!/usr/bin/env python3
"""Pauta — monitor diario de tendencias.

    python run.py                 # corre todo para hoy
    python run.py --day 2026-07-14
    python run.py --no-explain    # sin llamar a Claude
    python run.py --report-only   # re-renderiza sin recolectar
"""
import argparse
import logging
import os
import sys
from datetime import date

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tm import db, sources, entities, spike, explain, report

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s  %(message)s")
log = logging.getLogger("pauta")


def load_env(path=".env"):
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--day", default=date.today().isoformat())
    ap.add_argument("--no-explain", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()

    load_env()
    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))
    day = args.day
    secrets = {"YOUTUBE_API_KEY": os.environ.get("YOUTUBE_API_KEY")}

    with db.connect(cfg["db"]) as conn:
        db.init(conn)
        coverage = {}

        # ── 1. recolectar ───────────────────────────────────
        if not args.report_only:
            all_items = []
            for m in cfg["markets"]:
                items, rep = sources.collect(m, day, cfg["sources"], secrets)
                coverage[m["id"]] = rep
                all_items += items
                log.info("%s: %d items  %s", m["id"], len(items), rep)

            new = db.upsert_items(conn, all_items)
            log.info("guardados %d nuevos de %d recolectados", new, len(all_items))

            # ── 2. entidades ────────────────────────────────
            rows = [dict(r) for r in db.items_for_day(conn, day)]
            for r in rows:
                import json
                r["extra"] = json.loads(r["extra"] or "{}")
            pairs, display = entities.extract(rows, cfg["entities"])
            db.register_entities(conn, display, day)
            db.link_items(conn, pairs)
            log.info("%d entidades, %d vínculos", len(display), len(pairs))

            # ── 3. agregar ──────────────────────────────────
            db.rebuild_daily(conn, day)

        # ── 4. detectar ─────────────────────────────────────
        spikes = spike.detect(conn, day, cfg["spike"], cfg["markets"], db)
        db.save_spikes(conn, day, spikes)
        log.info("%d temas sobre el umbral", len(spikes))

        # ── 5. explicar ─────────────────────────────────────
        if not args.no_explain and not args.report_only:
            top = []
            for m in cfg["markets"]:
                top += [r for r in spikes if r["market"] == m["id"]][:cfg["spike"]["top_per_market"]]
            briefs = explain.run(conn, db, day, top, cfg["explain"], cfg["markets"])
            if briefs:
                db.save_briefs(conn, day, briefs)
                log.info("%d fichas editoriales", len(briefs))

        # ── 6. pauta ────────────────────────────────────────
        html = report.render(day, cfg["markets"], spikes, db.get_briefs(conn, day),
                             conn, db, coverage, cfg["spike"])
        path = report.write(html, cfg["out_dir"], day)
        print(f"\n→ {os.path.abspath(path)}")


if __name__ == "__main__":
    main()
