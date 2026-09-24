"""Recolectores. Cada uno devuelve una lista de items normalizados:

    {id, day, source, market, lang, title, url, author, published_at, weight, extra}

Regla de deduplicación: el `id` se deriva del contenido (URL / video id), no del
día. O sea, cada nota o video se cuenta UNA sola vez, el día que aparece por
primera vez. Eso hace que la serie temporal mida *llegada de información nueva*,
que es justo lo que necesitás para detectar algo que revienta hoy.
"""
import hashlib
import math
import re
import logging
from datetime import date, datetime, timedelta, timezone
from xml.etree import ElementTree as ET

import requests

log = logging.getLogger("tm.sources")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"

session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept-Language": "es,en;q=0.8,fr;q=0.6"})

# La API de Wikimedia rechaza User-Agent genérico de navegador: pide uno que
# identifique la app y un contacto (ver https://meta.wikimedia.org/wiki/User-Agent_policy).
# Sesión propia por lo mismo que reddit_session en breaking_run.py: no se
# quiere ensuciar el UA de navegador que usan gtrends/gnews/rss.
wiki_session = requests.Session()
wiki_session.headers.update({
    "User-Agent": "pauta-upsomedia/1.0 (contacto: felipecosta.310@gmail.com)",
})


def _id(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:20]


def _get(url, **kw):
    r = session.get(url, timeout=25, **kw)
    r.raise_for_status()
    return r


def _localname(tag):
    return tag.split("}")[-1] if "}" in tag else tag


def _find(el, name):
    for child in el:
        if _localname(child.tag) == name:
            return child
    return None


def _findall(el, name):
    return [c for c in el if _localname(c.tag) == name]


def _text(el, name, default=""):
    c = _find(el, name)
    return (c.text or default).strip() if c is not None else default


def _parse_traffic(s):
    """'50K+' -> 50000, '1M+' -> 1000000"""
    if not s:
        return 1000
    s = s.replace("+", "").replace(",", "").replace(" ", "").upper()
    mult = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    if s and s[-1] in mult:
        try:
            return float(s[:-1]) * mult[s[-1]]
        except ValueError:
            return 1000
    try:
        return float(s)
    except ValueError:
        return 1000


def _log_weight(n, divisor=2.0, cap=4.0):
    """Aplasta métricas de escala salvaje (views, upvotes) a un rango comparable
    con 'una nota de prensa = 1.0'. Sin esto, un video de 5M de views entierra
    a 40 notas de agencia."""
    return max(0.3, min(cap, math.log10(max(n, 1) + 1) / divisor))


# ─────────────────────────────────────────────────────────────
# Google Trends — qué está buscando la gente. Gratis, sin key.
# ─────────────────────────────────────────────────────────────
def gtrends(market, day, cfg):
    url = f"https://trends.google.com/trending/rss?geo={market['geo']}"
    out = []
    root = ET.fromstring(_get(url).content)
    for item in root.iter():
        if _localname(item.tag) != "item":
            continue
        query = _text(item, "title")
        if not query:
            continue
        traffic = _parse_traffic(_text(item, "approx_traffic"))
        news = [{
            "title": _text(n, "news_item_title"),
            "url": _text(n, "news_item_url"),
            "source": _text(n, "news_item_source"),
            "snippet": _text(n, "news_item_snippet"),
        } for n in _findall(item, "news_item")]

        out.append({
            "id": _id("gtrends", market["id"], query.lower()),
            "day": day, "source": "gtrends", "market": market["id"],
            "lang": market["lang"], "title": query, "url": None,
            "author": "Google Trends", "published_at": _text(item, "pubDate"),
            "weight": _log_weight(traffic, divisor=2.0),
            # El query de Trends ES la entidad — no hay que adivinarla.
            "extra": {"traffic": traffic, "is_query": True, "news": news},
        })
    return out


# ─────────────────────────────────────────────────────────────
# Google News — agrega miles de medios y agencias. Gratis, sin key.
# ─────────────────────────────────────────────────────────────
def _gnews_feed(url, market, day, topic):
    out = []
    root = ET.fromstring(_get(url).content)
    for item in root.iter():
        if _localname(item.tag) != "item":
            continue
        title = _text(item, "title")
        link = _text(item, "link")
        if not title:
            continue
        outlet = _text(item, "source")
        # Google News formatea el título como "Titular - Medio". Sacamos el medio.
        if not outlet and " - " in title:
            title, outlet = title.rsplit(" - ", 1)
        out.append({
            "id": _id("gnews", link or title),
            "day": day, "source": "gnews", "market": market["id"],
            "lang": market["lang"], "title": title.strip(), "url": link,
            "author": outlet.strip(), "published_at": _text(item, "pubDate"),
            "weight": 1.0, "extra": {"topic": topic},
        })
    return out


