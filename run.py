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
from tm import db, sources, entities, spike, explain, report, saturation
from tm import tags as tagmatch

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

            # Exclusión dura (gaming/conflicto) por NOTA individual, no por
            # tema completo: si un tema tiene 5 notas y 1 es de gaming, se
            # descarta esa nota y las otras 4 arman el tema igual, con menos
            # volumen. Si no le queda ninguna nota limpia, rebuild_daily() de
            # abajo no encuentra volumen para él y desaparece solo — no hace
            # falta un chequeo aparte. Ver tags.filter_excluded_items.
            items_by_id = {r["id"]: r for r in rows}
            pairs, excluded = tagmatch.filter_excluded_items(
                pairs, items_by_id, display, cfg.get("excluir"), "pauta_diaria")
            db.save_excluded(conn, day, excluded)

            excluded_counts = {}
            by_cat = {}
            for e in excluded:
                excluded_counts[e["category"]] = excluded_counts.get(e["category"], 0) + 1
                by_cat.setdefault(e["category"], []).append(f'{e["display"]} ({e["market"]})')
            for cat, names in by_cat.items():
                log.info("temas sin evidencia por %s (%d): %s", cat, len(names), ", ".join(names))

            db.register_entities(conn, display, day)
            db.link_items(conn, pairs)
            log.info("%d entidades, %d vínculos", len(display), len(pairs))

            # ── 3. agregar ──────────────────────────────────
            db.rebuild_daily(conn, day)
        else:
            excluded_counts = db.get_excluded_counts(conn, day)

        # ── 4. detectar ─────────────────────────────────────
        spikes = spike.detect(conn, day, cfg["spike"], cfg["markets"], db,
                              categorias=cfg.get("categorias_destacadas"))
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

        # ── 5b. saturación ──────────────────────────────────
        if not args.report_only:
            sat = saturation.run(conn, db, spikes, db.get_briefs(conn, day),
                                 cfg["markets"], cfg.get("saturation", {}),
                                 secrets["YOUTUBE_API_KEY"],
                                 cfg["spike"]["top_per_market"])
            if sat:
                db.save_saturation(conn, day, sat)
                log.info("saturación medida para %d picos", len(sat))

        # ── 6. pauta ────────────────────────────────────────
        archive = sorted(
            f[len("pauta-"):-len(".html")] for f in os.listdir(cfg["out_dir"])
            if f.startswith("pauta-") and f.endswith(".html")
        ) if os.path.isdir(cfg["out_dir"]) else []
        if day not in archive:
            archive.append(day)
        html = report.render(day, cfg["markets"], spikes, db.get_briefs(conn, day),
                             conn, db, coverage, cfg["spike"],
                             saturation=db.get_saturation(conn, day),
                             archive=archive,
                             categorias=cfg.get("categorias_destacadas"),
                             excluded_counts=excluded_counts)
        path = report.write(html, cfg["out_dir"], day)
        # Igualar el dropdown de archivo en todos los reportes: cada uno lista
        # la lista completa de fechas, sin que las nuevas desaparezcan al abrir
        # una vieja.
        report.sync_archive(cfg["out_dir"])

        # ── 7. podar historial ───────────────────────────────
        # Sin esto data/pauta.db crece sin límite y termina pasando el
        # límite de 100 MB de GitHub — ver tm/db.py (prune) y config.yaml
        # (retention). --report-only no recolecta ni cambia nada, así que
        # tampoco poda.
        if not args.report_only:
            retention_days = cfg.get("retention", {}).get("days")
            if retention_days:
                db.prune(conn, day, retention_days)
                log.info("historial podado a %d días + VACUUM", retention_days)

        print(f"\n→ {os.path.abspath(path)}")


if __name__ == "__main__":
    main()
