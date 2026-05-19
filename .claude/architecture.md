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
   DB interna (multi-user, autoritativa)  ◀────────  UI de control (HTMX)
        │
        ▼
   API HTTP
   ├ /<user>/<slug>/        (lista parent cruda)
   ├ /<user>/<sublist>/     (sublista del user con cap/filtros/rotación)
   ├ /<user>/watchlist/     (watchlist personal cruda)
   ├ /all/watchlist/<combo> (combinada cruda)
   └ /all/<sublist>/        (sublista sobre combinada)
        │
        ▼
   Radarr (Custom Lists, una por endpoint)
```

- Los sync workers traducen Letterboxd a DB. Cada uno con su frecuencia configurable (ver [`sync-strategy.md`](sync-strategy.md)).
- La DB es **autoritativa**: lo que servimos a Radarr es siempre un SELECT, nunca on-the-fly.
- La UI deja al usuario añadir perfiles de Letterboxd, activar listas descubiertas y crear sublistas con sus políticas (cap, filtros, rotación). Detalles: [`ui-features.md`](ui-features.md).
- Las listas combinadas crudas (`/all/watchlist/...`) son queries virtuales sobre las watchlists de todos los users registrados. Las sublistas pueden tener como parent una combinada.

## Componentes objetivo

### Sync workers (per-user, configurables, transaccionales)
- **Scraper de listas**: dos modos (incremental + full). Incremental detecta adiciones en O(2) fetches usando `/by/added-earliest/`. Full recorre toda la lista para detectar eliminaciones y reordenamientos. Detalles: [`letterboxd-lists.md`](letterboxd-lists.md), [`sync-strategy.md`](sync-strategy.md).
- **RSS watcher**: polling al RSS del usuario, captura eventos de visionado en caliente. Dedup por `<guid>`. Detalles: [`letterboxd-rss.md`](letterboxd-rss.md).
- **Films-backstop**: scrape periódico de `/{user}/films/` página 1 (≈72 últimos vistos) para rellenar gaps del RSS. También se dispara ad-hoc durante el anti-flap.
- **Discovery**: scrape periódico de `/{user}/lists/` para detectar listas nuevas o eliminadas. Las nuevas entran como `enabled=false`; el user las activa desde la UI.

### Combined views (crudas)
- `/all/watchlist/union/`, `/all/watchlist/intersection/`, `/all/watchlist/union-unwatched/`. Resueltas con queries SQL sobre `list_items` + `watched_films`. Universo = todos los users registrados, siempre.

### Sublistas
- Vistas servidas con cap (`max_items`), filtros estáticos (rating, año, fecha de adición) y rotación temporal opcional. Cada sublista tiene su propia URL bajo `/<user>/<slug>/` o `/all/<slug>/`.
- Modelo: [`data-model.md`](data-model.md). Operaciones desde UI: [`ui-features.md`](ui-features.md).

### Rotation worker
- Independiente del scraping, no toca la red. Recorre sublistas con rotación activada cada `ROTATION_TICK_INTERVAL` (default 1 h) y aplica FIFO temporal: saca las que llevan más tiempo servidas, mete random del pool elegible. Detalles: [`sync-strategy.md`](sync-strategy.md).

### DB interna
- Esquema canónico en [`data-model.md`](data-model.md). Multi-user nativo, identidad por `tmdb_id`.
- Motor TBD (SQLite probable).

### API a Radarr
- Endpoints HTTP que devuelven el array JSON de Custom List leyendo desde la DB. Detalles del formato: [`radarr-custom-list.md`](radarr-custom-list.md).
- Sin autenticación en MVP (asumimos red Docker interna).

### UI de control
- HTML server-rendered + HTMX. Sin SPA, sin build step si se puede evitar.
- Catálogo completo de páginas y acciones: [`ui-features.md`](ui-features.md).

## Principios de diseño

1. **DB autoritativa**. Lo servido a Radarr es siempre un SELECT, nunca on-the-fly. Evita parpadeos que llevarían a Radarr a borrar pelis que tardaron semanas en bajar.
2. **RSS-driven en caliente**. Cambios de vistos llegan por RSS con baja latencia. Los scrapes son para arranque inicial y verificación.
3. **Anti-flap por verificación cruzada**. Antes de retirar un item de la lista servida: cruzar con `watched_films`, con `/films/` backstop y con `(title, year)` para detectar rename. Solo eliminar tras `FLAP_CONFIRM_SCRAPES` (default 3) confirmaciones consecutivas.
4. **Multi-user nativo**. Una instancia soporta N perfiles + combinadas en `/all/`.
5. **Todo configurable**. Frecuencias de RSS, watchlist (incremental + full), listas (incremental + full), films-backstop y discovery son variables de entorno.

## Decisiones pendientes (TBD)

- **Lenguaje backend**: Python / Node-TS / Go. Decisivo para todo lo demás.
- **Motor de templates**: dependiente del backend (Jinja, Pug/EJS, html/template, Nunjucks…).
- **DB**: SQLite (recomendado) vs Postgres (overkill para un single-user self-hosted).
- **Scheduler**: cron interno del proceso vs job runner (APScheduler / node-cron / robfig/cron).
- **Cliente HTTP / parser HTML**: depende del backend (requests+bs4 / undici+cheerio / colly).

Estas decisiones se documentan aquí cuando se tomen — no antes.

## Docker

- Una sola imagen que arranca scraper + scheduler + API + UI en el mismo proceso (o supervisord si la división por procesos lo justifica).
- Volumen montado para persistir la DB (`/data` o equivalente).
- Variables de entorno principales (defaults sugeridos en [`sync-strategy.md`](sync-strategy.md)):
  - `HTTP_PORT` — puerto de UI/API.
  - `LOG_LEVEL` — verbosity.
  - `RSS_INTERVAL` — polling del RSS de cada user.
  - `WATCHLIST_INCREMENTAL_INTERVAL`, `WATCHLIST_FULL_INTERVAL` — scrapes de watchlist.
  - `LISTS_INCREMENTAL_INTERVAL`, `LISTS_FULL_INTERVAL` — scrapes de listas custom.
  - `FILMS_BACKSTOP_INTERVAL` — `/films/` página 1.
  - `DISCOVERY_INTERVAL` — `/lists/` para descubrir listas nuevas.
  - `ROTATION_TICK_INTERVAL` — cadencia del rotation worker (sublistas).
  - `FLAP_CONFIRM_SCRAPES` — umbral de confirmación antes de eliminar (default 3).
- Los users de Letterboxd se añaden vía UI, **no** por variable de entorno (multi-user). El primer arranque presenta un wizard.

## Integración con Radarr

Mecanismo: **Custom List** (no la API de Radarr). Radarr hace polling a una URL HTTP de watchlistarr y recibe un array JSON de películas con `tmdb_id`. Frecuencia de polling y comportamiento de auto-add se configuran en Radarr, no aquí.

Spec completa, formato JSON, pitfalls y referencias: [`radarr-custom-list.md`](radarr-custom-list.md).

## Letterboxd: estructura conocida

- **Discovery + listas + fichas (HTML)**: a partir de un username se descubren watchlist + todas las listas públicas creadas; spec completa de selectores, paginación, resolución de TMDB ID y anti-bot: [`letterboxd-lists.md`](letterboxd-lists.md).
- **RSS de usuario**: `https://letterboxd.com/{user}/rss/`. Spec completa del feed (namespaces, tipos de item, schemas, edge cases): [`letterboxd-rss.md`](letterboxd-rss.md).
- **No usar autenticación**: el proyecto se limita a contenido público.
