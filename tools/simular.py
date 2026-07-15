#!/usr/bin/env python3
"""Genera 30 días de datos sintéticos con picos plantados y verifica que el
detector los encuentre. Sirve para dos cosas:

  1. Probar el sistema sin esperar un mes de recolección real.
  2. Calibrar los umbrales (z_watch, z_spike) contra casos conocidos.

    python tools/simular.py            # crea data/sim.db + reports/
"""
import hashlib
import os
import random
import sys
from datetime import date, timedelta

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tm import db, entities, spike, report

random.seed(7)

# Fondo: temas que están siempre, con volumen ruidoso y estacionalidad semanal.
FONDO = {
    "MX": ["El presidente de México anuncia cambios en el {x}",
           "La Selección Mexicana define su lista para el {x}",
           "Reportan un aumento del {x} en la Ciudad de México"],
    "US": ["Federal Reserve signals shift on {x}",
           "New York City reports record {x} numbers",
           "Congress debates {x} bill ahead of recess"],
    "FR": ["Le gouvernement français annonce une réforme du {x}",
           "Emmanuel Macron reçoit une délégation sur le {x}",
           "La SNCF prévoit des perturbations liées au {x}"],
}
RELLENO = ["presupuesto", "mercado", "clima", "transporte", "empleo", "turismo",
           "consumo", "energia", "salario", "trafico"]

# Los picos plantados. Cada uno arranca en su día y sube.
PICOS = [
    {"market": "MX", "dia": 29, "n": 22,
     "t": "Erupción del Popocatépetl obliga a cerrar el aeropuerto",
     "esperado": "popocatepetl"},
    {"market": "US", "dia": 28, "n": 30,
     "t": "Sydney Sweeney addresses the leaked contract in a statement",
     "esperado": "sydney sweeney"},
    {"market": "FR", "dia": 29, "n": 18,
     "t": "Kylian Mbappé quitte le club après une réunion d'urgence",
     "esperado": "kylian mbappe"},
    # Trampa: tema alto pero PLANO. No debe salir como pico.
    {"market": "MX", "dia": 0, "n": 14, "todos_los_dias": True,
     "t": "Nuevo capítulo del caso Chapo Guzmán en tribunales",
     "esperado": "chapo guzman"},
]


def mk(day, market, source, title, weight=1.0, extra=None):
    return {"id": hashlib.sha1(f"{day}{market}{title}{random.random()}".encode()).hexdigest()[:20],
            "day": day, "source": source, "market": market,
            "lang": {"MX": "es", "US": "en", "FR": "fr"}[market],
            "title": title, "url": f"https://example.com/{random.randint(1, 9**9)}",
            "author": "sim", "published_at": day, "weight": weight,
            "extra": extra or {}}


def generar(dias=30):
    hoy = date.today()
    todos = []
    for d in range(dias):
        day = (hoy - timedelta(days=dias - 1 - d)).isoformat()
        finde = (hoy - timedelta(days=dias - 1 - d)).weekday() >= 5
        for mkt, plantillas in FONDO.items():
            n = int(random.gauss(26, 5) * (0.45 if finde else 1.0))
            for _ in range(max(4, n)):
                t = random.choice(plantillas).format(x=random.choice(RELLENO))
                todos.append(mk(day, mkt, random.choice(["gnews", "rss", "gnews"]), t))

        for p in PICOS:
            activo = p.get("todos_los_dias") or d >= p["dia"]
            if not activo:
                continue
            escala = 1.0 if p.get("todos_los_dias") else (d - p["dia"] + 1) * 0.7
            for _ in range(int(p["n"] * escala)):
                src = random.choice(["gnews", "gnews", "youtube", "gtrends", "reddit"])
                extra = {"is_query": True} if src == "gtrends" else {}
                t = p["t"] if src != "gtrends" else p["esperado"]
                todos.append(mk(day, p["market"], src, t,
                                weight=random.uniform(0.8, 3.0), extra=extra))
    return todos, hoy.isoformat()


def main():
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    cfg["db"] = "data/sim.db"
    if os.path.exists(cfg["db"]):
        os.remove(cfg["db"])

    items, hoy = generar()
    print(f"generados {len(items)} items sintéticos sobre 30 días")

    with db.connect(cfg["db"]) as conn:
        db.init(conn)
        db.upsert_items(conn, items)
        por_dia = {}
        for i in items:
            por_dia.setdefault(i["day"], []).append(i)
        for day, rows in sorted(por_dia.items()):
            pairs, display = entities.extract(rows, cfg["entities"])
            db.register_entities(conn, display, day)
            db.link_items(conn, pairs)
            db.rebuild_daily(conn, day)

        spikes = spike.detect(conn, hoy, cfg["spike"], cfg["markets"], db)
        db.save_spikes(conn, hoy, spikes)

        print(f"\n{'ESTADO':<9} {'MKT':<4} {'Z':>6} {'VOL':>7} {'BASE':>7}  TEMA")
        print("─" * 78)
        for r in spikes[:22]:
            print(f"{r['status']:<9} {r['market']:<4} {r['z']:>6.1f} "
                  f"{r['volume']:>7.1f} {r['baseline']:>7.1f}  "
                  f"{db.display_name(conn, r['entity_key'])[:44]}")

        # ── verificación ────────────────────────────────────
        print("\n" + "─" * 78)
        detectados = {(r["market"], r["entity_key"]): r for r in spikes}
        ok = True
        for p in PICOS:
            hit = next((r for (m, k), r in detectados.items()
                        if m == p["market"] and (p["esperado"] in k or p["esperado"].split()[-1] in k)), None)
            plano = p.get("todos_los_dias")
            if plano:
                bien = hit is None or hit["status"] != "PICO"
                print(f"{'✓' if bien else '✗'} plano '{p['esperado']}' NO debe ser PICO "
                      f"→ {hit['status'] if hit else 'no reportado'}")
            else:
                bien = hit is not None and hit["status"] in ("PICO", "NUEVO")
                print(f"{'✓' if bien else '✗'} pico '{p['esperado']}' detectado "
                      f"→ {hit['status']+' z='+format(hit['z'],'.1f') if hit else 'PERDIDO'}")
            ok &= bien

        html = report.render(hoy, cfg["markets"], spikes, db.get_briefs(conn, hoy),
                             conn, db, {"SIM": {"sintetico": len(items)}}, cfg["spike"])
        path = report.write(html, "reports", hoy)
        print(f"\npauta de prueba → {os.path.abspath(path)}")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
