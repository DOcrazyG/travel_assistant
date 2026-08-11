"""Tests for conversation-specific CRUD defaults."""

from uuid import uuid4

from app.services.crud.conversations import ConversationCRUD


def test_conversation_crud_enforces_user_scope_and_soft_deletion() -> None:
    user_id = uuid4()
    crud = ConversationCRUD(object(), user_id)  # type: ignore[arg-type]

    assert crud.scope == {"user_id": user_id}
    assert crud.soft_delete_field == "deleted_at"
    assert crud.mutable_fields == frozenset({"title", "title_source"})
