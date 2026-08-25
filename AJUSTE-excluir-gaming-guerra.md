# Ajuste: exclusión dura de gaming y guerras

Seguimiento de los cambios anteriores. El usuario probó la pauta y todavía ve
demasiados temas de gaming y de guerra. Ahora quiere **exclusión**, no
down-weight.

Cambio de mecanismo: un factor multiplicador (0.3) nunca llega a cero — el tema
siempre sobrevive con score bajo. Para sacarlos de verdad hace falta un filtro
que los DESCARTE antes de que entren a la pauta.

---

## 1. GAMING — eliminar por completo, de TODAS las fuentes

El usuario no quiere ver gaming en ningún lado. Hoy sigue apareciendo, así que
está entrando por algún lado que no cerramos. Revisá y cerrá los tres caminos:

**a) YouTube — la "ventana abierta".** Revisá `config.yaml` →
`youtube.categories`. Si incluye `"0"` (= todas las categorías), el gaming
entra por ahí aunque hayamos sacado el `"20"`. Solución: listá categorías
explícitas SIN el `"0"` y SIN el `"20"`. Ej: `["25", "24", "28"]`.

**b) Google News.** Puede estar entrando por los tópicos TECHNOLOGY o
ENTERTAINMENT. No hay que sacar esos tópicos enteros (traen cosas útiles),
sino filtrar los ítems de gaming dentro de ellos — ver punto (c).

**c) Filtro de exclusión por términos, aplicado a TODAS las fuentes.**
Agregá en config.yaml:

```yaml
excluir:
  gaming:
    scope: todo        # se aplica en pauta diaria Y en monitor
    terms: [gaming, gamer, videojuego, videojuegos, video game, videogame,
            playstation, ps5, xbox, nintendo, switch, steam, twitch,
            esports, e-sports, fortnite, minecraft, roblox, call of duty,
            gta, valorant, league of legends, jeu vidéo, gameplay,
            speedrun, streamer, consola, console gaming]
```

Lógica: si el nombre del tema o sus titulares de evidencia matchean cualquiera
de estos términos, el tema se DESCARTA (no entra a la pauta ni al monitor).

⚠️ Cuidado con falsos positivos: "steam" también significa vapor, "switch"
también es cambiar, "console" puede ser consolar. Usá match de palabra
completa (word boundary) y, si podés, exigí que el match sea en un contexto
de gaming. Si hay dudas con un término ambiguo, mejor sacalo de la lista que
descartar contenido bueno por error.

---

## 2. GUERRAS — eliminar de la pauta diaria, MANTENER en el monitor

Esto es lo más delicado del ajuste. El usuario quiere:
- **Pauta diaria (`run.py`)**: sin temas de guerra. Excluidos, no bajados.
- **Monitor última hora (`breaking_run.py`)**: guerras SÍ, normalmente. Si
  estalla algo grande, quiere enterarse en tiempo real.

Implementación:

```yaml
excluir:
  conflicto:
    scope: solo_pauta_diaria    # NO se aplica en breaking_run.py
    terms: [guerra, war, guerre, misil, missile, bombardeo, airstrike,
            tropas, troops, ofensiva, offensive, frontline, ceasefire,
            alto el fuego, invasión, invasion, milicia, militia,
            artillería, artillery, ejército, army, military strike,
            drone strike, cazas, fighter jets, refugiados de guerra]
```

- Aplicá este filtro en el pipeline de `run.py` (donde se arma la lista final
  de temas de la pauta), de forma que los temas que matcheen se descarten.
- **NO lo apliques en `breaking_run.py`.** Dejá un comentario explícito en el
  código explicando por qué está separado, para que un cambio futuro no lo
  unifique por error y rompa la intención.
- Sacá el down_weight de conflicto que se agregó antes (factor 0.3) — queda
  reemplazado por esta exclusión. No dejes los dos mecanismos conviviendo.

⚠️ Ojo con falsos positivos acá también: "army" aparece en nombres propios,
"invasion" se usa metafóricamente ("invasión de turistas"). Word boundary y
criterio.

---

## 3. Transparencia: que se note qué se filtró

Para que el usuario no quede a ciegas sobre qué se está descartando, agregá al
final del reporte (cerca de la leyenda existente) una línea discreta tipo:

> "Filtrados de esta pauta: N temas de gaming, N de conflicto bélico.
> Los de conflicto siguen activos en el monitor de última hora."

Así el usuario ve que el filtro está funcionando y cuánto está sacando, en vez
de preguntarse si dejó de haber noticias.

---

## Al terminar

1. Corré `run.py --report-only` contra una copia de la data real y verificá:
   - Cuántos temas de gaming y conflicto se descartaron (mostrá los nombres,
     para revisar que no haya falsos positivos obvios).
   - Que NO se hayan colado exclusiones raras (contenido bueno descartado por
     un término ambiguo).
2. Verificá que `breaking_run.py` SIGUE detectando temas de conflicto — es
   importante, es la parte que el usuario quiere conservar.
3. Commit + los dos workflows en verde en GitHub Actions.
4. Decime cuántos temas se filtraron y si viste algún falso positivo.
