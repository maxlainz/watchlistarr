# Features de la GUI

watchlistarr expone una GUI web (HTML server-rendered + HTMX) para que el usuario configure todo lo que no son secretos o ajustes de proceso. Sin autenticación en MVP — la app vive en una red Docker interna junto a Radarr.

Este doc cataloga **qué hace cada pantalla y cada acción**. El modelo de datos detrás está en [`data-model.md`](data-model.md); cuándo se ejecutan los workers que pueblan estas pantallas, en [`sync-strategy.md`](sync-strategy.md); el formato de los endpoints servidos a Radarr, en [`radarr-custom-list.md`](radarr-custom-list.md).

## Páginas / vistas

### Dashboard (`/`)
Resumen multi-user de un vistazo. Por cada user registrado:

- Estado de sus listas habilitadas: nº items, timestamp del último sync, `last_sync_status` (verde/rojo), `pending_removal_count` si > 0.
- Sus sublistas: nº items servidos, próxima rotación (si aplica), errores recientes.
- Botón **Forzar refresco** por user (lanza RSS + watchlist incremental + films-backstop).

### Users (`/users`)
Listado de users registrados con botón **+ Añadir user**.

- Añadir user: input `letterboxd_username`. Antes de guardar, validación con `GET https://letterboxd.com/{user}/` + cabecera `x-letterboxd-type: Member`. Rechazar si el username está en reservas (`all`, `api`, etc., ver [`data-model.md`](data-model.md)).
- Tras añadir: lanza el "arranque inicial" descrito en [`sync-strategy.md`](sync-strategy.md) (discovery + watchlist full + films-backstop + listas habilitadas).
- Eliminar user: confirmación explícita. Cascade: sus `lists`, `sublists`, `watched_films`, `viewing_logs` se borran; las combinadas `/all/` se recalculan en el siguiente render.

### Detalle de user (`/users/<user>`)
Todo lo de un user en una página:

- **Listas descubiertas** (de `/{user}/lists/`) con toggle activar/desactivar.
- **Watchlist personal** — fija, siempre presente, siempre habilitada.
- **Lista nueva detectada** — banner cuando el discovery encuentra una lista que no estaba antes, con CTA "Activar" / "Ignorar".
- **Añadir lista privada manualmente** — input para pegar la URL completa (`https://letterboxd.com/{user}/list/{slug}/`). Útil para listas privadas que el discovery no ve.
- **Botón "Forzar refresco"** por lista (lanza scrape incremental al vuelo).
- **Sublistas creadas por este user** con su slug, parent y resumen de políticas.
- **Botón "+ Nueva sublista"** → editor.

### Editor de sublista (`/users/<user>/sublists/new`, `…/<sublist-slug>`)
Wizard único usado para crear y editar.

Campos:

1. **Parent**: dropdown con todas las listas habilitadas del user + su watchlist personal + las 3 combinadas (`/all/watchlist/union`, `/intersection/`, `/union-unwatched/`).
2. **Slug** (segmento URL bajo `/<user>/` o `/all/`).
3. **Nombre** (display).
4. **Cap (`max_items`)** — opcional. Sin cap = sirve toda la lista filtrada.
5. **Sort order** dentro del set servido.
6. **Filtros estáticos** (todos opcionales):
   - Rating Letterboxd: `min_rating` / `max_rating`.
   - Año: `min_year` / `max_year`.
   - Fecha de añadido al parent: `added_after` / `added_before`.
7. **Rotación**:
   - Activar / desactivar.
   - Intervalo (`7d`, `30d`, libre).
   - `rotation_batch_size` (cuántas entran y salen en cada tick).
8. **Preview en vivo**:
   - Tamaño del **pool elegible** (items del parent que cumplen filtros).
   - Si se está editando: items **actualmente servidos** vs items que entrarían/saldrían si se rota ahora.

Al guardar:
- Crear: popular `sublist_items` con `max_items` aleatorias del pool. `served_since = now()`.
- Editar: eliminar items que ya no cumplen filtros; rellenar hasta `max_items` desde el pool restante.

### Combinadas (`/all`)
Listado de:
- Las **3 combinadas crudas** (`union`, `intersection`, `union-unwatched`) con su URL y nº items actual.
- Las **sublistas creadas sobre combinadas** (`/all/<slug>/`) con su parent (qué combinada usa) y políticas.
- Botón **+ Nueva sublista sobre combinada** → mismo editor.

### Intervalos de user (`/users/<user>/intervals`)
Form con 5 inputs opcionales (vacío = heredar default de env, mostrado como placeholder):

- `rss_interval`
- `watchlist_incremental_interval`, `watchlist_full_interval`
- `films_backstop_interval`
- `discovery_interval`

Submit guarda los overrides en `users.*` y llama a `scheduler.sync_jobs()` para re-crear los jobs de ese user con el nuevo trigger.

### Settings de lista (`/users/<user>/lists/<list-slug>/settings`)
Form con 3 inputs opcionales (vacío = heredar default de env):

- `lists_incremental_interval`, `lists_full_interval`
- `flap_confirm_scrapes` (umbral anti-flap)

Submit guarda en `lists.*` y re-aplica el scheduler. Los inputs vacíos se persisten como `NULL`.

> No existe pantalla global `/settings`. `ROTATION_TICK_INTERVAL` (ritmo del worker interno) es env-only.

### Activity (`/activity`)
Feed de `scrape_runs` con filtros por user, source (rss/watchlist/lists/films/discovery/rotation) y status. Útil para depurar errores intermitentes.

### Endpoints (`/endpoints`)
Tabla con todas las URLs servidas, agrupadas:

- **Parents crudos** (`/<user>/<slug>/`, `/<user>/watchlist/`).
- **Sublistas de user** (`/<user>/<sublist-slug>/`).
- **Combinadas crudas** (`/all/watchlist/union/`, `/intersection/`, `/union-unwatched/`).
- **Sublistas combinadas** (`/all/<sublist-slug>/`).

Cada fila con un botón **Copiar URL** para pegar en Radarr.

## Acciones operacionales — resumen

| Acción | Página | Notas |
|---|---|---|
| Añadir user | `/users` | Valida con `GET /{user}/`; lanza arranque inicial |
| Eliminar user | `/users` | Confirmación; cascade |
| Activar/desactivar lista | `/users/<user>` | Toggle |
| Añadir lista privada por URL | `/users/<user>` | Para listas que el discovery no ve |
| Forzar refresco | dashboard / `/users/<user>` | Scrape incremental al vuelo |
| Crear / editar / eliminar sublista | `/users/<user>/sublists/...` o `/all/...` | Editor unificado |
| Override intervalos de un user | `/users/<user>/intervals` | Vacío = heredar env |
| Override settings de una lista | `/users/<user>/lists/<slug>/settings` | Incl. `flap_confirm_scrapes`; vacío = heredar env |
| Ver log de actividad | `/activity` | Filtrable |
| Copiar URL para Radarr | `/endpoints` | Una por endpoint |

## Lo que NO está en GUI

Variables de proceso (necesarias antes de que la app arranque su web):

- `HTTP_PORT` — puerto del servidor web.
- `LOG_LEVEL` — nivel de log.
- Path del volumen de DB.
- `USER_AGENT` — UA con el que watchlistarr se identifica a Letterboxd.

Cualquier credencial futura (e.g. TMDB API key si se añade como fallback) también irá por env.
