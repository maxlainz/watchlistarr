"""Catálogo de mensajes humanos para eventos de structlog y patrones externos.

`MESSAGES` mapea `event` (structlog) a un template `str.format_map`. Si falta un
placeholder en runtime, `_SafeDict` lo deja como `{key}` literal en vez de
lanzar `KeyError`. Si el `event` no está en el catálogo, `humanize()` devuelve
el `fallback` (típicamente el `message` raw renderizado por structlog).

`EXTERNAL_RULES` reescribe mensajes de loggers no-structlog (APScheduler,
alembic) que llegan al buffer via `BufferHandler`.

Helpers internos:
- `_clean_slug` convierte slugs Letterboxd-style a títulos legibles.
- `humanize()` enriquece los fields con `slug_title` cuando hay un slug.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

MESSAGES: dict[str, str] = {
    # lifecycle / infra
    "watchlistarr.startup": "watchlistarr {version} starting up",
    "watchlistarr.ready": "Ready — database connected",
    "watchlistarr.shutdown": "Shutdown complete",
    "healthz.db_unreachable": "Healthcheck failed: database unreachable",
    "request.unhandled_exception": "Unhandled exception on {method} {path}",
    # scheduler
    "scheduler.synced": "Scheduler synced — {jobs} active jobs",
    "scheduler.sync_failed": "Scheduler sync failed",
    # onboarding
    "initial_run.background.start": "Initial run started for {user_label}",
    "initial_run.background.done": "Initial run finished for {user_label}",
    "initial_run.step_failed": "Initial run step failed — {source}",
    "toggle.immediate_sync_failed": "Immediate sync after toggle failed",
    # letterboxd client
    "letterboxd.forbidden": "Letterboxd rejected request — 403 Forbidden",
    "letterboxd.retry_5xx": "Retrying Letterboxd request — status {status}, attempt {attempt}",
    # discovery
    "discovery.new_list": "Discovered new list — {slug_title} for {user_label}",
    "discovery.disabled_missing": "Disabled missing list — {slug_title} for {user_label}",
    # watchlist scraper
    "watchlist.full_sync.start": "Watchlist full sync starting for {user_label}",
    "watchlist.full_sync.page": "Watchlist page {page}/{total_pages} fetched — {page_items} items",
    "watchlist.full_sync.resolving": "Resolving {total_slugs} films from watchlist for {user_label}",
    "watchlist.full_sync": "Watchlist full sync done — {resolved}/{slugs} resolved",
    "watchlist.incremental_sync": "Watchlist incremental sync done — {slugs} items",
    # list scraper
    "list.full_sync": "List full sync done — {slug_title} · {resolved}/{slugs} resolved",
    "list.incremental_sync": "List incremental sync done — {slug_title} · {slugs} items",
    # anti-flap
    "anti_flap.removed_watched": "Anti-flap: removed watched film",
    "anti_flap.rename_detected": "Anti-flap: rename detected — tmdb {old_tmdb_id} → {new_tmdb_id}",
    "anti_flap.removed_threshold": "Anti-flap: removed film after {count} missing checks",
    # custom lists
    "custom_list.init": "Custom list initialised — {chosen} films",
    "custom_list.rotated": "Custom list rotated — {rotated} films swapped",
    "custom_list.created": "Custom list created — {slug_title}",
    "custom_list.updated": "Custom list updated — {slug_title}",
    # rss / backfills
    "rss.poll": "RSS poll for {user_label} — {new} new of {total}",
    "rating_backfill.done": "Rating backfill done — {enriched}/{attempted} enriched",
    "imdb_backfill.done": "IMDB backfill done — {enriched}/{attempted} enriched",
    "films_backstop.done": "Films backstop done for {user_label} — {inserted}/{items} inserted",
    # films / users
    "film.resolve": "Resolving film {slug_title}",
    "film.skipped": "Skipped film {slug_title}",
    "user.added": "User added — {username}",
}


class _SafeDict(dict[str, Any]):
    """Dict que devuelve `{key}` literal cuando falta una clave en format_map."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


_YEAR_SUFFIX = re.compile(r"-(\d{4})$")


def _title_case(slug: str) -> str:
    return " ".join(word.capitalize() for word in slug.split("-") if word)


