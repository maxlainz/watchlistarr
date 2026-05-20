# Arquitectura

## Flujo general

```
Letterboxd (HTML + RSS, multi-user)
        │
        ▼
   Sync workers ─ scraper de listas (incremental + full)
                ├ RSS watcher
                ├ films-backstop
                ├ discovery
                └ rotation worker (sin red)
        │
        ▼
   DB interna (multi-user, autoritativa)  ◀────────  UI de control (React SPA + JSON API)
        │
        ▼
   API HTTP
   ├ /<user>/<slug>/    (lista cruda del user)
   ├ /<user>/watchlist/ (watchlist del user, si está enabled)
   └ /lists/<slug>/     (custom list multi-source)
        │
        ▼
   Radarr (Custom Lists, una por endpoint)
```

- Los sync workers traducen Letterboxd a DB. Cada uno con su frecuencia configurable (ver [`sync-strategy.md`](sync-strategy.md)).
- La DB es **autoritativa**: lo que servimos a Radarr es siempre un SELECT, nunca on-the-fly.
- La UI deja al usuario añadir perfiles de Letterboxd, activar listas descubiertas (watchlist incluida) y crear custom lists multi-source con sus políticas (cap, filtros, rotación). Detalles: [`ui-features.md`](ui-features.md).
- Las custom lists son **multi-source**: combinan N listas con `op=union/intersection`, opcionalmente restan otras listas (`role=subtract`) y restan films vistos por users seleccionados (`excluded_watchers`). Su cómputo vive en `custom_list_items`. Las viejas "combinadas predefinidas" (`union` / `intersection` / `union-unwatched`) desaparecieron: ahora son casos del editor multi-source.

## Componentes objetivo

### Sync workers (per-user, configurables, transaccionales)
- **Scraper de listas**: dos modos (incremental + full). Incremental detecta adiciones en O(2) fetches usando `/by/added-earliest/`. Full recorre toda la lista para detectar eliminaciones y reordenamientos. Detalles: [`letterboxd-lists.md`](letterboxd-lists.md), [`sync-strategy.md`](sync-strategy.md).
- **RSS watcher**: polling al RSS del usuario, captura eventos de visionado en caliente. Dedup por `<guid>`. Detalles: [`letterboxd-rss.md`](letterboxd-rss.md).
- **Films-backstop**: scrape periódico de `/{user}/films/` página 1 (≈72 últimos vistos) para rellenar gaps del RSS. También se dispara ad-hoc durante el anti-flap.
- **Discovery**: scrape periódico de `/{user}/lists/` para detectar listas nuevas o eliminadas. Las nuevas entran como `enabled=false`; el user las activa desde la UI.

