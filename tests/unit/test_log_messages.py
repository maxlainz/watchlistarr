from __future__ import annotations

from watchlistarr.services import log_messages
from watchlistarr.services.log_messages import MESSAGES, humanize


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
    assert isinstance(log_messages.MESSAGES, dict)
