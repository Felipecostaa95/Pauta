# Pauta

Monitor diario de tendencias. Cada mañana recolecta noticias, búsquedas, video y
foros en tres mercados, detecta qué se salió de su ruido de fondo, y escupe una
pauta en HTML con el porqué y un ángulo de video.

```bash
python run.py
open reports/index.html
```

---

## Lo primero: esto no sirve el día 1

Un pico se define contra un baseline. Sin historia no hay baseline y no hay
detección. La primera corrida va a decir "nada perforó el umbral" y va a estar
en lo correcto.

| Corriendo hace | Qué esperar |
|---|---|
| 1–4 días | Nada. Solo acumula. |
| 5–13 días | Detecta lo obvio, con falsos positivos. |
| 14–27 días | Ya sirve. |
| 28+ días | Ventana completa, con estacionalidad semanal. |

Si querés ver cómo se ve funcionando sin esperar un mes:

```bash
python tools/simular.py   # 30 días sintéticos con picos plantados
```

Ese script además es el banco de pruebas: si tocás los umbrales, corrélo y
verificá que siga cazando los picos y sigan sin colarse los señuelos.

---

## Cobertura real

Esto es lo que más importa que sepas antes de confiar en la pauta.

| Fuente | Qué te da | Estado |
|---|---|---|
| **Google Trends** | Qué busca la gente, por país, con volumen | Sólido, gratis, sin key |
| **Google News** | Miles de medios y agencias agregados | Sólido, gratis, sin key |
| **RSS directo** | Los medios que vos elijas, sin filtro de Google | Sólido, gratis |
| **YouTube** | Corrobora temas de otras fuentes y aporta shorts noticiosos (no genera temas por sí solo) | Sólido, gratis con key |
| **Agencias de video viral** | Newsflare, ViralHog, Caters, Jukin vía el RSS de su canal de YouTube | Sólido, gratis (RSS sin cuota) |
| **Wikipedia** | Artículos más vistos por país (pageviews) | Sólido, gratis, sin key — solo pauta diaria |
| **Reddit** | Usuario común, no el medio | **Desactivado permanentemente** — bloqueado, confirmado dos veces (ver nota abajo) |
| **TikTok** | — | **No cubierto** |
| **Instagram** | — | **No cubierto** |
| **X (Twitter)** | — | **No cubierto** |

> **Reddit se probó dos veces y falló las dos.** Primero desde la Mac de Felipe
> (403 con `curl` directo, dos técnicas distintas: User-Agent identificado y
> endpoint `old.reddit.com`). Después, una vez migrado a GitHub Actions, se
> reintentó asumiendo que la IP de los servidores de GitHub podría no estar
> bloqueada — también dio 403 en los tres mercados. Esto sugiere que Reddit
> bloquea rangos completos de datacenters conocidos (no solo IPs residenciales
> puntuales), así que no hay una tercera variante obvia que valga la pena
> intentar sin pagar un proxy residencial — desproporcionado para una sola
> fuente de cinco. Se da por cerrado.

> **Wikipedia (pageviews) es el colector más valioso del paquete de
> septiembre 2026.** Usa el endpoint público `top-per-country` de Wikimedia
> (gratis, sin key, pero exige un User-Agent con contacto) para ver qué
> artículos se dispararon ayer en US/FR/MX. Cuando alguien famoso muere, es
> arrestado o protagoniza un escándalo, su página de Wikipedia se dispara — es
> una señal muy fuerte que ninguna otra fuente cubre igual. Solo corre en la
> pauta diaria (`run.py`), nunca en el monitor de 15 min: Wikimedia publica
> los pageviews con horas de retraso, así que no sirve para rupturas. Límite
> conocido: `top-per-country` trae también páginas de otros idiomas que no
> son US/FR/MX (japonés, polaco, etc.); el filtro de no-artículos cubre
> inglés/español/francés, así que ocasionalmente se cuela alguna página en
> otro idioma como ruido menor.

### El hueco de TikTok e Instagram

No hay API pública de tendencias para ninguno de los dos, y no es un detalle de
implementación que se pueda resolver escribiendo más código:

