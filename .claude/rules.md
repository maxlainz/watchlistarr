# Reglas de código, git y estilo

## Git

- Rama de trabajo: `dev`. Nunca commitear directamente a `main`.
- Tras cada edición de código → commit en `dev` → `git push` inmediato → **rebuild del contenedor dev local**. Detalle del rebuild en [`workflows.md`](workflows.md#refresh-local-tras-cada-commit).
- Merge a `main` solo si el usuario lo pide explícitamente. El mensaje debe resumir todo lo nuevo desde el anterior commit en `main`.
- `CLAUDE.md` y `.claude/` **sí** entran a `main` en este repo (no se excluyen en el merge).
- Commits en español, mensaje corto y descriptivo. Prefijos convencionales (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`) bienvenidos pero no obligatorios.

## CI (GitHub Actions, [`.github/workflows/ci.yml`](../.github/workflows/ci.yml))

CI corre 5 steps en `qa`: `ruff check`, `ruff format --check`, `mypy`, `pytest`, `scripts/smoke.py`. Antes de pushear, ejecutar **todos** localmente — un fallo en cualquiera bloquea el merge. El comando único de abajo es el gate de la casa, no una réplica exacta del CI (ver primer bullet).

- **Local ≠ CI, a propósito**: CI solo linta y format-checkea `src tests` (`ci.yml:35,38`); el comando de la casa añade `scripts` — gate deliberadamente más estricto en local (un fallo de lint solo-en-`scripts` te bloquea aquí pero pasaría CI). El pytest de CI además corre con `--cov=src/watchlistarr --cov-report=term` (mismos tests; coverage informativo, sin umbral).
- **`ruff format --check`** se rompe en silencio cuando añades código nuevo sin formatear. Correr `uv run ruff format src tests scripts` antes del commit.
- **`scripts/smoke.py`** importa modelos y golpea endpoints reales con un server real. Si renombras un modelo, cambias el esquema de la DB, alteras una ruta HTTP o cambias la forma del JSON, actualízalo en el mismo commit. Es la única red de seguridad end-to-end del CI.
- **Cualquier cambio en `pyproject.toml`** (deps añadidas/quitadas) requiere `uv lock` + commitear `uv.lock`. CI usa `--frozen` y falla si no concuerdan.
- Cuando añadas/borres rutas HTTP, actualiza también los asserts `404` en `scripts/smoke.py` y `tests/integration/test_ui_smoke.py` para que las rutas viejas sigan siendo verificadas como muertas.
- **Cambios en `.github/workflows/ci.yml` no se validan en local** — los 5 steps no cubren el workflow en sí. Antes de tocar un pin de action, verificar que el ref existe (`git ls-remote --tags`; no todas publican tag flotante de major — p.ej. `setup-uv` solo publica minors flotantes tipo `v8.2`). Tras pushear a `dev`, **esperar a que el run remoto esté en verde antes de mergear a `main`**.

Comando único antes de pushear:

```
uv run ruff check src tests scripts && \
uv run ruff format --check src tests scripts && \
uv run mypy src && \
uv run pytest -q && \
uv run python scripts/smoke.py
```

## Versionado

Cortamos releases con tags `vX.Y.Z` desde `main`. SemVer + Conventional Commits → bump, doble bump (`pyproject.toml` + `__init__.py`) y entrada en `CHANGELOG.md` en el mismo commit `chore(release): vX.Y.Z`. Push del tag dispara build Docker multi-arch con tags `X.Y.Z` y `X.Y`. Detalles, tabla de mapping y procedimiento paso a paso: [`versioning.md`](versioning.md).

## Idioma

- Documentación interna (`.claude/`, `CLAUDE.md`), comentarios (cuando existan) y mensajes de commit: español.
- **`README.md` y `CHANGELOG.md`: inglés** — son la cara pública del repo.
- Código, identificadores, nombres de archivos, branches y variables de entorno: inglés.

## Lenguaje y tipado

- **Python 3.12+** (floor). Pin en `pyproject.toml`.
- **Type hints en todo el código de aplicación**. `from __future__ import annotations` no necesario en 3.12+.
- **`mypy --strict`** en CI. Sin `Any` salvo en fronteras (HTML scraping, JSON de Radarr) — y entonces convertir a tipos propios cuanto antes.
- **Pydantic v2** para schemas de I/O (API request/response, settings, structs de scraping). No para modelos de DB (esos van con SQLAlchemy `Mapped[T]`).
- **`ruff`** como linter + formatter (sustituye black/isort/flake8). Config en `pyproject.toml`.
- Configuración (puertos, paths, intervalos, credenciales) siempre vía env vars (`Settings` de Pydantic) o columnas de override por entidad (`users`/`lists`, resueltas en `services/intervals.py`). Nunca hardcoded. (La tabla `settings` se retiró en la migración 0002.)
- Detalles de versiones, layout y comandos: [`tech-stack.md`](tech-stack.md).

## Estilo de código

- Módulos por dominio (`services/letterboxd/`, `services/scrape/`, etc.), no por capa horizontal.
- **Async-first**. Si una función puede ser async (toca DB o red), lo es. No mezclar sync + async sin razón.
- Funciones pequeñas; una función hace una cosa.
- `print()` prohibido en código de aplicación; usar `structlog`.
- No `from x import *`. Imports explícitos.
- Frontend: SPA React 18 servida desde `static/`, sin build step (Babel-standalone). No introducir bundlers ni dependencias de build (Vite, webpack, etc.).
- Tests viven en `tests/`, espejando la estructura de `src/watchlistarr/`.

## Comentarios

- Por defecto, sin comentarios.
- Solo añadir uno cuando el WHY no es obvio: restricción de la web de Letterboxd, workaround de un bug concreto, invariante sutil, rate limit no evidente.
- Nunca explicar el QUÉ — el nombre de la función ya lo dice.

## Abstracciones

- Sin abstracciones prematuras. Tres líneas similares son preferibles a un helper genérico si no hay reutilización real.
- No añadir manejo de errores para escenarios imposibles. Confiar en las garantías del framework.
- Validación solo en fronteras del sistema: input de usuario en la UI, respuesta del scraper sobre Letterboxd, payload que se envía a Radarr.
- Sin feature flags ni shims de retrocompatibilidad mientras no haya usuarios externos. Cambiar el código directamente.

## Scraping de Letterboxd

Letterboxd no ofrece API pública estable; el proyecto entero se apoya en scraping del HTML público y el RSS de usuario. Reglas operativas permanentes:

- **Rate limit**: una request cada X segundos como mínimo (ajustar empíricamente, empezar conservador con 2-3 s). Nunca paralelizar peticiones a la misma cuenta de Letterboxd. Estado real: hoy el límite es **por instancia de `LetterboxdClient`** y cada job/onboarding crea su propio cliente (6 sitios en `src/`), así que jobs concurrentes del mismo user sí pueden golpear Letterboxd en paralelo — la regla sigue vigente como ley, pero aún no está aplicada globalmente. Candidato (no implementado): limitador global por dominio.
- **User-Agent**: identificarse con `watchlistarr/<version> (+<repo-url>)`. No suplantar navegador.
- **Caché**: cachear respuestas durante el ciclo de scraping. Si una lista no ha cambiado (mismo número de items, mismo orden) no re-scrapear sus detalles.
- **Robustez al cambio de HTML**: si un selector falla, fallar ruidosamente y loggear suficiente contexto para reparar el selector. No intentar "adivinar" estructura alternativa.
- **Datos mínimos**: extraer solo lo que se necesita (TMDB ID, título, año). No clonar metadatos enteros que Radarr ya tiene de TMDB.
