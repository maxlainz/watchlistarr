# Features de la GUI

watchlistarr expone una GUI web dark-themed: **SPA React 18** (sin build step — Babel-standalone compila los `.jsx` en el navegador) servida desde `/`, alimentada por el JSON API bajo `/api/v1/*`. Sin autenticación en MVP — la app vive en una red Docker interna junto a Radarr.

Copy de la UI **en inglés**. Los docs siguen en español.

Este doc cataloga **qué hace cada pantalla y cada acción**. El modelo de datos detrás está en [`data-model.md`](data-model.md); cuándo se ejecutan los workers que pueblan estas pantallas, en [`sync-strategy.md`](sync-strategy.md); el formato de los endpoints servidos a Radarr, en [`radarr-custom-list.md`](radarr-custom-list.md).

## Layout

Sidebar fijo a la izquierda (248px) con:

- Marca + tag mono `letterboxd → radarr`.
- 5 entradas de navegación con contador (Users / Lists / Custom Lists con counts en mono).
- Footer con `status-dot` + resumen de errores recientes / items servidos.

La SPA mantiene estado client-side (no hay rutas reales — `setPage(id)` cambia la vista activa). El topbar muestra breadcrumbs y un botón "Docs" que abre el repo.

| Vista | Estado React | Datos backend |
|---|---|---|
| Dashboard | `page='dashboard'` | `GET /api/v1/dashboard` (refrescado cada 15 s) |
| Users | `page='users'` | Estado bootstrap, mutaciones via API |
| User detail | `page='user-detail'` con `pageParam=userId` | `POST /api/v1/users/{u}/lists/{id}/toggle` |
| Lists | `page='lists'` | Mismo array `users` filtrado a lists enabled |
| Custom Lists | `page='custom-lists'` | `GET /api/v1/custom-lists` |
| Custom List editor | `page='custom-list-editor'` con `pageParam='new'` o `slug` | `POST/PUT/DELETE /api/v1/custom-lists/{slug}`, `POST .../preview` |
| Activity | `page='activity'` | `GET /api/v1/activity?since=<seq>` polled cada 2 s |

Al cargar, App.jsx hace `GET /api/v1/bootstrap` (single round-trip que devuelve `{users, customLists, dashboard}`). Mientras carga muestra un `LoadingShell`.

## Páginas

### Dashboard
- 4 stat cards con sparkline (Users / Lists / Custom lists / Items served). Click navega al tab correspondiente.
- Banner rojo si `dashboard.stats.recentErrors > 0` con link a Activity.
- **Recent activity** — feed de los últimos `scrape_runs`, con icono por kind (sync/error/rotation/watched).
- **Next scheduled** — próximos 5 jobs de APScheduler (`scheduler.upcoming_jobs(limit=5)`), con ETA humano (`in 22 min`, `in 1h 14m`).

### Users
- Form "Add user" con prefijo mono `letterboxd.com/` baked in, validación contra Letterboxd antes de persistir.
- Search inline filtra por username.
- Tabla: avatar + `@username` + path mono · "N of M" listas habilitadas (badge ámbar si N>0) · total · added (relativo) · ⚙ + 🗑.
- Fila click → User detail. Add lanza `_initial_run_in_background` (ensure watchlist row + discovery + films-backstop) y muestra toast.

### User detail
- Header con avatar grande + path mono + acciones (Delete).
- Card "Discovered lists" con `Switch` por fila (toggle vía API). Watchlist primero, resto alpha.
- Cada fila muestra: name + slug mono · film count · last sync (relativo) · status badge (`synced` / `error` / `pending`) · link externo a Letterboxd.
- Empty state cuando `lists.length === 0` (discovery aún corriendo).

### Lists
- Vista global agrupada por user (`user-block` por user). Solo lists con `enabled=true`.
- Por cada lista: name + tipo + film count + last sync + status + `CodeLine` con la URL Radarr (copy-to-clipboard inline) + toggle Advanced.
- Advanced panel inline (no modal): inputs en horas con placeholder mostrando el default heredado del env (`X (default)`):
  - Watchlist row → `users.watchlist_incremental_interval`, `users.watchlist_full_interval`, `lists.flap_confirm_scrapes`.
  - List row → `lists.lists_incremental_interval`, `lists.lists_full_interval`, `lists.flap_confirm_scrapes`.
- Save → `POST /api/v1/users/{u}/lists/{id}/settings`, refresca el bootstrap.

### Custom Lists
- Card grid (auto-fill 420px+). Cada card:
  - Icono según `op` (layers para union, sparkle para intersection).
  - Name + slug mono.
  - Pills de operación, número de sources, watchers excluidos, rotation on/off.
  - Resumen textual de fuentes (servicio `describe_sources`).
  - Items served + max + `CodeLine` con la URL Radarr `/lists/<slug>/`.
