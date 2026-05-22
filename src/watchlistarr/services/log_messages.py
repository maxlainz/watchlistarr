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
    "healthz.db_unreachable": "Healthcheck failed: database unreachable ({error})",
    "request.unhandled_exception": "Unhandled exception on {method} {path}",
    # scheduler
    "scheduler.synced": "Scheduler synced ({jobs} active jobs)",
    "scheduler.sync_failed": "Scheduler sync failed",
    # onboarding
    "initial_run.background.start": "Initial run started for user {user_id}",
    "initial_run.background.done": "Initial run finished for user {user_id}",
    "initial_run.step_failed": "Initial run step '{source}' failed",
    "toggle.immediate_sync_failed": "Immediate sync after toggle failed for list {list_id}",
    # letterboxd client
    "letterboxd.forbidden": "Letterboxd rejected request (403): {url}",
    "letterboxd.retry_5xx": "Retrying Letterboxd request (status {status}, attempt {attempt}): {url}",
    # discovery
    "discovery.new_list": "Discovered new list '{slug_title}' for user {user_id}",
    "discovery.disabled_missing": "Disabled missing list '{slug_title}' for user {user_id}",
    # watchlist scraper
    "watchlist.full_sync.start": "Watchlist full sync starting (user {user_id}, list {list_id})",
    "watchlist.full_sync.page": "Watchlist page {page}/{total_pages} fetched ({page_items} items, user {username})",
    "watchlist.full_sync.resolving": "Resolving {total_slugs} films from watchlist (user {user_id}, list {list_id})",
    "watchlist.full_sync": "Watchlist full sync done: {resolved}/{slugs} resolved (user {user_id}, list {list_id})",
    "watchlist.incremental_sync": "Watchlist incremental sync done: {slugs} items (user {user_id}, list {list_id})",
    # list scraper
    "list.full_sync": "List '{slug_title}' full sync done: {resolved}/{slugs} resolved (list {list_id})",
    "list.incremental_sync": "List '{slug_title}' incremental sync done: {slugs} items (list {list_id})",
    # anti-flap
    "anti_flap.removed_watched": "Anti-flap: removed watched film tmdb={tmdb_id} from list {list_id}",
    "anti_flap.rename_detected": "Anti-flap: rename detected on list {list_id} (tmdb {old_tmdb_id} → {new_tmdb_id})",
    "anti_flap.removed_threshold": "Anti-flap: removed tmdb={tmdb_id} from list {list_id} after {count} missing checks",
    # custom lists
    "custom_list.init": "Custom list {custom_list_id} initialised with {chosen} films",
    "custom_list.rotated": "Custom list {custom_list_id} rotated ({rotated} films swapped)",
    "custom_list.created": "Custom list '{slug_title}' created (id {custom_list_id})",
    "custom_list.updated": "Custom list '{slug_title}' updated (id {custom_list_id})",
    # rss / backfills
    "rss.poll": "RSS poll for user {user_id}: {new} new of {total}",
    "rating_backfill.done": "Rating backfill done ({enriched}/{attempted} enriched)",
    "imdb_backfill.done": "IMDB backfill done ({enriched}/{attempted} enriched)",
    "films_backstop.done": "Films backstop done for user {user_id}: {inserted}/{items} inserted",
    # films / users
    "film.resolve": "Resolving film {slug_title}",
    "film.skipped": "Skipped film {slug_title} (tmdb_type={tmdb_type}, tmdb_id={tmdb_id})",
    "user.added": "User '{username}' added (id {user_id})",
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
        lambda m: f"Job '{m.group(1)}' finished",
    ),
    (
        re.compile(r'^Job "(.+?) \(trigger:.+?\)" raised an exception'),
        lambda m: f"Job '{m.group(1)}' raised an exception",
    ),
    (
        re.compile(r'^Execution of job "(.+?) \(trigger:.+?\)" skipped'),
        lambda m: f"Skipped job '{m.group(1)}' (concurrent run still in progress)",
    ),
    (
        re.compile(r'^Job "(.+?)" has already reached its maximum number of instances'),
        lambda m: f"Job '{m.group(1)}' reached max concurrent instances",
    ),
    (
        re.compile(r'^Added job "(.+?)" to job store'),
        lambda m: f"Scheduled job '{m.group(1)}'",
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
