#!/usr/bin/env python3
"""Retrospectiva mensual — los 5 temas de más repercusión por mercado, con
análisis de por qué se volvieron tendencia.

    python monthly.py --month 2026-07
    python monthly.py --month 2026-08 --no-explain   # sin llamar a Claude

A diferencia de run.py, esto NO recolecta nada nuevo: solo lee lo que ya
existe (data/pauta.db para días recientes, reports/pauta-*.html archivado
para lo que la retención de 30 días ya podó — ver tm/monthly.py). Corrida
manual/on-demand por ahora, no está en el cron diario."""
import argparse
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

        if not args.no_explain:
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
