# Modelo de datos

Esquema lógico de la DB interna de watchlistarr. Motor concreto: SQLite. Las entidades, claves y relaciones que siguen son canónicas.

Doc hermano: [`sync-strategy.md`](sync-strategy.md) describe cómo se pueblan estas tablas y cuándo.

## Identidad canónica de una película

- **`tmdb_id`** (entero) es la clave canónica interna en toda la app. Es estable entre renombrados de slug en Letterboxd.
- **`imdb_id`** (string `tt…`) es **necesario para Radarr**: su parser de Custom List (`StevenLuParser.cs`) solo lee `title` y `imdb_id` y descarta cualquier item sin `imdb_id`. Se extrae del HTML de la ficha de Letterboxd (link "More at IMDb") cuando resolvemos un slug y se guarda en `films.imdb_id`. Ver [`radarr-custom-list.md`](radarr-custom-list.md#por-qué-tmdb_id-no-basta).
- El **slug de Letterboxd** (`/film/{slug}/`) es secundario. Se usa para construir URLs de scrape y como caché en `films.letterboxd_slug`. Puede cambiar entre scrapes (raro pero pasa) — cuando ocurre, persistimos el slug nuevo manteniendo el mismo `tmdb_id`.
- **Variables redundantes** para validar coincidencia en caso de cambio de slug: `title` + `year`. Si en un scrape desaparece un slug pero aparece otro con el mismo (`title`, `year`), asumimos rename y no eliminamos del listado (ver anti-flap en sync-strategy).

## Entidades

| Tabla | Clave / campos | Notas |
|---|---|---|
| `users` | `id` (PK), `letterboxd_username` (unique), `display_name`, `added_at`, `rss_interval` (nullable), `watchlist_incremental_interval` (nullable), `watchlist_full_interval` (nullable), `films_backstop_interval` (nullable), `discovery_interval` (nullable) | Un perfil de Letterboxd = un user en la app. Los `*_interval` son **overrides**: NULL = heredar el default de la env var del mismo nombre |
| `lists` | `id` (PK), `user_id` (FK), `source_type` (`list` / `watchlist`), `letterboxd_list_id` (nullable; null para watchlist), `slug`, `name`, `film_count`, `enabled`, `last_synced_at`, `last_sync_status`, `lists_incremental_interval` (nullable), `lists_full_interval` (nullable), `flap_confirm_scrapes` (nullable) | Lista importada de Letterboxd. La watchlist es solo un `source_type='watchlist'` y `slug='watchlist'`. Todas las listas (watchlist incluida) llegan `enabled=False`; el user activa lo que le interese |
| `films` | `tmdb_id` (PK), `letterboxd_slug`, `title`, `year`, `imdb_id` (nullable, unique parcial), `tmdb_type` (`movie`), `letterboxd_avg_rating` (nullable), `last_resolved_at` | Caché de la resolución HTML → TMDB/IMDb ID; global, no por user. `imdb_id` requerido por Radarr (ver radarr-custom-list.md). Rating Letterboxd persistido si la ficha lo expone |
| `list_items` | `(list_id, tmdb_id)` (PK), `position`, `added_at`, `last_seen_at`, `pending_removal_count` | `pending_removal_count` para anti-flap (ver [`sync-strategy.md`](sync-strategy.md)) |
| `custom_lists` | `id` (PK), `slug` (unique global), `name`, `op` (`union`/`intersection`), `max_items` (nullable), `sort_order`, `min_rating`, `max_rating`, `min_year`, `max_year`, `added_after`, `added_before`, `rotation_enabled`, `rotation_interval`, `rotation_batch_size`, `last_rotated_at`, `enabled` | Lista derivada multi-source con políticas (cap, filtros, rotación). Servida en `/lists/<slug>/` |
| `custom_list_sources` | `(custom_list_id, list_id, role)` (PK) | `role`: `include` o `subtract`. Una custom list puede tener N includes (combinados por `op`) y N subtracts (siempre se restan) |
| `custom_list_excluded_watchers` | `(custom_list_id, user_id)` (PK) | Films que estos users ya vieron se restan del resultado final |
| `custom_list_items` | `(custom_list_id, tmdb_id)` (PK), `served_since`, `position` | Pelis actualmente servidas. FIFO por `served_since` durante la rotación |
| `watched_films` | `(user_id, tmdb_id)` (PK), `first_seen_watched_at`, `last_seen_watched_at`, `source` (`rss` / `films-page`) | Una peli vista por un user, agregada entre todos los visionados |
| `viewing_logs` | `letterboxd_guid` (PK), `user_id` (FK), `tmdb_id`, `watched_date`, `rating`, `member_like`, `recorded_at` | Eventos crudos del RSS, dedup por `<guid>` |
| `scrape_runs` | `id` (PK), `source` (`list` / `watchlist` / `films` / `rss` / `discovery` / `rotation`), `target_id` (FK polimórfico), `started_at`, `ended_at`, `status`, `error` | Audit + soporte para anti-flap (necesitamos historial de scrapes consecutivos). **No expuesto en UI** — los logs reemplazaron este feed |

> No hay tabla global de settings. Los **defaults** de todos los intervalos viven en env vars (inmutables tras arranque); los **overrides** viven en columnas nullable de `users` y `lists`. El ritmo del rotation worker (`ROTATION_TICK_INTERVAL`) y `FLAP_CONFIRM_SCRAPES` también vienen de env, este último con override por lista.

**Nota sobre tipado**: las tablas se mapean a SQLAlchemy 2.0 `Mapped[T]` declarative. Migrations en `alembic/versions/` generadas con `--autogenerate`. Detalles en [`tech-stack.md`](tech-stack.md).

## Multi-user

- Cada `list` pertenece a exactamente un `user`.
- `films` es **global por `tmdb_id`**: dos users que tienen la misma peli comparten la fila.
- `watched_films` es **por `(user_id, tmdb_id)`**: cada user tiene su propio set de vistos.
- Las **custom lists** son **globales** (no `user_id`). Su URL es `/lists/<slug>/` y combinan listas de cualquier user.

## Custom lists: resolución

Las custom lists no son views virtuales — sus items se materializan en `custom_list_items` (igual que antes las sublists). El cómputo del **pool elegible** se hace al crear, editar o rotar:

```text
includes  = union of list_items where list_id in (sources WHERE role='include')   if op=union
            intersection                                                          if op=intersection
subtracts = union of list_items where list_id in (sources WHERE role='subtract')
watched   = union of watched_films.tmdb_id where user_id in excluded_watchers
universe  = (includes - subtracts - watched)
pool      = universe filtered by min_rating, max_rating, min_year, max_year, added_after, added_before
```

Casos comunes:

| Quiero | Sources include | op | Subtract | Excluded watchers |
|---|---|---|---|---|
| Watchlist combinada de varios users | watchlists de N users | union | — | — |
| Pelis que todos quieren ver | watchlists de N users | intersection | — | — |
| Pendientes en común (combinada menos vistas por cualquiera) | watchlists de N users | union | — | los N users |
| Lo de mi pareja que yo no he visto | watchlist de pareja | union | — | yo |
| Mi lista "2010s" menos lo que ya está en mi watchlist | lista "2010s" | union | mi watchlist | — |

## Reservas en el espacio de URLs

Las URLs servidas son:
- `/<user>/<slug>/` — lista cruda del user
- `/<user>/watchlist/` — watchlist del user (alias de `/<user>/watchlist/`)
- `/lists/<slug>/` — custom list

Hay que evitar choques.

**Reservados como `<username>`** (no se aceptan como `letterboxd_username` en la app):
- `all`, `api`, `admin`, `static`, `health`, `_`, `lists`.

**Reservados como `<slug>` bajo `/<user>/`**:
- `watchlist` — siempre apunta a la watchlist parent del user.

## Resolución de slugs ↔ TMDB ID / IMDb ID

- Cuando un scrape de lista encuentra un `data-item-slug` que no existe en `films`, lanza un fetch a `https://letterboxd.com/film/{slug}/`, parsea `body[data-tmdb-id]` y el link `imdb.com/title/tt…` con regex, y upsert en `films`.
- Si el slug ya existe **pero tiene `imdb_id IS NULL`**, `resolve_film` re-resuelve el fetch para enriquecer el campo (backfill lazy). Cuando `imdb_id` ya está, devuelve la fila cacheada sin tocar HTTP.
- Si el slug ya existe y `last_resolved_at` es antiguo (TBD: ¿1 semana?), se puede re-resolver para detectar renombrados, pero no es prioritario — los renombrados se detectan también vía cruz `(title, year)` durante el anti-flap.
- TV shows (`tmdb_type != 'movie'`) **no se persisten**. Se descartan en el scrape.

## Cross-references con otros docs

- Cómo se pueblan estas tablas y con qué frecuencia: [`sync-strategy.md`](sync-strategy.md).
- Selectores HTML que alimentan `films`, `list_items`, `lists`: [`letterboxd-lists.md`](letterboxd-lists.md).
- Eventos que alimentan `viewing_logs` y `watched_films`: [`letterboxd-rss.md`](letterboxd-rss.md).
- Formato del JSON que servimos leyendo de estas tablas: [`radarr-custom-list.md`](radarr-custom-list.md).
- Pantallas que tocan cada tabla: [`ui-features.md`](ui-features.md).
