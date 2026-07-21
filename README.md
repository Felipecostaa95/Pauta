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
| **YouTube** | Creadores y medios en video, con views | Sólido, gratis con key |
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

**1. Pauta diaria (`run.py`) — tendencias.** Corre 1 vez al día. Responde a
"¿de qué se habla más que lo normal ESTA SEMANA?". Compara contra un baseline
de 28 días. Es contenido de guion: temas que vienen creciendo y dan para
producir video. Workflow: `.github/workflows/pauta.yml`.

**2. Monitor de última hora (`breaking_run.py`) — rupturas.** Corre cada 15
minutos. Responde a "¿algo apareció de la nada en los últimos MINUTOS?". No
compara contra 28 días — compara contra su propia corrida anterior (hace 15
min). Si un tema salta de "casi nadie lo cubre" a "5+ fuentes distintas lo
cubren AL MISMO TIEMPO", eso es una ruptura (una muerte, un escándalo, algo que
rompió), y aparece en la banda "⚡ Última hora" arriba del reporte, sin esperar
a la pauta del día siguiente. Workflow: `.github/workflows/breaking.yml`.

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
