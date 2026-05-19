# Modelo de datos

Esquema lógico de la DB interna de watchlistarr. El motor concreto (SQLite / Postgres / otro) es TBD hasta que se elija stack, pero las entidades, claves y relaciones que siguen son canónicas.

Doc hermano: [`sync-strategy.md`](sync-strategy.md) describe cómo se pueblan estas tablas y cuándo.

## Identidad canónica de una película

- **`tmdb_id`** (entero) es la clave canónica en toda la app. Es estable entre renombrados de slug en Letterboxd y es lo que Radarr necesita.
- El **slug de Letterboxd** (`/film/{slug}/`) es secundario. Se usa para construir URLs de scrape y como caché en `films.letterboxd_slug`. Puede cambiar entre scrapes (raro pero pasa) — cuando ocurre, persistimos el slug nuevo manteniendo el mismo `tmdb_id`.
- **Variables redundantes** para validar coincidencia en caso de cambio de slug: `title` + `year`. Si en un scrape desaparece un slug pero aparece otro con el mismo (`title`, `year`), asumimos rename y no eliminamos del listado (ver anti-flap en sync-strategy).

## Entidades

| Tabla | Clave / campos | Notas |
|---|---|---|
| `users` | `id` (PK), `letterboxd_username` (unique), `display_name`, `added_at` | Un perfil de Letterboxd = un user en la app |
| `lists` | `id` (PK), `user_id` (FK), `source_type` (`list` / `watchlist`), `letterboxd_list_id` (nullable; null para watchlist), `slug`, `name`, `film_count`, `enabled`, `last_synced_at`, `last_sync_status` | Lista parent (fuente). `max_items`/`sort_order`/rotación viven en `sublists`, no aquí. Watchlist = `source_type='watchlist'` y `slug='watchlist'` |
| `films` | `tmdb_id` (PK), `letterboxd_slug`, `title`, `year`, `tmdb_type` (`movie`), `letterboxd_avg_rating` (nullable), `last_resolved_at` | Caché de la resolución HTML → TMDB ID; global, no por user. Rating Letterboxd persistido si la ficha lo expone |
| `list_items` | `(list_id, tmdb_id)` (PK), `position`, `added_at`, `last_seen_at`, `pending_removal_count` | `pending_removal_count` para anti-flap (ver [`sync-strategy.md`](sync-strategy.md)) |
| `sublists` | `id` (PK), `user_id` (FK nullable), `parent_list_id` (FK nullable), `parent_combined_kind` (enum nullable), `slug`, `name`, `max_items` (nullable), `sort_order`, `min_rating`, `max_rating`, `min_year`, `max_year`, `added_after`, `added_before`, `rotation_enabled`, `rotation_interval`, `rotation_batch_size`, `last_rotated_at`, `enabled` | Vista servida con cap/filtros/rotación. Exactamente uno de `parent_list_id` o `parent_combined_kind` debe estar set. Slug único por `(user_id, slug)` o por `(parent_combined_kind, slug)` |
| `sublist_items` | `(sublist_id, tmdb_id)` (PK), `served_since`, `position` | Pelis actualmente servidas en una sublista. FIFO por `served_since` durante la rotación |
| `watched_films` | `(user_id, tmdb_id)` (PK), `first_seen_watched_at`, `last_seen_watched_at`, `source` (`rss` / `films-page`) | Una peli vista por un user, agregada entre todos los visionados |
| `viewing_logs` | `letterboxd_guid` (PK), `user_id` (FK), `tmdb_id`, `watched_date`, `rating`, `member_like`, `recorded_at` | Eventos crudos del RSS, dedup por `<guid>` |
| `scrape_runs` | `id` (PK), `source` (`list` / `watchlist` / `films` / `rss` / `discovery` / `rotation`), `target_id` (FK polimórfico), `started_at`, `ended_at`, `status`, `error` | Audit + soporte para anti-flap (necesitamos historial de scrapes consecutivos) |

## Multi-user

