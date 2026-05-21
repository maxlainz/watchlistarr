# watchlistarr

Alternativa moderna a [letterboxd-list-radarr](https://github.com/screeny05/letterboxd-list-radarr) (deprecado por cambios en la API de Letterboxd).

Scrapea listas y RSS públicos de Letterboxd → DB interna → expone una API que Radarr consume como custom list.
Docker-based, con UI web mínima para controlar sort order, tamaño de servido a Radarr y rotación de catálogo.

## Reglas

- Desarrollo siempre en rama `dev`; merge a `main` solo cuando se pida explícitamente.
- Tras cada edición de código → commit en `dev` → `git push` inmediato → `docker compose -f docker-compose.dev.yml up -d --build` para refrescar la copia local de QC en `:8088`. Detalles: [`.claude/workflows.md` → Refresh local](.claude/workflows.md#refresh-local-tras-cada-commit).
- **Antes de pushear, correr los 5 steps del CI localmente** (`ruff check`, `ruff format --check`, `mypy`, `pytest`, `scripts/smoke.py`). Si tocas modelos, rutas HTTP o forma del JSON, **actualiza `scripts/smoke.py` en el mismo commit** — es la única red de seguridad end-to-end. Detalle por step: [`.claude/rules.md` → CI](.claude/rules.md#ci-github-actions-githubworkflowsciyml).
- `CLAUDE.md` y `.claude/` **sí** viajan a `main` (no excluir en merge, a diferencia de otros proyectos personales).
- Al mergear a `main`, el mensaje debe resumir todo lo nuevo desde el último commit en `main`.
- Actualizar los docs de `.claude/` tras cualquier cambio mayor en arquitectura, comandos o reglas.
- Idioma de docs y commits: español. Identificadores, nombres de variables, ramas y código en inglés.
- Cortar releases con tag `vX.Y.Z` solo desde `main`. Doble bump (`pyproject.toml` + `src/watchlistarr/__init__.py`) y entrada en `CHANGELOG.md` en el mismo commit `chore(release): vX.Y.Z`. Detalles: [`.claude/versioning.md`](.claude/versioning.md).

## Contexto (leer según tarea)

| Archivo | Cuándo leer |
|---|---|
| [`.claude/rules.md`](.claude/rules.md) | Antes de cualquier edición — git, CI, idioma, tipado, comentarios, estilo |
| [`.claude/architecture.md`](.claude/architecture.md) | Stack, componentes (scraper, DB, API a Radarr, RSS watcher, UI), decisiones pendientes |
| [`.claude/radarr-custom-list.md`](.claude/radarr-custom-list.md) | Antes de tocar la API que sirve a Radarr — formato JSON, pitfalls, headers |
| [`.claude/letterboxd-rss.md`](.claude/letterboxd-rss.md) | Antes de tocar el RSS watcher — formato del feed, namespaces, tipos de item, edge cases |
| [`.claude/letterboxd-lists.md`](.claude/letterboxd-lists.md) | Antes de tocar el scraper de listas — discovery por username, selectores HTML, paginación, resolución de TMDB ID, anti-bot |
| [`.claude/data-model.md`](.claude/data-model.md) | Antes de tocar la DB o cualquier endpoint que lea/escriba estado — entidades, multi-user, custom lists multi-source, identidad canónica |
| [`.claude/sync-strategy.md`](.claude/sync-strategy.md) | Antes de tocar scheduling, scraping o invalidación — frecuencias, política anti-flap, qué fuente actualiza qué |
| [`.claude/ui-features.md`](.claude/ui-features.md) | Antes de tocar la GUI — catálogo de páginas, acciones y formularios; qué se configura por web y qué por env |
| [`.claude/tech-stack.md`](.claude/tech-stack.md) | Antes de tocar dependencias, configuración del proyecto o estructura de directorios — versiones, layout, comandos, decisiones técnicas |
| [`.claude/workflows.md`](.claude/workflows.md) | Comandos de desarrollo, Docker, deploy, merge a `main`, variables de entorno |
| [`.claude/versioning.md`](.claude/versioning.md) | Antes de cortar una release — SemVer, conventional commits → bump, tags git y Docker, CHANGELOG, procedimiento |
