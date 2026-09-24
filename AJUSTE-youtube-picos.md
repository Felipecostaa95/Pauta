# Ajuste: YouTube como señal de picos, no de audiencia

## El problema

Empezaron a salir videoclips y vlogs. Causa: en el paquete anterior se
cambiaron las categorías de YouTube a 10 (Música = videoclips) y 22 (Gente y
blogs = vlogs). Pero hay un problema de fondo: `chart=mostPopular` mide
AUDIENCIA (lo más visto), y este monitor tiene que detectar PICOS de actividad
y discusión: noticias, eventos de celebridades, deportivos, etc.

## Principio que tiene que guiar todo el ajuste

Palabras del usuario: la idea del monitor no es juntar lo que más se ve, sino
detectar verdaderos picos de actividad, discusión y debate en internet. Si son
shorts, que sea por actividad y veces que se comparten, idealmente no nichos
(gaming, bailes), y privilegiando shorts noticiosos, del tipo que se
encontrarían en Newsflare.

Traducido a reglas: YouTube deja de ser una fuente que genera temas por sí sola
y pasa a cumplir dos roles:
1. **Corroborar** temas que ya están picando en otras fuentes (noticias,
   Wikipedia, Google Trends).
2. **Aportar shorts virales noticiosos** que pasen filtros estrictos.

---

## 1. Categorías

Sacá 10 (Música), 22 (Gente y blogs) y 23 (Comedia: trae sketches de
youtubers). Quedan:

```yaml
categories: ["15", "17", "25"]
# 15 = Mascotas y animales (rescates, animales virales)
# 17 = Deportes (golazos, knockouts)
# 25 = Noticias y política (clips noticiosos; la guerra ya la saca el filtro)
```

Mantener el descarte de cualquier video con `snippet.categoryId` 20 (Gaming) y
agregar 10 (Música).

## 2. Clasificar cada video

Pedí también `contentDetails` en la llamada a `videos.list` (mismo costo de
cuota) para tener la duración. Clasificá cada video en:

- **videoclip**: categoryId 10, canal que termina en "VEVO" o " - Topic", o
  título con patrones como "Official Video", "Official Music Video", "Music
  Video", "Lyric Video", "Lyrics", "Visualizer", "Official Audio", "Video
  Oficial", "Videoclip", "Clip officiel".
- **short**: duración ≤ 3 minutos.
- **largo**: duración > 3 minutos (vlogs, programas, etc.).

## 3. Reglas de admisión (por video, no por tema)

- **Videoclip**: nunca cuenta como evidencia. Si el artista está en tendencia
  (Britney Spears, por ejemplo), el tema entra igual por las noticias,
  Wikipedia o Google Trends, y la fila muestra esas notas, no el clip.
- **Largo**: solo cuenta si el tema está corroborado el mismo día por al menos
  una fuente que no sea YouTube (gnews, rss, gtrends, wikipedia). Si un vlogger
  está en tendencia por algo, la noticia explica el porqué y su video
  acompaña. Si es solo un video con muchas vistas, queda afuera.
- **Short**: entra si NO es música, baile, gaming ni IA, y además cumple una
  de estas dos condiciones:
  a) está corroborado por una fuente que no es YouTube; o
  b) tiene señal viral fuerte (ver punto 4) Y matchea una categoría destacada
     (rescate, policial, animales, deporte viral, boda viral, viral de niños,
     celebridades, parejas).
- **Tema cuya única evidencia es YouTube sin corroborar** (y sin shorts que
  pasen la regla b): fuera de la pauta.

Nueva exclusión de bailes (scope todo, match de palabra completa):
`[dance challenge, baile, bailando, coreografía, choreography, dance trend,
tiktok dance, danse]`. Cuidado con "dance" suelto: también aparece en noticias.

## 4. Peso por actividad, no por vistas acumuladas

Reemplazá el peso basado en `views` totales por señales de actividad:

- **Velocidad**: vistas por hora desde `publishedAt`.
- **Discusión**: `commentCount` relativo a las vistas.

"Señal viral fuerte" (regla 3b) = el short está en el cuartil superior de
velocidad Y de discusión entre los shorts recolectados ese día en su mismo
mercado. Calibrá con datos reales y mostrame qué shorts pasan.

## 5. Tags de YouTube

Dejá de crear entidades a partir de los tags de YouTube: son palabras SEO que
generan temas basura (nombres de canal, "vlog", "official", etc.). Las
entidades de videos salen solo del título.

## 6. Fuente estilo Newsflare: canales de agencias de video viral

Newsflare, ViralHog y similares no tienen feed público de su sitio, pero sí
publican en YouTube. Cada canal de YouTube tiene un RSS gratis y sin cuota:
`https://www.youtube.com/feeds/videos.xml?channel_id=<ID>`

Buscá el ID real del canal oficial de cada uno, verificá el feed con curl y
agregá los que respondan:
- Newsflare
- ViralHog
- Storyful
- Caters Clips
- Jukin Media / FailArmy (solo si traen clips noticiosos y no solo fails armados)

Para las estadísticas de esos videos, usá `videos.list` con hasta 50 IDs por
llamada (1 unidad de cuota). Estos videos pasan por las mismas reglas del
punto 3, pero cuentan como fuente "agencia de video viral" y muéstralos con un
chip propio en el reporte. Mercado: US (salvo que el canal sea claramente de
otro país).

## 7. Transparencia

Sumá a la línea de filtrados del reporte: "N videoclips, N videos largos sin
corroborar, N shorts sin señal viral, N bailes".

## Verificación

1. Test simulado del caso Britney: artista con noticias en gnews + su
   videoclip en YouTube → la fila aparece con las noticias, sin el videoclip.
2. Test simulado: vlog con muchas vistas sin corroboración → fuera. El mismo
   vlogger con una noticia sobre él → dentro, con la noticia como porqué.
3. `run.py --report-only` contra una copia de la base real. Mostrame:
   - videoclips descartados
   - videos largos descartados por falta de corroboración
   - shorts admitidos (con velocidad y comentarios), para revisar que sean
     noticiosos y no nichos
   - qué canales de agencias de video viral entraron
4. Commit, push y los workflows en verde.
5. README actualizado con el nuevo rol de YouTube.
