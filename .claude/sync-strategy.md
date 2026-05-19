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
| Rotation tick (interno, sin red) | scheduled | `ROTATION_TICK_INTERVAL` | 1 h | `sublist_items` de sublistas cuyo `last_rotated_at + rotation_interval ≤ now` |

**Principio**: RSS-driven en caliente, scrapes incrementales frecuentes para detectar adiciones, scrapes completos espaciados para confirmar todo lo demás.

Detalles de selectores y URLs para cada scrape: [`letterboxd-lists.md`](letterboxd-lists.md) (listas, watchlist, films, discovery) y [`letterboxd-rss.md`](letterboxd-rss.md) (RSS).

## DB autoritativa, scrape transaccional

- El JSON que servimos a Radarr en `/<user>/<slug>/`, `/<user>/watchlist/` y `/all/watchlist/<combo>/` es **siempre un SELECT de la DB**.
- Un scrape completo **solo aplica cambios** si recorre todas sus páginas sin error. Si falla a mitad, se aborta, no se persisten cambios parciales, `scrape_runs.status='error'` y `lists.last_sync_status='error'`.
- Un scrape incremental nunca elimina; solo añade. Las eliminaciones solo provienen de scrapes completos (y pasan por la verificación anti-flap).

Esto cubre el 95% de casos de parpadeo (errores transitorios, timeouts).

## Política anti-flap (eliminaciones)

Algoritmo cuando un **scrape completo** detecta `(tmdb_id ∈ list_items[list_id]) AND (tmdb_id ∉ scrape result)`:

1. **Match alternativo por (title, year)**: si el `letterboxd_slug` original ya no aparece pero hay otro slug nuevo en el scrape con mismo `title` + `year`, NO eliminar — Letterboxd renombró el slug. Actualizar `films.letterboxd_slug` y `list_items.position`. Reset `pending_removal_count=0`.

2. **¿Visto por el owner?**: si `(user_id, tmdb_id) ∈ watched_films` → **eliminar inmediatamente** del `list_items`. Caso legítimo: el RSS ya capturó el visionado y el user lo retiró de la watchlist tras verla.

3. **Backstop check ad-hoc**: lanzar un fetch a `/{user}/films/` página 1 del owner. Si el `tmdb_id` aparece allí pero no en `watched_films` (el RSS perdió el evento), insertar en `watched_films` con `source='films-page'` y eliminar el item.

4. **Sin confirmación de visto**: incrementar `list_items.pending_removal_count`. **No** retirar del estado servido todavía.

5. Cuando `pending_removal_count >= FLAP_CONFIRM_SCRAPES` (env var, default `3`) en scrapes completos consecutivos, **eliminar**.

6. Si el item reaparece en cualquier scrape posterior antes de llegar al umbral: reset `pending_removal_count=0`.

### Asimetría intencionada: adiciones sin protección

Una peli nueva que aparece en Letterboxd entra a `list_items` en el primer scrape donde la veamos.

Razón: el coste de un falso positivo es asimétrico:
- Añadir una peli incorrectamente → Radarr la descarga (consumimos ancho de banda + disco; reversible).
- Eliminar una peli incorrectamente → Radarr borra una peli que tardó semanas en bajarse (caro, frustante, a veces irreversible).

## Eventos vistos vía RSS

- Cada fetch del RSS itera los `<item>` con prefix `letterboxd-watch-` y `letterboxd-review-`.
- Dedup por `<guid>` contra `viewing_logs.letterboxd_guid`.
- Para cada nuevo guid:
  1. Insertar fila en `viewing_logs`.
  2. Upsert en `watched_films` por `(user_id, tmdb_id)`:
     - Si no existe: `first_seen_watched_at = <watched_date del item>`, `last_seen_watched_at = <watched_date>`, `source='rss'`.
     - Si existe: actualizar solo `last_seen_watched_at` (cualquier rewatch lo refresca; `first_seen_watched_at` es inmutable).
- Items con prefix `letterboxd-list-` se ignoran (las listas se descubren por `/lists/`).

## Backstop: `/films/` página 1

Cubre el gap conocido del RSS (ventana limitada a ~20-50 items).

