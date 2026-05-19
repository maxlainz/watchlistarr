# Listas, watchlist y fichas de Letterboxd (HTML)

watchlistarr quiere funcionar **solo con el nombre de usuario de Letterboxd**: a partir de él descubre la watchlist y todas las listas públicas creadas por ese usuario, las sincroniza periódicamente y resuelve el TMDB ID de cada película para servirlo a Radarr. Este doc consolida la spec del scraping HTML (no hay docs oficiales — todo verificado contra HTML real).

Doc hermano: [`letterboxd-rss.md`](letterboxd-rss.md) cubre el otro extremo (eventos de visionado vía RSS). Los `data-film-list-id` de aquí coinciden con los `<guid>` `letterboxd-list-<id>` de allí — útil para dedup cross-fuente.

## Modelo de fuentes desde un único username

Input de configuración: `LETTERBOXD_USER` (slug del perfil, no el display name).

Descubrimiento automático:

| Paso | Request | Para qué |
|---|---|---|
| 1 | `GET /{user}/` | Validar que el usuario existe (200 + `x-letterboxd-type: Member`) |
| 2 | `GET /{user}/lists/` + paginación | Enumerar todas las listas públicas creadas por el usuario |
| 3 | `GET /{user}/watchlist/` + paginación | Fuente especial siempre disponible si el perfil es público (no aparece en `/lists/`) |
| 4 | Por cada slug de film: `GET /film/{slug}/` | Resolver TMDB ID |

La UI ofrece el catálogo descubierto y deja al usuario elegir cuáles activar y con qué políticas (sort, max items, rotación).

## Anti-bot, robots.txt y rate limit

- Cloudflare delante (`server: cloudflare`). HTML de páginas normales responde 200 sin challenge **cuando el `User-Agent` parece de navegador**.
- UAs tipo `python-requests/X.Y` muy probablemente reciben 403 (ya confirmado con el RSS).
- UA recomendado: `watchlistarr/<version> (+<repo-url>)`. Honesto pero realista; **nunca usar UA de bot de IA** (`robots.txt` los bloquea explícitamente con `Disallow: /`).
- **`/film/{slug}/json/` está detrás de Cloudflare Managed Challenge** ("Just a moment…", CAPTCHA invisible). No usable sin headless browser. **Usar el HTML de la ficha en su lugar.**
- Sin headers `X-RateLimit-*` ni `Retry-After`. Política conservadora: **≥2 s entre requests**, sin paralelismo contra el mismo usuario/dominio.
- Cookie CSRF (`com.xk72.webparts.csrf`) se setea en cada respuesta pero **no es requerida** para GETs anónimos.

### `robots.txt`

- Disallow `/` para bots de IA (`ClaudeBot`, `GPTBot`, `CCBot`, `Applebot-Extended`, `Bytespider`, `Google-Extended`, etc.).
- Para `User-agent: *` (donde encaja watchlistarr): disallow solo en filtros que **no usamos**: `/*/by/*`, `/*/popular/this/*`, `/*/on/*`, `/*/tag/*`, `/*/genre/*`, `/*/country/*`, `/*/language/*`, `/*/decade/*`, `/films/year/*`, `/*/friends/*`.
- **NO bloquea** las rutas que sí usamos: `/{user}/`, `/{user}/lists/`, `/{user}/list/{slug}/`, `/{user}/watchlist/`, `/film/{slug}/`.

### Headers Letterboxd útiles para sanity check

- `x-letterboxd-identifier`: ID interno del recurso (ej. `NroWY` para la lista Favs).
- `x-letterboxd-type`: `Member` / `List` / `Film`. **Verificar antes de parsear** que coincide con el tipo esperado.

## Página `/{user}/lists/` — índice de listas del usuario

Enumera **solo las listas creadas por el usuario** (no incluye la watchlist, que es una URL aparte).

Selector raíz por lista:

```css
article.list-summary[data-film-list-id]
```

Atributos clave del article:

- `data-film-list-id` — ID interno de Letterboxd. **Mismo ID que el `<guid>` `letterboxd-list-<id>` del RSS.** Dedup gratis entre fuentes.
- `data-person` — username del owner.

Dentro del article:

