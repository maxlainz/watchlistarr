# watchlistarr

Alternativa moderna a [letterboxd-list-radarr](https://github.com/screeny05/letterboxd-list-radarr).
Scrapea listas y RSS públicos de Letterboxd → DB interna → expone una API que Radarr consume como Custom List.

- **Multi-user** desde el principio.
- **GUI HTMX** para añadir users, activar listas, crear sublistas (con filtros + rotación) y configurar frecuencias.
- **Combinadas** (`union` / `intersection` / `union-unwatched`) sobre las watchlists de todos los users registrados.
- **DB autoritativa**: lo servido a Radarr es siempre un SELECT, nunca on-the-fly. Anti-flap por verificación cruzada antes de eliminar.
- **Docker + DockerHub** (`maxlainz/watchlistarr`), un único proceso (uvicorn + APScheduler embebido).

## Stack

Python 3.12 · FastAPI · SQLAlchemy 2 async · SQLite + Alembic · APScheduler · HTMX + Pico CSS · httpx · BeautifulSoup4 · feedparser · structlog · uv.

## Docker

```bash
cp .env.example .env
docker compose up -d
docker compose logs -f watchlistarr
```

UI en `http://localhost:8080`. Volumen `./data` para la SQLite.

## Desarrollo local

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn watchlistarr.main:app --reload --port 8080

uv run ruff check src tests
uv run ruff format src tests
uv run mypy src
uv run pytest
uv run python scripts/smoke.py
```

## Integración con Radarr

`Settings → Import Lists → Custom List`, URL `http://watchlistarr:8080/<user>/watchlist/` (u otra de `/endpoints` en la UI). Spec del formato JSON: [`.claude/radarr-custom-list.md`](.claude/radarr-custom-list.md).

## Documentación

Reglas, arquitectura y specs de scraping/RSS/data-model viven en [`.claude/`](.claude/) y [`CLAUDE.md`](CLAUDE.md).

## CI / publicación

GitHub Actions: lint + mypy + pytest + smoke en cada push y PR. Solo en push a `main` se construye la imagen multi-arquitectura (amd64+arm64) y se publica `maxlainz/watchlistarr:latest` + `maxlainz/watchlistarr:sha-<short>` en DockerHub. Requiere secrets `DOCKERHUB_USERNAME` y `DOCKERHUB_TOKEN` configurados en el repo.
