# Arquitectura

## Flujo general

```
Letterboxd (HTML público + RSS de usuario)
        │
        ▼
   Scraper / RSS watcher
        │
        ▼
   DB interna  ◀────────  UI de control (web, HTMX)
        │
        ▼
   API HTTP (formato custom list)
        │
        ▼
      Radarr
```

- El scraper traduce listas de Letterboxd a registros en la DB interna.
- El RSS watcher lee la actividad del usuario; cuando aparece una película marcada como vista, se purga de las listas configuradas para hacerlo (rotación).
- La UI deja al usuario configurar fuentes (listas), políticas (cuántos servir, sort), y forzar refrescos.
- La API expone los resultados en el formato que Radarr espera para custom lists.

## Componentes objetivo

### Scraper de listas
- Recibe una URL de lista pública de Letterboxd (`/{user}/list/{slug}/`).
- Recorre paginación, extrae cada film y su TMDB ID (resolviendo desde la ficha individual si no aparece en la lista).
- Guarda en DB: `list_id`, `position`, `tmdb_id`, `title`, `year`, `scraped_at`.

### RSS watcher
- Polling periódico al RSS público del usuario (`/{user}/rss/`).
- Detecta entradas de tipo "watched" (atributo `letterboxd:watchedDate` en el item).
- Marca la película como vista en la DB y aplica la política configurada (eliminar de listas que así lo indiquen vs. ignorar).

### DB interna
- **TBD**: probable SQLite por simplicidad de empaquetado en Docker (un solo binario, un volumen de datos).
- Esquema tentativo (rellenar cuando se elija stack y ORM/driver):
  - `lists` — fuentes Letterboxd configuradas + políticas (sort, max items, rotación).
  - `items` — películas ingeridas por lista, con posición y estado (`pending`, `served`, `watched`).
  - `settings` — configuración global (rate limit, user-agent, intervalos).

### API a Radarr
- Endpoint HTTP `GET /list/{list_id}` que devuelve JSON en el formato custom list de Radarr (lista de objetos con `tmdbId` mínimo; investigar exactamente qué campos exige Radarr v5).
- Filtros aplicados en el endpoint: sort order configurado, límite de tamaño, exclusión de vistos según política.
- Sin autenticación en MVP (asumimos que watchlistarr y Radarr corren en la misma red Docker). Añadir token si se expone fuera.

### UI de control
- HTML server-rendered + HTMX para interacciones (añadir lista, editar política, refrescar manualmente, ver últimos errores de scraping).
- Sin SPA. Sin build step de frontend si se puede evitar.
- Páginas: dashboard (listas + estado), edición de lista, ajustes globales, log de actividad.

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
- Variables de entorno principales: TBD según stack, pero como mínimo:
  - `LETTERBOXD_USER` — usuario cuyo RSS se monitoriza.
  - `SCRAPE_INTERVAL` — frecuencia del ciclo de scraping.
  - `RSS_INTERVAL` — frecuencia del polling de RSS.
  - `HTTP_PORT` — puerto de UI/API.
  - `LOG_LEVEL` — verbosity.

## Integración con Radarr

Radarr permite añadir custom lists vía URL JSON. Verificar antes de implementar:

- Formato exacto que Radarr 5.x acepta (probablemente array de objetos con `tmdbId` como mínimo).
- Si Radarr cachea o pide ETag/Last-Modified — implementarlo para no forzar reimportaciones innecesarias.
- Si Radarr puede consumir múltiples listas desde un solo host watchlistarr (sí, vía URLs distintas por lista).

## Letterboxd: estructura conocida

- **Listas públicas**: `https://letterboxd.com/{user}/list/{slug}/`, paginadas (`/page/2/`...). Cada item es un `<li class="poster-container">` con `data-film-slug`.
- **Ficha de film**: `https://letterboxd.com/film/{film-slug}/` — contiene `<body data-tmdb-id="...">` y `data-tmdb-type="movie|tv"`.
- **RSS de usuario**: `https://letterboxd.com/{user}/rss/`. Items de tipo watched llevan `<letterboxd:watchedDate>` y `<letterboxd:filmTitle>`.
- **No usar autenticación**: el proyecto se limita a contenido público.