- **Slug + nombre display**: `h2.name a` → `href="/{user}/list/{slug}/"` + texto = nombre.
- **Film count**: `.content-reactions-strip .value` → string `"N films"` (parsear entero).
- **Preview de 5 posters** (no la lista completa): `<ul class="posterlist">` con `<li class="posteritem">` que usan el mismo schema `data-item-*` de los items reales. Útil para mostrar miniatura sin abrir cada lista.

Ejemplo verbatim (esqueleto, sin las 5 posterítems internas):

```html
<article class="list-summary js-list-summary js-list"
         data-film-list-id="73057123" data-person="maxlainz">
  <div class="layout">
    <figure class="figure posterset">
      <div class="poster-list-overlapped -p70" style="--poster-count: 5;">
        <a href="/maxlainz/list/favs/" class="poster-list-link">
          <ul class="posterlist">
            <li class="posteritem">…</li>
            …
          </ul>
        </a>
      </div>
    </figure>
    <div class="body">
      <div class="masthead">
        <h2 class="name prettify">
          <a href="/maxlainz/list/favs/">Favs</a>
        </h2>
        <div class="content-reactions-strip -filmlist">
          <span class="value">5&nbsp;films</span>
          …
        </div>
      </div>
    </div>
  </div>
</article>
```

**Paginación**: mismo patrón `/{user}/lists/page/N/`. Si no aparece bloque `<div class="pagination">` → página única.

**Limitación: listas privadas**. No aparecen en `/lists/` para visitantes no autenticados. Si el usuario tiene listas privadas que quiere sincronizar, la UI debe permitir pegar la URL manualmente como fallback.

## Página `/{user}/watchlist/` — watchlist personal

- **No aparece en `/lists/`**. Es un concepto separado en la UI de Letterboxd (`js-page-watchlist` vs `js-page-lists`).
- watchlistarr la trata como una **fuente especial fija**: fila propia en la tabla `lists` con `type='watchlist'`, no descubierta dinámicamente.
- Misma estructura de grid que las listas regulares (ver siguiente sección).
- 28 items por página, paginación `/page/N/`.

## Página de lista o watchlist — items

URL: `/{user}/list/{slug}/[page/N/]` o `/{user}/watchlist/[page/N/]`.

- **28 ítems por página** (confirmado en watchlist página 1 y 2).
- Cada item: `<li class="griditem">` → `<div class="react-component" data-component-class="LazyPoster" …>` dentro.
- **Todos los datos están en atributos `data-*` del div**, no en hijos del DOM.

Atributos relevantes:

| Atributo | Contenido | Uso en watchlistarr |
|---|---|---|
| `data-item-slug` | slug Letterboxd (`3-faces`) | Construir URL de ficha |
| `data-item-link` | `/film/{slug}/` | Idem |
| `data-item-name` | `Título (YYYY)` | Display / logging |
| `data-item-full-display-name` | Igual o variante con info extra | Display |
| `data-postered-identifier` | JSON con `uid: "film:<lb_id>"` | ID interno LB (opcional para dedup) |
| `data-poster-url` | `/film/{slug}/image-150/` | Poster (opcional) |
| `data-target-link` | `/film/{slug}/` | Idem `data-item-link` |
| `data-details-endpoint` | `/film/{slug}/json/` | **Inútil** (Cloudflare bloquea) |

**El orden del grid = orden definido por el usuario en Letterboxd.** Preservarlo para que `position` en la DB tenga sentido (la política `sort=letterboxd` lo respeta tal cual).

**TMDB ID NO está en el listing.** Solo slug + ID interno de Letterboxd. Para conseguir el TMDB ID hay que fetchear la ficha individual.

Ejemplo verbatim de un `<div class="react-component">` (atributos en una línea como en el HTML real; reformateados aquí con saltos para legibilidad):

```html
<div class="react-component"
     data-component-class="LazyPoster"
     data-item-name="3 Faces (2018)"
     data-item-slug="3-faces"
     data-item-link="/film/3-faces/"
     data-item-full-display-name="3 Faces (2018)"
     data-postered-identifier='{"lid":"iLoE","uid":"film:447210","type":"film","typeName":"film"}'
     data-poster-url="/film/3-faces/image-150/"
     data-target-link="/film/3-faces/"
     data-details-endpoint="/film/3-faces/json/"
     data-show-menu="true">
</div>
```

