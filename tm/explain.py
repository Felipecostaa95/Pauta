"""Capa editorial.

La estadística te dice QUÉ subió. No te dice POR QUÉ. Para eso agrupamos las
entidades que pican en temas y le pedimos a Claude que lea la evidencia y
explique el hecho que las disparó.

Regla dura del prompt: si los titulares no dicen por qué, la respuesta es
"no está claro". Un por-qué inventado es peor que un casillero vacío — tu
guionista lo va a creer.

Es opcional. Sin ANTHROPIC_API_KEY el pipeline corre igual y la pauta sale con
la evidencia cruda, que ya sirve.
"""
import json
import os
import re
import logging

log = logging.getLogger("tm.explain")

SYSTEM = """Sos el editor de la pauta matinal de una operación de video corto que \
publica en tres mercados (Estados Unidos/inglés, Francia/francés, México/español).

Cada mañana recibís los temas que la estadística detectó en alza, con la evidencia \
cruda que los disparó: titulares de medios, búsquedas de Google, videos de YouTube, \
posts de foros. Tu trabajo es que un guionista entienda en diez segundos qué pasó y \
si hay video adentro.

Reglas:
- El "por qué" sale SOLO de la evidencia que te doy. Si la evidencia no explica el \
hecho, escribí exactamente: "No está claro en la evidencia." No completes con lo que \
creas saber. Un por-qué inventado le arruina el guion a alguien.
- Varias entidades pueden ser el mismo tema (persona + lugar + evento). Agrupalas y \
devolvé una sola fila, listando todas sus claves.
- Ignorá entidades que sean ruido de scraping, nombres de sección o basura de tags.
- El ángulo es para video vertical de ~90 segundos, no para una nota escrita. Si el \
tema no da para video, decilo: "sin video".
- Escribí en español rioplatense neutro, seco, sin adjetivos de relleno.

Devolvé SOLO un array JSON, sin markdown ni texto alrededor:
[{"keys": ["clave1","clave2"], "topic": "Nombre del tema, 2-6 palabras",
  "why": "El hecho concreto, 1-2 frases", "angle": "El ángulo de video, 1 frase",
  "durability": "horas" | "dias" | "semanas"}]"""


def _payload(rows, conn, db, day):
    lines = []
    for r in rows:
        ev = db.evidence(conn, r["entity_key"], r["market"], day, limit=5)
        titles = [f"      - [{e['source']}] {e['title']}" for e in ev]
        lines.append(
            f"  clave: {r['entity_key']}\n"
            f"    nombre: {db.display_name(conn, r['entity_key'])}\n"
            f"    estado: {r['status']}  z={r['z']:.1f}  "
            f"volumen={r['volume']:.1f} (base {r['baseline']:.1f})\n"
            f"    evidencia:\n" + "\n".join(titles)
        )
    return "\n".join(lines)


def _parse(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    log.warning("respuesta no parseable del modelo")
    return []


def run(conn, db, day, spikes, cfg, markets):
    if not cfg.get("enabled"):
        return []
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.info("explain: sin ANTHROPIC_API_KEY, la pauta sale sin el 'por qué'")
        return []
    try:
        import anthropic
    except ImportError:
        log.warning("explain: falta `pip install anthropic`")
        return []

    client = anthropic.Anthropic(api_key=api_key)
    names = {m["id"]: m["name"] for m in markets}
    briefs = []

    for mkt in {r["market"] for r in spikes}:
        rows = [r for r in spikes if r["market"] == mkt][:cfg.get("max_topics_per_market", 8)]
        if not rows:
            continue
        prompt = (f"Mercado: {names.get(mkt, mkt)} ({mkt}) — {day}\n\n"
                  f"Temas en alza detectados:\n\n{_payload(rows, conn, db, day)}")
        try:
            # Ojo: los modelos de la generación Sonnet 5 / Opus 4.7+ rechazan
            # temperature con un 400. No lo mandes.
            resp = client.messages.create(
                model=cfg.get("model", "claude-sonnet-5"),
                max_tokens=2000,
                system=SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in resp.content if b.type == "text")
        except Exception as e:
            log.error("explain %s: %s", mkt, e)
            continue

        valid = {r["entity_key"] for r in rows}
        for t in _parse(text):
            for k in t.get("keys", []):
                if k in valid:
                    briefs.append({
                        "market": mkt, "entity_key": k, "topic": t.get("topic"),
                        "why": t.get("why"), "angle": t.get("angle"),
                        "durability": t.get("durability"),
                    })
    return briefs
