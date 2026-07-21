#!/usr/bin/env python3
"""Prueba del monitor de última hora. Simula dos corridas consecutivas:
  Corrida 1: estado normal, un tema apenas mencionado (silencio).
  Corrida 2: ese tema EXPLOTA — muchas fuentes distintas de golpe.
Verifica que la corrida 2 lo detecte como ruptura, y que un tema que ya venía
fuerte NO se marque como ruptura (eso es tendencia, no última hora).
"""
import hashlib, os, sys, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tm import db, breaking

random.seed(11)

def mk(market, title, outlet, source="gnews"):
    return {"id": hashlib.sha1(f"{title}{outlet}{random.random()}".encode()).hexdigest()[:20],
            "day": "2026-07-17", "source": source, "market": market, "lang": "en",
            "title": title, "url": "https://ex.com/"+str(random.randint(1,10**8)),
            "author": outlet, "published_at": "", "weight": 1.0, "extra": {}}

MEDIOS = ["CNN","BBC","Reuters","AP","Fox","NBC","ABC News","The Guardian",
          "USA Today","NYT","Washington Post","Sky News"]

def ruido(market):
    """Titulares de fondo REALISTAS pero controlados: muchos temas, cada uno
    cubierto por pocas fuentes (1-2), para que ninguno cruce el umbral de
    ruptura por accidente. Determinista (sin random) para que sea idéntico
    entre corridas — así el único cambio entre vueltas es lo que plantamos
    a propósito, y no un falso positivo del ruido."""
    out=[]
    temas=["economy budget talks","weather forecast update","local election recount",
           "sports trade rumor","tech gadget review","traffic road closure",
           "housing market report","school board meeting","airline delay notice"]
    for idx, t in enumerate(temas):
        # cada tema: 2 medios fijos distintos, siempre los mismos
        for m in (MEDIOS[idx % len(MEDIOS)], MEDIOS[(idx+3) % len(MEDIOS)]):
            out.append(mk(market, f"{m} reports on {t} details today", m))
    return out

def main():
    dbpath="data/sim_breaking.db"
    if os.path.exists(dbpath): os.remove(dbpath)
    with db.connect(dbpath) as conn:
        db.init(conn); breaking.init(conn)

        # ── Corrida 1: ARRANQUE EN FRÍO. Siembra estado, no debe alertar. ──
        items1 = ruido("US")
        items1.append(mk("US","Famous Actor spotted at restaurant in LA","TMZ"))
        r1 = breaking.detect(conn, items1)
        breaking.record_alerts(conn, r1)
        print(f"Corrida 1 (arranque frío): {len(r1)} rupturas  (esperado: 0)")

        # ── Corrida 2: sigue tranquilo, actor en silencio. Nada debe romper. ──
        items2 = ruido("US")
        items2.append(mk("US","Famous Actor spotted at restaurant in LA","TMZ"))
        r2 = breaking.detect(conn, items2)
        breaking.record_alerts(conn, r2)
        print(f"Corrida 2 (silencio):      {len(r2)} rupturas  (esperado: 0)")

        # ── Corrida 3: "Famous Actor" EXPLOTA — 8 medios distintos de golpe ──
        items3 = ruido("US")
        for m in MEDIOS[:8]:
            items3.append(mk("US","Famous Actor dies suddenly at 58, family confirms", m))
        r3 = breaking.detect(conn, items3)
        breaking.record_alerts(conn, r3)
        print(f"Corrida 3 (explosión):     {len(r3)} rupturas  (esperado: 1, colapsada)")
        for r in r3:
            print(f"    → {r['display']!r}: {r['n_sources']} fuentes | {r['headline'][:50]}")

        # ── Corrida 4: mismo tema sigue fuerte pero YA no es ruptura nueva ──
        items4 = ruido("US")
        for m in MEDIOS[:8]:
            items4.append(mk("US","Famous Actor dies suddenly at 58, family confirms", m))
        r4 = breaking.detect(conn, items4)
        print(f"Corrida 4 (ya venía):      {len(r4)} rupturas nuevas  (esperado: 0)")

        alerts = breaking.active_alerts(conn)
        print(f"\nAlertas activas para mostrar en web: {len(alerts)}")

        ok = (len(r1)==0 and len(r2)==0 and len(r3)==1 and len(r4)==0 and
              any("actor" in a["entity_key"] for a in alerts))
        print("\n" + ("✓ TODO BIEN" if ok else "✗ ALGO FALLÓ"))
        return 0 if ok else 1

if __name__=="__main__":
    sys.exit(main())