def _clean_slug(slug: str) -> str:
    """Convierte un slug a frase legible.

    - "the-thing-with-feathers-2025" → "The Thing With Feathers (2025)"
    - "favorites"                    → "Favorites"
    - "top-rated"                    → "Top Rated"
    - ""                             → ""
    """
    if not slug:
        return slug
    match = _YEAR_SUFFIX.search(slug)
    if match is not None:
        base = slug[: match.start()]
        return f"{_title_case(base)} ({match.group(1)})"
    return _title_case(slug)


def humanize(event: str | None, fields: dict[str, Any], fallback: str) -> str:
    """Traduce un event + fields a frase humana.

    Si los fields incluyen `slug` (str), se añade `slug_title` derivado de
    `_clean_slug` para que los templates puedan usar `{slug_title}` en lugar
    del slug crudo.

    Si `event` no está en el catálogo, o el formato falla por razones no
    previstas, devuelve `fallback` para garantizar que la UI siempre tenga
    algo que mostrar.
    """
    if not event:
        return fallback
    template = MESSAGES.get(event)
    if template is None:
        return fallback
    enriched: dict[str, Any] = dict(fields)
    slug = enriched.get("slug")
    if isinstance(slug, str) and slug:
        enriched.setdefault("slug_title", _clean_slug(slug))
    # Si hay username, úsalo como etiqueta de usuario en el mensaje principal;
    # si no, caer a "user {id}". Los templates usan {user_label} en lugar de
    # {user_id} para evitar el formato técnico "user 1" cuando hay username.
    username = enriched.get("username")
    if isinstance(username, str) and username:
        enriched.setdefault("user_label", username)
    elif "user_id" in enriched:
        enriched.setdefault("user_label", f"user {enriched['user_id']}")
    try:
        return template.format_map(_SafeDict(enriched))
    except Exception:
        return fallback


# ---- External (non-structlog) message rewriting ---------------------------
#
# APScheduler 3.x loguea con formato: 'Job "%s" executed successfully' % job,
# donde `job.__str__()` devuelve `"{name} (trigger: {trigger}, next run at: {dt})"`.
# Las quotes resultantes en el mensaje final son DOBLES.

EXTERNAL_RULES: list[tuple[re.Pattern[str], Callable[[re.Match[str]], str]]] = [
    # APScheduler — job lifecycle
    (
        re.compile(r'^Job "(.+?) \(trigger:.+?\)" executed successfully$'),
        lambda m: f"Job finished — {m.group(1)}",
    ),
    (
        re.compile(r'^Job "(.+?) \(trigger:.+?\)" raised an exception'),
        lambda m: f"Job raised an exception — {m.group(1)}",
    ),
    (
        re.compile(r'^Execution of job "(.+?) \(trigger:.+?\)" skipped'),
        lambda m: f"Job skipped — {m.group(1)} · concurrent run still in progress",
    ),
    (
        re.compile(r'^Job "(.+?)" has already reached its maximum number of instances'),
        lambda m: f"Job reached max concurrent instances — {m.group(1)}",
    ),
    (
        re.compile(r'^Added job "(.+?)" to job store'),
        lambda m: f"Scheduled job — {m.group(1)}",
    ),
    (
        re.compile(r"^Removed job (\S+)"),
        lambda m: f"Unscheduled job {m.group(1)}",
    ),
    # APScheduler — scheduler lifecycle
    (
        re.compile(r"^Adding job tentatively"),
        lambda m: "Job pending — will start when scheduler is running",
    ),
    (
        re.compile(r"^Scheduler started$"),
        lambda m: "Scheduler started",
    ),
    (
        re.compile(r"^Scheduler has been (paused|resumed|shut down)$"),
        lambda m: f"Scheduler {m.group(1)}",
    ),
]


def humanize_external(message: str) -> str:
    """Aplica las reglas regex de loggers no-structlog (APScheduler, etc.).

    Devuelve el mensaje original si ninguna regla matchea o si el replace
    function falla — garantiza que el `human_message` siempre tenga algo.
    """
    for pattern, replace_fn in EXTERNAL_RULES:
        match = pattern.search(message)
        if match is None:
            continue
        try:
            return replace_fn(match)
        except Exception:
            return message
    return message


# Mensajes que NO queremos en el buffer/UI. Siguen apareciendo en stdout
# (los emite APScheduler tal cual) pero no contaminan la página Activity.
# "Running job" es redundante con el "executed successfully" que llega
# segundos después con la misma info.
SUPPRESSED_EXTERNAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'^Running job "'),
]


def should_suppress_external(message: str) -> bool:
    return any(p.search(message) is not None for p in SUPPRESSED_EXTERNAL_PATTERNS)
