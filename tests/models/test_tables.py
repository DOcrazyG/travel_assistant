"""Tests for the application-owned SQLModel table metadata."""

from typing import cast
from uuid import UUID

from sqlalchemy import DateTime
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.sql.schema import PrimaryKeyConstraint, UniqueConstraint
from sqlmodel import SQLModel

import app.models  # noqa: F401  # Register all table models in SQLModel metadata.
from app.models.base import APP_SCHEMA, new_uuid7


def test_all_application_tables_are_registered_in_the_app_schema() -> None:
    expected_tables = {
        "agent_runs",
        "attachments",
        "auth_one_time_tokens",
        "auth_sessions",
        "conversations",
        "data_deletion_requests",
        "idempotency_keys",
        "message_attachments",
        "message_citations",
        "messages",
        "refresh_tokens",
        "revoked_access_tokens",
        "security_audit_events",
        "tool_calls",
        "travel_preferences",
        "users",
    }

    registered_tables = {
        table.name for table in SQLModel.metadata.tables.values() if table.schema == APP_SCHEMA
    }

    assert registered_tables == expected_tables


def test_conversation_history_and_run_indexes_are_declared() -> None:
    conversations = SQLModel.metadata.tables[f"{APP_SCHEMA}.conversations"]
    messages = SQLModel.metadata.tables[f"{APP_SCHEMA}.messages"]
    agent_runs = SQLModel.metadata.tables[f"{APP_SCHEMA}.agent_runs"]

    assert "ix_conversations_user_history" in {index.name for index in conversations.indexes}
    assert "ix_messages_conversation_history" in {index.name for index in messages.indexes}
    assert "uq_agent_runs_active_conversation" in {index.name for index in agent_runs.indexes}


def test_idempotency_keys_are_scoped_to_one_user() -> None:
    idempotency_keys = SQLModel.metadata.tables[f"{APP_SCHEMA}.idempotency_keys"]

    assert "user_id" in idempotency_keys.columns
    request_index = next(
        index for index in idempotency_keys.indexes if index.name == "uq_idempotency_keys_request"
    )
    assert tuple(request_index.columns.keys()) == (
        "user_id",
        "http_method",
        "route",
        "idempotency_key",
    )


def test_user_models_have_no_tenant_or_principal_columns() -> None:
    forbidden_columns = {"tenant_id", "principal_id", "owner_principal_id", "user_principal_id"}

    application_tables = [
        table for table in SQLModel.metadata.tables.values() if table.schema == APP_SCHEMA
    ]

    assert all(forbidden_columns.isdisjoint(table.columns.keys()) for table in application_tables)

    users = SQLModel.metadata.tables[f"{APP_SCHEMA}.users"]
    assert "uq_users_single_active_account" not in {index.name for index in users.indexes}
    assert "uq_users_single_admin" in {index.name for index in users.indexes}


def test_uuid7_defaults_are_uuid_version_seven() -> None:
    identifier = new_uuid7()

    assert isinstance(identifier, UUID)
    assert identifier.version == 7


def test_all_models_compile_to_postgresql_ddl() -> None:
    dialect = postgresql.dialect()
    application_tables = [
        table for table in SQLModel.metadata.tables.values() if table.schema == APP_SCHEMA
    ]

    for table in application_tables:
        str(CreateTable(table).compile(dialect=dialect))
        for index in table.indexes:
            str(CreateIndex(index).compile(dialect=dialect))


def test_all_datetime_columns_use_timezone_aware_postgresql_types() -> None:
    application_tables = [
        table for table in SQLModel.metadata.tables.values() if table.schema == APP_SCHEMA
    ]

    datetime_columns = [
        column
        for table in application_tables
        for column in table.columns
        if isinstance(column.type, DateTime)
    ]

    assert datetime_columns
    assert all(cast(DateTime, column.type).timezone for column in datetime_columns)


def test_composite_foreign_keys_reference_unique_parent_keys() -> None:
    application_tables = [
        table for table in SQLModel.metadata.tables.values() if table.schema == APP_SCHEMA
    ]

    for table in application_tables:
        for foreign_key in table.foreign_key_constraints:
            if len(foreign_key.elements) < 2:
                continue

            parent_table = foreign_key.elements[0].column.table
            referenced_columns = tuple(element.column.name for element in foreign_key.elements)
            parent_keys = {
                tuple(constraint.columns.keys())
                for constraint in parent_table.constraints
                if isinstance(constraint, (PrimaryKeyConstraint, UniqueConstraint))
            }

            assert referenced_columns in parent_keys
