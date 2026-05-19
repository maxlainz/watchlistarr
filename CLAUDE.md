# watchlistarr

Alternativa moderna a [letterboxd-list-radarr](https://github.com/screeny05/letterboxd-list-radarr) (deprecado por cambios en la API de Letterboxd).

Scrapea listas y RSS públicos de Letterboxd → DB interna → expone una API que Radarr consume como custom list.
Docker-based, con UI web mínima para controlar sort order, tamaño de servido a Radarr y rotación de catálogo.

## Reglas

- Desarrollo siempre en rama `dev`; merge a `main` solo cuando se pida explícitamente.
- Tras cada edición de código → commit en `dev` → `git push` inmediato.
- `CLAUDE.md` y `.claude/` **sí** viajan a `main` (no excluir en merge, a diferencia de otros proyectos personales).
- Al mergear a `main`, el mensaje debe resumir todo lo nuevo desde el último commit en `main`.
- Actualizar los docs de `.claude/` tras cualquier cambio mayor en arquitectura, comandos o reglas.
- Idioma de docs y commits: español. Identificadores, nombres de variables, ramas y código en inglés.

## Contexto (leer según tarea)

| Archivo | Cuándo leer |
|---|---|
| [`.claude/rules.md`](.claude/rules.md) | Antes de cualquier edición — git, idioma, tipado, comentarios, estilo |
| [`.claude/architecture.md`](.claude/architecture.md) | Stack, componentes (scraper, DB, API a Radarr, RSS watcher, UI), decisiones pendientes |
| [`.claude/radarr-custom-list.md`](.claude/radarr-custom-list.md) | Antes de tocar la API que sirve a Radarr — formato JSON, pitfalls, headers |
| [`.claude/letterboxd-rss.md`](.claude/letterboxd-rss.md) | Antes de tocar el RSS watcher — formato del feed, namespaces, tipos de item, edge cases |
| [`.claude/workflows.md`](.claude/workflows.md) | Comandos de desarrollo, Docker, deploy, merge a `main`, variables de entorno |
