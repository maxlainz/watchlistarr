# Estrategia de sincronización

Cómo watchlistarr mantiene su DB interna alineada con Letterboxd. Las entidades referenciadas aquí (`list_items`, `watched_films`, etc.) están definidas en [`data-model.md`](data-model.md).

Principio rector: **la DB es autoritativa**. Lo que servimos a Radarr nunca se computa on-the-fly desde Letterboxd. Los scrapes solo actualizan la DB si terminan sin error. Esto, combinado con verificación cruzada antes de eliminar, evita el "parpadeo" en las listas servidas a Radarr (crítico porque Radarr puede borrar de la biblioteca pelis que tardaron semanas en bajarse).

## Fuentes y qué actualiza cada una

| Fuente | Tipo | Frecuencia (env var) | Default | Qué actualiza |
|---|---|---|---|---|
| RSS `/{user}/rss/` | hot | `RSS_INTERVAL` | 15 min | `viewing_logs`, `watched_films` (delta) |
| Watchlist página 1 (default order) | incremental | `WATCHLIST_INCREMENTAL_INTERVAL` | 1 h | Detección de adiciones (newest-added cae aquí) |
| Watchlist scrape completo (todas las páginas) | full | `WATCHLIST_FULL_INTERVAL` | 24 h | Detección de eliminaciones + verificación |
| Lista custom: página 1 default + última de `/by/added-earliest/` | incremental | `LISTS_INCREMENTAL_INTERVAL` | 6 h | Detección de adiciones en O(2) fetches |
| Lista custom scrape completo | full | `LISTS_FULL_INTERVAL` | 7 d | Eliminaciones + reordenamientos + verificación |
| `/{user}/films/` página 1 (backstop) | hot | `FILMS_BACKSTOP_INTERVAL` | 24 h | `watched_films` (rellena gaps del RSS, sin fecha) |
| `/{user}/lists/` (discovery) | discovery | `DISCOVERY_INTERVAL` | 7 d | `lists` (descubre listas nuevas o desaparecidas) |
| Rotation tick (interno, sin red) | scheduled | `ROTATION_TICK_INTERVAL` | 1 h | `custom_list_items` de custom lists cuyo `last_rotated_at + rotation_interval ≤ now` |
| Prune scrape runs (interno, sin red) | scheduled | — (fijo) | 24 h | Borra `scrape_runs` con más de 30 días |

Todos los jobs (onboarding y periódicos) se envuelven con `with_scrape_audit`: cada ejecución deja un `scrape_runs` con `status` y `error`. Un fallo en un sync de lista/watchlist marca además `lists.last_sync_status='error'`.

**Principio**: RSS-driven en caliente, scrapes incrementales frecuentes para detectar adiciones, scrapes completos espaciados para confirmar todo lo demás.

Detalles de selectores y URLs para cada scrape: [`letterboxd-lists.md`](letterboxd-lists.md) (listas, watchlist, films, discovery) y [`letterboxd-rss.md`](letterboxd-rss.md) (RSS).

## DB autoritativa, scrape transaccional

- El JSON que servimos a Radarr en `/<user>/<slug>/`, `/<user>/watchlist/` y `/lists/<slug>/` (custom lists) es **siempre un SELECT de la DB**.
- Un scrape completo **solo aplica cambios** si recorre todas sus páginas sin error. Si falla a mitad, se aborta, no se persisten cambios parciales, `scrape_runs.status='error'` y `lists.last_sync_status='error'`.
- Un scrape incremental nunca elimina; solo añade. Las eliminaciones solo provienen de scrapes completos (y pasan por la verificación anti-flap).

Esto cubre el 95% de casos de parpadeo (errores transitorios, timeouts).

## Política anti-flap (eliminaciones)

Algoritmo cuando un **scrape completo** detecta `(tmdb_id ∈ list_items[list_id]) AND (tmdb_id ∉ scrape result)`:

1. **¿Visto por el owner?**: si `(user_id, tmdb_id) ∈ watched_films` → **eliminar inmediatamente** del `list_items`. Caso legítimo: el RSS ya capturó el visionado y el user lo retiró de la watchlist tras verla.

2. **Backstop check ad-hoc**: si tras el scrape quedan desapariciones sin explicar (no vistas), un único fetch a `/{user}/films/` página 1 del owner **antes de abrir la transacción de escritura** (no se hace HTTP con el write-lock de SQLite abierto; los slugs se resuelven solo contra `films`). Si el `tmdb_id` aparece allí (el RSS perdió el evento), insertar en `watched_films` con `source='films-page'` y eliminar el item. Si el fetch falla, se degrada al contador del paso siguiente.

3. **Sin confirmación de visto**: incrementar `list_items.pending_removal_count`. **No** retirar del estado servido todavía.

4. Cuando `pending_removal_count >= FLAP_CONFIRM_SCRAPES` (env var, default `3`) en scrapes completos consecutivos, **eliminar**.

