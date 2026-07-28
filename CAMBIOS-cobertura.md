# Cambios de cobertura — spec para Claude Code

Tres cambios al sistema de tendencias (Pauta). Están ordenados de más simple a
más complejo. Verificá cada feed RSS con curl ANTES de agregarlo (200 + XML
real), igual que se hizo con TMZ/Infobae. Los que fallen, descartalos y
documentá por qué.

---

## 1. Quitar gaming (simple)

En `config.yaml`, la sección `youtube.categories` incluye la categoría de
gaming. Sacala. Las categorías de YouTube son:
- "0" = todas
- "25" = News & Politics
- "24" = Entertainment
- "28" = Science & Tech
- "20" = **Gaming ← ESTA hay que quitarla si está**

Revisá qué categorías están hoy y quitá gaming (20). Si "0" (todas) está
presente, gaming entra igual por ahí — en ese caso, mejor listar categorías
explícitas SIN el 0 y SIN el 20, para excluir gaming de verdad.

---

## 2. Guerras: bajar peso en la pauta diaria, dejar pasar en el monitor (bisturí)

El usuario NO quiere eliminar noticias de guerra — quiere que no sean
protagonistas en la pauta diaria, pero que sí aparezcan en el monitor de última
hora (breaking_run.py) si algo grande rompe.

Implementación sugerida (ajustá si tenés mejor idea):

- Creá una lista de términos de conflicto en config.yaml, algo como:
  ```yaml
  down_weight:
    conflicto:
      terms: [guerra, war, guerre, misil, missile, bombardeo, airstrike,
              tropas, troops, ofensiva, offensive, frente, frontline,
              ataque aéreo, ceasefire, alto el fuego, invasión, invasion,
              milicia, militia, artillería, artillery]
      factor: 0.3   # multiplica el peso/score de temas que matcheen
  ```
- En `spike.py` (o donde se calcula el score final del tema): si el nombre del
  tema o sus titulares de evidencia matchean varios de esos términos,
  multiplicá su `value`/score por el `factor` (0.3). Así siguen apareciendo
  pero caen en el ranking, no encabezan la pauta.
- En `breaking_run.py` (monitor 15 min): NO apliques este down-weight. El
  monitor debe detectar rupturas de guerra normalmente — si estalla algo
  grande, el usuario quiere enterarse en tiempo real aunque no lo cubra en
  video.

Clave: el down-weight es SOLO para la pauta diaria, no para el monitor.
Explicá en un comentario por qué están separados.

---

## 3. Ampliar cobertura: celebridades, rescates, detenciones, virales de niños

El usuario quiere DOS cosas (ambas):

### 3a. Agregar fuentes RSS especializadas

Verificá con curl y agregá al `sources.rss.feeds` de config.yaml las que
respondan 200 + XML. Candidatos por categoría (market: US salvo que se indique):

**Rescates de animales / family-friendly viral:**
- The Dodo: `https://www.thedodo.com/feeds/feed.rss`  ← el más importante,
  es EL medio de rescates virales compartibles. Verificá bien.

**Celebridades:** (ya hay TMZ, ET, Perez, Just Jared — sumar si querés)
- People: buscá el RSS real de people.com (sección celebrity)
- Entertainment Weekly: buscá su RSS

**Rescates humanos / detenciones policiales / virales:**
- buscá RSS de "Good News Network" (goodnewsnetwork.org/feed) para rescates
  y virales positivos
- Para detenciones ya está Law & Crime, que cubre eso bien

**Virales de niños / family-friendly:**
- buscá si "Good News Network" o similar cubre esto; el nicho puro de "niños
  haciendo cosas divertidas" casi no tiene RSS dedicado — probablemente
  venga mejor por el tagging (3b) que por una fuente específica.

Para CADA candidato: `curl -s -o /dev/null -w "%{http_code}\n" -A "Mozilla/5.0" "URL"`.
Solo agregá los que den 200. Documentá los que fallen.