### Custom lists (multi-source)
- Una custom list referencia N `lists` como `include` sources (combinadas con `op=union` o `intersection`), N como `subtract` sources (siempre se restan) y N `users` como `excluded_watchers` (sus `watched_films` se restan).
- Se sirven en `/lists/<slug>/`. Slug único global.
- Soportan cap (`max_items`), filtros estáticos (rating, año, fecha de adición) y rotación temporal opcional.
- Resolución detallada en [`data-model.md`](data-model.md#custom-lists-resolución).

### Rotation worker
- Independiente del scraping, no toca la red. Recorre custom lists con rotación activada cada `ROTATION_TICK_INTERVAL` (default 1 h) y aplica FIFO temporal: saca las que llevan más tiempo servidas, mete random del pool elegible. Detalles: [`sync-strategy.md`](sync-strategy.md).

### DB interna
- Esquema canónico en [`data-model.md`](data-model.md). Multi-user nativo, identidad por `tmdb_id`.
- Motor TBD (SQLite probable).

### API a Radarr
- Endpoints HTTP que devuelven el array JSON de Custom List leyendo desde la DB. Detalles del formato: [`radarr-custom-list.md`](radarr-custom-list.md).
- Sin autenticación en MVP (asumimos red Docker interna).

### UI de control
- SPA React 18 con tema oscuro, servida desde `src/watchlistarr/static/`. Sin build step: `@babel/standalone` compila los `.jsx` en el navegador. React, ReactDOM, Babel y las fuentes Geist están vendorizados en `static/vendor/` para que el contenedor funcione offline.
- Backend expone JSON-only bajo `/api/v1/*`; la SPA hace `GET /api/v1/bootstrap` al cargar y luego CRUD contra los recursos individuales.
- Catálogo completo de páginas y acciones: [`ui-features.md`](ui-features.md).

## Principios de diseño

1. **DB autoritativa**. Lo servido a Radarr es siempre un SELECT, nunca on-the-fly. Evita parpadeos que llevarían a Radarr a borrar pelis que tardaron semanas en bajar.
2. **RSS-driven en caliente**. Cambios de vistos llegan por RSS con baja latencia. Los scrapes son para arranque inicial y verificación.
3. **Anti-flap por verificación cruzada**. Antes de retirar un item de la lista servida: cruzar con `watched_films`, con `/films/` backstop y con `(title, year)` para detectar rename. Solo eliminar tras `FLAP_CONFIRM_SCRAPES` (default 3) confirmaciones consecutivas.
4. **Multi-user nativo**. Una instancia soporta N perfiles. Las custom lists pueden combinar listas de cualquier user.
5. **Todo configurable**. Frecuencias de RSS, watchlist (incremental + full), listas (incremental + full), films-backstop y discovery son variables de entorno.

## Decisiones técnicas

Stack completo en [`tech-stack.md`](tech-stack.md). Resumen:

- **Backend**: Python 3.12+ con FastAPI.
- **DB**: SQLite + SQLAlchemy 2.0 async + Alembic.
- **Frontend**: React 18 + Babel-standalone, dark theme; vanilla CSS con design tokens en `static/styles.css`. Sin build step. Datos via `fetch` contra `/api/v1/*`.
- **Scheduling**: APScheduler dentro del mismo proceso FastAPI.
- **Scraping**: httpx + BeautifulSoup4/lxml + feedparser.
- **Packaging**: uv + Docker `python:3.12-slim`.

Los cambios de stack se documentan aquí cuando se tomen — `tech-stack.md` es la fuente canónica.

## Docker

- Una sola imagen, multi-stage build:
  - **Builder**: `python:3.12-slim`, instala `uv`, ejecuta `uv sync --frozen --no-dev`.
  - **Runtime**: `python:3.12-slim`, copia `.venv` + `src/` + `alembic/`.
- Tamaño esperado ~150–180 MB.
- Un solo proceso (`uvicorn watchlistarr.main:app`) con APScheduler embebido. Sin supervisord.
- Volumen `/data` para el archivo SQLite (`DATABASE_URL=sqlite+aiosqlite:///data/watchlistarr.db`).
- Healthcheck: `GET /healthz` → 200 si la DB es accesible.
- Variables de entorno: ver [`workflows.md`](workflows.md).
- Los users de Letterboxd se añaden vía UI, **no** por env (multi-user). Primer arranque presenta el wizard.
- Detalles del Dockerfile y del wiring de procesos: [`tech-stack.md`](tech-stack.md).

## Integración con Radarr

Mecanismo: **Custom List** (no la API de Radarr). Radarr hace polling a una URL HTTP de watchlistarr y recibe un array JSON de películas con `tmdb_id`. Frecuencia de polling y comportamiento de auto-add se configuran en Radarr, no aquí.

Spec completa, formato JSON, pitfalls y referencias: [`radarr-custom-list.md`](radarr-custom-list.md).

## Letterboxd: estructura conocida

- **Discovery + listas + fichas (HTML)**: a partir de un username se descubren watchlist + todas las listas públicas creadas; spec completa de selectores, paginación, resolución de TMDB ID y anti-bot: [`letterboxd-lists.md`](letterboxd-lists.md).
- **RSS de usuario**: `https://letterboxd.com/{user}/rss/`. Spec completa del feed (namespaces, tipos de item, schemas, edge cases): [`letterboxd-rss.md`](letterboxd-rss.md).
- **No usar autenticación**: el proyecto se limita a contenido público.
