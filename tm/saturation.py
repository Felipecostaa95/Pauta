"""Saturación: cuántos videos del tema ya se publicaron en las últimas horas.

Un PICO con 400 videos arriba no es una oportunidad, es una fila. Esto le
pregunta a YouTube cuántos resultados hay para el tema publicados en la
ventana reciente y lo muestra en la tarjeta como baja/media/alta.

Cuota: search.list cuesta 100 unidades por llamada (la recolección entera
gasta ~12). Por eso solo se mide para los PICO, con tope por mercado. Con
los defaults (5 por mercado, 3 mercados, 3 corridas/día) el peor caso son
4.500 unidades de las 10.000 diarias.
"""
import logging
from datetime import datetime, timedelta, timezone

import requests

log = logging.getLogger("tm.saturation")

URL = "https://www.googleapis.com/youtube/v3/search"


def run(conn, db, spikes, briefs, markets, cfg, api_key, top_per_market):
    """Devuelve [{market, entity_key, n_videos}] para los PICO medidos."""
    if not cfg.get("enabled"):
        return []
    if not api_key:
        log.info("saturation: sin YOUTUBE_API_KEY, se salta")
        return []

    hours = cfg.get("window_hours", 24)
    cap = cfg.get("max_per_market", 5)
    after = (datetime.now(timezone.utc) - timedelta(hours=hours)) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []

    for m in markets:
        rows = [r for r in spikes if r["market"] == m["id"]][:top_per_market]
        picos = [r for r in rows if r["status"] == "PICO"][:cap]
        for r in picos:
            brief = briefs.get((m["id"], r["entity_key"])) or {}
            query = brief.get("topic") or db.display_name(conn, r["entity_key"])
            try:
                data = requests.get(URL, params={
                    "part": "id", "q": query, "type": "video",
                    "publishedAfter": after, "maxResults": 1,
                    "regionCode": m["geo"], "relevanceLanguage": m["lang"],
                    "key": api_key,
                }, timeout=25).json()
            except Exception as e:
                log.warning("saturation %s/%s: %s", m["id"], query, e)
                continue
            if "error" in data:
                log.warning("saturation %s/%s: %s", m["id"], query,
                            data["error"].get("message"))
                continue
            # totalResults es una estimación de YouTube, no un conteo exacto.
            # Como señal de "ventana abierta vs fila" alcanza y sobra.
            n = int(data.get("pageInfo", {}).get("totalResults", 0))
            out.append({"market": m["id"], "entity_key": r["entity_key"],
                        "n_videos": n})
    return out
