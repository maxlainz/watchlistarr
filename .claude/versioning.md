# Versionado

Reglas para cortar releases de watchlistarr. Leer antes de bumpear versión o publicar imagen Docker etiquetada.

## SemVer

Formato `MAJOR.MINOR.PATCH`. Mientras estemos en `0.x.y`, está permitido romper compatibilidad en MINOR — pero hay que documentarlo en el CHANGELOG.

- **MAJOR**: cambios incompatibles en superficies estables.
  - Endpoint Radarr (`/radarr/list/{id}` y la forma del JSON).
  - Env vars obligatorias renombradas o eliminadas.
  - Esquema DB sin migración Alembic automática.
- **MINOR**: nueva funcionalidad backwards-compatible.
  - Nuevos endpoints HTTP, nuevas env vars opcionales, nuevos scrapers.
  - Cambios de DB con migración Alembic incluida.
- **PATCH**: bugfix backwards-compatible. Sin cambios de schema ni de contrato.

## Conventional Commits → bump

El repo ya usa prefijos en los mensajes (`feat:`, `fix:`, `docs:`, `refactor:`, `ci:`, `chore:`, `test:`). Cómo se traducen al decidir un release:

| Prefijo en commits desde el último tag | Bump |
|---|---|
| `feat!:` o cualquier commit con `BREAKING CHANGE:` en el cuerpo | MAJOR |
| Al menos un `feat:` (sin breaking) | MINOR |
| Solo `fix:` (y otros sin impacto funcional) | PATCH |
| Solo `docs:` / `chore:` / `refactor:` / `ci:` / `test:` | No cortar release |

## Tags git

- Formato: `v<MAJOR>.<MINOR>.<PATCH>`, ej. `v0.2.0`. Siempre con prefijo `v`.
- **Anotados, no lightweight**: `git tag -a v0.2.0 -m "v0.2.0"`.
- Solo desde `main`, después de mergear `dev`. Nunca taggear desde `dev`.

## Tags en Docker Hub y GHCR

Los produce `docker/metadata-action` en [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) automáticamente. Cada build publica los mismos tags en **dos registries**: `maxlainz/watchlistarr` (Docker Hub) y `ghcr.io/maxlainz/watchlistarr` (GitHub Container Registry, autenticado con el `GITHUB_TOKEN` del workflow — no necesita secrets propios).

| Origen | Tags publicados en ambos registries |
|---|---|
| Push a `main` (commit normal) | `latest`, `sha-<short>` |
| Push de tag `v0.2.0` | `0.2.0`, `0.2`, `sha-<short>` |
| Push a `dev` u otra rama | Nada (CI corre QA pero no publica) |

`latest` siempre apunta al `HEAD` de `main`. Para producción reproducible, en `docker-compose.yml` usar el tag semver (`maxlainz/watchlistarr:0.2.0`), no `latest`.

Mientras estemos en `0.x.y` no publicamos el tag `:0` — el `pattern={{major}}` no está activo en el workflow porque aporta poco.

## Procedimiento de release

Desde `main` actualizado y con CI verde:

1. Decidir bump según la tabla de arriba. Calcular `X.Y.Z`.
2. Editar [`pyproject.toml`](../pyproject.toml) — campo `version = "X.Y.Z"`.
3. Editar [`src/watchlistarr/__init__.py`](../src/watchlistarr/__init__.py) — `__version__ = "X.Y.Z"`. **Doble bump obligatorio**: si solo cambias uno, `/healthz` y `pyproject` se desincronizan.
4. Editar [`CHANGELOG.md`](../CHANGELOG.md): mover el bloque `## [Unreleased]` a `## [X.Y.Z] - YYYY-MM-DD` y crear un nuevo `[Unreleased]` vacío arriba. Las entradas se escriben **en inglés** (el CHANGELOG es público y el README lo enlaza).
5. Sincronizar `uv.lock`: `uv lock` — refresca la entrada `[[package]] name = "watchlistarr"` con la nueva `version`. **Obligatorio antes del commit**: el lockfile incluye la versión del propio paquete y el CI corre `uv sync --frozen`, que falla si `pyproject.toml` y `uv.lock` discrepan. Verificar con `grep -A1 'name = "watchlistarr"' uv.lock | grep version` que aparece `X.Y.Z`.
6. Correr CI local completo (ver [`rules.md` → CI](rules.md#ci-github-actions-githubworkflowsciyml)). Si esto se hace antes del paso 5, `uv run` regenera `uv.lock` por su cuenta y el commit lo agarra; pero el orden explícito evita olvidos.
7. Commit: `chore(release): vX.Y.Z` (incluye los **4 archivos** editados: `pyproject.toml`, `src/watchlistarr/__init__.py`, `CHANGELOG.md`, `uv.lock`).
8. Tag anotado: `git tag -a vX.Y.Z -m "vX.Y.Z"`.
9. Push: `git push origin main && git push origin vX.Y.Z`.
10. Opcional, recomendado: `gh release create vX.Y.Z --notes-file <(awk '/^## \[X\.Y\.Z\]/,/^## \[/' CHANGELOG.md | head -n -1)` — o crear la Release a mano pegando el bloque del CHANGELOG.

> **Pitfall histórico — v1.2.2**: olvidar el paso 5 dejó `uv.lock` con la versión vieja en el commit `chore(release)`. CI con `uv sync --frozen` habría fallado sobre el tag (impidiendo publicar la imagen Docker) y requirió `git commit --amend` + borrar tag remoto + retag + force-push de `main`. Coste evitable con `uv lock` antes del commit.

## Verificación tras el push

- En **Actions**, los jobs `qa` y `docker` deben correr en el contexto del tag y completar.
- En **Docker Hub** (`https://hub.docker.com/r/maxlainz/watchlistarr/tags`), aparecen `X.Y.Z`, `X.Y`, `sha-<short>`. `latest` apunta al mismo digest si el tag se cortó desde `HEAD` de `main`. Mismos tags en **GHCR** (`https://github.com/maxlainz/watchlistarr/pkgs/container/watchlistarr`).
- `docker pull maxlainz/watchlistarr:X.Y.Z` y luego:
  ```
  docker run --rm maxlainz/watchlistarr:X.Y.Z \
    python -c "import watchlistarr; print(watchlistarr.__version__)"
  ```
  debe devolver `X.Y.Z`.
- `/healthz` del contenedor devuelve `"version": "X.Y.Z"`.
- Multi-arch: `docker manifest inspect maxlainz/watchlistarr:X.Y.Z | jq '.manifests[].platform'` muestra `linux/amd64` y `linux/arm64`.
