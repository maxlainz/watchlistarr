# RSS de usuario de Letterboxd

watchlistarr usa el RSS público de cada usuario de Letterboxd como fuente del **RSS watcher**: el componente que detecta cuándo el usuario ha marcado una película como vista y lo persiste en DB (`viewing_logs` + `watched_films`, ver `services/scrape/rss_watcher.py`). El poll **no dispara nada más**: ese estado lo consumen después el anti-flap de los full scrapes (visto por el owner → eliminación inmediata de la raw list) y las custom lists con `excluded_watchers` (el film cae en su siguiente rotación/recálculo).

> Letterboxd no documenta este RSS oficialmente. Todo lo que sigue se ha verificado fetcheando `https://letterboxd.com/maxlainz/rss/` y observando 22 ítems reales. El formato puede cambiar sin aviso — revisar este doc cada vez que toquemos el watcher o veamos un campo nuevo.

## Endpoint y fetching

- URL: `https://letterboxd.com/{username}/rss/`.
- Público, sin autenticación.
- Encoding: UTF-8.
- **User-Agent obligatorio**: Letterboxd devuelve `403 Forbidden` a clientes con UA por defecto de varias libs (`Mozilla/5.0`, etc. funcionan; UA vacío o `python-requests/x.y` falla). Identificarse siempre con `watchlistarr/<version> (+<repo-url>)`.
- Headers de caché (`ETag`, `Last-Modified`): verificar empíricamente si Letterboxd los devuelve; si sí, respetarlos para ahorrar ancho de banda en el polling.

## Estructura raíz

```xml
<?xml version='1.0' encoding='utf-8'?>
<rss version="2.0"
     xmlns:atom="http://www.w3.org/2005/Atom"
     xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:letterboxd="https://letterboxd.com"
     xmlns:tmdb="https://themoviedb.org">
  <channel>
    <title>Letterboxd - {Display Name}</title>
    <link>https://letterboxd.com/{username}/</link>
    <description>Letterboxd - {Display Name}</description>
    <atom:link rel="self" href="https://letterboxd.com/{username}/rss/" type="application/rss+xml"/>
    <item>…</item>
    <item>…</item>
    …
  </channel>
</rss>
```

Items ordenados por `pubDate` desc (más reciente primero).

## Tipos de item

Se distinguen por el prefijo del `<guid>`:

| Prefijo del GUID | Tipo | Qué hace watchlistarr |
|---|---|---|
| `letterboxd-watch-<id>` | watch | Procesar: upsert en `viewing_logs` + `watched_films` (estado que luego consumen el anti-flap y las custom lists con `excluded_watchers`) |
| `letterboxd-review-<id>` | review | Procesar igual que `watch` (también es una visualización; solo cambia que el usuario escribió texto) |
| `letterboxd-list-<id>` | list | Ignorar — las listas del usuario se scrapean por separado desde su URL HTML |

## Schema de item watch / review

### Elementos del namespace `letterboxd:`

| Elemento | Tipo | Obligatorio | Significado |
|---|---|---|---|
| `letterboxd:watchedDate` | `YYYY-MM-DD` | sí | Fecha en que se marcó como vista. Se persiste en `viewing_logs.watched_date` |
| `letterboxd:rewatch` | `Yes` / `No` | sí | Si el usuario marcó la peli como revisionado |
| `letterboxd:filmTitle` | string | sí | Título sin año |
| `letterboxd:filmYear` | entero | sí | Año del film |
| `letterboxd:memberRating` | decimal `0.5`–`5.0` (paso 0.5) | no | Ausente si no rateó |
| `letterboxd:memberLike` | `Yes` / `No` | sí | Si el usuario le dio "like" |

### Elementos del namespace `tmdb:`

| Elemento | Tipo | Obligatorio | Significado |
|---|---|---|---|
| `tmdb:movieId` | entero | sí (en watch/review de movies) | **Identificador que cruzamos con la DB interna** |
| `tmdb:tvId` | entero | sí (en watch/review de series) | watchlistarr lo ignora (Radarr es solo películas) |

### Elementos RSS estándar

| Elemento | Notas |
|---|---|
| `<title>` | `Film Title, YYYY` o `Film Title, YYYY - ★★★★½` si hay rating (estrellas + media estrella `½` para fracciones) |
| `<link>` | URL del log individual: `/{username}/film/{slug}/[N/]`. El sufijo `/N/` aparece en revisionados |
| `<guid isPermaLink="false">` | Formato `letterboxd-<type>-<id>`. **ID estable entre fetches — usar como clave de deduplicación** |
| `<pubDate>` | RFC 2822 con timezone (`+1200`, `+1300`, …). Es el momento de **publicación en el RSS**, no la fecha de visionado |
| `<description>` | CDATA con HTML: `<img>` del poster + `<p>` con texto de reseña (review) o `"Watched on <date>."` (watch) |
| `<dc:creator>` | Display name del usuario |

### Ejemplo verbatim — watch sin rating

```xml
<item>
  <title>Mondays in the Sun, 2002</title>
  <link>https://letterboxd.com/maxlainz/film/mondays-in-the-sun/</link>
  <guid isPermaLink="false">letterboxd-watch-1310048973</guid>
  <pubDate>Sun, 10 May 2026 10:00:30 +1200</pubDate>
  <letterboxd:watchedDate>2026-05-09</letterboxd:watchedDate>
  <letterboxd:rewatch>No</letterboxd:rewatch>
  <letterboxd:filmTitle>Mondays in the Sun</letterboxd:filmTitle>
  <letterboxd:filmYear>2002</letterboxd:filmYear>
  <letterboxd:memberLike>Yes</letterboxd:memberLike>
  <tmdb:movieId>54580</tmdb:movieId>
  <description><![CDATA[ <p><img src="https://a.ltrbxd.com/resized/film-poster/1/1/5/1/0/11510-mondays-in-the-sun-0-600-0-900-crop.jpg?v=ee413f58db"/></p> <p>Watched on Saturday May 9, 2026.</p> ]]></description>
  <dc:creator>Max Lainz</dc:creator>
</item>
```

