# Integración Radarr vía Custom List

watchlistarr **no** habla con la API de Radarr. La integración es al revés: Radarr hace polling a un endpoint HTTP de watchlistarr usando su tipo de Import List llamado **"Custom List"**. Este documento es la spec de lo que watchlistarr debe servir.

> No hay documentación oficial del formato. El issue [Radarr/Radarr#8370](https://github.com/Radarr/Radarr/issues/8370) pidiendo specs fue cerrado como *not planned*. Todo lo que sigue viene de ingeniería inversa, listas que funcionan en producción y reportes de comunidad.

## Cómo lo configura el usuario en Radarr

1. `Settings → Import Lists → ➕ → Custom List`.
2. Campos:
   - **Name**: libre.
   - **Enable Automatic Add**: típicamente sí (si no, Radarr solo lista candidatos sin importarlos).
   - **Monitor**: `Movie Only` / `None`.
   - **Search on Add**: a gusto del usuario.
   - **Minimum Availability**, **Quality Profile**, **Root Folder**: a gusto del usuario.
   - **List URL**: `http://<host-watchlistarr>:<port>/<user>/<slug>/` para listas personales, `/<user>/watchlist/` para una watchlist, o `/all/watchlist/<combo>/` para combinadas. Ver sección "URL routing en watchlistarr".
   - **Sync Interval**: lo decide Radarr (default histórico 6 h; mínimo aceptable ~1 h). watchlistarr **no controla** la frecuencia.
3. **Test** → debería decir OK. **Save**.

## URL routing en watchlistarr

Multi-user en una sola instancia. Patrones expuestos:

| URL | Significado |
|---|---|
| `/<user>/<slug>/` | Lista custom del user, identificada por su slug Letterboxd |
| `/<user>/watchlist/` | Watchlist personal del user |
| `/all/watchlist/union/` | Pelis en alguna watchlist (todos los users registrados) |
| `/all/watchlist/intersection/` | Pelis en TODAS las watchlists |
| `/all/watchlist/union-unwatched/` | Union, excluyendo pelis ya vistas por al menos un user |

**Reservas**: `all`, `api`, `admin`, `static`, `health` no son usernames válidos. Dentro de un user, el slug `watchlist` está reservado para el endpoint de la watchlist personal.

## Listas combinadas (`/all/`)

Sirven el mismo formato JSON que las individuales. Cada item es una película con `tmdb_id` único — la unión deduplica por TMDB ID, no por slug. El sort y los filtros aplicados son los de la combinación, no los de las watchlists subyacentes.

- `union`: aparece si está en al menos una watchlist.
- `intersection`: aparece si está en TODAS las watchlists.
- `union-unwatched`: union, excluyendo pelis ya vistas por al menos un user (caso "noche de cine en grupo" — si alguien ya la vio, fuera).

Detalles del modelo: [`data-model.md`](data-model.md). Detalles del sync (cuándo se recalcula, anti-flap): [`sync-strategy.md`](sync-strategy.md).

## Formato JSON que watchlistarr debe devolver

Array JSON **en la raíz**. No envolver en un objeto.

```json
[
  {
    "tmdb_id": 1084242,
    "title": "Zootopia 2",
    "imdb_id": "tt26443597",
    "poster_url": "http://image.tmdb.org/t/p/w500/oJ7g2CifqpStmoYQyaLQgEU32qO.jpg",
    "genres": ["animation", "comedy"]
  },
  {
    "tmdb_id": 83533,
    "title": "Avatar: Fire and Ash"
  }
]
```

- **Único campo realmente necesario**: `tmdb_id` (entero). Sin él Radarr no resuelve la película.
- **snake_case**, no camelCase. Confirmado por el ejemplo canónico [StevenLu popular-movies](https://s3.amazonaws.com/popular-movies/movies.json) que Radarr consume desde hace años sin tocar.
- **Content-Type**: `application/json; charset=utf-8`.
- **HTTP 200** con body válido. Lista vacía (`[]`) es válida.

### Campos opcionales

| Campo | Tipo | Uso |
|---|---|---|
| `title` | string | Útil para logs y debug; Radarr lo refresca desde TMDB |
| `imdb_id` | string `tt…` | Fallback de matching si TMDB falla; omisible |
| `poster_url` | string | Ignorado por Radarr (lo coge de TMDB); útil solo para la UI propia |
| `genres` | string[] | Ignorado por Radarr; útil solo para la UI propia |

watchlistarr puede omitir `imdb_id`, `poster_url` y `genres` sin consecuencias funcionales. Letterboxd no expone IMDb ID directamente — `tmdb_id` solo basta.

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
- [StevenLu popular-movies.json](https://s3.amazonaws.com/popular-movies/movies.json) — ejemplo vivo de formato aceptado.
- [Servarr Wiki — Radarr Settings](https://wiki.servarr.com/radarr/settings) — UI path para Import Lists.
