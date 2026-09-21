# Paquete: fuentes nuevas + filtros afinados + horario 7 am

Objetivo del usuario: acercar la pauta a "lo más viral de internet" en sus
categorías (celebridades, animales, parejas, personas, rescates, arrestos,
virales de niños, bodas virales) y sacar lo que no sirve (youtubers, gameplays,
videos hechos con IA, guerra).

Hacé los pasos EN ORDEN. Verificá todo antes de pushear.

---

## Paso 0 — Tamaño de data/pauta.db (primero, antes que nada)

La última vez `data/pauta.db` pesaba ~104,8 MB y GitHub rechazaba el push de la
pauta diaria (límite 100 MB). Revisá si sigue así:

- Si ya está resuelto (base bajo ~80 MB y la pauta diaria viene quedando en
  verde), seguí al Paso 1.
- Si NO está resuelto: implementá la poda de la base. Mantené solo items de los
  últimos 60 días (la detección usa 28 días; el resto es margen). Los reportes
  HTML ya quedan archivados aparte, no se tocan. Agregá la poda como paso
  automático al final de run.py para que no vuelva a crecer. Antes de borrar
  nada, mostrame el tamaño actual y el estimado después de podar, y esperá mi
  confirmación.

Esto es importante porque este paquete suma fuentes y la base va a crecer más
rápido.

---

## Paso 1 — Horario: pauta diaria a las 7:00 hora de Chile

En `.github/workflows/pauta.yml`, cambiá el cron a:

```yaml
- cron: "0 10 * * *"   # 7:00 Chile en horario de verano (UTC-3)
```

Dejá un comentario y una nota en el README: cuando Chile vuelva al horario
normal (UTC-4, ~abril), hay que cambiarlo a `"0 11 * * *"` para mantener las
7:00. Una sola línea de cron, sin chequeos de hora extra (ya aprendimos que
esos chequeos bloquean corridas).

No toques el cron del monitor de última hora (sigue cada 15 min).

---

## Paso 2 — Fuentes nuevas

### 2a. Wikipedia: artículos más vistos (nuevo colector)

API oficial de Wikimedia, gratis, sin clave:

- Por país: `https://wikimedia.org/api/rest_v1/metrics/pageviews/top-per-country/{CC}/all-access/{YYYY}/{MM}/{DD}`
- Requiere un User-Agent descriptivo con contacto (ej.
  `pauta-upsomedia/1.0 (contacto: <email del repo>)`), si no, rechaza.
- Usá el día de AYER (UTC). Si todavía no está publicado, probá el día anterior.
- Mercados: US, FR, MX (códigos de país).
- Descartá páginas que no son artículos: Main_Page, "-", y títulos que empiecen
  con Special:, Wikipedia:, File:, Portal:, Help:, Template:, Category:, Talk:,
  User:, y sus equivalentes en español/francés (Especial:, Spécial:, Archivo:,
  Fichier:, etc.).
- El título del artículo ES la entidad (como el query de Google Trends):
  reemplazá "_" por espacios y marcalo `is_query: True`.
- Peso: usá `_log_weight(views)` como YouTube.
- Solo para la pauta diaria (run.py). NO en el monitor de 15 min: Wikipedia
  publica con horas de retraso, no sirve para rupturas.

Este es el colector más valioso del paquete: cuando alguien famoso muere, es
arrestado o protagoniza un escándalo, su página de Wikipedia se dispara.

### 2b. YouTube: cambiar las categorías

Los youtubers y gameplays entran sobre todo por Entretenimiento (24) y
Ciencia/Tecnología (28). Reemplazá las categorías por las que calzan con el
contenido buscado:

```yaml
categories: ["10", "15", "17", "22", "23"]
# 10 = Música (celebridades)
# 15 = Mascotas y animales (rescates, animales virales)
# 17 = Deportes (golazos, knockouts, momentos virales)
# 22 = Gente y blogs (virales de personas, parejas, niños)
# 23 = Comedia
```

Nada de "0" (todas), nada de "20" (Gaming), nada de "24" ni "28".

Probá cada categoría en cada región (US, FR, MX). Algunas categorías no tienen
ranking en todas las regiones y la API devuelve error o vacío: en ese caso,
logueá un aviso y seguí con las demás, sin romper la corrida.

Extra de seguridad: cada video trae su `snippet.categoryId`. Descartá cualquier
video cuyo categoryId sea 20 (Gaming), sin importar por qué lista entró.

### 2c. Medios de virales (RSS)

Buscá la URL real del feed de cada uno y verificala con:
`curl -s -o /dev/null -w "%{http_code}\n" -A "Mozilla/5.0" "URL"`

Solo agregá los que respondan 200 con XML/RSS real. Todos van con market: US
(audiencia en inglés).

- Bored Panda (animales, personas, parejas, bodas raras)
- UNILAD (virales, rescates, policiales)
- LADbible (virales, rescates, policiales)
- Daily Dot (cultura de internet, virales de TikTok)
- Know Your Meme (memes y virales)
- The Dodo, si no quedó agregado en el paquete anterior