5. Si el item reaparece en cualquier scrape posterior antes de llegar al umbral: reset `pending_removal_count=0`.

**Renames y remaps**: un rename de slug (mismo `tmdb_id`) nunca llega al anti-flap — `resolve_films` lo absorbe al matchear la ficha por `tmdb_id` y actualizar `films.letterboxd_slug`. Un remap de TMDB id (Letterboxd re-mapea la ficha a otra entrada TMDB, mismo título/año) no recibe trato especial: el id nuevo entra como item nuevo en el mismo scrape y el viejo se retira vía el contador — el film se sirve sin hueco durante la transición.

### Asimetría intencionada: adiciones sin protección

Una peli nueva que aparece en Letterboxd entra a `list_items` en el primer scrape donde la veamos.

Razón: el coste de un falso positivo es asimétrico:
- Añadir una peli incorrectamente → Radarr la descarga (consumimos ancho de banda + disco; reversible).
- Eliminar una peli incorrectamente → Radarr borra una peli que tardó semanas en bajarse (caro, frustante, a veces irreversible).

## Eventos vistos vía RSS

- Cada fetch del RSS itera los `<item>` con prefix `letterboxd-watch-` y `letterboxd-review-`.
- Dedup por `<guid>` contra `viewing_logs.letterboxd_guid`.
- Para cada nuevo guid:
  1. Insertar fila en `viewing_logs` (con la `watched_date` real del item).
  2. Upsert en `watched_films` por `(user_id, tmdb_id)`:
     - Si no existe: `first_seen_watched_at = now()` (momento del poll), `last_seen_watched_at = now()`, `source='rss'`. La fecha real del visionado vive en `viewing_logs.watched_date`; estos timestamps registran cuándo lo vimos nosotros.
     - Si existe: actualizar solo `last_seen_watched_at` (cualquier rewatch lo refresca; `first_seen_watched_at` es inmutable).
- Items con prefix `letterboxd-list-` se ignoran (las listas se descubren por `/lists/`).

## Backstop: `/films/` página 1

Cubre el gap conocido del RSS (ventana limitada a ~20-50 items).

- Frecuencia: `FILMS_BACKSTOP_INTERVAL` (default 24h).
- También se dispara ad-hoc dentro del paso 2 del anti-flap.
- Para cada `data-item-slug` extraído de la página 1 de `/films/`:
  - Resolver `tmdb_id` si no está en `films` (fetch de ficha).
  - Upsert en `watched_films` con `source='films-page'`. **No** crea entrada en `viewing_logs` (no tenemos `<guid>` ni fecha).

## Discovery de listas

- Frecuencia: `DISCOVERY_INTERVAL` (default 7d).
- Fetch a `/{user}/lists/` (+ paginación si aplica).
- Para cada `<article class="list-summary" data-film-list-id="...">`:
  - Upsert en `lists` con `letterboxd_list_id`, `slug`, `name`, `film_count`, `source_type='list'`.
  - Si es una lista nueva, `enabled=false` por defecto — aparece como fila toggleable en el detalle del user (no hay prompt dedicado; candidato no implementado).
- Listas que existían y ya no aparecen: `enabled=false` (no borrar la fila — el user puede haber tenido razones para tenerla activa).

## Rotation worker

Independiente del scraping — no toca la red. Recorre todas las custom lists con `rotation_enabled = true` cada `ROTATION_TICK_INTERVAL` (default 1 h).

Por cada custom list:

