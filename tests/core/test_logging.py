"""Tests for request-scoped logging context."""

from app.core.logging import bind_context, clear_context, get_context, reset_context


def test_context_can_be_bound_and_restored_without_leaking_to_the_caller() -> None:
    outer_context = clear_context()
    try:
        bind_context(request_id="request-1")
        request_context = clear_context()
        try:
            bind_context(request_id="request-2", user_id="user-hash")
            assert get_context() == {"request_id": "request-2", "user_id": "user-hash"}
        finally:
            reset_context(request_context)
        assert get_context() == {"request_id": "request-1"}
    finally:
        reset_context(outer_context)