### 3b. Marcar/resaltar esos temas cuando aparezcan (tagging)

Además de las fuentes, el usuario quiere que cuando un tema que YA apareció
encaje en estas categorías, se resalte para que salte a la vista.

Implementación sugerida:
- En config.yaml, definí categorías con sus términos:
  ```yaml
  categorias_destacadas:
    celebridades: [celebrity, actor, actress, singer, famosa, famoso, star]
    rescate: [rescue, rescate, rescued, saved, sauvetage, rescatado]
    policial: [arrest, arrested, detenido, police, arrestado, custody]
    viral_ninos: [kid, child, niño, toddler, adorable, wholesome, enfant]
    boda_viral: []   # ← caso especial, ver nota abajo
  ```
- Al renderizar cada tema en el reporte, si su nombre o evidencia matchea una
  categoría, mostrá una etiqueta/badge visible (ej: un chip "🐾 rescate",
  "⭐ celebridad", "🚔 policial", "👶 viral"). Reusá el estilo de chips que ya
  existe en el reporte.

### 3c. Categoría especial: bodas virales/fallidas/excéntricas (💍)

El usuario quiere detectar videos de bodas fallidas o excéntricas — muy
virales y compartibles. PERO esta categoría necesita lógica distinta a las
demás, porque "boda/wedding" a secas trae mucho ruido (bodas de famosos,
consejos, moda) que NO es lo que se busca. Lo viral es el momento
caótico/gracioso/insólito, no la boda en sí.

Implementación: requiere match COMBINADO (un término de boda Y un término de
lo viral/caótico en el mismo tema), no un solo término suelto.

```yaml
  boda_viral:
    # Se activa SOLO si matchea AL MENOS UNO de cada grupo:
    grupo_boda: [boda, wedding, mariage, novia, bride, groom, novio, altar]
    grupo_gancho: [viral, fail, fallida, caos, chaos, disaster, desastre,
                   insólito, unexpected, worst, awkward, ridiculous,
                   se vuelve viral, goes viral, drama, pelea, brawl]
```

Lógica: el tag "💍 boda viral" y su boost se activan únicamente si el tema
matchea un término de `grupo_boda` Y ADEMÁS uno de `grupo_gancho`. Una boda
sin gancho viral NO se marca. Documentá esta diferencia con un comentario,
porque es la única categoría con match combinado — las demás usan match
simple.

Nota honesta para el usuario (poné esto en el README): este contenido vive
sobre todo en TikTok/Instagram, que el sistema no cubre gratis. La prensa a
veces recoge estos videos DESPUÉS de que explotaron, así que esta categoría
va a capturar bastante menos que las otras hasta que (si alguna vez) se sume
una fuente de video social paga. Es una limitación de la fuente, no del tag.
- DECIDIDO por el usuario: badge visual + boost MODERADO en el ranking.
  Aplicá un boost al score (x1.3 aprox) de los temas que matcheen estas
  categorías, para que aparezcan más arriba en la pauta — es el contenido que
  el usuario más quiere. IMPORTANTE: que sea moderado, no que dominen del todo
  la pauta. Si un tema matchea varias categorías, NO acumules el boost varias
  veces (aplicá el x1.3 una sola vez), para no distorsionar demasiado el
  ranking. El objetivo es que suban, no que tapen todo lo demás.

  Nota sobre interacción con el down-weight de guerra (punto 2): si un tema
  matchea AMBOS (ej. un rescate en zona de guerra), aplicá los dos factores
  (0.3 x 1.3). No es un caso común pero conviene que el comportamiento sea
  predecible: los factores se multiplican, no se anula uno al otro.

---

## Al terminar

1. Verificá que corran sin error: `python run.py` y `python breaking_run.py`
   localmente (o con workflow_dispatch en GitHub).
2. Confirmá en GitHub Actions que los dos workflows queden en verde.
3. Decime qué feeds agregaste, cuáles descartaste y por qué.
4. Actualizá el README documentando las categorías nuevas y el down-weight de
   guerra.
