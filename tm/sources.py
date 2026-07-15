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
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import requests

log = logging.getLogger("tm.sources")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"

session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept-Language": "es,en;q=0.8,fr;q=0.6"})


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
# YouTube — creadores y medios en video. Requiere YOUTUBE_API_KEY.
# chart=mostPopular cuesta 1 unidad de cuota. search cuesta 100.
# ─────────────────────────────────────────────────────────────
def youtube(market, day, cfg, api_key=None):
    if not api_key:
        log.info("youtube: sin YOUTUBE_API_KEY, se salta")
        return []
    out = []
    for cat in cfg.get("categories", ["0"]):
        params = {
            "part": "snippet,statistics", "chart": "mostPopular",
            "regionCode": market["geo"], "maxResults": 50, "key": api_key,
        }
        if cat != "0":
            params["videoCategoryId"] = cat
        try:
            data = _get("https://www.googleapis.com/youtube/v3/videos", params=params).json()
        except Exception as e:
            log.warning("youtube %s/cat%s: %s", market["id"], cat, e)
            continue
        for v in data.get("items", []):
            sn, st = v.get("snippet", {}), v.get("statistics", {})
            views = int(st.get("viewCount", 0) or 0)
            tags = sn.get("tags", []) or []
            out.append({
                "id": _id("yt", v["id"]),
                "day": day, "source": "youtube", "market": market["id"],
                "lang": sn.get("defaultAudioLanguage") or market["lang"],
                "title": sn.get("title", ""),
                "url": f"https://youtu.be/{v['id']}",
                "author": sn.get("channelTitle"),
                "published_at": sn.get("publishedAt"),
                "weight": _log_weight(views, divisor=2.0),
                "extra": {"views": views, "likes": int(st.get("likeCount", 0) or 0),
                          "category": cat, "tags": tags[:15]},
            })
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
    "reddit": reddit,
}


def collect(market, day, sources_cfg, secrets):
    """Corre todos los recolectores habilitados. Si uno se cae, el resto sigue —
    una fuente muerta no puede tumbar la pauta del día."""
    items, report = [], {}
    for name, fn in COLLECTORS.items():
        cfg = sources_cfg.get(name, {})
        if not cfg.get("enabled"):
            continue
        try:
            kw = {"api_key": secrets.get("YOUTUBE_API_KEY")} if name == "youtube" else {}
            got = fn(market, day, cfg, **kw)
            items += got
            report[name] = len(got)
        except Exception as e:
            log.error("fuente %s cayó en %s: %s", name, market["id"], e)
            report[name] = f"ERROR: {e}"
    return items, report