- Cada `list` pertenece a exactamente un `user`.
- `films` es **global por `tmdb_id`**: dos users que tienen la misma peli comparten la fila.
- `watched_films` es **por `(user_id, tmdb_id)`**: cada user tiene su propio set de vistos.
- Las **listas combinadas crudas** (`/all/watchlist/union/`, `/intersection/`, `/union-unwatched/`) no son filas — son queries virtuales sobre `list_items` y `watched_films`.
- Las **sublistas** (`sublists`) son la única "vista servida" con políticas (cap, filtros, rotación). Pueden tener como parent:
  - Una lista o watchlist concreta (`parent_list_id`) → URL bajo `/<user>/<slug>/`.
  - Una combinada virtual (`parent_combined_kind`) → URL bajo `/all/<slug>/`.

## Listas combinadas (virtuales)

Solo sobre **watchlist** en MVP (el único concepto común garantizado entre users). Universo = todos los `users` registrados.

```sql
-- /all/watchlist/union/
SELECT DISTINCT li.tmdb_id, MIN(li.position) AS position
FROM list_items li
JOIN lists l ON li.list_id = l.id
WHERE l.source_type = 'watchlist'
GROUP BY li.tmdb_id
ORDER BY position;

-- /all/watchlist/intersection/
SELECT li.tmdb_id
FROM list_items li
JOIN lists l ON li.list_id = l.id
WHERE l.source_type = 'watchlist'
GROUP BY li.tmdb_id
HAVING COUNT(DISTINCT l.user_id) = (SELECT COUNT(*) FROM users);

-- /all/watchlist/union-unwatched/
SELECT DISTINCT li.tmdb_id
FROM list_items li
JOIN lists l ON li.list_id = l.id
WHERE l.source_type = 'watchlist'
  AND li.tmdb_id NOT IN (SELECT tmdb_id FROM watched_films);
```

- Las queries se resuelven **al servir**, leyendo el estado actual de las tablas (que sí es autoritativo y estable). No hay materialización ni caché adicional — la DB interna ya garantiza que `list_items` solo cambia tras un scrape transaccional exitoso.
- Si el coste de las queries empieza a notarse en producción, se materializan en una tabla `combined_watchlist_<combo>` que se recalcula tras cada scrape de watchlist. **Decisión TBD** según motor.

## Reservas en el espacio de URLs

Las URLs servidas son `/<user>/<slug>/`, `/<user>/watchlist/`, `/all/watchlist/<combo>/` y `/all/<sublist-slug>/`. Hay que evitar choques.

**Reservados como `<user>`** (no se aceptan como `letterboxd_username` en la app):
- `all`, `api`, `admin`, `static`, `health`, `_`.

**Reservados como `<slug>` bajo `/<user>/`**:
- `watchlist` — siempre apunta a la watchlist parent del user.

**Reservados como `<slug>` bajo `/all/`**:
- `watchlist` — namespace de las 3 combinadas crudas (`/all/watchlist/union/`, etc.). No es válido como slug de sublista bajo `/all/`.

**Espacio de slugs compartido por user**: dentro de un mismo user, listas parent y sublistas comparten namespace de slugs. Si el user tiene una lista parent `watchlist-2010s`, no puede crear una sublista con el mismo slug. La UI valida en el momento de guardar.

**Decisión TBD**: qué hacer si un user tiene una lista custom llamada literalmente `watchlist` en Letterboxd. Sugerencia: añadir sufijo numérico (`watchlist-2`) al servir y al guardar en `lists.slug`. Documentar al implementar.

## Resolución de slugs ↔ TMDB ID

- Cuando un scrape de lista encuentra un `data-item-slug` que no existe en `films`, lanza un fetch a `https://letterboxd.com/film/{slug}/`, parsea `body[data-tmdb-id]` y upsert en `films`.
- Si el slug ya existe pero `last_resolved_at` es antiguo (TBD: ¿1 semana?), se puede re-resolver para detectar renombrados, pero no es prioritario — los renombrados se detectan también vía cruz `(title, year)` durante el anti-flap.
- TV shows (`tmdb_type != 'movie'`) **no se persisten**. Se descartan en el scrape.

## Cross-references con otros docs

- Cómo se pueblan estas tablas y con qué frecuencia: [`sync-strategy.md`](sync-strategy.md).
- Selectores HTML que alimentan `films`, `list_items`, `lists`: [`letterboxd-lists.md`](letterboxd-lists.md).
- Eventos que alimentan `viewing_logs` y `watched_films`: [`letterboxd-rss.md`](letterboxd-rss.md).
- Formato del JSON que servimos leyendo de estas tablas: [`radarr-custom-list.md`](radarr-custom-list.md).