- Card click → editor.
- Botón primary `+ New custom list`.

### Custom List editor
Form en una sola página con secciones:

1. **Basics** — name, slug mono (readonly en edit, derivado de name en new).
2. **Sources to include** — `SourcePicker` (acordeones por user, **cerrado por defecto**; auto-open si ya hay selección al editar). Badge ámbar "N selected" en el header del user. Cada lista muestra type + film count.
3. **Combine with** — dos radio cards: Union (any of) / Intersection (all of).
4. **Sources to subtract** *(optional)* — mismo `SourcePicker`, oculto hasta que clickas "Add subtract sources".
5. **Exclude already-watched** *(optional)* — checkboxes de users.
6. **Preview pool** — `POST /api/v1/custom-lists/preview` con el body actual; devuelve `{pool: N}`. No persiste.
7. **Serving** — Max items + Sort order (letterboxd / random / reverse).
8. **Static filters** *(optional)* — min/max rating; **release year** con toggle Fixed/Relative (Fixed: min/max year; Relative: "Released in the last N years" con helper que muestra el rango resuelto, p.ej. `= 2022–2026`); **added in the last N days** (input relativo único). Los modos relativos se persisten en `year_last_n` / `added_last_n_days` y se recalculan contra `utcnow()` en cada serve.
9. **Time rotation** *(optional)* — toggle + interval (horas) + batch size.

Save → `POST /api/v1/custom-lists` (nuevo) o `PUT /api/v1/custom-lists/<slug>` (edit). El backend reusa `init_items` / `recalculate` del service existente.

### Activity
- Toolbar con `LIVE` dot + level pills (counts por nivel) + búsqueda inline + toggle auto-scroll.
- Body: log lines en mono, color por nivel (info/warn/error/debug), `borderLeft` rojo para ERROR.
- Polling cada 2 s (`window.API.activity(since)`); auto-scroll se desactiva si el user scrollea arriba.
- Botón "Download full log" → `GET /api/v1/activity/download`.

## Tweaks panel

`tweaks-panel.jsx` viene del bundle de claude.ai/design y solo se activa cuando un parent window le manda `__activate_edit_mode`. En producción es invisible. Si se activa, expone:

- Accent color (4 swatches: amber / violet / teal / rose) → rewrites `--accent*` vars en tiempo real.
- Density (cozy / compact) → `data-density="compact"` baja `--row-h`, `--pad`, `--gap`.

## Acciones operacionales — resumen

| Acción | Endpoint | Notas |
|---|---|---|
| Add user | `POST /api/v1/users` | Valida en Letterboxd + lanza background discovery; nada queda enabled |
| Delete user | `DELETE /api/v1/users/{u}` | Cascade vía SQLAlchemy |
| Enable/Disable list | `POST /api/v1/users/{u}/lists/{id}/toggle` | Re-syncea los jobs del scheduler |
| Edit per-list settings | `POST /api/v1/users/{u}/lists/{id}/settings` | Body JSON con `incrementalInterval`, `fullInterval`, `flapConfirmScrapes` en horas/integer |
| Copy Radarr URL | (UI) `CodeLine` component | Click en el icono copy → toast |
| Create / edit / delete custom list | `POST/PUT/DELETE /api/v1/custom-lists/[slug]` | Editor unificado multi-source con rotation en horas |
| Preview eligible pool | `POST /api/v1/custom-lists/preview` | No persiste; devuelve `{pool}` |
| Watch live log | `GET /api/v1/activity?since=<seq>` | Polling cada 2 s desde Activity.jsx |
| Download full log | `GET /api/v1/activity/download` | Adjunto descargable |

## Lo que NO está en GUI

Variables de proceso (necesarias antes de que la app arranque su web):

- `HTTP_PORT` — puerto del servidor web.
- `LOG_LEVEL` / `LOG_FORMAT` — config de logging.
- `DATABASE_URL` — path del volumen de DB.
- `USER_AGENT` — UA con el que watchlistarr se identifica a Letterboxd.
- `ROTATION_TICK_INTERVAL` — ritmo del worker de rotación.
- `RSS_INTERVAL`, `DISCOVERY_INTERVAL`, `FILMS_BACKSTOP_INTERVAL` — son por-user pero solo se configuran via env (no expuestos en UI).
- `FLAP_CONFIRM_SCRAPES` — default global, admite override por lista en la pestaña Lists → Advanced.

Todas las custom lists viven en `/lists/<slug>/`. **Ya no existen** las URLs `/all/watchlist/<combo>/` ni `/all/<slug>/` — rotura intencional al introducir multi-source. Tras desplegar este cambio, hay que reconfigurar Radarr con las nuevas URLs.
