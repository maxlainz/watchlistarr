from __future__ import annotations

import pytest

from watchlistarr.services import log_messages
from watchlistarr.services.log_messages import (
    MESSAGES,
    _clean_slug,
    humanize,
    humanize_external,
)


def test_known_event_formats_with_complete_fields() -> None:
    assert (
        humanize("watchlist.full_sync.start", {"user_id": 7, "list_id": 42}, "raw")
        == "Watchlist full sync starting (user 7, list 42)"
    )


def test_missing_field_keeps_placeholder_no_keyerror() -> None:
    # _SafeDict deja {list_id} literal en vez de lanzar KeyError
    assert (
        humanize("watchlist.full_sync.start", {"user_id": 7}, "raw")
        == "Watchlist full sync starting (user 7, list {list_id})"
    )


def test_event_without_catalog_entry_returns_fallback() -> None:
    assert humanize("never.registered.event", {"foo": 1}, "raw-fallback") == "raw-fallback"


def test_none_event_returns_fallback() -> None:
    assert humanize(None, {"foo": 1}, "raw-fallback") == "raw-fallback"


def test_empty_event_string_returns_fallback() -> None:
    assert humanize("", {"foo": 1}, "raw-fallback") == "raw-fallback"


def test_all_catalog_templates_use_format_safe_keys() -> None:
    """Asegura que ningún template del catálogo rompe con format_map vacío."""
    for event, template in MESSAGES.items():
        # Con _SafeDict y dict vacío, nunca debe lanzar.
        result = humanize(event, {}, "fallback")
        assert isinstance(result, str), f"event {event} returned non-string"
        # El fallback se usa solo cuando humanize falla; con _SafeDict no debería.
        assert result != "fallback" or template == "fallback", (
            f"event {event} unexpectedly hit fallback path"
        )


def test_module_exports() -> None:
    # Sanity: las funciones públicas existen.
    assert callable(log_messages.humanize)
    assert callable(log_messages.humanize_external)
    assert isinstance(log_messages.MESSAGES, dict)
    assert isinstance(log_messages.EXTERNAL_RULES, list)


@pytest.mark.parametrize(
    ("slug", "expected"),
    [
        ("the-thing-with-feathers-2025", "The Thing With Feathers (2025)"),
        ("parasite-2019", "Parasite (2019)"),
        ("favorites", "Favorites"),
        ("top-rated", "Top Rated"),
        ("3-faces", "3 Faces"),  # sin año al final → solo title case
        ("one-battle-after-another", "One Battle After Another"),
        ("", ""),
    ],
)
def test_clean_slug_variants(slug: str, expected: str) -> None:
    assert _clean_slug(slug) == expected


def test_humanize_adds_slug_title_field() -> None:
    msg = humanize("film.resolve", {"slug": "the-thing-2025"}, "raw")
    assert msg == "Resolving film The Thing (2025)"


def test_humanize_uses_slug_title_for_list_events() -> None:
    msg = humanize(
        "list.full_sync",
        {"slug": "favorites", "list_id": 5, "resolved": 10, "slugs": 12},
        "raw",
    )
    assert msg == "List 'Favorites' full sync done: 10/12 resolved (list 5)"


def test_humanize_falls_back_when_slug_missing_in_field() -> None:
    # No hay slug en fields → slug_title queda como {slug_title} literal (sin crash)
    msg = humanize("film.resolve", {}, "raw")
    assert msg == "Resolving film {slug_title}"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            'Job "Watchlist incremental sync (alice) (trigger: interval[1:00:00], '
            'next run at: 2026-05-22 17:05:23 UTC)" executed successfully',
            "Job 'Watchlist incremental sync (alice)' finished",
        ),
        (
            'Job "List full sync (bob/favs) (trigger: interval[6:00:00], '
            'next run at: 2026-05-22 23:05:23 UTC)" raised an exception: boom',
            "Job 'List full sync (bob/favs)' raised an exception",
        ),
        (
            'Execution of job "RSS poll (alice) (trigger: interval[0:01:00], '
            'next run at: 2026-05-22 17:06:23 UTC)" skipped: maximum number of '
            "running instances reached (1)",
            "Skipped job 'RSS poll (alice)' (concurrent run still in progress)",
        ),
        (
            'Added job "Custom list rotation tick" to job store "default"',
            "Scheduled job 'Custom list rotation tick'",
        ),
        (
            "Adding job tentatively -- it will be properly scheduled when the scheduler starts",
            "Job pending — will start when scheduler is running",
        ),
        ("Scheduler started", "Scheduler started"),
        ("Scheduler has been paused", "Scheduler paused"),
        ("Scheduler has been shut down", "Scheduler shut down"),
    ],
)
def test_humanize_external_apscheduler(raw: str, expected: str) -> None:
    assert humanize_external(raw) == expected


def test_humanize_external_returns_original_when_no_match() -> None:
    raw = "Some random log line that nothing matches."
    assert humanize_external(raw) == raw