Deportes (mismo proceso de verificación, con el mercado indicado):
- ESPN (US)
- MMA Fighting o MMA Junkie (US) — deportes de contacto
- Récord (MX)
- L'Équipe (FR)

Decime cuáles entraron y cuáles no (con el código de error).

---

## Paso 3 — Filtros y categorías destacadas

### 3a. Filtrar por nota individual, no por tema completo

Si esto no se hizo en el ajuste anterior, hacelo ahora. Hoy, si un tema agrupa
5 notas y 1 sola tiene un término excluido, se descarta el tema entero. Eso
causó falsos positivos como "tareas", "trucos para estudiar" y "colegio"
descartados como gaming, "infinity war" (la película) y "Biden/Obama" como
conflicto.

Lógica nueva: descartar solo las notas/videos que matchean. Si después de eso
el tema se queda sin evidencia, recién ahí descartar el tema.

### 3b. Nueva exclusión: videos hechos con IA

```yaml
excluir:
  contenido_ia:
    scope: todo
    terms: [ai generated, ai-generated, made with ai, ai video, ai art,
            generado con ia, hecho con ia, creado con ia, video ia,
            généré par ia, sora, midjourney, deepfake, #aiart, #aivideo]
```

No uses "AI" ni "IA" sueltos: aparecen en noticias normales y en otras
palabras. Match de palabra completa.

### 3c. Reforzar la exclusión de gaming y youtubers

Agregá a los términos de gaming: gameplay, let's play, walkthrough, speedrun,
minecraft, roblox, fortnite, gta, "probé" solo si va junto a un término de
juego. Mantené el cuidado con términos ambiguos (steam, switch, console).

### 3d. Categorías destacadas (badge + boost x1.3, no acumulable)

Mantener las que ya existen (celebridades, rescate, policial, viral_ninos,
boda_viral con match combinado). Agregar:

```yaml
    animales: [dog, puppy, cat, kitten, perro, perrito, gato, gatito,
               chien, chiot, chaton, animal, animals, wildlife]
    parejas: [couple, pareja, novios, boyfriend, girlfriend, novio, novia,
              proposal, propuesta de matrimonio, demande en mariage, couple goals]
```

No incluyas "chat" (en francés es gato pero también es chat) ni otros términos
ambiguos. Si el tema matchea varias categorías, el boost se aplica una sola vez.

### 3e. Deportes virales (⚽ badge + boost)

El usuario quiere videos de deporte VIRALES: desde fútbol hasta deportes de
contacto y peleas callejeras. Igual que con las bodas, "fútbol" a secas trae
mucho ruido (resultados, fichajes, tablas de posiciones) que no es lo que se
busca. Lo viral es el momento: el golazo, el knockout, la pelea, el error
insólito.

Por eso usa match combinado, con una excepción:

```yaml
  deporte_viral:
    # Se activa si matchea un término de deporte Y uno de gancho:
    grupo_deporte: [fútbol, futbol, football, soccer, foot, gol, goal, but,
                    nba, nfl, boxeo, boxing, boxe, ufc, mma, kickboxing,
                    lucha, wrestling, rugby, tenis, tennis, béisbol, baseball]
    grupo_gancho: [viral, golazo, knockout, ko, nocaut, brutal, insane,
                   increíble, incroyable, épico, epic, fail, blooper,
                   pelea, fight, brawl, bagarre, trifulca, bronca,
                   se vuelve viral, goes viral, record, récord]
    # EXCEPCIÓN: estos términos activan la categoría SOLOS, sin necesitar
    # un término de deporte (son virales por definición):
    solos: [pelea callejera, street fight, bagarre de rue, knockout viral,
            riña callejera, pelea en la calle]
```

Documentá en un comentario que esta categoría tiene match combinado + lista de
términos que activan solos.

⚠️ Conflicto con el filtro de guerra: revisá que ningún término de la lista de
conflicto descarte deportes por error. Por ejemplo "offensive" aparece en
fútbol americano ("offensive line") y "ofensiva" en crónicas deportivas. Si un
tema matchea deporte_viral, no lo excluyas por un término de conflicto
ambiguo. Mostrame en la verificación final si algún tema deportivo cayó en la
exclusión de conflicto.

La exclusión de guerra se mantiene como está: fuera de la pauta diaria, activa
en el monitor de 15 min.

---

## Al terminar

1. Corré `run.py --report-only` contra una copia de la base real y mostrame:
   - la lista de temas excluidos por categoría (para revisar falsos positivos)
   - cuántos temas entraron por Wikipedia y ejemplos
   - qué categorías de YouTube funcionaron en cada región
2. Commit + push, y dispará los dos workflows a mano. Tienen que quedar los dos
   en verde. Tenés mi permiso para el gasto de API de esta validación.
3. Actualizá el README: fuentes nuevas, categorías de YouTube, exclusiones,
   categorías destacadas y la nota del horario de abril.
