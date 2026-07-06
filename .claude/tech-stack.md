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
| Frontend | React 18 + Babel-standalone | SPA en `src/watchlistarr/static/`, sin build step (Babel compila los `.jsx` en el navegador). React/ReactDOM/Babel vendorizados en `static/vendor/` para que la imagen Docker funcione offline. |
| CSS | Vanilla (design tokens en `static/styles.css`) | Dark theme, oklch + variables. Geist y Geist Mono vendorizados en `static/vendor/geist/`. |
| Data fetching | `fetch` directo contra `/api/v1/*` | JSON-only, sin cliente intermedio. Bootstrap inicial via `GET /api/v1/bootstrap`. |
| DB | SQLite | Un archivo en volumen Docker |
| Data layer | SQLAlchemy 2.0 async + Alembic | `Mapped[T]` declarative |
| Driver SQLite | `aiosqlite` | Async oficial |
| Cliente HTTP | `httpx` async | Wrapper propio con UA + rate limit |
| Parser HTML | BeautifulSoup4 + `lxml` | lxml para velocidad |
| Parser RSS | `feedparser` | Maneja namespaces de Letterboxd sin esfuerzo |
| Scheduler | APScheduler 3.x | `AsyncIOScheduler` embebido en el loop de FastAPI |
| Validación / settings | Pydantic v2 + `pydantic-settings` | `BaseSettings` lee `.env` y `os.environ` |
| Logging | `structlog` | JSON en prod, plain en dev |
| Testing | `pytest` + `pytest-asyncio` + `pytest-cov` + `respx` | Fixtures HTML/RSS recortados |
| Linter / formatter | `ruff` | Sustituye black/isort/flake8 |
| Type checker | `mypy --strict` | En CI |
| Package manager | `uv` | Venv + lockfile + Python versions |
| Docker base | `python:3.12-slim-bookworm` | lxml sin compilación |

## Versiones congeladas (pyproject.toml)

**`pyproject.toml` es la fuente canónica** (pin exacto en `uv.lock`); este bloque es una copia de conveniencia — ante cualquier duda, verificar allí:

```toml
[project]
requires-python = ">=3.12"
dependencies = [
    "fastapi ~= 0.115",
    "uvicorn[standard] ~= 0.32",
    "sqlalchemy[asyncio] ~= 2.0",
    "greenlet ~= 3.1",
    "aiosqlite ~= 0.20",
    "alembic ~= 1.13",
    "httpx ~= 0.27",
    "beautifulsoup4 ~= 4.12",
    "lxml ~= 5.3",
    "feedparser ~= 6.0",
    "apscheduler ~= 3.10",
    "pydantic ~= 2.9",
    "pydantic-settings ~= 2.6",
    "structlog ~= 24.4",
]

[dependency-groups]
dev = [
    "ruff ~= 0.7",
    "mypy ~= 1.13",
    "pytest ~= 8.3",
    "pytest-asyncio ~= 0.24",
    "pytest-cov ~= 5.0",
    "respx ~= 0.21",
    "types-beautifulsoup4 ~= 4.12",
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
├── .github/workflows/ci.yml   # ruff ×2, mypy, pytest --cov, smoke + publish imagen
├── scripts/                   # smoke.py (E2E), backfill_imdb.py, backfill_ratings.py
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
├── src/watchlistarr/
│   ├── __init__.py
│   ├── main.py                # FastAPI app factory + lifespan
│   ├── config.py              # Settings (Pydantic)
│   ├── db.py                  # engine, session factory, pragmas SQLite (WAL)
│   ├── logging.py             # structlog setup
│   ├── models/                # SQLAlchemy models (Mapped[T])
│   ├── schemas/               # Pydantic schemas para API I/O
│   ├── services/
│   │   ├── letterboxd/
│   │   │   ├── client.py      # httpx wrapper (UA + rate limit por instancia)
│   │   │   ├── rss.py
│   │   │   ├── lists.py
│   │   │   ├── films.py       # backstop /films/ p1
│   │   │   └── film_page.py   # /film/{slug}/ → tmdb_id
│   │   ├── scrape/            # orquestadores full + incremental
│   │   │   ├── anti_flap.py
│   │   │   ├── audit.py       # scrape_runs + fail_interrupted_runs
│   │   │   ├── discovery.py
│   │   │   ├── film_resolver.py
│   │   │   ├── films_backstop.py
│   │   │   ├── imdb_backfill.py
│   │   │   ├── initial_run.py
│   │   │   ├── lists.py
│   │   │   ├── rating_backfill.py
│   │   │   ├── rss_watcher.py
│   │   │   └── watchlist.py
│   │   ├── custom_lists.py    # resolver multi-source + rotación
│   │   ├── intervals.py       # override por entidad `or` default de env
│   │   ├── log_buffer.py
│   │   ├── log_messages.py
│   │   ├── onboarding.py      # initial run al añadir user
│   │   └── radarr.py          # serializador JSON
│   ├── scheduler.py           # APScheduler wiring
│   ├── routes/api/
│   │   ├── v1.py              # JSON API consumida por la SPA
│   │   ├── radarr.py          # /<user>/<slug>/, /lists/<slug>/ → Radarr Custom List
│   │   └── admin.py           # POST /admin/refresh/{job_id}, POST /admin/scheduler/sync
│   └── static/                # SPA shell + JSX + vendor
│       ├── index.html
│       ├── styles.css
│       ├── tweaks-panel.jsx
│       ├── src/
│       │   ├── app.jsx
│       │   ├── icons.jsx
│       │   ├── ui.jsx
│       │   ├── data.jsx       # window.API (fetch wrappers)
│       │   └── pages/
│       └── vendor/
│           ├── react.min.js
│           ├── react-dom.min.js
│           ├── babel.min.js
│           └── geist/         # geist.css + .woff2
└── tests/
    ├── conftest.py
    ├── fixtures/              # HTML/RSS recortados de Letterboxd real
    ├── unit/
    └── integration/
```

