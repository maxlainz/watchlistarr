# watchlistarr

Scrapea listas y RSS públicos de Letterboxd → DB SQLite interna (autoritativa, multi-user) → sirve
endpoints JSON que Radarr consume como Custom List. Docker-based, con SPA React de control (users,
listas, custom lists multi-source con filtros/rotación/snapshot). El código es la ground truth de
toda la documentación.

## Reglas

- Desarrollo siempre en rama `dev`; merge a `main` solo cuando se pida explícitamente.
- Tras cada edición de código → commit en `dev` → `git push` inmediato → `docker compose -f docker-compose.dev.yml up -d --build` para refrescar la copia local de QC (puerto = `HTTP_PORT` de tu `.env`; 8080 en un clone fresco). Detalles: [`.claude/workflows.md` → Refresh local](.claude/workflows.md#refresh-local-tras-cada-commit).
- **Antes de pushear, correr los 5 steps del CI localmente** (`ruff check`, `ruff format --check`, `mypy`, `pytest`, `scripts/smoke.py`). Si tocas modelos, rutas HTTP o forma del JSON, **actualiza `scripts/smoke.py` en el mismo commit** — es la única red de seguridad end-to-end. Detalle por step: [`.claude/rules.md` → CI](.claude/rules.md#ci-github-actions-githubworkflowsciyml).
- **El payload de Radarr es sagrado**: cambiar la forma del JSON servido, el esquema de URLs o la semántica de 404 es breaking por defecto — checklist de enforcement en `.claude/skills/watchlistarr-change-control/`.
- `CLAUDE.md` y `.claude/` **sí** viajan a `main` (no excluir en merge, a diferencia de otros proyectos personales).
- Al mergear a `main`, el mensaje debe resumir todo lo nuevo desde el último commit en `main`.
- Idioma: docs internos (`.claude/*.md`) y commits en español; `README.md` y `CHANGELOG.md` en inglés (cara pública); **las skills de `.claude/skills/` en inglés** (excepción aprobada 2026-07 — audiencia: sesiones de IA y contributors externos). Identificadores, ramas y código en inglés.
- Cortar releases con tag `vX.Y.Z` solo desde `main`. Doble bump (`pyproject.toml` + `src/watchlistarr/__init__.py`) y entrada en `CHANGELOG.md` en el mismo commit `chore(release): vX.Y.Z`. Cambios solo-docs no cortan release. Detalles: [`.claude/versioning.md`](.claude/versioning.md).

## Capas de documentación (orden de lectura)

1. **Este archivo** — router y reglas de convivencia.
2. [`.claude/rules.md`](.claude/rules.md) — ley de la casa: git, CI, idioma, tipado, estilo, scraping.
3. Docs de dominio en `.claude/` — la referencia de diseño (tabla abajo).
4. **Skills en [`.claude/skills/`](.claude/skills/)** — 16 runbooks operativos en inglés con
   profundidad ejecutable (comandos exactos, anclas `file:line`, incidentes históricos). Cada una
   declara cuándo usarla y cuándo NO en su frontmatter.
5. `README.md` / `CHANGELOG.md` — cara pública, en inglés.

**Regla de mantenimiento**: si un cambio de código altera un hecho que una skill guarda en su
sección "Provenance and maintenance", actualiza esa skill **en el mismo commit**. Drift que no
puedas arreglar en el momento → fila en la tabla de erratas de
`.claude/skills/watchlistarr-docs-and-writing/`. Ante cualquier contradicción doc↔código, gana el
código; corrige el doc o registra la errata.

## Contexto de diseño (leer según tarea)

| Archivo | Cuándo leer |
|---|---|
| [`.claude/rules.md`](.claude/rules.md) | Antes de cualquier edición — git, CI, idioma, tipado, comentarios, estilo |
| [`.claude/architecture.md`](.claude/architecture.md) | Stack, componentes (scraper, DB, API a Radarr, RSS watcher, UI) |
| [`.claude/radarr-custom-list.md`](.claude/radarr-custom-list.md) | Antes de tocar la API que sirve a Radarr — formato JSON, pitfalls, headers |
| [`.claude/letterboxd-rss.md`](.claude/letterboxd-rss.md) | Antes de tocar el RSS watcher — formato del feed, namespaces, edge cases |
| [`.claude/letterboxd-lists.md`](.claude/letterboxd-lists.md) | Antes de tocar el scraper de listas — selectores, paginación, TMDB ID, anti-bot |
| [`.claude/data-model.md`](.claude/data-model.md) | Antes de tocar la DB o endpoints con estado — entidades, multi-user, identidad canónica |
| [`.claude/sync-strategy.md`](.claude/sync-strategy.md) | Antes de tocar scheduling, scraping o invalidación — frecuencias, anti-flap |
| [`.claude/ui-features.md`](.claude/ui-features.md) | Antes de tocar la GUI — páginas, acciones, qué se configura por web vs env |
| [`.claude/tech-stack.md`](.claude/tech-stack.md) | Dependencias, configuración del proyecto, estructura de directorios |
| [`.claude/workflows.md`](.claude/workflows.md) | Comandos de desarrollo, Docker, deploy, merge a `main`, variables de entorno |
| [`.claude/versioning.md`](.claude/versioning.md) | Antes de cortar una release — SemVer, tags, CHANGELOG, procedimiento |

## Enrutado tarea → skill

| Si la tarea es… | Empieza por |
|---|---|
| Commitear, mergear, clasificar un cambio como breaking, cortar release | `watchlistarr-change-control` |
| Algo está roto en runtime (sync parado, 403, DB locked, Radarr vacío, flicker) | `watchlistarr-debugging-playbook` |
| Inspeccionar estado de una instancia YA (DB, scheduler, payload servido) | `watchlistarr-diagnostics-and-tooling` (scripts read-only) |
| "¿Esto ya pasó antes?" / revisar código que toca UNIQUE, positions, transacciones | `watchlistarr-failure-archaeology` |
| Diseñar un cambio que toca sync, modelos, rutas, scheduler u orden servido | `watchlistarr-architecture-contract` (invariantes I1-I8) |
| Selectores/URLs/RSS de Letterboxd, scrape devuelve 0 items | `letterboxd-scraping-reference` |
| Contrato JSON de Radarr, StevenLu, ETag, mass-delete | `radarr-integration-reference` |
| Env vars, intervalos, precedencia de settings, "mi cambio de .env no aplica" | `watchlistarr-config-and-flags` |
| Setup local, deps/uv.lock, migraciones Alembic, Dockerfile/compose | `watchlistarr-build-and-env` |
| Arrancar/operar, QC loop, triggers manuales, backup, onboarding real | `watchlistarr-run-and-operate` |
| CI rojo, añadir tests, qué asserts de smoke.py tocar | `watchlistarr-validation-and-qa` |
| Escribir/corregir docs, política de idioma, tabla de erratas | `watchlistarr-docs-and-writing` |
| Endurecer el sistema (rate limiting global, zero-flap, primer sync, correctness) | `watchlistarr-hardening-campaign` (4 tracks con gates) |
| Reproducir/probar una hipótesis con evidencia (fixtures, respx, bisect, EXPLAIN) | `watchlistarr-proof-and-analysis-toolkit` |
| Explicar un mecanismo desconocido antes de arreglar; proponer/retirar ideas | `watchlistarr-research-methodology` |
| Elegir la próxima inversión ambiciosa; claims públicos; integraciones nuevas | `watchlistarr-research-frontier` (incluye non-goals) |

## Actualización de docs

- Actualizar los docs de `.claude/` tras cualquier cambio mayor en arquitectura, comandos o reglas,
  y las skills afectadas en el mismo commit (regla de mantenimiento de arriba).
- Triggers detallados de qué actualizar cuándo: `.claude/skills/watchlistarr-docs-and-writing/`.
