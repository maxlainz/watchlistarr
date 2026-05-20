# Features de la GUI

watchlistarr expone una GUI web (HTML server-rendered + HTMX + Pico CSS classless). Sin autenticación en MVP — la app vive en una red Docker interna junto a Radarr.

Copy de la UI **en inglés**. Los docs siguen en español.

Este doc cataloga **qué hace cada pantalla y cada acción**. El modelo de datos detrás está en [`data-model.md`](data-model.md); cuándo se ejecutan los workers que pueblan estas pantallas, en [`sync-strategy.md`](sync-strategy.md); el formato de los endpoints servidos a Radarr, en [`radarr-custom-list.md`](radarr-custom-list.md).

## Estructura de pestañas

Cinco entradas en la nav del header:

| Tab | URL HTML | Propósito |
|---|---|---|
| Dashboard | `/` | Resumen de un vistazo (counts + errores recientes) |
| Users | `/users` | Gestionar usuarios de Letterboxd + activar/desactivar las listas que se monitorean por cada uno |
| Lists | `/lists-view` | Vista global, solo lectura, de todas las listas habilitadas, con la URL para Radarr de cada una |
| Custom Lists | `/custom-lists` | CRUD de custom lists multi-source |
| Activity | `/activity` | Tail en vivo del stdout del contenedor |

> La pestaña de la nav se llama "Lists" pero la URL HTML es `/lists-view` para no chocar con el namespace `/lists/<slug>/` usado para servir custom lists a Radarr.

## Páginas / vistas

### Dashboard (`/`)
Cards mínimas:
- `Users registered` → link a `/users`
- `Lists monitored` → link a `/lists-view`
- `Custom lists active` → link a `/custom-lists`
- `Last successful scrape` — timestamp del último `scrape_runs.status=success`
- Banner rojo si hay `scrape_runs.status=error` en la última hora

Sin feed de scrape_runs ni nada técnico embebido (eso vive en Activity ahora).

### Users (`/users`)
- Tabla: username · display name · listas habilitadas (count) · actions (delete).
- Form "+ Add user".
- Al añadir un user nuevo: validar con `GET https://letterboxd.com/{user}/` + cabecera `x-letterboxd-type: Member`. Si OK, lanzar background discovery (descubre watchlist + listas públicas, todas como `enabled=False`) + films-backstop. **No** se scrapea la watchlist automáticamente.

### Detalle de user (`/users/<username>`)
- Datos del user.
- Sección **"Discovered lists"** — tabla con TODAS las listas (watchlist primero, luego públicas). Toggle Enable/Disable por fila. La watchlist **no está hardcoded como enabled**: se trata igual que cualquier otra.
- Colapsable `<details>` "⚙ Advanced" al final con form para los 5 overrides de intervalos del user (rss_interval, watchlist_*_interval, films_backstop_interval, discovery_interval). Vacío = heredar default de env.

### Lists (`/lists-view`)
- Vista global agrupada por user (un `<article>` por usuario).
- Por cada lista habilitada: name · items · last sync · status · **Radarr URL** (`<code>` + botón Copy) · colapsable Advanced con overrides de `lists_incremental_interval`, `lists_full_interval`, `flap_confirm_scrapes`.
- Solo lectura para activar/desactivar (eso está en Users).
- Las listas deshabilitadas no aparecen aquí.

### Custom Lists (`/custom-lists`)
- Tabla única: name · slug · sources summary (texto generado por `services.custom_lists.describe_sources()`) · items served · Radarr URL · Edit · Delete.
- Botón "+ New custom list".

### Editor de custom list (`/custom-lists/new`, `/custom-lists/<slug>/edit`)
Form único para crear y editar. Secciones:

1. **Basics**: name, slug (lowercase + dashes; readonly en edit).
2. **Sources to include** — checkboxes agrupados por user (acordeones), watchlist primero. Selección múltiple.
3. **Combine with**: `Union (any of them)` | `Intersection (all of them)`.
4. **Sources to subtract** (optional) — checkboxes como en includes.
5. **Exclude already watched by** (optional) — checkboxes de users.
6. **Preview** — botón "Refresh preview" que hace POST a `/custom-lists/preview` con HTMX y devuelve el conteo del pool elegible (sin persistir nada).
7. **Serving**: Max items, Order (letterboxd/random/reverse).
8. **Static filters**: min/max rating, min/max year.
9. **Time rotation**: Enable + batch size.

Al guardar:
- Crear: persistir custom_list + sources + excluded_watchers, llamar `init_items()` para popular `custom_list_items`.
- Editar: actualizar atributos + reemplazar sources + reemplazar excluded_watchers + llamar `recalculate()` (drop items que ya no califican, rellenar hasta `max_items`).

### Activity (`/activity`)
- Tail en vivo del stdout del contenedor.
- Implementación: handler de logging escribe a un buffer circular en memoria (~2000 líneas). Endpoint `GET /activity/tail?since=<seq>` devuelve fragment HTML con líneas nuevas. La pestaña hace polling con HTMX `hx-trigger="every 2s"` y `hx-swap="outerHTML"` sobre un span trigger al final del `<pre>`.
- Filtro por nivel: `All` / `DEBUG` / `INFO` / `WARNING` / `ERROR`.
- Botón "Download full log" → `GET /activity/download` (texto plano).

La tabla `scrape_runs` sigue existiendo en DB (la usa el anti-flap). **No se expone en UI.**

## Acciones operacionales — resumen

| Acción | Página | Notas |
|---|---|---|
| Add user | `/users` | Valida + background discovery; nada queda enabled |
| Delete user | `/users` | Confirmación; cascade (sus lists + custom lists vinculadas pierden sources) |
| Enable/Disable list | `/users/<user>` | Toggle inline. La watchlist se comporta igual que las demás |
| Edit per-user intervals | `/users/<user>` → Advanced | Inline en el detalle |
| Edit per-list settings | `/lists-view` → Advanced | Inline por fila |
| Copy Radarr URL | `/lists-view` o `/custom-lists` | Botón Copy junto al `<code>` |
| Create / edit / delete custom list | `/custom-lists/...` | Editor unificado multi-source |
| Watch live log | `/activity` | Polling HTMX cada 2 s |
| Download full log | `/activity/download` | Adjunto descargable |

## Lo que NO está en GUI

Variables de proceso (necesarias antes de que la app arranque su web):

- `HTTP_PORT` — puerto del servidor web.
- `LOG_LEVEL` / `LOG_FORMAT` — config de logging.
- `DATABASE_URL` — path del volumen de DB.
- `USER_AGENT` — UA con el que watchlistarr se identifica a Letterboxd.
- `ROTATION_TICK_INTERVAL`, `FLAP_CONFIRM_SCRAPES` (este último admite override por lista).

Todas las custom lists viven en `/lists/<slug>/`. **Ya no existen** las URLs `/all/watchlist/<combo>/` ni `/all/<slug>/` — rotura intencional al introducir multi-source. Tras desplegar este cambio, hay que reconfigurar Radarr con las nuevas URLs.
