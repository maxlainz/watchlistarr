# Integración Radarr vía Import List

watchlistarr **no** habla con la API de Radarr. La integración es al revés: Radarr hace polling a un endpoint HTTP de watchlistarr usando uno de sus dos Import List providers basados en URL. Este documento es la spec de lo que watchlistarr debe servir.

Radarr expone **dos provider distintos** que aceptan URL custom y leen JSON:

| Provider en la UI | Identificador que lee | Archivo en el código fuente de Radarr |
|---|---|---|
| **Custom Lists** | `id` (case-insensitive Newtonsoft) → `TmdbId` | [`ImportLists/RadarrList/RadarrListParser.cs`](https://github.com/Radarr/Radarr/blob/develop/src/NzbDrone.Core/ImportLists/RadarrList/RadarrListParser.cs) |
| **StevenLu Custom** | `imdb_id` (`tt...`) | [`ImportLists/StevenLu/StevenLuParser.cs`](https://github.com/Radarr/Radarr/blob/develop/src/NzbDrone.Core/ImportLists/StevenLu/StevenLuParser.cs) |

watchlistarr emite un **superset JSON compatible con ambos**: cada item incluye `id`, `tmdb_id`, `title` e `imdb_id` (cuando lo tenemos). Newtonsoft.Json ignora silenciosamente los campos que cada parser no conoce, así que la misma URL funciona contra los dos provider — el usuario elige en la UI de Radarr cuál usar.

> No hay documentación oficial del formato. El issue [Radarr/Radarr#8370](https://github.com/Radarr/Radarr/issues/8370) pidiendo specs fue cerrado como *not planned*. Todo lo que sigue viene de ingeniería inversa, listas que funcionan en producción y reportes de comunidad.

## Cómo lo configura el usuario en Radarr

1. `Settings → Import Lists → ➕` → elegir **Custom Lists** *o* **StevenLu Custom**. Ambos funcionan contra la misma URL de watchlistarr. Recomendamos **Custom Lists** porque resuelve por TMDB ID (más rápido, no depende de que tengamos el `imdb_id` scrapeado).
2. Campos:
   - **Name**: libre.
   - **Enable Automatic Add**: típicamente sí (si no, Radarr solo lista candidatos sin importarlos).
   - **Monitor**: `Movie Only` / `None`.
   - **Search on Add**: a gusto del usuario.
   - **Minimum Availability**, **Quality Profile**, **Root Folder**: a gusto del usuario.
   - **List URL**: `http://<host-watchlistarr>:<port>/<user>/<slug>/` para listas personales del user, `/<user>/watchlist/` para la watchlist del user (si está enabled), o `/lists/<slug>/` para custom lists multi-source. Ver sección "URL routing en watchlistarr".
   - **Sync Interval**: lo decide Radarr (default histórico 6 h; mínimo aceptable ~1 h). watchlistarr **no controla** la frecuencia.
3. **Test** → debería decir OK. **Save**.

## URL routing en watchlistarr

Multi-user en una sola instancia. Cada URL apunta a una "vista" servida desde DB:

| URL | Significado |
|---|---|
| `/<user>/<list-slug>/` | Lista del user, **cruda** (sin cap, sin rotación). Solo se sirve si `lists.enabled=True` |
| `/<user>/watchlist/` | Watchlist del user, **cruda**. Solo si la fila correspondiente está enabled |
| `/lists/<slug>/` | **Custom list** multi-source (sources + op + subtract + excluded_watchers + filtros + cap + rotación) |

**Reservas**:
- Como `<username>`: `all`, `api`, `admin`, `static`, `health`, `_`, `lists`.
- Como `<slug>` bajo `/<user>/`: `watchlist` (siempre apunta a su watchlist).
- Los slugs de custom lists viven en el namespace global `/lists/<slug>/` y son únicos en toda la app.

Detalles del modelo y de cuándo se actualiza cada vista: [`data-model.md`](data-model.md) y [`sync-strategy.md`](sync-strategy.md).

## Custom lists (`/lists/<slug>/`)

Sirven el mismo formato JSON que las individuales. Cada item es una película con `tmdb_id` único — la combinación deduplica por TMDB ID, no por slug.

Su contenido se materializa en la tabla `custom_list_items` y se recalcula:
- al guardar el editor (drop items que ya no califican + rellenar hasta `max_items`),
- en cada tick del rotation worker (si `rotation_enabled=True`).

Las viejas combinadas predefinidas (`/all/watchlist/union/`, `/all/watchlist/intersection/`, `/all/watchlist/union-unwatched/`) **ya no existen** — devuelven 404. Se reemplazaron por custom lists multi-source equivalentes (ver [`data-model.md`](data-model.md#custom-lists-resolución) para los casos típicos).

## Formato JSON que watchlistarr debe devolver

Array JSON **en la raíz**. No envolver en un objeto.

```json
[
  {
    "id": 1084242,
    "tmdb_id": 1084242,
    "title": "Zootopia 2",
    "imdb_id": "tt26443597"
  },
  {
    "id": 83533,
    "tmdb_id": 83533,
    "title": "Avatar: Fire and Ash"
  }
]
```

- **Custom Lists** lee `id` (Newtonsoft.Json es case-insensitive, así que `id` minúscula encaja con la property `Id` del DTO `MovieResultResource`). Sin `id` el item se descarta y la lista aparece vacía.
- **StevenLu Custom** lee `imdb_id`. Sin `imdb_id` el item se descarta silenciosamente para ese parser y aparece el error "No results were returned from your import list".
- **snake_case**, no camelCase. Confirmado por el ejemplo canónico [StevenLu popular-movies](https://s3.amazonaws.com/popular-movies/movies.json) y por el código de los dos parsers.
- **Content-Type**: `application/json; charset=utf-8`.
- **HTTP 200** con body válido. Lista vacía (`[]`) es válida.

### Campos

| Campo | Tipo | Uso |
|---|---|---|
| `id` | int | **Requerido por Custom Lists**: Radarr lo trata como TMDB ID y resuelve la película directo. Ignorado por StevenLu Custom |
| `tmdb_id` | int | Alias interno (= `id`). Ignorado por ambos parsers. Lo mantenemos como ayuda al debug y para tooling propio |
| `imdb_id` | string `tt…` | **Requerido por StevenLu Custom**. Ignorado por Custom Lists. Puede faltar si todavía no scrapeamos la film page del título |
| `title` | string | Lo lee StevenLu Custom (Custom Lists lo ignora). Útil para logs igualmente. Radarr lo refresca desde TMDB tras resolver |

### Cómo lee cada parser

**Custom Lists** (`RadarrListParser.cs` + `MovieResultResource`):

```csharp
public class MovieResultResource {
    public int Id { get; set; }  // case-insensitive → "id" en JSON
    // ... resto de campos opcionales
}

foreach (var m in jsonResponse.Where(m => m.Id > 0))
    movies.Add(new ImportListMovie { TmdbId = m.Id });
```

**StevenLu Custom** (`StevenLuParser.cs` + `StevenLuResponse`):

```csharp
public class StevenLuResponse {
    public string title { get; set; }
    public string imdb_id { get; set; }
    public string poster_url { get; set; }
}

foreach (var item in jsonResponse)
    movies.AddIfNotNull(new ImportListMovie {
        Title = item.title,
        ImdbId = item.imdb_id,
    });
```

Como cada parser deserializa a su propio DTO e ignora el resto, podemos servir un único JSON con todos los campos y dejar que Radarr elija qué leer según el provider configurado.

### Cómo obtenemos el `imdb_id`

Letterboxd expone el IMDb ID en cada ficha de film como link "More at IMDb":
`<a href="http://www.imdb.com/title/tt6751668/maindetails">...</a>`. `parse_film_page` (en `src/watchlistarr/services/letterboxd/film_page.py`) lo extrae con regex y se persiste en `films.imdb_id` durante la resolución de slug → TMDB.

## Errores conocidos y pitfalls

- **Envolver el array** (`{"movies": [...]}`) → Radarr lo parsea como vacío sin error visible. Issue [Radarr/Radarr#9139](https://github.com/Radarr/Radarr/issues/9139).
- **`tmdb_id` como string** (`"1084242"`) → no parsea. Debe ser entero JSON.
- **TMDB ID inexistente** → Radarr lo ignora silenciosamente en su siguiente sync; aparece en logs como "movie not found".
- **HTTP 404 / 5xx** → Radarr marca la lista en estado de error en la UI pero no la borra. Reintenta en el siguiente sync.
- **Tamaño**: no hay límite documentado. Listas de 10k+ items funcionan; ser conservadores igualmente.

## Headers, caché y polling

- Radarr **no envía** `If-None-Match` ni `If-Modified-Since` en versiones actuales (verificar empíricamente con cada release que probemos).
- Aun así, watchlistarr debería **exponer `ETag`** y respetar `If-None-Match`: cuesta poco y deja el camino preparado si Radarr lo implementa.
- La frecuencia de polling la fija el usuario en Radarr. watchlistarr sirve siempre desde la DB (el scraping a Letterboxd corre en background con su propio scheduler), así que cada GET es barato.

## Filtros aplicados antes de servir

Cuando llega un `GET /list/<list_id>`, watchlistarr aplica sobre los items en DB:

1. **Sort order** configurado para la lista (`letterboxd` / `random` / `reverse`).
2. **Límite** `max_items` configurado para la lista.
3. **Exclusión de vistas** si la lista tiene rotación activada (cruzando con la tabla de "watched" alimentada por el RSS watcher).

El resultado se serializa al formato de arriba y se devuelve.

## Múltiples listas

Una Custom List en Radarr ↔ una URL en watchlistarr ↔ un `list_id`. El usuario puede registrar N listas distintas en Radarr apuntando todas al mismo host watchlistarr; el `list_id` en el path las distingue.

## Referencias

- [Radarr/Radarr#8370](https://github.com/Radarr/Radarr/issues/8370) — request de spec oficial (cerrado *not planned*).
- [Radarr/Radarr#9139](https://github.com/Radarr/Radarr/issues/9139) — pitfall del array envuelto.
- [`RadarrListParser.cs`](https://github.com/Radarr/Radarr/blob/develop/src/NzbDrone.Core/ImportLists/RadarrList/RadarrListParser.cs) — parser del provider "Custom Lists" (lee `id`).
- [`RadarrListImport.cs`](https://github.com/Radarr/Radarr/blob/develop/src/NzbDrone.Core/ImportLists/RadarrList/RadarrListImport.cs) — `Name = "Custom Lists"`.
- [`StevenLuParser.cs`](https://github.com/Radarr/Radarr/blob/develop/src/NzbDrone.Core/ImportLists/StevenLu/StevenLuParser.cs) — parser del provider "StevenLu Custom" (lee `imdb_id`).
- [StevenLu popular-movies.json](https://s3.amazonaws.com/popular-movies/movies.json) — ejemplo vivo de formato aceptado por StevenLu Custom.
- [Servarr Wiki — Radarr Settings](https://wiki.servarr.com/radarr/settings) — UI path para Import Lists.
