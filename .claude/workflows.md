# Workflows: desarrollo, deploy y operaciones

## Desarrollo local

Requisitos: Python 3.12+ y [uv](https://docs.astral.sh/uv/).

```bash
# Setup inicial
cp .env.example .env
uv sync                                  # crea .venv y resuelve deps
uv run alembic upgrade head              # aplica migrations

# Arrancar el servidor con reload
uv run uvicorn watchlistarr.main:app --reload --port "$HTTP_PORT"

# Lint / format / type check
uv run ruff check src tests
uv run ruff format src tests
uv run mypy src

# Tests
uv run pytest

# Migrations nuevas (tras tocar src/watchlistarr/models/)
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```

Servicio disponible en `http://localhost:<HTTP_PORT>`. Stack completo: [`tech-stack.md`](tech-stack.md).

## Añadir una lista nueva

1. Abrir la UI (`http://localhost:<HTTP_PORT>`).
2. Ir a "Listas → Añadir".
3. Pegar la URL de la lista pública de Letterboxd (`https://letterboxd.com/{user}/list/{slug}/`).
4. Configurar política: sort order (Letterboxd / random / reverse), max items servidos, regla de rotación al ver una película.
5. Guardar. El siguiente ciclo de scraping la ingiere.
6. Copiar la URL del endpoint generado y pegarla en Radarr → Custom Lists.

## Conectar con Radarr

1. En Radarr: Settings → Lists → Add List → "Custom List".
2. URL: `http://<host-watchlistarr>:<HTTP_PORT>/list/<list_id>`.
   - Si Radarr y watchlistarr corren en la misma red Docker, usar el nombre de servicio (`http://watchlistarr:<HTTP_PORT>/...`).
3. Quality profile, root folder, minimum availability: a gusto del usuario.
4. Test → Save. Radarr empezará a importar películas en su siguiente sync.

## Forzar refresco manual

- Desde la UI: botón "Refrescar" en cada lista (lanza el scraper de esa lista fuera de su ciclo).
- Desde CLI: TBD según stack (`docker exec watchlistarr <comando>` o endpoint admin).

## Deploy con Docker

```bash
docker compose up -d
docker compose logs -f watchlistarr
docker compose down
```

Volumen persistente en `./data` (o el path configurado) para la DB.
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
| `HTTP_PORT` | `8080` | Puerto de UI + API |
| `LOG_LEVEL` | `info` | `debug` / `info` / `warning` / `error` |
| `LOG_FORMAT` | `plain` | `plain` (dev) / `json` (prod) |
| `DATABASE_URL` | `sqlite+aiosqlite:///data/watchlistarr.db` | Path del archivo SQLite |
| `USER_AGENT` | `watchlistarr/<version> (+https://github.com/maxlainz/watchlistarr)` | UA enviado a Letterboxd |
| `RSS_INTERVAL` | `15m` | Env-only |
| `WATCHLIST_INCREMENTAL_INTERVAL` | `1h` | Default global; override por watchlist en la pestaña Lists (fila watchlist → ⚙ Advanced) |
| `WATCHLIST_FULL_INTERVAL` | `24h` | Default global; override por watchlist en la pestaña Lists |
| `LISTS_INCREMENTAL_INTERVAL` | `6h` | Default global; override por lista en la pestaña Lists |
| `LISTS_FULL_INTERVAL` | `7d` | Default global; override por lista en la pestaña Lists |
| `FILMS_BACKSTOP_INTERVAL` | `24h` | Env-only |
| `DISCOVERY_INTERVAL` | `7d` | Env-only |
| `ROTATION_TICK_INTERVAL` | `1h` | Env-only (ritmo del worker interno) |
| `FLAP_CONFIRM_SCRAPES` | `3` | Default global; override por lista en la pestaña Lists |

Los env vars son **inmutables tras arranque**: para cambiar un valor global, edita `.env` y reinicia. Para overrides per-lista/per-watchlist usa el ⚙ Advanced en la pestaña Lists. La rotación per-custom-list (incl. `rotation_interval` en horas) vive en el editor de la pestaña Custom Lists. Detalles: [`sync-strategy.md`](sync-strategy.md) y [`tech-stack.md`](tech-stack.md).