- Frecuencia: `FILMS_BACKSTOP_INTERVAL` (default 24h).
- También se dispara ad-hoc dentro del paso 3 del anti-flap.
- Para cada `data-item-slug` extraído de la página 1 de `/films/`:
  - Resolver `tmdb_id` si no está en `films` (fetch de ficha).
  - Upsert en `watched_films` con `source='films-page'`. **No** crea entrada en `viewing_logs` (no tenemos `<guid>` ni fecha).

## Discovery de listas

- Frecuencia: `DISCOVERY_INTERVAL` (default 7d).
- Fetch a `/{user}/lists/` (+ paginación si aplica).
- Para cada `<article class="list-summary" data-film-list-id="...">`:
  - Upsert en `lists` con `letterboxd_list_id`, `slug`, `name`, `film_count`, `source_type='list'`.
  - Si es una lista nueva, `enabled=false` por defecto — la UI muestra "Lista nueva detectada, ¿activarla?".
- Listas que existían y ya no aparecen: `enabled=false` (no borrar la fila — el user puede haber tenido razones para tenerla activa).

## Rotation worker

Independiente del scraping — no toca la red. Recorre todas las sublistas con `rotation_enabled = true` cada `ROTATION_TICK_INTERVAL` (default 1 h).

Por cada sublista:

1. Si `last_rotated_at + rotation_interval > now` → skip.
2. Calcular **pool elegible** = items del parent (o de la combinada) que cumplen los filtros (`min_rating`, `max_year`, `added_after`, etc.) **y** no están actualmente en `sublist_items`.
3. Si `len(pool) >= rotation_batch_size`:
   - Sacar las `rotation_batch_size` filas de `sublist_items` con `served_since` más antiguo (FIFO temporal).
   - Insertar `rotation_batch_size` filas aleatorias del pool con `served_since = now()`.
4. Si `len(pool) < rotation_batch_size`:
   - Insertar las que haya. Sacar la misma cantidad de las más antiguas para mantener `max_items` aproximado. Si el pool está vacío, **no sacar nada** (mejor servir menos que servir vacío).
5. Update `last_rotated_at = now()`.

**Inicialización al crear**: cuando se crea una sublista con `rotation_enabled`, popular `sublist_items` con `max_items` aleatorias del pool elegible y `served_since = now()`. Si la sublista tiene `rotation_enabled = false` pero sí `max_items`, hacer lo mismo (selección random inicial) y dejarla congelada hasta que se edite.

**Recálculo al editar filtros o `max_items`**: síncrono al guardar en la UI:
- Eliminar de `sublist_items` las que ya no cumplen filtros.
- Si quedan menos de `max_items`, rellenar desde el pool actual.

**Ortogonalidad con `watched_films`**: el RSS marca pelis como vistas; las sublistas cuyo parent es `union-unwatched` o cuyos filtros excluyen vistas las pierden en la **siguiente rotación**, no al instante. Si en uso real necesitamos retirada inmediata, se añade después como flag por sublista (decisión TBD).

## Modo "arranque inicial" (cuando se añade un user)

Al añadir un user nuevo en la UI, ejecutar una secuencia única:

1. **Validar**: `GET /{user}/` → debe devolver 200 con `x-letterboxd-type: Member`.
2. **Discovery**: `/{user}/lists/`.
3. **Watchlist full sync**: scrape completo, poblar `list_items` desde cero.
4. **Films-backstop full**: `/films/` página 1, poblar `watched_films` con lo reciente.
5. **Listas habilitadas**: el user elige cuáles activar en la UI tras ver el discovery. Cada una habilitada lanza un full sync.

Luego el user entra al régimen periódico configurado.

## Configuración

Todas las `*_INTERVAL` y `FLAP_CONFIRM_SCRAPES` son **variables de entorno** con defaults razonables. Se documentan en `workflows.md` cuando se elija stack. Cambios en runtime requieren restart (a menos que decidamos hot-reload, decisión TBD).

## Cross-references

- Tablas que alimentamos: [`data-model.md`](data-model.md).
- Selectores y URLs concretas: [`letterboxd-lists.md`](letterboxd-lists.md) y [`letterboxd-rss.md`](letterboxd-rss.md).
- Formato del JSON resultante: [`radarr-custom-list.md`](radarr-custom-list.md).