## Paginación

URL: `/.../page/N/`.

Detectar nº total parseando el último `<a>` del bloque:

```html
<div class="pagination">
  ...
  <li class="paginate-page"><a href="/maxlainz/watchlist/page/23/">23</a></li>
</div>
```

- Sin bloque `pagination` → **página única**.
- **No iterar páginas a ciegas**: `/page/N/` inexistente devuelve **`403 Forbidden`** (no 404). Si no parseaste primero la paginación, no podrás distinguir entre "página fuera de rango" y "rate limit real". Siempre parsear paginación en página 1 antes de iterar.

## Resolución de TMDB ID

URL: `https://letterboxd.com/film/{slug}/`.

TMDB ID en el `<body>`:

```html
<body class="film backdropped"
      data-type="film"
      data-tmdb-type="movie"
      data-tmdb-id="496243">
```

- Selector: `body[data-tmdb-id]`.
- Si `data-tmdb-type != "movie"` (caso `tv`): descartar — Radarr es solo películas.
- Si `data-tmdb-id` vacío o ausente: logear y saltar (peli sin entry en TMDB, raro pero posible).
- **Cloudflare cachea las fichas** (`cache-control: s-maxage=300`, `cf-cache-status: HIT`). Scraping es barato; **persistir el TMDB ID en DB** y no re-resolver salvo refresco explícito.

## Pipeline del scraper end-to-end

1. **Validar username** (al guardar la config en la UI):
   - `GET /{user}/` debe devolver 200 con `x-letterboxd-type: Member`. Si no → error en la UI.
2. **Descubrimiento de listas** (periódico, ej. 1×/día):
   - `GET /{user}/lists/` (+ paginación si aplica).
   - Para cada `<article class="list-summary">`: upsert en `lists` con `(letterboxd_id, slug, name, film_count)`.
   - Watchlist: fila fija con `type='watchlist'`, no descubierta.
3. **Sync de items por lista** (periódico, intervalo configurable, ej. 1-2 h):
   - Para cada lista habilitada por el usuario:
     - Página 1 → detectar paginación → iterar `1..N` secuencialmente.
     - Por cada página: extraer slugs en orden, upsert en `list_items`.
   - Por cada slug nuevo (sin fila en `films`): fetchear `/film/{slug}/`, extraer TMDB ID, persistir.
4. **Servir a Radarr**: cuando llega `GET /list/{list_id}`, leer items de DB, aplicar políticas (sort / max_items / exclusión de vistos según RSS), devolver JSON en el formato de [`radarr-custom-list.md`](radarr-custom-list.md).

## Edge cases

- **Lista privada**: no aparece en `/lists/`. La UI debe permitir pegar URL manual como fallback.
- **Lista borrada o slug cambiado**: `/list/{slug}/` devuelve 404 → marcar lista en error, **no** borrar los items previos.
- **Slug que ya no existe en `/film/{slug}/`**: logear, no crashear, registrar error por slug.
- **TV shows** (`data-tmdb-type="tv"`): ignorar — Radarr es solo películas.
- **Películas sin TMDB ID**: gap conocido, mostrar en UI.
- **`/page/N/` inexistente → 403**: parsear paginación de página 1 antes de iterar para distinguirlo de un rate limit real.
- **Selectores que cambian**: si `data-item-slug`, `data-film-list-id` o `data-tmdb-id` desaparecen, **fallar ruidosamente** con log de la URL — no intentar parseo alternativo. Indica que Letterboxd cambió el render y este doc debe revisarse.

## Referencias

URLs verificadas durante la spec:

- `https://letterboxd.com/maxlainz/lists/` — índice de listas.
- `https://letterboxd.com/maxlainz/list/favs/` — lista normal.
- `https://letterboxd.com/maxlainz/watchlist/` y `/page/2/` — watchlist con paginación.
- `https://letterboxd.com/film/parasite-2019/` — ficha con TMDB ID.
- `https://letterboxd.com/robots.txt` — política para bots.

No existe documentación oficial de Letterboxd para ninguna de estas estructuras. El doc debe revisarse cada vez que toquemos el scraper o veamos un cambio de selector.