1. Si `last_rotated_at + rotation_interval > now` → skip.
2. Calcular **pool elegible** = resolución multi-source (union/intersection de los `include`-sources, menos `subtract`-sources, menos `watched_films` de los `excluded_watchers`) filtrada por `min_rating`, `max_year`, `added_after`, etc., **menos** las que ya están en `custom_list_items`.
3. Si `len(pool) >= rotation_batch_size`:
   - Sacar las `rotation_batch_size` filas de `custom_list_items` con `served_since` más antiguo (FIFO temporal).
   - Insertar `rotation_batch_size` filas del pool con `served_since = now()`, elegidas según `sort_order` vía `_choose_from_pool` (top-N por rating con `RATING_DESC`, por posición de source con `LETTERBOXD`/`REVERSE`; aleatorias **solo** con `sort_order=RANDOM`). Ver [`data-model.md`](data-model.md#custom-lists-resolución).
4. Si `len(pool) < rotation_batch_size`:
   - Insertar las que haya. Sacar la misma cantidad de las más antiguas para mantener `max_items` aproximado. Si el pool está vacío, **no sacar nada** (mejor servir menos que servir vacío).
5. Update `last_rotated_at = now()`.

**Inicialización al crear**: cuando se crea una custom list, popular `custom_list_items` con `max_items` filas del pool elegible (misma selección por `sort_order` vía `_choose_from_pool`; aleatorias solo con `RANDOM`) y `served_since = now()`.

**Recálculo al editar sources, exclusiones, filtros o `max_items`**: síncrono al guardar en la UI (`recalculate()` en `services/custom_lists.py`):
- Eliminar de `custom_list_items` las que ya no cumplen filtros o quedan fuera del nuevo universo.
- Si quedan menos de `max_items`, rellenar desde el pool actual (vía `_choose_from_pool`).
- Si quedan más de `max_items` (se redujo el cap), truncar el excedente eligiendo qué conservar según `sort_order` y reindexar las posiciones.

**Ortogonalidad con `watched_films`**: el RSS marca pelis como vistas; las custom lists con `excluded_watchers` no eliminan a la velocidad del RSS — pierden los items en la **siguiente rotación** (o en el siguiente recálculo).

### Modo snapshot (alternativo a rotation)

Cuando una custom list tiene `snapshot_interval` set, el rotation tick **no la rota**: en su lugar, llama a `refresh_snapshot()` que (si `now >= last_snapshot_at + snapshot_interval`) borra todos los `custom_list_items`, reejecuta `init_items()` para regenerar el set completo, y actualiza `last_snapshot_at`. Entre snapshots:

- El set servido a Radarr es 100 % estable (no entra ni sale nada).
- El orden también: en modo snapshot, `serialize_custom_list` **deja de re-ordenar por rating al servir** (incluso con `sort_order=RATING_DESC`) y sirve por `position` persistida, que `init_items` ya materializó en orden de ranking en el momento del último snapshot.

Uso típico: "top-10 by rating" que quiero estable durante una semana y se refresque cada lunes. Activar snapshot prevalece sobre rotation aunque ambos estén configurados (el refresh completo hace inútil el cycle parcial).

## Modo "arranque inicial" (cuando se añade un user)

Al añadir un user nuevo en la UI:

1. **Validar**: `GET /{user}/` → debe devolver 200 con `x-letterboxd-type: Member` (síncrono, en el endpoint de add-user). El resto corre en background (`schedule_initial_run` → `_initial_run`, `services/onboarding.py`):
2. **Watchlist row**: se asegura la fila de la watchlist en `lists`. La watchlist deja de ser especial: es una lista más.
3. **Discovery**: `/{user}/lists/` — descubre listas públicas. **Todas se crean `enabled=False`**.
4. **Films-backstop**: `/{user}/films/` página 1 — pobla `watched_films` con lo reciente (no requiere lista enabled, es soporte transversal para anti-flap y custom lists con `excluded_watchers`).
5. **Full sync de TODAS las listas descubiertas, watchlist incluida**, aunque sigan `enabled=False`: sus items quedan pre-sincronizados en la DB para que activar una lista sirva contenido al instante.
6. El usuario elige en la UI qué listas activar (toggle por lista, watchlist incluida). Activar una = empezar a servirla + un full sync inmediato adicional (sin esperar al scheduler).

Coste a tener en cuenta: el onboarding escala con el número y tamaño de listas del perfil — un user con muchas listas grandes implica un arranque largo (y cada slug nuevo cuesta además un fetch de ficha para resolver TMDB/IMDb).

## Configuración

Defaults globales: env vars (ver [`workflows.md`](workflows.md)). Son inmutables tras arranque — no hay tabla global de settings ni pantalla `/settings`.

Overrides por entidad (NULL = heredar default de env):

- `users.watchlist_incremental_interval`, `users.watchlist_full_interval` — editables en el colapsable "Advanced" de la fila watchlist en la pestaña Lists (`POST /api/v1/users/{u}/lists/{id}/settings`).
- `users.rss_interval`, `users.films_backstop_interval`, `users.discovery_interval` — el scheduler los honra (`services/intervals.py`), pero **ningún endpoint ni pantalla los escribe**: hoy solo son editables tocando la DB directamente. Candidato (no implementado): exponerlos en la UI.
- `lists.lists_incremental_interval`, `lists.lists_full_interval`, `lists.flap_confirm_scrapes` — editables en el colapsable "Advanced" por lista en la pestaña Lists.
- `custom_lists.rotation_interval`, `custom_lists.snapshot_interval` — editables desde el editor de custom list. `snapshot_interval` activa el modo "snapshot periódico" (ver arriba), que congela el output a Radarr entre regeneraciones completas.
- `ROTATION_TICK_INTERVAL` queda solo en env (ritmo del worker interno, no por entidad).

La resolución del valor efectivo vive en `watchlistarr.services.intervals` y siempre se calcula como `entity.<col> or env.<key>` (umbral entero usa `is None`). Cuando un override se guarda o limpia desde la UI, el endpoint llama a `scheduler.sync_jobs()` y los jobs se re-crean con el nuevo trigger sin restart.

## Cross-references

- Tablas que alimentamos: [`data-model.md`](data-model.md).
- Selectores y URLs concretas: [`letterboxd-lists.md`](letterboxd-lists.md) y [`letterboxd-rss.md`](letterboxd-rss.md).
- Formato del JSON resultante: [`radarr-custom-list.md`](radarr-custom-list.md).