- **TikTok**: el Creative Center tiene los datos (hashtags, sonidos, videos, por
  país) y es gratis, pero es una web para mirar a mano. La Research API es solo
  para uso académico. Scrapear el backend del Creative Center funciona pero se
  rompe seguido y va contra sus términos.
- **Instagram**: la Graph API te da tus propias cuentas y nada más. Tendencias de
  Reels no se exponen. Punto.

### El hueco de X (Twitter)

Distinto a TikTok/Instagram: acá **sí existe** una API funcional para leer datos,
pero desde febrero de 2026 X eliminó el nivel gratuito por completo y pasó a cobrar
por uso (~USD 0.005 por tweet leído desde la API oficial, o ~USD 0.15 por cada
1.000 tweets vía proveedores terceros más baratos). Para un monitoreo diario en
tres mercados, esto rondaría los USD 10-30/mes con un proveedor tercero, o mucho
más con la API oficial.

Decisión: **no se incluyó**, a propósito. El resto del sistema es 100% gratuito
y esa era una condición de diseño desde el principio — no vale la pena romperla
por una sola fuente cuando ya tenés prensa, búsquedas y YouTube cubriendo la
mayoría de lo importante. Si en el futuro cambia esa decisión, el mecanismo para
agregarla es el mismo que cualquier otra fuente nueva (ver sección "Agregar una
fuente" más abajo) — técnicamente no es difícil, es una decisión de costo, no
de capacidad.

Tres caminos, elegí con los ojos abiertos:

1. **A mano.** 10 minutos al día en el Creative Center filtrando por US/FR/MX y
   por "Rising" (no "Popular" — cuando está en Popular ya llegaste tarde). Es lo
   que hace la mayoría y no es tan malo.
2. **Pagar un scraper.** Actores de Apify para Creative Center, ~USD 20–50/mes
   según volumen. Se meten en `tm/sources.py` como un colector más: devolvés
   items con el mismo formato y el resto del pipeline no se entera.
3. **Aceptar el hueco.** Búsquedas + prensa + YouTube ya te anticipan la mayoría
   de los temas que después explotan en TikTok, con horas de ventaja. TikTok es
   casi siempre reactivo a algo que pasó en otro lado primero.

---

## Instalación

```bash
cd tendencias
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # y pegá las keys
```

**YouTube API key** (gratis, 5 minutos): console.cloud.google.com → nuevo
proyecto → habilitar "YouTube Data API v3" → Credenciales → API key. Cuota de
10.000 unidades/día; esto gasta ~12. Sin la key, todo lo demás corre igual.

**ANTHROPIC_API_KEY** (opcional): sin esto la pauta sale con la evidencia cruda
pero sin la columna del "por qué". Cuesta centavos por día.

**spaCy** (opcional, recomendado): mejora bastante la extracción de entidades.

```bash
pip install spacy
python -m spacy download es_core_news_sm
python -m spacy download en_core_web_sm
python -m spacy download fr_core_news_sm
```

Sin spaCy cae a una heurística de mayúsculas + n-gramas que anda razonable en
titulares, pero confunde más.

### Que corra solo cada mañana

```bash
crontab -e
# 7:15 todos los días
15 7 * * * cd /ruta/a/tendencias && .venv/bin/python run.py >> data/cron.log 2>&1
```

En una Mac que duerme, `cron` se saltea la corrida. Si te importa que no se
pierdan días, usá `launchd` con `StartCalendarInterval`, que sí dispara al
despertar.

---

## Dos sistemas, dos velocidades

Este proyecto corre **dos** monitores distintos, con lógicas distintas, que no
se pisan:

**1. Pauta diaria (`run.py`) — tendencias.** Corre 2 veces al día, 7:00 y
13:00 Chile. Responde a "¿de qué se habla más que lo normal ESTA SEMANA?".
Compara contra un baseline de 28 días. Es contenido de guion: temas que vienen
creciendo y dan para producir video. Workflow: `.github/workflows/pauta.yml`.

> **Arranque temprano + espera, para blindarse de los atrasos de GitHub:**
> GitHub puede atrasar un cron programado varias horas (le pasó, hasta ~4h) o
> saltárselo directamente, y el minuto `:00` es el momento más congestionado.
> Por eso `pauta.yml` ya no dispara "a las 7:00 UTC-lo-que-sea": dispara horas
> antes (minuto `:07`, dos triggers por turno — principal y respaldo) y el
> job, ya corriendo, **duerme hasta la hora objetivo calculada en hora de
> Chile** (`TZ='America/Santiago'`, así el horario de verano/invierno se
> maneja solo, sin tocar nada dos veces al año). Si GitHub lo atrasó, la
> espera absorbe el atraso. Si la espera ya pasó (atraso enorme), arranca de
> inmediato — nunca se salta un turno por estar tarde. Lo que **nunca** hace
> es arrancar antes de hora: con los triggers actuales la espera real máxima
> es ~4h53 (invierno, turno principal), siempre por debajo de un tope de
> seguridad de 300 min; si ese tope se activara igual (no debería, en
> operación normal), la corrida corta sin hacer nada y deja el turno a la de
> respaldo, que dispara ~1h después con una espera bien más corta. Cada turno
> deja un marcador (`data/turnos/AAAA-MM-DD-07.done` / `-13.done`) para que la
> corrida de respaldo no repita el trabajo si la principal ya lo hizo. Ver los
> comentarios en `pauta.yml` para el detalle completo.

**2. Monitor de última hora (`breaking_run.py`) — rupturas.** Responde a
"¿algo apareció de la nada en los últimos MINUTOS?". No compara contra 28
días — compara contra su propia corrida anterior (hace 15 min). Si un tema
salta de "casi nadie lo cubre" a "5+ fuentes distintas lo cubren AL MISMO
TIEMPO", eso es una ruptura (una muerte, un escándalo, algo que rompió), y
aparece en la banda "⚡ Última hora" arriba del reporte, sin esperar a la
pauta del día siguiente. Workflow: `.github/workflows/breaking.yml`.

> **Modo continuo en horario útil:** el "cada 15 min" de un cron de GitHub no
> es confiable (en la práctica corría cada 2-5 horas). Por eso, en horario
> útil (7:00 a 00:00 Chile), UNA corrida hace un loop interno: corre
> `breaking_run.py`, commitea, dispara el deploy a Pages, duerme 15 min y
> repite — sin depender de que GitHub relance el cron a tiempo. El loop corta
> a las ~5h30 de iniciado o al llegar las 00:00 Chile, lo que pase primero; un
> cron cada 30 min (`7,37 * * * *`) reinicia el loop si por algún motivo no
> quedó uno activo. Fuera de horario útil, una sola pasada y listo (como
> antes). El deploy a Pages se hace disparando un workflow liviano aparte
> (`deploy.yml`) con `gh workflow run`, porque el job de Pages no se puede
> invocar desde dentro del loop de bash. Ver los comentarios en `breaking.yml`
> y `deploy.yml`.

Por qué separados: una tendencia necesita historia para medirse; una ruptura
necesita 0 historia (si se murió alguien hace 20 min, comparar contra las
últimas 4 semanas es inútil). Meterlos en el mismo motor arruinaría a los dos.
El monitor de rupturas es liviano a propósito (solo Google News + Trends, sin
YouTube ni spaCy), así que correrlo 96 veces al día no cuesta casi nada — y en
un repo público, los minutos de GitHub Actions son gratis e ilimitados.

El monitor **no usa lista de palabras clave** ("murió", "arrestado"...). Esas
listas siempre se quedan cortas justo con lo que no anticipaste. La señal es la
velocidad de aparición multi-fuente, sea cual sea el tema.

**Arranque en frío:** la primera corrida del monitor no alerta nada — solo
siembra el estado base. Recién desde la segunda vuelta puede comparar y
detectar rupturas. Igual que la pauta diaria necesita días para calibrar, el
monitor necesita al menos una vuelta previa.

## Cómo funciona

```
recolectar → extraer entidades → agregar por día → detectar picos → explicar → pauta
  sources.py     entities.py         db.py            spike.py     explain.py  report.py
```

**Por qué entidades y no clustering.** Para saber si un tema picó hoy hay que
compararlo con el mismo tema ayer. Si reagrupás los titulares con clustering
cada día, los IDs de cluster no son estables entre días y no existe serie
temporal. Las entidades normalizadas sí son claves estables. El clustering (vía
Claude) viene después, solo para redactar.

**Por qué mediana y no promedio.** El pico de la semana pasada infla el promedio
y sube la vara: el sistema se vuelve ciego justo con los temas que más te
importan. La mediana lo ignora. El z se calcula como `(hoy − mediana) / (1.4826 ×
MAD)`.

**Por qué el baseline mira el día de semana.** El volumen de prensa se desploma
sábado y domingo. Sin corregir, todos los lunes parecen un pico.

**Cada nota se cuenta una sola vez**, el día que aparece. La serie mide *llegada
de información nueva*, que es lo que detecta algo reventando hoy — no cuánta
gente sigue hablando de algo viejo.

### Los cuatro estados

| | Significa | Qué hacer |
|---|---|---|
| `PICO` | Perforó su ruido y sigue subiendo | Producir hoy |
| `TECHO` | Perforó pero ya baja | Llegaste tarde, evaluá |
| `NUEVO` | Sin historia suficiente para juzgar | Mirar a ojo |
| `OBSERVAR` | Se mueve, no explota | Dejar en el radar |

---

## Categorías destacadas y exclusiones

Todo esto vive en `config.yaml` (`excluir`, `categorias_destacadas`) y en
`tm/tags.py`, que hace el matching de términos una sola vez y lo comparten
`run.py`/`breaking.py` (para descartar), `spike.py` (para el boost) y
`report.py` (para pintar el badge) — así nunca divergen.

**Exclusión dura, no down-weight.** Gaming, conflicto bélico y contenido hecho
con IA no bajan de posición: se **descartan** antes de entrar a la pauta. Un
factor multiplicador nunca llega a cero (el tema siempre sobrevive con score
bajo); para sacarlos de verdad hace falta un filtro que los descarte. El
filtro corre **por nota individual, no por tema completo**: si un tema agrupa
5 notas y 1 sola matchea un término excluido, se descarta esa nota — las otras
4 siguen armando el tema igual, con menos volumen. El tema entero desaparece
solo si se queda sin ninguna nota limpia (ver `tags.filter_excluded_items`).

- **`gaming`** (`scope: todo`): aplica en la pauta diaria Y en el monitor de
  15 min. Incluye términos directos (fortnite, minecraft, roblox, twitch,
  gameplay, walkthrough, "let's play"...) y un match por **combinación** para
  "probé": esa palabra sola es de uso corriente ("probé la receta"), así que
  solo cuenta si aparece junto a un término de juego en el mismo texto (ver
  `excluir.gaming.combo` y `tags.excluded_categories`).
- **`conflicto`** (`scope: solo_pauta_diaria`): **solo se aplica en la pauta
  diaria**. El monitor de última hora (`breaking_run.py`) nunca la descarta a
  propósito — si estalla una guerra grande, el usuario quiere enterarse en
  tiempo real aunque no la quiera en el contenido de guion del día siguiente.
- **`contenido_ia`** (`scope: todo`, nuevo): videos/notas que se anuncian como
  hechos con IA (ai generated, sora, midjourney, deepfake, #aiart...). Sin
  "AI"/"IA" sueltos — aparecen en palabras y noticias normales.
- **`bailes`** (`scope: todo`, nuevo): retos de baile y coreografías. Son
  nicho, no pico noticioso. Sin "dance" suelto, por ambiguo.

Los términos ambiguos (steam, switch, console, army, invasion...) se dejan
afuera a propósito: mejor perder algún caso límite que descartar contenido
bueno por error. La línea "Filtrados de esta pauta" al pie de cada reporte
muestra cuántos temas se descartó por cada categoría, para que el filtro no
sea una caja negra. Esa misma línea trae después una segunda frase con las
reglas de admisión del video (cuántos videoclips, videos largos sin corroborar
y shorts sin señal viral quedaron afuera). Son dos cuentas distintas y van
separadas a propósito: `excluir` descarta **temas** (un tema se va cuando
ninguna de sus notas sobrevive) y las reglas del video descartan **videos**
sueltos.

**Categorías destacadas: badge + boost moderado.** Celebridades, rescates,
detenciones/policiales, virales de niños, **animales** (🐶), **parejas** (💑)
y **deporte viral** (⚽, nuevo) se marcan con un chip visible y suben ×1.3 en
el score (una sola vez, aunque matcheen varias categorías a la vez — no se
acumula). La evidencia contra la que se matchea ya pasó por `excluir`, así
que un tema con una nota de gaming entre varias no pierde el boost por eso.

**Bodas virales (💍) y deporte viral (⚽) son la excepción con match
combinado.** "Boda"/"wedding" y "fútbol"/"football" solos traen demasiado
ruido (bodas de famosos, moda, consejos / resultados, fichajes, tablas de
posiciones). El tag y el boost se activan únicamente si el tema matchea un
término del grupo principal (`grupo_boda`, `grupo_deporte`) **Y además** uno
de `grupo_gancho` (viral, fail, caos, drama / golazo, knockout, pelea...). Una
boda sin gancho viral, o un partido sin momento viral, no se marcan.
`deporte_viral` suma una tercera lista, `solos`: términos que son virales por
definición ("pelea callejera", "street fight") y activan la categoría sin
necesitar además un término de deporte. `tags.matched_tags()` trata cualquier
categoría escrita como dict (en vez de lista simple) en `config.yaml` como
match combinado — mismo mecanismo genérico para las dos.

**Guard deporte_viral ↔ conflicto.** "Offensive"/"ofensiva" aparece tanto en
crónicas de guerra como en fútbol americano ("offensive line") y crónicas
deportivas. Si un tema ya matchea `deporte_viral`, no se excluye por
`conflicto` aunque comparta ese vocabulario (`tags.excluded_categories()`,
parámetro `categorias_cfg`). Esto NO blanquea cualquier texto con una palabra
de deporte: sigue haciendo falta el combo completo (deporte + gancho, o un
término de `solos`), así que una crónica deportiva común sin gancho viral que
además matchee `conflicto` sigue excluida — la pauta lo reporta en la
verificación final para poder ajustar a mano si hace falta.
Ojo con términos de deporte que también son palabras comunes en otro idioma:
el paquete original proponía "foot"/"goal"/"but" (fútbol/gol en francés) en
`grupo_deporte`, pero son palabras corrientes del inglés (pie, objetivo, la
conjunción "pero") y colaban titulares de guerra reales como deporte_viral en
combinación con un gancho ambiguo como "brutal" — se sacaron del listado.
`box`/`ring` sí quedaron adentro pese a tener el mismo problema ("black box"
de un avión, "ring" como cerco militar) — decisión explícita del usuario
(2026-09-21) para rescatar videos de boxeo tipo "Box Azteca"/"GUERRA EN EL
RING" que si no quedaban excluidos por `conflicto` sin que nada los
rescatara. Riesgo conocido y aceptado, no un descuido: ver el comentario
sobre `deporte_viral` en `config.yaml` para el caso de prueba concreto.

**Nota honesta sobre virales de niños y bodas virales:** este contenido vive
sobre todo en TikTok/Instagram, que el sistema no cubre gratis (ver el hueco
más arriba). La prensa a veces lo recoge, pero solo después de que ya explotó
viralmente, así que estas dos categorías van a capturar bastante menos que
"celebridades" o "policial" hasta que (si alguna vez) se sume una fuente de
video social paga. Es una limitación de la fuente, no del tag.

### El rol de YouTube: corroborar, no generar temas

Esto es lo más importante que cambió en la fuente de video, y conviene tenerlo
claro antes de leer una pauta.

`chart=mostPopular` mide **audiencia** (lo más visto). Este monitor busca
**picos de actividad y discusión**. No son lo mismo, y mientras YouTube generó
temas por sí solo la pauta se llenó de videoclips y vlogs: eran efectivamente
lo más visto del día, pero no había pasado nada. Hoy el video cumple dos roles
y ninguno más:

1. **Corroborar** temas que ya están picando en prensa, búsquedas o Wikipedia.
2. **Aportar shorts virales noticiosos** que pasen filtros estrictos.

**Qué se recolecta.** `youtube.categories` es `["15","17","25"]` (Mascotas y
animales, Deportes, Noticias y política). Se sacaron la `"10"` (Música =
videoclips), la `"22"` (Gente y blogs = vlogs) y la `"23"` (Comedia = sketches
de youtubers). Sigue sin `"0"` (todas, por donde se colaba gaming aunque no
estuviera listada la `"20"`). Seguridad extra: se descarta cualquier video
cuyo `snippet.categoryId` **real** sea `"20"` (Gaming) o `"10"` (Música), sin
importar por qué categoría entró. Cada categoría se prueba en cada región
(US/FR/MX) por separado: si una no tiene ranking en una región la API devuelve
vacío, se loguea un aviso y la corrida sigue con las demás.

**Cómo se clasifica cada video** (`tm/sources.py`, se pide `contentDetails`
además de `snippet,statistics` — mismo costo de cuota):

- **videoclip**: categoría 10, canal terminado en `VEVO` o ` - Topic`, o
  título con "Official Video", "Lyric Video", "Video Oficial", etc.
- **short**: dura 3 minutos o menos (`youtube.short_max_seconds`).
- **largo**: más de 3 minutos, o duración desconocida (vivos y estrenos traen
  `P0D`, que es "no sé cuánto dura", no "dura cero").

**Reglas de admisión** (`tm/ytrules.py`), por video y no por tema:

| Tipo | Entra si |
|---|---|
| Videoclip | **Nunca.** Si el artista está en tendencia, el tema entra por la noticia y la fila muestra esas notas, no el clip |
| Largo | El tema está corroborado hoy por una fuente que **no** es video (gnews, rss, gtrends, wikipedia) |
| Short | Está corroborado **o** tiene señal viral fuerte **y** matchea una categoría destacada noticiosa |

Consecuencia deliberada: un tema cuya única evidencia del día es video sin
corroborar se queda sin evidencia y desaparece solo de la pauta.

**Peso por actividad, no por vistas acumuladas.** El peso de un video ya no
sale de sus views totales (un videoclip con 40M enterraba a 40 notas de
agencia) sino de dos señales: **velocidad** (vistas por hora desde
`publishedAt`, con piso de 1 hora) y **discusión** (comentarios sobre vistas,
acotada a un factor `[0.8, 1.4]` — modula, no decide).

**"Señal viral fuerte"** = el short está en el cuartil superior de velocidad
**y** de discusión entre los shorts del mismo día, mismo mercado y **misma
fuente**. Lo de la fuente se midió con datos reales: en US los shorts de
`mostPopular` cortan en ~37.000 vistas/hora y los de las agencias de video
viral en ~126. En un solo pool ningún clip de agencia pasaría nunca, y es la
fuente más parecida a lo que la pauta busca. Con menos de 4 shorts en un grupo
no se calcula cuartil y ninguno entra por esta vía (los corroborados sí).

**Los tags de YouTube ya no crean entidades.** Son palabras SEO (nombres de
canal, "vlog", "official", "viral 2026") y cada video metía hasta 15 temas
basura. Las entidades de un video salen solo del título. Los tags **se siguen
guardando y se siguen usando para excluir**: un video clickbait etiquetado
`Roblox` se cae por el tag, no por el título.

### Agencias de video viral (estilo Newsflare)

Newsflare, ViralHog y compañía no exponen RSS de su sitio, pero sí publican en
YouTube, y el RSS de canal es gratis y sin cuota:
`https://www.youtube.com/feeds/videos.xml?channel_id=<ID>`. De ahí salen los
IDs; las estadísticas se piden con `videos.list` en lotes de 50 IDs (1 unidad
de cuota por lote). Estos videos pasan por las **mismas** reglas de admisión y
se muestran con chip propio ("video viral") en el reporte.

Activos: **Newsflare**, **ViralHog**, **Caters Clips**, **Jukin Media**.
Verificados y **desactivados** por contenido, no por feed roto (los dos
responden 200):

- **Storyful**: su canal de YouTube es marketing B2B, no clips ("How does
  AI-generated video show up during breaking news?", "The untapped editorial
  value of the comment section").
- **FailArmy**: fails armados y compilaciones, justo lo que el ajuste vino a
  excluir.

Si alguno cambia de línea editorial, alcanza con sacarle el `enabled: false`
en `config.yaml`.

> **Limitación conocida.** Muchos clips de agencia describen un hecho sin
> nombrar nada ("Feisty Kitten Sneak Attack", "Dog Gets Stuck In Chair") y
> spaCy no les extrae ninguna entidad, así que no llegan a la pauta aunque
> tengan señal viral. Es la contracara del diseño por entidades: sin una clave
> estable no hay serie temporal contra la cual medir un pico. Entran cuando el
> clip nombra algo seguible (un huracán, una marca, un país).

**Bailes excluidos.** Nueva categoría en `excluir` (scope `todo`): un reto de
baile mete millones de vistas sin que haya pasado nada. `dance` **suelto** se
dejó afuera a propósito, por el mismo criterio de ambigüedad que
`switch`/`steam`: aparece en noticias reales.

**RSS nuevos:** Good News Network, Bored Panda, Daily Dot, Know Your Meme,
MMA Fighting (US) y Récord (MX) (los seis verificados con
`curl -A "Mozilla/5.0 ..."` antes de sumarlos: 200 + XML real). Se probaron y
**descartaron** The Dodo, People, Entertainment Weekly, UNILAD, LADbible, ESPN,
MMA Junkie y L'Équipe. The Dodo/UNILAD/LADbible/MMA Junkie son SPA modernas
sin feed RSS público (404 en cualquier variante de `/feed`; LADbible solo
expone sitemap para Google News). ESPN y L'Équipe responden pero bloquean el
request a nivel de borde — ESPN con un challenge de AWS WAF (HTTP 202, cuerpo
vacío) y L'Équipe con un 403 de Akamai — mismo patrón que The Sun. Google News
(`sources.gnews`) trae algo de ese contenido de todos modos. El nicho de
"niños haciendo cosas divertidas" casi no tiene RSS dedicado — depende del
tagging (`viral_ninos`) más que de una fuente específica.

**Wikipedia** es la fuente nueva más fuerte del paquete: cuando alguien
famoso muere, es arrestado o protagoniza un escándalo, su página se dispara
mucho antes (o con más volumen) que cualquier nota de prensa. Ver la sección
de fuentes más arriba para los detalles y el límite conocido.

---

## Ajustes

Todo en `config.yaml`.

**Si sale demasiado ruido**: subí `z_spike` (3.0 → 4.0) o `min_volume` (2.0 → 4.0).
**Si no sale nada**: bajá `z_watch`, o revisá que las fuentes estén respondiendo
(la línea de cobertura arriba de la pauta te dice cuántos items trajo cada una).
**Si un tema sale partido en varias filas**: bajá `spike.collapse` (0.6 → 0.5).
**Si dos historias distintas se fusionan**: subilo.

`cpm_index` por mercado no afecta la detección, solo el orden: un z=4 en US
pesa más que un z=4 en MX porque el CPM es ~8x. Si preferís ordenar por
magnitud pura, poné todos los mercados en 1.0.

### Agregar una fuente

Escribís una función que devuelva items con este shape y la registrás en
`COLLECTORS`:

```python
def mi_fuente(market, day, cfg):
    return [{
        "id": _id("mifuente", algo_unico),   # estable por contenido, no por día
        "day": day, "source": "mifuente", "market": market["id"],
        "lang": market["lang"], "title": "...", "url": "...",
        "author": "...", "published_at": "...",
        "weight": 1.0,        # 1.0 = una nota de prensa
        "extra": {},
    }]
```

`weight` es la escala común. Si tu fuente trae views o upvotes, pasalos por
`_log_weight()` — sin eso un video de 5M de views entierra a 40 notas de agencia.

---

## Lo que no hace

- No mide **saturación**. Te dice que un tema subió, no cuántos canales ya lo
  hicieron. Un `PICO` con 400 videos publicados puede no valer la pena.
- No sabe qué te **funcionó** a vos. Cruzar esta pauta con el rendimiento real
  de tus publicaciones es el paso siguiente, y el más valioso.
- No detecta un tema que **nunca** aparece en prensa, búsquedas ni YouTube. Si
  nace y muere dentro de TikTok, esto no lo ve.
- No **traduce** temas entre mercados. Que algo pique en US no significa que
  vaya a picar en MX; a veces sí, con dos días de delay. Mirar las tres columnas
  en paralelo te muestra ese delay, pero el sistema no lo modela.
