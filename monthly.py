#!/usr/bin/env python3
"""Retrospectiva mensual — los 5 temas de más repercusión por mercado, con
análisis de por qué se volvieron tendencia.

    python monthly.py --month 2026-07
    python monthly.py --month 2026-08 --no-explain   # sin llamar a Claude
    python monthly.py --month 2026-07 --analysis-json julio.json  # análisis
                                                        # ya escrito, sin API

A diferencia de run.py, esto NO recolecta nada nuevo: solo lee lo que ya
existe (data/pauta.db para días recientes, reports/pauta-*.html archivado
para lo que la retención de 30 días ya podó — ver tm/monthly.py). Corrida
manual/on-demand por ahora, no está en el cron diario."""
import argparse
import json
import logging
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tm import db, monthly

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s  %(message)s")
log = logging.getLogger("monthly")


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
    ap.add_argument("--month", required=True, help="YYYY-MM, ej. 2026-07")
    ap.add_argument("--no-explain", action="store_true")
    ap.add_argument("--analysis-json", help="topic/why ya escritos a mano, sin llamar a Claude")
    args = ap.parse_args()

    year, month = (int(x) for x in args.month.split("-", 1))

    load_env()
    cfg = yaml.safe_load(open(args.config, encoding="utf-8"))
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    with db.connect_readonly(cfg["db"]) as conn:
        top = monthly.collect_month(conn, db, cfg["out_dir"], year, month,
                                    cfg["markets"], cfg.get("excluir"))
        for mkt, cands in top.items():
            log.info("%s: %d temas — %s", mkt, len(cands),
                     ", ".join(c["display"] for c in cands))

        if args.analysis_json:
            with open(args.analysis_json, encoding="utf-8") as f:
                monthly.apply_analysis(top, json.load(f))
        elif not args.no_explain:
            monthly.generate_analysis(top, cfg["markets"],
                                      cfg["explain"].get("model", "claude-sonnet-5"),
                                      api_key)

        html = monthly.render(year, month, top, cfg["markets"], cfg["out_dir"])
        path = monthly.write(html, cfg["out_dir"], year, month)
        touched = monthly.sync_selector(cfg["out_dir"])
        log.info("selector sincronizado en %d archivos", len(touched))
        print(f"\n→ {os.path.abspath(path)}")


if __name__ == "__main__":
    main()