def gnews(market, day, cfg):
    g = market["gnews"]
    qs = f"hl={g['hl']}&gl={g['gl']}&ceid={g['ceid']}"
    out = _gnews_feed(f"https://news.google.com/rss?{qs}", market, day, "TOP")
    for topic in cfg.get("topics", []):
        try:
            out += _gnews_feed(
                f"https://news.google.com/rss/headlines/section/topic/{topic}?{qs}",
                market, day, topic)
        except Exception as e:
            log.warning("gnews %s/%s: %s", market["id"], topic, e)
    return out


# ─────────────────────────────────────────────────────────────
# RSS directo — agencias y medios específicos que quieras vigilar.
# ─────────────────────────────────────────────────────────────
def rss(market, day, cfg):
    out = []
    for feed in cfg.get("feeds", []):
        if feed.get("market") != market["id"]:
            continue
        try:
            root = ET.fromstring(_get(feed["url"]).content)
        except Exception as e:
            log.warning("rss %s: %s", feed["url"], e)
            continue
        for item in root.iter():
            if _localname(item.tag) not in ("item", "entry"):
                continue
            title = _text(item, "title")
            link = _text(item, "link")
            if not link:
                l = _find(item, "link")
                link = l.get("href") if l is not None else None
            if not title:
                continue
            out.append({
                "id": _id("rss", link or title),
                "day": day, "source": "rss", "market": market["id"],
                "lang": market["lang"], "title": title, "url": link,
                "author": feed.get("name", "RSS"),
                "published_at": _text(item, "pubDate") or _text(item, "published"),
                "weight": 1.0, "extra": {"feed": feed.get("name")},
            })
    return out


# ─────────────────────────────────────────────────────────────
# Wikipedia — artículos más vistos por país. Gratis, sin key (pero exige un
# User-Agent con contacto). Solo para la pauta diaria: Wikimedia publica los
# pageviews con horas de retraso, no sirve para el monitor de rupturas.
# Cuando alguien famoso muere, es arrestado o protagoniza un escándalo, su
# página se dispara — es la señal más fuerte del paquete.
# ─────────────────────────────────────────────────────────────
_WIKI_JUNK_PREFIXES = (
    "special:", "especial:", "spécial:",
    "wikipedia:", "wikipédia:",
    "file:", "archivo:", "fichier:",
    "portal:", "portail:",
    "help:", "ayuda:", "aide:",
    "template:", "plantilla:", "modèle:",
    "category:", "categoría:", "catégorie:",
    "talk:", "discusión:", "discussion:",
    "user:", "usuario:", "utilisateur:",
)


def _wiki_is_article(title):
    if not title or title in ("Main_Page", "-"):
        return False
    return not title.lower().startswith(_WIKI_JUNK_PREFIXES)


def wikipedia(market, day, cfg):
    # Los pageviews se publican con retraso: pedimos el día de AYER (UTC) y,
    # si todavía no está listo (404), probamos un día más atrás.
    target = date.fromisoformat(day) - timedelta(days=1)
    out, data = None, None
    for _ in range(2):
        url = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/"
               f"top-per-country/{market['geo']}/all-access/"
               f"{target.year}/{target.month:02d}/{target.day:02d}")
        try:
            r = wiki_session.get(url, timeout=25)
            if r.status_code == 404:
                target -= timedelta(days=1)
                continue
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.warning("wikipedia %s %s: %s", market["id"], target, e)
            target -= timedelta(days=1)
            continue
        break

    out = []
    if data is None:
        return out
    for entry in data.get("items", []):
        for a in entry.get("articles", []):
            title = a.get("article", "")
            if not _wiki_is_article(title):
                continue
            views = a.get("views_ceil", 0)
            out.append({
                # Contenido, no fecha: si el artículo se mantiene arriba
                # varios días, cuenta una sola vez, el día que apareció.
                "id": _id("wiki", market["id"], title.lower()),
                "day": day, "source": "wikipedia", "market": market["id"],
                "lang": market["lang"], "title": title.replace("_", " "),
                "url": None, "author": "Wikipedia", "published_at": None,
                "weight": _log_weight(views, divisor=2.0),
                # El título del artículo ES la entidad, como en Google Trends.
                "extra": {"views": views, "is_query": True,
                          "project": a.get("project"), "rank": a.get("rank")},
            })
    return out


