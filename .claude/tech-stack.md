# Stack técnico

Referencia central de las decisiones técnicas de watchlistarr: librerías elegidas, versiones, layout del repo, ciclo de vida del proceso y comandos canónicos. Si tocas dependencias, estructura de directorios o configuración base del proyecto, este es el doc a actualizar.

Cross-references:
- Flujo y componentes funcionales: [`architecture.md`](architecture.md).
- Modelo de datos: [`data-model.md`](data-model.md).
- Estrategia de sync: [`sync-strategy.md`](sync-strategy.md).
- GUI: [`ui-features.md`](ui-features.md).
- Comandos día a día: [`workflows.md`](workflows.md).

## Resumen

| Área | Elección | Notas |
|---|---|---|
| Lenguaje | Python 3.12+ | Floor pin en `pyproject.toml` |
| HTTP framework | FastAPI | Async, Pydantic v2 integrado |
| Templates | Jinja2 | Vía `fastapi.templating.Jinja2Templates` |
| Frontend interactivo | HTMX | Sin SPA, sin build step |
| CSS | Pico CSS v2 | Classless, ~10 KB |
| DB | SQLite | Un archivo en volumen Docker |
| Data layer | SQLAlchemy 2.0 async + Alembic | `Mapped[T]` declarative |
| Driver SQLite | `aiosqlite` | Async oficial |
| Cliente HTTP | `httpx` async | Wrapper propio con UA + rate limit |
| Parser HTML | BeautifulSoup4 + `lxml` | lxml para velocidad |
| Parser RSS | `feedparser` | Maneja namespaces de Letterboxd sin esfuerzo |
| Scheduler | APScheduler 3.x | `AsyncIOScheduler` embebido en el loop de FastAPI |
| Validación / settings | Pydantic v2 + `pydantic-settings` | `BaseSettings` lee `.env` y `os.environ` |
| Logging | `structlog` | JSON en prod, plain en dev |
| Testing | `pytest` + `pytest-asyncio` + `respx` | Fixtures HTML/RSS recortados |
| Linter / formatter | `ruff` | Sustituye black/isort/flake8 |
| Type checker | `mypy --strict` | En CI |
| Package manager | `uv` | Venv + lockfile + Python versions |
| Docker base | `python:3.12-slim-bookworm` | lxml sin compilación |

## Versiones congeladas (pyproject.toml)

Rangos sugeridos al implementar — pin exacto vendrá del `uv.lock`:

```toml
[project]
requires-python = ">=3.12"
dependencies = [
    "fastapi ~= 0.115",
    "uvicorn[standard] ~= 0.32",
    "sqlalchemy ~= 2.0",
    "aiosqlite ~= 0.20",
    "alembic ~= 1.13",
    "httpx ~= 0.27",
    "beautifulsoup4 ~= 4.12",
    "lxml ~= 5.3",
    "feedparser ~= 6.0",
    "apscheduler ~= 3.10",
    "jinja2 ~= 3.1",
    "pydantic ~= 2.9",
    "pydantic-settings ~= 2.6",
    "structlog ~= 24.4",
]

[dependency-groups]
dev = [
    "ruff",
    "mypy",
    "pytest",
    "pytest-asyncio",
    "respx",
]
```

## Estructura del repo

```
watchlistarr/
├── pyproject.toml             # uv-managed
├── uv.lock
├── Dockerfile
├── docker-compose.yml
├── docker-compose.dev.yml
├── .env.example
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
├── src/watchlistarr/
│   ├── __init__.py
│   ├── main.py                # FastAPI app factory + lifespan
│   ├── config.py              # Settings (Pydantic)
│   ├── db.py                  # engine, session factory
│   ├── logging.py             # structlog setup
│   ├── models/                # SQLAlchemy models (Mapped[T])
│   ├── schemas/               # Pydantic schemas para API I/O
│   ├── services/
│   │   ├── letterboxd/
│   │   │   ├── client.py      # httpx wrapper (UA + rate limit)
│   │   │   ├── rss.py
│   │   │   ├── lists.py
│   │   │   ├── films.py       # backstop /films/ p1
│   │   │   └── film_page.py   # /film/{slug}/ → tmdb_id
│   │   ├── scrape/            # full + incremental orchestrators
│   │   ├── custom_lists.py    # resolver multi-source + rotation + log_buffer
│   │   ├── log_buffer.py
│   │   └── radarr.py          # serializador JSON
│   ├── scheduler.py           # APScheduler wiring
│   ├── routes/
│   │   ├── ui/                # routers HTML (Jinja2)
│   │   └── api/               # routers JSON (Radarr endpoints)
│   └── templates/             # Jinja2 templates
│       ├── base.html
│       ├── dashboard.html
│       ├── users/
│       ├── lists/
│       ├── custom_lists/
│       └── activity/
└── tests/
    ├── conftest.py
    ├── fixtures/              # HTML/RSS recortados de Letterboxd real
    ├── unit/
    └── integration/
```