Nota: `letterboxd:memberRating` ausente porque el usuario no rateó.

### Ejemplo verbatim — review con rating

```xml
<item>
  <title>Flow, 2024 - ★★★★½</title>
  <link>https://letterboxd.com/maxlainz/film/flow-2024/1/</link>
  <guid isPermaLink="false">letterboxd-review-1153149850</guid>
  <pubDate>Mon, 12 Jan 2026 09:03:05 +1300</pubDate>
  <letterboxd:watchedDate>2026-01-11</letterboxd:watchedDate>
  <letterboxd:rewatch>Yes</letterboxd:rewatch>
  <letterboxd:filmTitle>Flow</letterboxd:filmTitle>
  <letterboxd:filmYear>2024</letterboxd:filmYear>
  <letterboxd:memberRating>4.5</letterboxd:memberRating>
  <letterboxd:memberLike>Yes</letterboxd:memberLike>
  <tmdb:movieId>823219</tmdb:movieId>
  <description><![CDATA[ <p><img src="https://a.ltrbxd.com/resized/film-poster/7/3/9/4/5/1/739451-flow-2024-0-600-0-900-crop.jpg?v=d664eca804"/></p> <p>una peli molt humana</p> ]]></description>
  <dc:creator>Max Lainz</dc:creator>
</item>
```

> En el RSS real Letterboxd entrega cada `<item>` y sus hijos en una sola línea. Aquí se formatean con indentación para legibilidad; la estructura XML es idéntica.

## Schema de item list

Estructura completamente distinta a watch/review. **Sin** elementos `letterboxd:*` ni `tmdb:*`.

```xml
<item>
  <title>Favs</title>
  <link>https://letterboxd.com/maxlainz/list/favs/</link>
  <guid isPermaLink="false">letterboxd-list-73057123</guid>
  <pubDate>Thu, 14 Aug 2025 20:06:06 +1200</pubDate>
  <description><![CDATA[ <ul> <li> <a href="https://letterboxd.com/film/youth-2015/">Youth</a> </li> <li> <a href="https://letterboxd.com/film/rapture-1979/">Rapture</a> </li> </ul> ]]></description>
  <dc:creator>Max Lainz</dc:creator>
</item>
```

watchlistarr **ignora** estos items en el watcher. Si el usuario quiere ingerir una lista, la añade explícitamente desde la UI y el scraper la procesa desde la URL HTML, no desde este RSS.

## Pipeline del RSS watcher

1. **Fetch** periódico al endpoint (intervalo configurable; sugerencia inicial 15 min).
2. **Parsear** el XML respetando namespaces.
3. **Iterar** sobre `<item>` en orden:
   - Tomar `<guid>`. Si su prefijo es `letterboxd-list-`, saltar.
   - Si ya existe en DB (clave única `<guid>`), saltar.
   - Si no:
     - Extraer `tmdb:movieId`, `letterboxd:watchedDate`, `<guid>`, opcionalmente `letterboxd:filmTitle` / `letterboxd:filmYear` para logging.
     - Si falta `tmdb:movieId` (caso teórico) o hay `tmdb:tvId` en lugar de `tmdb:movieId`: logear y saltar.
     - Insertar en `viewing_logs` + upsert en `watched_films` (clave `(user_id, tmdb_id)`).
4. **Consumo diferido**: el poll termina ahí. Las eliminaciones llegan por otras vías: el anti-flap de los full scrapes cruza `watched_films` (visto por el owner → eliminación inmediata de la raw list), y las custom lists con `excluded_watchers` retiran el film en su siguiente rotación/recálculo.

## Edge cases

- **Sin `letterboxd:memberRating`**: tolerar, no afecta a rotación.
- **Series (`tmdb:tvId`)**: ignorar; Radarr es solo películas.
- **Multiple viewings del mismo film**: cada uno genera un `<guid>` distinto. Todos se registran como filas separadas en `viewing_logs`; en `watched_films` hay una sola fila por `(user_id, tmdb_id)` (los eventos posteriores solo refrescan `last_seen_watched_at`), así que los revisionados no cambian nada aguas abajo.
- **Timezone variable**: el mismo feed puede mezclar `+1200` y `+1300` cuando el usuario está en zona con horario de verano. Parsear como datetime con tz y normalizar a UTC en DB.
- **Caracteres especiales** (`Sirāt`, comillas tipográficas, acentos): UTF-8 en todo el feed; sin sorpresas si el parser respeta la declaración del XML.

## Volumen, paginación y latencia

- **Sin parámetro de paginación documentado**. Solo se obtiene la "ventana" reciente del feed (en el fetch de prueba: 22 ítems abarcando ~10 meses; el techo varía con la actividad del usuario, probablemente 20–50 ítems).
- **Implicación**: si watchlistarr corre con poca frecuencia y el usuario es muy activo, pueden perderse eventos que ya hayan caído fuera de la ventana.
- **Mitigación**:
  - Polling frecuente (15 min default).
  - Forzar fetch manual: `POST /admin/refresh/rss-<user_id>`. Candidato (no implementado): botón "Refrescar" en la UI.
  - Documentar el límite como conocido — no es un bug del watcher.

## Referencias

- Feed de ejemplo verificado durante la investigación: `https://letterboxd.com/maxlainz/rss/`.
- No existe documentación oficial de Letterboxd sobre este formato.
