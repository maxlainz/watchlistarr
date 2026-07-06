# Workflows: desarrollo, deploy y operaciones

## Desarrollo local

Requisitos: Python 3.12+ y [uv](https://docs.astral.sh/uv/).

```bash
# Setup inicial
cp .env.example .env
uv sync                                  # crea .venv y resuelve deps
uv run alembic upgrade head              # aplica migrations

# Arrancar el servidor con reload
# Ojo: .env lo lee pydantic-settings, NO el shell — $HTTP_PORT está vacío
# tras el cp salvo que lo exportes. Puerto explícito:
uv run uvicorn watchlistarr.main:app --reload --port 8080

# Lint / format / type check (scope de la casa: incluye scripts, ver "CI antes de pushear")
uv run ruff check src tests scripts
uv run ruff format src tests scripts
uv run mypy src

# Tests
uv run pytest

# Migrations nuevas (tras tocar src/watchlistarr/models/)
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```

Servicio disponible en `http://localhost:8080` (o el puerto que pases a `--port`). Stack completo: [`tech-stack.md`](tech-stack.md).

## Añadir una lista nueva

Las listas no se añaden a mano: entran por **discovery automático** al añadir a su dueño como user.

1. Abrir la UI → pestaña **Users** → "Add user" con el username de Letterboxd.
2. El onboarding descubre la watchlist y las listas públicas del user y hace un full sync inicial de **todas** (quedan `enabled=False`: los items están listos pero no se sirven).
3. En el detalle del user, activar el toggle de cada lista que se quiera servir. El toggle off→on lanza un full sync inmediato si no hay otro scrape de esa lista en vuelo.
4. La URL Radarr-ready de cada lista activada aparece en la pestaña **Lists**.

Sort order, max items y rotación **no existen a nivel de lista cruda** (se sirve completa, en orden de posición): son propiedades de las **Custom Lists**, configurables en el editor de la pestaña Custom Lists. Candidato (no implementado): pegar la URL de una lista pública ajena sin añadir a su dueño como user.

## Conectar con Radarr

1. En Radarr: Settings → **Import Lists** → Add List → "Custom List".
2. URL según lo que se sirva (el **trailing slash es obligatorio**):
   - Watchlist de un user: `http://<host>:<puerto>/{user}/watchlist/`
   - Lista de un user: `http://<host>:<puerto>/{user}/{slug}/`
   - Custom list: `http://<host>:<puerto>/lists/{slug}/`
   - `<puerto>` es el host-side (`HTTP_PORT` del compose, default 8080). Si Radarr y watchlistarr comparten red Docker, usar el nombre de servicio y el puerto interno fijo: `http://watchlistarr:8080/...`.
3. Quality profile, root folder, minimum availability: a gusto del usuario.
4. Test → Save. Radarr empezará a importar películas en su siguiente sync.

## Forzar refresco manual

No hay botón "Refrescar" en la UI — candidato (no implementado). Mecanismos reales:

- **Toggle off→on**: desactivar y reactivar la lista en el detalle del user lanza un full sync inmediato (salvo que ya haya un scrape de esa lista en vuelo).
- **Endpoint admin**: `POST /admin/refresh/{job_id}` con el id **exacto** del job. Ids reales: `rss-{user_id}`, `discovery-{user_id}`, `films-backstop-{user_id}`, `watchlist-incr-{user_id}`, `watchlist-full-{user_id}`, `list-incr-{list_id}`, `list-full-{list_id}`, `rotation-tick`, `prune-scrape-runs`.

```bash
curl -X POST http://127.0.0.1:8080/admin/refresh/watchlist-full-1
```

## Refresh local tras cada commit

El stack `docker-compose.dev.yml` corre `watchlistarr-dev` mapeando `${HTTP_PORT:-8080}:8080` — en un clone fresco el QC queda en **`:8080`**. El `:8088` del entorno del owner viene de su `.env` local **no commiteado** (`HTTP_PORT=8088`, porque su 8080 lo ocupa FutureFin). Cada commit en `dev` debe ir seguido de un rebuild para que el QC manual vea siempre la última build:

```bash
git push origin dev && \
docker compose -f docker-compose.dev.yml up -d --build
```

Verificación rápida (10 s; sustituir `8080` por tu `HTTP_PORT` si lo cambiaste en `.env`):

```bash
curl -sf http://127.0.0.1:8080/healthz
curl -sf http://127.0.0.1:8080/api/v1/bootstrap | jq '.users | length'
```

Si una respuesta falla, ver `docker compose -f docker-compose.dev.yml logs -f`. El volumen `./data` sobrevive al rebuild, así que el estado del QC se conserva.

## CI antes de pushear

`.github/workflows/ci.yml` corre 5 steps. El bloque local es el **gate de la casa** — cubre los 5 steps pero no es idéntico al CI: CI solo linta/format-checkea `src tests` (aquí se añade `scripts`, a propósito: más estricto en local) y su pytest corre con `--cov=src/watchlistarr --cov-report=term` (mismos tests; coverage informativo, sin umbral).

```bash
uv run ruff check src tests scripts && \
uv run ruff format --check src tests scripts && \
uv run mypy src && \
uv run pytest -q && \
uv run python scripts/smoke.py
```

Reglas operativas asociadas (qué actualizar en qué condiciones): [`rules.md` → CI](rules.md#ci-github-actions-githubworkflowsciyml).

## Deploy con Docker

```bash
docker compose up -d
docker compose logs -f watchlistarr
docker compose down
```

Volumen persistente en `./data` (o el path configurado) para la DB.
Backup: la DB corre en modo WAL (`db.py`) — copiar solo `watchlistarr.db` en caliente puede perder los cambios pendientes del `-wal`; usar `sqlite3 data/watchlistarr.db ".backup '...'"` o parar el contenedor (o copiar también `-wal`/`-shm`).
Actualización: `docker compose pull && docker compose up -d`.

## Merge a producción (`main`)

Solo cuando el usuario lo pide explícitamente:

```bash
git checkout main
git merge dev
git push origin main
```

- Mensaje de merge: resume todo lo nuevo desde el anterior commit en `main`.
- **No** excluir `CLAUDE.md` ni `.claude/` (a diferencia de otros proyectos personales): aquí ambos viajan a `main`.

## Variables de entorno

| Variable | Default | Uso |
|---|---|---|
| `HTTP_PORT` | `8080` | Solo mapea el puerto **host-side** en compose (y el `--port` en dev); el contenedor escucha siempre en 8080 y el código de la app nunca lee esta variable |
| `LOG_LEVEL` | `info` | `debug` / `info` / `warning` / `error` |
| `LOG_FORMAT` | `plain` | `plain` (dev) / `json` (prod) |
| `DATABASE_URL` | `sqlite+aiosqlite:///data/watchlistarr.db` | Path del archivo SQLite |
| `USER_AGENT` | `watchlistarr/<version> (+https://github.com/maxlainz/watchlistarr)` | UA enviado a Letterboxd |
| `LETTERBOXD_OFFLINE` | `false` | Mata todo HTTP a Letterboxd; lo usan los tests y `scripts/smoke.py` |
| `RSS_INTERVAL` | `15m` | Default global; override per-user solo editando la DB (ver nota) |
| `WATCHLIST_INCREMENTAL_INTERVAL` | `1h` | Default global; override por watchlist en la pestaña Lists (fila watchlist → ⚙ Advanced) |
| `WATCHLIST_FULL_INTERVAL` | `24h` | Default global; override por watchlist en la pestaña Lists |
| `LISTS_INCREMENTAL_INTERVAL` | `6h` | Default global; override por lista en la pestaña Lists |
| `LISTS_FULL_INTERVAL` | `7d` | Default global; override por lista en la pestaña Lists |
| `FILMS_BACKSTOP_INTERVAL` | `24h` | Default global; override per-user solo editando la DB (ver nota) |
| `DISCOVERY_INTERVAL` | `7d` | Default global; override per-user solo editando la DB (ver nota) |
| `ROTATION_TICK_INTERVAL` | `1h` | Env-only (ritmo del worker interno) |
| `FLAP_CONFIRM_SCRAPES` | `3` | Default global; override por lista en la pestaña Lists |

Los env vars son **inmutables tras arranque**: para cambiar un valor global, edita `.env` y reinicia. Para overrides per-lista/per-watchlist (intervalos incr/full y flap) usa el ⚙ Advanced en la pestaña Lists. Los overrides per-user de RSS/films-backstop/discovery tienen columna en `users` y el scheduler los honra (`services/intervals.py`), pero **no hay UI ni endpoint** que los edite — solo edición directa de la DB; UI candidata (no implementada). La rotación per-custom-list (incl. `rotation_interval` en horas) vive en el editor de la pestaña Custom Lists. Detalles: [`sync-strategy.md`](sync-strategy.md) y [`tech-stack.md`](tech-stack.md).