`src/` layout — los tests no pueden importar accidentalmente del checkout sin instalar el paquete (más seguro y estándar).

## Ciclo de vida (FastAPI lifespan)

Al arrancar (`src/watchlistarr/main.py`, `lifespan`):

1. Configurar `structlog` según `LOG_FORMAT` + instalar el buffer handler de Activity.
2. Ejecutar `alembic upgrade head` (idempotente, en thread). Después se re-aplica la config de logging: `alembic.fileConfig` pisa los handlers del root logger.
3. Crear engine SQLAlchemy con `DATABASE_URL` (`init_engine`).
4. `fail_interrupted_runs`: marcar como `error` los `scrape_runs` que quedaron `running` de un proceso anterior.
5. Crear `JobScheduler` y llamar a `sync_jobs()`: registra todos los jobs (rotation-tick, prune-scrape-runs; por user: RSS, discovery, films-backstop, watchlist incr/full; por lista enabled: incr/full) leyendo intervalos de env + columnas override por entidad (`services/intervals.py`).
6. Arrancar el scheduler.
7. Listo para servir HTTP.

Al cerrar:

1. `scheduler.shutdown()` (`wait=True`, delegado al threadpool para no bloquear el loop).
2. Cerrar engine (`dispose_engine`).

## APScheduler wiring

- `AsyncIOScheduler` corriendo en el mismo loop que FastAPI (no procesos separados).
- Cada job se identifica con un `job_id` estable (`scheduler.py`): globales `rotation-tick` y `prune-scrape-runs`; por entidad `rss-{user_id}`, `discovery-{user_id}`, `films-backstop-{user_id}`, `watchlist-incr-{user_id}`, `watchlist-full-{user_id}`, `list-incr-{list_id}`, `list-full-{list_id}`. `POST /admin/refresh/{job_id}` exige el id exacto.
- No hay reschedule granular en runtime: cuando la UI cambia un intervalo (`POST /api/v1/users/{u}/lists/{id}/settings`) o el set de listas enabled, el handler escribe las columnas override en `users`/`lists` y llama a `scheduler.sync_jobs()`, que hace **remove-all + re-add** de todos los jobs releyendo DB + env (`routes/api/v1.py`, `scheduler.py:sync_jobs`). Sin restart del proceso. `JobScheduler.reschedule` existe pero ningún endpoint lo usa.
- Los jobs **no persisten** (sin `SQLAlchemyJobStore`). Se recrean en cada arranque vía `sync_jobs()` desde DB + env. El historial de ejecuciones vive en la tabla `scrape_runs`.

## Letterboxd client (`services/letterboxd/client.py`)

Wrapper sobre `httpx.AsyncClient` con:

- `User-Agent` desde `Settings.USER_AGENT`.
- Rate limit **por instancia de cliente** (no global ni por dominio): un `asyncio.Lock` + sleep mínimo (≥2 s, `MIN_INTERVAL_SECONDS`) entre requests de esa instancia. Cada job del scheduler y cada run de onboarding crea su propio cliente, así que dos jobs concurrentes del mismo user sí pueden pegar a Letterboxd en paralelo (hay un test de concurrencia que lo ejercita: `tests/integration/test_scrape_concurrency.py`).
- Reintentos solo en `5xx`, exponential backoff (1 s / 2 s / 4 s), máximo 3 intentos.
- **NO reintentar 403**: es Cloudflare diciendo "no". Falla ruidosa, logear URL exacta.
- Timeout: 30 s.