`src/` layout — los tests no pueden importar accidentalmente del checkout sin instalar el paquete (más seguro y estándar).

## Ciclo de vida (FastAPI lifespan)

Al arrancar:

1. Configurar `structlog` según `LOG_FORMAT`.
2. Crear engine SQLAlchemy con `DATABASE_URL`.
3. Ejecutar `alembic upgrade head` (idempotente).
4. Inicializar tabla `settings` desde env vars en el primer arranque.
5. Crear `AsyncIOScheduler` y registrar todos los jobs (RSS, watchlist incr/full, lists incr/full, films-backstop, discovery, rotation) leyendo intervalos de la tabla `settings`.
6. Arrancar el scheduler.
7. Listo para servir HTTP.

Al cerrar:

1. `scheduler.shutdown(wait=True)`.
2. Cerrar engine.

## APScheduler wiring

- `AsyncIOScheduler` corriendo en el mismo loop que FastAPI (no procesos separados).
- Cada job se identifica con un `job_id` estable (`rss-watcher`, `watchlist-incremental-<user_id>`, etc.) para poder rescheduarlo en runtime.
- Cuando la UI cambia un `*_INTERVAL`, el handler:
  1. Actualiza la fila en `settings`.
  2. Llama a `scheduler.reschedule_job(job_id, trigger=IntervalTrigger(seconds=new))`.
  3. Sin restart del proceso.
- Los jobs **no persisten** (sin `SQLAlchemyJobStore`). Se recrean en cada arranque leyendo `settings`. El historial de ejecuciones vive en la tabla `scrape_runs`.

## Letterboxd client (`services/letterboxd/client.py`)

Wrapper sobre `httpx.AsyncClient` con:

- `User-Agent` desde `Settings.USER_AGENT`.
- Rate limit por dominio: semáforo + sleep mínimo (≥2 s) entre requests al mismo host.
- Reintentos solo en `5xx`, exponential backoff (1 s / 2 s / 4 s), máximo 3 intentos.
- **NO reintentar 403**: es Cloudflare diciendo "no". Falla ruidosa, logear URL exacta.
- Timeout: 30 s.

## Persistencia de config dinámica

Tabla `settings(key TEXT PK, value TEXT, updated_at TIMESTAMP)`.

- Primer arranque: para cada clave conocida (`RSS_INTERVAL`, `FLAP_CONFIRM_SCRAPES`, etc.), insertar si no existe usando el valor de la env var del mismo nombre.
- Lectura: el scheduler y cualquier código que necesite la config la lee de `settings`, no de `os.environ`.
- Modificación: la UI escribe en `settings` y llama al método público del scheduler para aplicar.

## Logging

`structlog` con:

- Processor que añade `user_id`, `job_id`, `request_id` cuando estén en el contexto (`structlog.contextvars`).
- Output:
  - `LOG_FORMAT=json` → `JSONRenderer()`.
  - `LOG_FORMAT=plain` → `ConsoleRenderer(colors=True)`.
- Nivel desde `LOG_LEVEL`.
- `print()` **prohibido** en código de aplicación (regla en [`rules.md`](rules.md)).

## Testing

- `pytest` con `pytest-asyncio` en modo `auto`.
- Fixtures HTML/RSS reales en `tests/fixtures/` (recortes de los capturados durante la investigación: watchlist página 1, films/page 1, RSS feed, /lists/, ficha individual). Cada fixture ≤ 5 KB.
- Tests de parsers (`services/letterboxd/*.py`): input = fixture, output = struct tipado. Sin red.
- Tests de scrape orchestration: mock `httpx` con `respx`.
- Tests de DB: SQLite in-memory por test (fixture `engine`).
- Coverage objetivo: parsers ≥ 90%, orchestration ≥ 70%.

## Lint, format, type check

- `uv run ruff check src tests`
- `uv run ruff format src tests`
- `uv run mypy src` (con `strict = true` en `pyproject.toml`).
- Pre-commit hooks: opcional, decisión al implementar.

Config en `pyproject.toml`:

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.mypy]
strict = true
python_version = "3.12"
```

## Docker

Multi-stage:

```dockerfile
# Builder
FROM python:3.12-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Runtime
FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY src/ /app/src/
COPY alembic/ /app/alembic/
COPY alembic.ini /app/
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fs http://127.0.0.1:8080/healthz || exit 1
CMD ["uvicorn", "watchlistarr.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

- Imagen final esperada ~150–180 MB.
- Volumen `/data` para el archivo SQLite (`DATABASE_URL=sqlite+aiosqlite:///data/watchlistarr.db`).
- Un solo proceso (`uvicorn`). APScheduler embebido en el mismo loop.
