# Horarios confiables dentro de GitHub (sin servicios externos)

## El problema

GitHub está atrasando mucho las corridas programadas (hasta ~4 horas) y a veces
las salta. Ejemplos reales del 21/09: la corrida de las 13:00 Chile arrancó a las
17:10; la de las 18:00 arrancó a las 20:45. El 22/09 la de las 7:00 no arrancó.
El monitor "cada 15 min" en la práctica corre cada 2-5 horas. El peor momento es
el minuto :00 de cada hora, que es justo cuando estaba todo programado.

El usuario NO quiere servicios externos (cron-job.org, etc.). Todo tiene que
resolverse dentro de GitHub Actions.

---

## Parte 1 — Pauta diaria: 7:00 y 13:00 Chile, con "arranque temprano + espera"

Nuevos horarios: SOLO 7:00 y 13:00 hora de Chile. Sacá la de las 18:00 y todos
los crons en minuto :00.

### Idea

Cada horario se dispara varias horas ANTES, y el workflow espera dormido hasta
la hora objetivo. Si GitHub se atrasa, la espera absorbe el atraso. Hay una
corrida de respaldo por si GitHub se salta la primera.

### Triggers (UTC, minuto :07 para evitar la congestión del :00)

```yaml
on:
  schedule:
    - cron: "7 5 * * *"    # turno 07 — principal
    - cron: "7 7 * * *"    # turno 07 — respaldo
    - cron: "7 11 * * *"   # turno 13 — principal
    - cron: "7 13 * * *"   # turno 13 — respaldo
  workflow_dispatch: {}
```

Usá `github.event.schedule` (contiene el cron que disparó la corrida) para saber
a qué turno pertenece: los dos primeros → turno 07; los dos últimos → turno 13.

### Lógica del job (en este orden)

1. **Calcular la hora objetivo en hora de Chile**, no en UTC:
   `TZ='America/Santiago' date -d "today 07:00" +%s` (o 13:00). Así el horario
   de verano/invierno se maneja solo y NO hay que tocar nada en abril. Los
   triggers UTC de arriba caen antes de la hora objetivo en ambos horarios.
2. **Esperar** (`sleep`) hasta la hora objetivo. Si ya pasó (atraso enorme),
   seguir de inmediato. Una pauta tarde es mejor que ninguna: NUNCA saltear por
   estar atrasada.
3. Recién después de la espera: `git pull` para traer lo último del repo.
4. **Chequear si el turno ya se hizo**: marcador en el repo, por ejemplo
   `data/turnos/2026-09-22-07.done`. Si existe (lo hizo la corrida principal),
   terminar sin hacer nada. Este es el ÚNICO chequeo que puede cortar una
   corrida, y solo corta si el trabajo ya está hecho.
5. Correr la pauta como hoy (run.py, commit, deploy a Pages).
6. Crear el marcador del turno y commitearlo junto con los datos.

Detalles obligatorios:
- `timeout-minutes: 350` en el job (GitHub corta a las 6 h; la espera más larga
  es ~5 h).
- `concurrency: group: pauta-turno-${{ <turno> }}` con
  `cancel-in-progress: false`, para que principal y respaldo del mismo turno no
  corran en paralelo: la de respaldo queda en espera y, al arrancar, hace el
  `git pull` y ve el marcador.
- `workflow_dispatch` (manual) corre de inmediato, sin espera y sin marcador,
  para no bloquear el turno automático del día.
- Mantener el push robusto que ya existe (rebase con reintentos, abort limpio).

Dejá un comentario en el workflow explicando por qué este chequeo es distinto
del que se sacó antes: aquel comparaba la hora exacta y bloqueaba corridas
atrasadas; este solo corta si el turno ya se completó.

---

## Parte 2 — Monitor de última hora: modo continuo en horario útil

Hoy el cron `*/15` depende de que GitHub lo lance cada 15 min, y no lo hace.
Nueva lógica: una corrida larga que revisa cada 15 min por dentro.

### Comportamiento

- Horario útil: 7:00 a 00:00 hora de Chile (calculado con
  `TZ='America/Santiago'`).
- Dentro del horario útil, el job hace un loop: correr `breaking_run.py`,
  commitear, desplegar, esperar 15 min, repetir. El loop termina a las ~5 h 30
  de iniciado o al llegar las 00:00 Chile, lo que ocurra primero.
- Fuera del horario útil: una sola pasada y termina (comportamiento normal).
- Trigger de relanzamiento: `cron: "7,37 * * * *"` (cada 30 min, fuera del
  :00). Con `concurrency: group: breaking-monitor`, `cancel-in-progress: false`,
  mientras hay un loop corriendo los nuevos triggers quedan en espera (GitHub
  deja uno solo pendiente) y toman la posta cuando el loop termina.
- `timeout-minutes: 350`.

### El deploy a Pages dentro del loop

El deploy actual usa `actions/deploy-pages` en un job aparte, que no se puede
llamar desde dentro de un loop de bash. Sugerencia: crear un workflow liviano
`deploy.yml` (solo `workflow_dispatch`) que sube `reports/` a Pages, y que el
loop lo dispare después de cada push con `gh workflow run deploy.yml` usando
`GITHUB_TOKEN` (permiso `actions: write`). Los eventos `workflow_dispatch`
disparados con GITHUB_TOKEN sí lanzan workflows. Si tenés una opción mejor,
usala y explicame cuál.

### Límite de uso

Esto deja un runner ocupado ~17 h por día. En repos públicos no cuesta, pero
GitHub prohíbe uso desproporcionado de Actions. Por eso el loop es solo en
horario útil, no 24 h. No lo extiendas a 24 h.

---

## Verificación

1. `actionlint` o validación YAML de los tres workflows, y `bash -n` de los
   scripts.
2. Probá la lógica de espera y del marcador con fechas simuladas (sin esperar
   horas de verdad): que calcule bien la hora objetivo en Chile, que no espere
   si ya pasó, que la de respaldo se corte si existe el marcador.
3. Dispará a mano la pauta diaria (workflow_dispatch) y confirmá verde.
4. Dispará a mano el monitor y confirmá que entra al loop (si es horario útil) y
   que el deploy se hace después de cada vuelta. Podés cancelarlo tras 2 vueltas.
5. Actualizá el README: horarios 7:00 y 13:00, por qué se arranca temprano, el
   marcador de turno, el modo continuo del monitor y su horario útil.
6. Decime a qué hora quedaron los triggers y mañana revisamos a qué hora corrió
   de verdad cada turno.
