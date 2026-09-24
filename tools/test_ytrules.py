"""Tests simulados de las reglas de admisión del video (AJUSTE-youtube-picos).

No pegan a ninguna API: arman items a mano y verifican qué sobrevive.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import yaml
from tm import ytrules, entities, sources
from tm import tags as tagmatch

CFG = yaml.safe_load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.yaml"), encoding="utf-8"))
CAT = CFG["categorias_destacadas"]
EXC = CFG["excluir"]

_n = [0]


def item(title, source, market="US", kind="short", vph=1000.0, disc=0.002,
         author="Canal", tags=()):
    _n[0] += 1
    return {
        "id": f"i{_n[0]}", "day": "2026-09-24", "source": source, "market": market,
        "lang": "en", "title": title, "url": "http://x", "author": author,
        "published_at": "2026-09-24T06:00:00Z", "weight": 1.0,
        "extra": ({"yt_kind": kind, "vph": vph, "disc": disc, "tags": list(tags)}
                  if source in ytrules.VIDEO_SOURCES else {}),
    }


def corre(items, pairs):
    """Aplica el pipeline real: exclusión dura y después admisión de video."""
    by_id = {i["id"]: i for i in items}
    display = {k: k for _, k in pairs}
    pairs2, excluidos = tagmatch.filter_excluded_items(
        pairs, by_id, display, EXC, "pauta_diaria", categorias_cfg=CAT)
    pairs3, motivos = ytrules.filter_video_items(pairs2, by_id, CAT)
    temas = {k for _, k in pairs3}
    fuentes = {}
    for iid, k in pairs3:
        fuentes.setdefault(k, set()).add(by_id[iid]["source"])
    return temas, fuentes, motivos, {e["category"] for e in excluidos}


ok = fallos = 0


def check(nombre, cond, detalle=""):
    global ok, fallos
    if cond:
        ok += 1
        print(f"  PASA  {nombre}")
    else:
        fallos += 1
        print(f"  FALLA {nombre}  {detalle}")


print("\n== 1. Caso Britney: noticias + videoclip ==")
its = [
    item("Britney Spears breaks silence on conservatorship in new statement", "gnews"),
    item("Britney Spears spotted at LA courthouse", "rss"),
    item("Britney Spears - Toxic (Official Video)", "youtube", kind="videoclip",
         author="BritneySpearsVEVO"),
]
pairs = [(i["id"], "britney spears") for i in its]
temas, fuentes, motivos, _ = corre(its, pairs)
check("el tema sobrevive", "britney spears" in temas)
check("la fila NO muestra el videoclip", "youtube" not in fuentes.get("britney spears", set()),
      f'fuentes={fuentes.get("britney spears")}')
check("se contó 1 videoclip", motivos.get("videoclip") == 1, dict(motivos))

print("\n== 2a. Vlog con muchas vistas, sin corroborar ==")
its = [item("I spent 24 hours in the world's smallest apartment", "youtube",
            kind="largo", vph=90000.0, disc=0.01, author="Big Vlogger")]
pairs = [(its[0]["id"], "big vlogger")]
temas, fuentes, motivos, _ = corre(its, pairs)
check("el tema desaparece", "big vlogger" not in temas, temas)
check("motivo = largo sin corroborar",
      motivos.get("largo_sin_corroborar") == 1, dict(motivos))

print("\n== 2b. El mismo vlogger, ahora con una noticia sobre él ==")
its = [
    item("Big Vlogger sued over viral apartment stunt, faces eviction", "gnews"),
    item("I spent 24 hours in the world's smallest apartment", "youtube",
         kind="largo", vph=90000.0, disc=0.01, author="Big Vlogger"),
]
pairs = [(i["id"], "big vlogger") for i in its]
temas, fuentes, motivos, _ = corre(its, pairs)
check("el tema entra", "big vlogger" in temas)
check("el video acompaña a la noticia",
      fuentes.get("big vlogger") == {"gnews", "youtube"}, fuentes.get("big vlogger"))
check("nada descartado", not motivos, dict(motivos))

print("\n== 3. Bailes afuera ==")
its = [item("New dance challenge takes over the internet", "youtube",
            kind="short", vph=99999.0, disc=0.05)]
pairs = [(its[0]["id"], "dance challenge")]
temas, _, motivos, cats = corre(its, pairs)
check("el baile desaparece", "dance challenge" not in temas, temas)
check("lo sacó la exclusión de bailes", "bailes" in cats, cats)

print("\n== 4. Short corroborado (regla 3a) ==")
its = [
    item("Firefighters pull driver from burning car on I-95", "gnews"),
    item("Dramatic rescue on I-95 caught on camera", "agencias_video",
         kind="short", vph=50.0, disc=0.0001, author="Newsflare"),
]
pairs = [(i["id"], "i 95") for i in its]
temas, fuentes, motivos, _ = corre(its, pairs)
check("entra aunque tenga señal floja", "agencias_video" in fuentes.get("i 95", set()),
      fuentes.get("i 95"))

print("\n== 5. Short sin corroborar: señal viral + categoría vs. sin categoría ==")
# 6 shorts de relleno para que haya cuartil; los últimos son los evaluados.
base = [item(f"Random clip number {i}", "youtube", kind="short",
             vph=100.0 * i, disc=0.0001 * i) for i in range(1, 7)]
fuerte_cat = item("Firefighter rescues puppy from frozen lake", "youtube",
                  kind="short", vph=99999.0, disc=0.05)
fuerte_sin = item("Man assembles a bookshelf very quickly", "youtube",
                  kind="short", vph=99999.0, disc=0.05)
debil_cat = item("Police arrest suspect after slow chase", "youtube",
                 kind="short", vph=1.0, disc=0.0000001)
its = base + [fuerte_cat, fuerte_sin, debil_cat]
pairs = ([(i["id"], f"tema{n}") for n, i in enumerate(base)]
         + [(fuerte_cat["id"], "frozen lake"), (fuerte_sin["id"], "bookshelf"),
            (debil_cat["id"], "slow chase")])
temas, fuentes, motivos, _ = corre(its, pairs)
check("señal viral + categoría destacada ENTRA", "frozen lake" in temas, temas)
check("señal viral sin categoría QUEDA AFUERA", "bookshelf" not in temas, temas)
check("categoría sin señal viral QUEDA AFUERA", "slow chase" not in temas, temas)


print("\n== 5b. El cuartil se mide por fuente, no en un solo pool ==")
# Escala real medida el 2026-09-24: los shorts de mostPopular corren a decenas
# de miles de vistas/hora y los de agencia a decenas. En un solo pool ningún
# clip de agencia pasaría nunca, que es justo la fuente más noticiosa.
grandes = [item(f"Popular short {i}", "youtube", kind="short",
                vph=30000.0 * i, disc=0.002 * i) for i in range(1, 7)]
chicos = [item(f"Agency filler {i}", "agencias_video", kind="short",
               vph=30.0 * i, disc=0.0005 * i, author="Newsflare") for i in range(1, 7)]
clip = item("Feisty kitten sneak attack on sleeping dog", "agencias_video",
            kind="short", vph=740.0, disc=0.004, author="ViralHog")
its = grandes + chicos + [clip]
pairs = ([(i["id"], f"g{n}") for n, i in enumerate(grandes)]
         + [(i["id"], f"c{n}") for n, i in enumerate(chicos)]
         + [(clip["id"], "feisty kitten")])
temas, _, motivos, _ = corre(its, pairs)
check("el clip de agencia entra pese a su velocidad absoluta baja",
      "feisty kitten" in temas, temas)
check("los clips de relleno de la agencia NO entran",
      not any(f"c{n}" in temas for n in range(6)), temas)

print("\n== 6. Sin muestra suficiente no hay cuartil ==")
its = [item("Firefighter rescues puppy from frozen lake", "youtube",
            kind="short", vph=99999.0, disc=0.05)]
pairs = [(its[0]["id"], "frozen lake")]
temas, _, motivos, _ = corre(its, pairs)
check("con 1 solo short nadie entra por señal viral", "frozen lake" not in temas, temas)

print("\n== 7. Los tags de YouTube ya no crean entidades ==")
it = {"id": "x", "title": "Puppy rescued from storm drain", "lang": "en",
      "extra": {"tags": ["vlog", "official", "mrbeast", "viral 2026"]}}
cands = entities._extract_one(it, entities.build_caps_prior([it["title"]]))
check("ningún tag entre los candidatos",
      not any(t in cands for t in it["extra"]["tags"]), cands)

print("\n== 8. Peso por actividad, no por vistas acumuladas ==")
# Mismas vistas totales, distinta antigüedad: gana el reciente.
viejo = sources._yt_weight(*sources._yt_activity("2026-06-24T06:00:00Z", 5_000_000, 10_000),
                           views=5_000_000)
nuevo = sources._yt_weight(*sources._yt_activity("2026-09-24T06:00:00Z", 5_000_000, 10_000),
                           views=5_000_000)
check("un video de hoy pesa más que uno de hace 3 meses con las mismas vistas",
      nuevo > viejo, f"{nuevo:.2f} vs {viejo:.2f}")
poco, mucho = (sources._yt_weight(*sources._yt_activity("2026-09-24T06:00:00Z", 100_000, c),
                                  views=100_000) for c in (50, 6_000))
check("más discusión pesa más", mucho > poco, f"{mucho:.2f} vs {poco:.2f}")

print(f"\n{ok} pasan, {fallos} fallan")
sys.exit(1 if fallos else 0)
