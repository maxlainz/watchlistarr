"""Catálogo de mensajes humanos para eventos de structlog.

Cada entrada mapea un `event` name a un template `str.format_map`. Los placeholders
son los `kwargs` que pasa cada llamada `logger.info("event", k=v, ...)`. Si falta
un placeholder en runtime, `_SafeDict` lo deja como `{key}` literal en vez de
lanzar `KeyError`. Si el `event` no está en el catálogo, `humanize()` devuelve el
`fallback` (típicamente el `message` raw renderizado por structlog).
"""

from __future__ import annotations

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
    "discovery.new_list": "Discovered new list '{slug}' for user {user_id}",
    "discovery.disabled_missing": "Disabled missing list '{slug}' for user {user_id}",
    # watchlist scraper
    "watchlist.full_sync.start": "Watchlist full sync starting (user {user_id}, list {list_id})",
    "watchlist.full_sync.page": "Watchlist page {page}/{total_pages} fetched ({page_items} items, user {username})",
    "watchlist.full_sync.resolving": "Resolving {total_slugs} films from watchlist (user {user_id}, list {list_id})",
    "watchlist.full_sync": "Watchlist full sync done: {resolved}/{slugs} resolved (user {user_id}, list {list_id})",
    "watchlist.incremental_sync": "Watchlist incremental sync done: {slugs} items (user {user_id}, list {list_id})",
    # list scraper
    "list.full_sync": "List '{slug}' full sync done: {resolved}/{slugs} resolved (list {list_id})",
    "list.incremental_sync": "List '{slug}' incremental sync done: {slugs} items (list {list_id})",
    # anti-flap
    "anti_flap.removed_watched": "Anti-flap: removed watched film tmdb={tmdb_id} from list {list_id}",
    "anti_flap.rename_detected": "Anti-flap: rename detected on list {list_id} (tmdb {old_tmdb_id} → {new_tmdb_id})",
    "anti_flap.removed_threshold": "Anti-flap: removed tmdb={tmdb_id} from list {list_id} after {count} missing checks",
    # custom lists
    "custom_list.init": "Custom list {custom_list_id} initialised with {chosen} films",
    "custom_list.rotated": "Custom list {custom_list_id} rotated ({rotated} films swapped)",
    "custom_list.created": "Custom list '{slug}' created (id {custom_list_id})",
    "custom_list.updated": "Custom list '{slug}' updated (id {custom_list_id})",
    # rss / backfills
    "rss.poll": "RSS poll for user {user_id}: {new} new of {total}",
    "rating_backfill.done": "Rating backfill done ({enriched}/{attempted} enriched)",
    "imdb_backfill.done": "IMDB backfill done ({enriched}/{attempted} enriched)",
    "films_backstop.done": "Films backstop done for user {user_id}: {inserted}/{items} inserted",
    # films / users
    "film.resolve": "Resolving film '{slug}'",
    "film.skipped": "Skipped film '{slug}' (tmdb_type={tmdb_type}, tmdb_id={tmdb_id})",
    "user.added": "User '{username}' added (id {user_id})",
}


class _SafeDict(dict[str, Any]):
    """Dict que devuelve `{key}` literal cuando falta una clave en format_map."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def humanize(event: str | None, fields: dict[str, Any], fallback: str) -> str:
    """Traduce un event + fields a frase humana.

    Si `event` no está en el catálogo, o el formato falla por razones no previstas,
    devuelve `fallback` para garantizar que la UI siempre tenga algo que mostrar.
    """
    if not event:
        return fallback
    template = MESSAGES.get(event)
    if template is None:
        return fallback
    try:
        return template.format_map(_SafeDict(fields))
    except Exception:
        return fallback