# ─────────────────────────────────────────────────────────────
# YouTube — corroboración y shorts virales noticiosos.
#
# Ojo con qué mide esta fuente: `chart=mostPopular` mide AUDIENCIA (lo más
# visto), no picos de actividad. Por eso el video NO genera temas por sí solo:
# las reglas de admisión de tm/ytrules.py deciden, video por video, si cuenta
# como evidencia (corroborando un tema que ya pica en prensa/búsquedas/
# Wikipedia, o aportando un short viral noticioso). Acá solo se recolecta, se
# clasifica cada video y se le pone un peso por ACTIVIDAD, no por vistas
# acumuladas.
#
# Cuota: chart=mostPopular cuesta 1 unidad por llamada, videos.list también 1
# (hasta 50 IDs). `search` costaría 100 y no se usa.
# ─────────────────────────────────────────────────────────────

# Un videoclip nunca es evidencia de un pico: el tema entra por la noticia, no
# por el clip. Estos patrones, más el canal (VEVO / " - Topic") y la categoría
# 10, son lo que identifica uno.
_VIDEOCLIP_RX = re.compile(
    r"(?<!\w)("
    r"official\s+music\s+video|official\s+video|music\s+video|lyric\s+video"
    r"|lyrics|visualizer|official\s+audio|video\s+oficial|videoclip"
    r"|clip\s+officiel|audio\s+oficial"
    r")(?!\w)", re.IGNORECASE)