## Persistencia de config dinámica

**No hay tabla de settings global.** La configuración se resuelve en dos capas:

- **Env (inmutable en runtime)**: `Settings` de Pydantic (`config.py`) lee `.env`/`os.environ` una vez por proceso (`get_settings()` cacheado con `lru_cache`). Cambiar un default exige reiniciar el contenedor.
- **Overrides por entidad**: columnas nullable en `users` (`rss_interval`, `watchlist_incremental_interval`, `watchlist_full_interval`, `films_backstop_interval`, `discovery_interval`) y `lists` (`lists_incremental_interval`, `lists_full_interval`, `flap_confirm_scrapes`). `services/intervals.py` las resuelve con semántica `or`: `override or default_de_env` (NULL → cae al env; excepción: `flap_confirm_scrapes` usa chequeo explícito de `is None` para que `0` sea un override válido).
- **Escritura**: `POST /api/v1/users/{u}/lists/{id}/settings` escribe incr/full de watchlist en `users`, incr/full de lista en `lists`, más `flap_confirm_scrapes`, y luego llama a `scheduler.sync_jobs()`. `rss_interval`, `films_backstop_interval` y `discovery_interval` no tienen endpoint ni UI: solo editables a mano en la DB (el scheduler sí los honra).

Candidato (no implementado): tabla global `settings(key, value, updated_at)` seeded desde env y editable por la UI — se creó en la migración `0001` y se **dropeó** en `0002_settings_per_entity.py`; retirada en favor de los overrides por entidad.

## Logging

`structlog` con:

- Processor que añade `user_id`, `job_id`, `request_id` cuando estén en el contexto (`structlog.contextvars`).
- Output:
  - `LOG_FORMAT=json` → `JSONRenderer()`.
  - `LOG_FORMAT=plain` → `ConsoleRenderer(colors=True)`.
- Nivel desde `LOG_LEVEL`.
- `print()` **prohibido** en código de aplicación (regla en [`rules.md`](rules.md)).

## Testing

- `pytest` con `pytest-asyncio` en modo `auto`. Coverage con `pytest-cov` (CI: `uv run pytest --cov=src/watchlistarr --cov-report=term`). Stubs de tipos: `types-beautifulsoup4` (grupo dev).
- Fixtures HTML/RSS reales en `tests/fixtures/` (recortes de los capturados durante la investigación: watchlist página 1, films/page 1, RSS feed, /lists/, ficha individual). Cada fixture ≤ 5 KB.
- Tests de parsers (`services/letterboxd/*.py`): input = fixture, output = struct tipado. Sin red.
- Tests de scrape orchestration: mock `httpx` con `respx`.
- Tests de DB: SQLite in-memory por test (fixture `engine`).
- Coverage: aspiración parsers ≥ 90% / orchestration ≥ 70% — **ningún threshold se aplica** (ni `fail_under` en `pyproject.toml` ni gate en CI; el step de pytest solo imprime el reporte).

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

Multi-stage — **el `Dockerfile` de la raíz del repo es la fuente canónica** (no copiar bloques de este doc a overrides sin contrastarlo). Anatomía:

- **Builder** (`python:3.12-slim-bookworm`): copia `uv` desde `ghcr.io/astral-sh/uv:latest` y ejecuta `uv sync --frozen --no-dev` sobre `pyproject.toml` + `uv.lock` (+ `src/` y `README.md`, que hatchling necesita para el build).
- **Runtime** (`python:3.12-slim-bookworm`): copia `.venv` + `src/` + `alembic/` + `alembic.ini`; `VOLUME /data`, `EXPOSE 8080`.
- `ENV DATABASE_URL="sqlite+aiosqlite:////data/watchlistarr.db"` — **4 slashes** = ruta absoluta `/data/watchlistarr.db`. El default de `config.py` con 3 slashes (`sqlite+aiosqlite:///data/...`, relativa) es solo para dev local fuera de Docker.
- Healthcheck vía python stdlib porque **`curl` no está instalado en la imagen slim**: `HEALTHCHECK ... CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).status==200 else 1)"`.
- `CMD ["uvicorn", "watchlistarr.main:app", "--host", "0.0.0.0", "--port", "8080"]` — un solo proceso; APScheduler embebido en el mismo loop.
- Imagen final esperada ~150–180 MB. Volumen `/data` para el archivo SQLite.