_DURATION_RX = re.compile(
    r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$")

# Categorías que se descartan siempre, sin importar por qué lista entró el
# video: el categoryId REAL del video manda sobre el parámetro que pedimos.
_YT_CATEGORIAS_FUERA = {"20", "10"}   # 20 = Gaming · 10 = Música


def _yt_duration_seconds(iso):
    """'PT1M30S' -> 90. Devuelve None si no viene o no se entiende.

    Los vivos y estrenos traen 'P0D' (0 segundos): eso NO es un short de 0
    segundos, es 'no sé cuánto dura'. Devolvemos None y el clasificador los
    trata como largo, que es la regla más estricta (exige corroboración)."""
    m = _DURATION_RX.match(iso or "")
    if not m:
        return None
    d, h, mi, sec = (float(x) if x else 0.0 for x in m.groups())
    total = d * 86400 + h * 3600 + mi * 60 + sec
    return total or None


def _yt_kind(snippet, duration_s, short_max):
    """'videoclip' | 'short' | 'largo'. El orden importa: un videoclip de 2
    minutos es videoclip, no short."""
    canal = (snippet.get("channelTitle") or "").strip()
    if (snippet.get("categoryId") == "10"
            or canal.endswith("VEVO") or canal.endswith(" - Topic")
            or _VIDEOCLIP_RX.search(snippet.get("title") or "")):
        return "videoclip"
    if duration_s is not None and duration_s <= short_max:
        return "short"
    return "largo"


def _yt_activity(published_at, views, comments):
    """Señales de ACTIVIDAD, que es lo que el monitor busca:

    - velocidad (`vph`): vistas por hora desde publishedAt. Un video con 2M de
      vistas en tres meses no es un pico; 200k en seis horas sí.
    - discusión (`disc`): comentarios sobre vistas. Mide debate, no consumo.

    Devuelve (vph, disc). vph es None si no se pudo fechar el video."""
    horas = None
    if published_at:
        try:
            pub = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            horas = (datetime.now(timezone.utc) - pub).total_seconds() / 3600.0
        except ValueError:
            horas = None
    # Piso de 1 hora: sin él, un video de hace 4 minutos da una velocidad
    # absurda y se come el ranking solo por ser recién publicado.
    vph = views / max(horas, 1.0) if horas is not None else None
    disc = comments / views if views > 0 else 0.0
    return vph, disc


def _yt_weight(vph, disc, views):
    """Peso por actividad, no por vistas acumuladas (que era lo que hacía que
    un videoclip con 40M enterrara a 40 notas de agencia).

    Base = velocidad aplastada con log (mismo rango que el resto de las
    fuentes). Factor de discusión acotado a [0.8, 1.4]: el ratio
    comentarios/vistas normal en YouTube ronda el 0.2%, y 0.6% ya es mucha
    conversación. Acotado a propósito: la discusión modula, no decide.

    Si no se pudo calcular la velocidad (video sin fecha), cae a las vistas
    para no dejarlo en cero — es el peor caso, no el caso normal."""
    base = _log_weight(vph if vph is not None else views, divisor=2.0)
    factor = min(1.4, max(0.8, 0.8 + 100.0 * (disc or 0.0)))
    return max(0.3, min(4.0, base * factor))


def _yt_item(v, market, day, source, short_max, author=None, extra_base=None):
    """Normaliza un video de la API (videos.list) al formato común. Devuelve
    None si el video cae en una categoría vetada."""
    sn, st = v.get("snippet", {}), v.get("statistics", {})
    cd = v.get("contentDetails", {})
    if sn.get("categoryId") in _YT_CATEGORIAS_FUERA:
        return None

    views = int(st.get("viewCount", 0) or 0)
    comments = int(st.get("commentCount", 0) or 0)
    duration_s = _yt_duration_seconds(cd.get("duration"))
    kind = _yt_kind(sn, duration_s, short_max)
    published_at = sn.get("publishedAt")
    vph, disc = _yt_activity(published_at, views, comments)

    extra = {
        "views": views, "likes": int(st.get("likeCount", 0) or 0),
        "comments": comments,
        "yt_kind": kind, "duration_s": duration_s,
        "vph": vph, "disc": disc,
        # Los tags siguen guardándose porque el filtro de exclusión los mira
        # (un video titulado con puro clickbait pero etiquetado 'Roblox' se
        # cae por el tag, no por el título — ver tags.item_text). Lo que ya
        # NO se hace es crear entidades a partir de ellos: son palabras SEO y
        # generaban temas basura (nombres de canal, "vlog", "official").
        # Ver tm/entities.py.
        "tags": (sn.get("tags") or [])[:15],
    }
    extra.update(extra_base or {})

    return {
        "id": _id("yt", v["id"]),
        "day": day, "source": source, "market": market["id"],
        "lang": sn.get("defaultAudioLanguage") or market["lang"],
        "title": sn.get("title", ""),
        "url": f"https://youtu.be/{v['id']}",
        "author": author or sn.get("channelTitle"),
        "published_at": published_at,
        "weight": _yt_weight(vph, disc, views),
        "extra": extra,
    }


def _videos_list(ids, api_key, part="snippet,statistics,contentDetails"):
    """videos.list en lotes de 50 IDs. 1 unidad de cuota por lote."""
    out = []
    for i in range(0, len(ids), 50):
        lote = ids[i:i + 50]
        try:
            data = _get("https://www.googleapis.com/youtube/v3/videos", params={
                "part": part, "id": ",".join(lote), "maxResults": 50, "key": api_key,
            }).json()
        except Exception as e:
            log.warning("videos.list (%d ids): %s", len(lote), e)
            continue
        out += data.get("items", [])
    return out


def youtube(market, day, cfg, api_key=None):
    if not api_key:
        log.info("youtube: sin YOUTUBE_API_KEY, se salta")
        return []
    short_max = cfg.get("short_max_seconds", 180)
    out = []
    for cat in cfg.get("categories", []):
        params = {
            "part": "snippet,statistics,contentDetails", "chart": "mostPopular",
            "regionCode": market["geo"], "maxResults": 50, "key": api_key,
        }
        if cat != "0":
            params["videoCategoryId"] = cat
        try:
            data = _get("https://www.googleapis.com/youtube/v3/videos", params=params).json()
        except Exception as e:
            log.warning("youtube %s/cat%s: %s", market["id"], cat, e)
            continue
        if not data.get("items"):
            log.info("youtube %s/cat%s: sin ranking en esta región", market["id"], cat)
            continue
        for v in data["items"]:
            it = _yt_item(v, market, day, "youtube", short_max,
                          extra_base={"category": cat})
            if it is not None:
                out.append(it)
    return out


# ─────────────────────────────────────────────────────────────
# Agencias de video viral (Newsflare, ViralHog, Caters, Jukin).
#
# Es la fuente que más se parece a lo que el monitor busca en video: clips
# noticiosos y virales reales, no contenido de creador. Ninguna expone RSS de
# su sitio, pero todas publican en YouTube, y el RSS de canal es gratis y sin
# cuota. De ahí salen los IDs; las estadísticas se piden con videos.list
# (1 unidad por lote de 50). Los videos pasan por las MISMAS reglas de
# admisión que el resto (tm/ytrules.py) y se muestran con chip propio.
# ─────────────────────────────────────────────────────────────
def agencias_video(market, day, cfg, api_key=None):
    canales = [c for c in cfg.get("canales", [])
               if c.get("enabled", True) and c.get("market", "US") == market["id"]]
    if not canales:
        return []

    # video_id -> nombre de la agencia que lo publicó
    agencia_de, orden = {}, []
    for canal in canales:
        url = ("https://www.youtube.com/feeds/videos.xml?channel_id="
               + canal["channel_id"])
        try:
            root = ET.fromstring(_get(url).content)
        except Exception as e:
            log.warning("agencias_video %s: %s", canal.get("name"), e)
            continue
        for entry in root:
            if _localname(entry.tag) != "entry":
                continue
            vid = _text(entry, "videoId")
            if vid and vid not in agencia_de:
                agencia_de[vid] = canal.get("name", "agencia")
                orden.append(vid)

    if not orden:
        return []
    if not api_key:
        # Sin key no hay duración ni estadísticas, así que no se puede
        # clasificar ni medir actividad. Se saltea entero en vez de meter
        # videos sin clasificar: una fuente de video que no pasa por las
        # reglas de admisión es justo lo que este ajuste vino a sacar.
        log.info("agencias_video: sin YOUTUBE_API_KEY, se salta (%d videos)", len(orden))
        return []

    short_max = cfg.get("short_max_seconds", 180)
    out = []
    for v in _videos_list(orden, api_key):
        agencia = agencia_de.get(v.get("id"), "agencia")
        it = _yt_item(v, market, day, "agencias_video", short_max,
                      author=agencia, extra_base={"agencia": agencia})
        if it is not None:
            out.append(it)
    log.info("agencias_video %s: %d videos de %d canales",
             market["id"], len(out), len(canales))
    return out


# ─────────────────────────────────────────────────────────────
# Reddit — el usuario común, no el medio. Frágil pero gratis.
# ─────────────────────────────────────────────────────────────
def reddit(market, day, cfg):
    out = []
    for sub in market.get("reddit", []):
        try:
            data = _get(f"https://www.reddit.com/r/{sub}/hot.json?limit=100").json()
        except Exception as e:
            log.warning("reddit r/%s: %s", sub, e)
            continue
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            if d.get("stickied"):
                continue
            score = int(d.get("score", 0) or 0)
            out.append({
                "id": _id("rd", d.get("id")),
                "day": day, "source": "reddit", "market": market["id"],
                "lang": market["lang"], "title": d.get("title", ""),
                "url": "https://reddit.com" + d.get("permalink", ""),
                "author": f"r/{sub}",
                "published_at": datetime.fromtimestamp(
                    d.get("created_utc", 0), tz=timezone.utc).isoformat(),
                "weight": _log_weight(score, divisor=2.5),
                "extra": {"score": score, "comments": d.get("num_comments", 0)},
            })
    return out


COLLECTORS = {
    "gtrends": gtrends,
    "gnews": gnews,
    "rss": rss,
    "youtube": youtube,
    "agencias_video": agencias_video,
    "reddit": reddit,
    "wikipedia": wikipedia,
}

# Fuentes que necesitan la API key de YouTube.
_NEEDS_YT_KEY = ("youtube", "agencias_video")


def collect(market, day, sources_cfg, secrets):
    """Corre todos los recolectores habilitados. Si uno se cae, el resto sigue —
    una fuente muerta no puede tumbar la pauta del día."""
    items, report = [], {}
    for name, fn in COLLECTORS.items():
        cfg = sources_cfg.get(name, {})
        if not cfg.get("enabled"):
            continue
        try:
            kw = ({"api_key": secrets.get("YOUTUBE_API_KEY")}
                  if name in _NEEDS_YT_KEY else {})
            got = fn(market, day, cfg, **kw)
            items += got
            report[name] = len(got)
        except Exception as e:
            log.error("fuente %s cayó en %s: %s", name, market["id"], e)
            report[name] = f"ERROR: {e}"
    return items, report
