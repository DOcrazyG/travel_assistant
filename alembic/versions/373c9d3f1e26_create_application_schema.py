"""create single-user application schema

Revision ID: 373c9d3f1e26
Revises:
Create Date: 2026-08-11
"""

from collections.abc import Sequence

from alembic import op


revision: str = "373c9d3f1e26"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the immutable initial schema for the single-user application."""

    op.execute("CREATE SCHEMA IF NOT EXISTS app")

    # The database is intentionally rebuilt for this baseline. Keep this DDL
    # self-contained: an Alembic revision must not import mutable ORM metadata.
    for statement in (
        """
        CREATE TABLE app.users (
            created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
            id UUID PRIMARY KEY, email VARCHAR(320) NOT NULL,
            email_normalized VARCHAR(320) NOT NULL, password_hash TEXT NOT NULL,
            status VARCHAR(32) NOT NULL, email_verified_at TIMESTAMPTZ,
            password_changed_at TIMESTAMPTZ, security_invalid_before TIMESTAMPTZ,
            last_login_at TIMESTAMPTZ, deleted_at TIMESTAMPTZ,
            CONSTRAINT ck_users_status CHECK (status IN ('pending_verification', 'active', 'disabled', 'deleted')),
            CONSTRAINT ck_users_email_normalized CHECK (email_normalized = lower(email_normalized)),
            CONSTRAINT ck_users_deleted_lifecycle CHECK ((status = 'deleted') = (deleted_at IS NOT NULL))
        )
        """,
        "CREATE UNIQUE INDEX uq_users_single_active_account ON app.users ((true)) WHERE deleted_at IS NULL",
        "CREATE UNIQUE INDEX uq_users_active_email_normalized ON app.users (email_normalized) WHERE deleted_at IS NULL",
        "CREATE INDEX ix_users_active_status ON app.users (status) WHERE deleted_at IS NULL",
        """
        CREATE TABLE app.auth_sessions (
            id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES app.users(id),
            token_family_id UUID NOT NULL UNIQUE, created_at TIMESTAMPTZ NOT NULL,
            last_used_at TIMESTAMPTZ, expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ, revoked_reason VARCHAR(100),
            user_agent VARCHAR(512), ip_hash BYTEA
        )
        """,
        "CREATE INDEX ix_auth_sessions_active_user_expiry ON app.auth_sessions (user_id, expires_at) WHERE revoked_at IS NULL",
        "CREATE INDEX ix_auth_sessions_expiry ON app.auth_sessions (expires_at)",
        """
        CREATE TABLE app.refresh_tokens (
            id UUID PRIMARY KEY, session_id UUID NOT NULL REFERENCES app.auth_sessions(id),
            token_hash BYTEA NOT NULL UNIQUE, issued_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL, consumed_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ, replaced_by_id UUID REFERENCES app.refresh_tokens(id)
        )
        """,
        "CREATE INDEX ix_refresh_tokens_session_issued ON app.refresh_tokens (session_id, issued_at)",
        "CREATE INDEX ix_refresh_tokens_expiry ON app.refresh_tokens (expires_at)",
        """
        CREATE TABLE app.revoked_access_tokens (
            jti UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES app.users(id),
            expires_at TIMESTAMPTZ NOT NULL, revoked_at TIMESTAMPTZ NOT NULL,
            reason VARCHAR(100) NOT NULL
        )
        """,
        "CREATE INDEX ix_revoked_access_tokens_expiry ON app.revoked_access_tokens (expires_at)",
        """
        CREATE TABLE app.auth_one_time_tokens (
            id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES app.users(id),
            purpose VARCHAR(32) NOT NULL, token_hash BYTEA NOT NULL UNIQUE,
            expires_at TIMESTAMPTZ NOT NULL, consumed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL, request_ip_hash BYTEA,
            request_user_agent VARCHAR(512),
            CONSTRAINT ck_auth_one_time_tokens_purpose CHECK (purpose IN ('email_verify', 'password_reset'))
        )
        """,
        "CREATE INDEX ix_auth_one_time_tokens_user_purpose_created ON app.auth_one_time_tokens (user_id, purpose, created_at)",
        "CREATE INDEX ix_auth_one_time_tokens_expiry ON app.auth_one_time_tokens (expires_at)",
        """
        CREATE TABLE app.conversations (
            created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
            id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES app.users(id),
            thread_id UUID NOT NULL UNIQUE, title VARCHAR(500), title_source VARCHAR(16),
            status VARCHAR(16) NOT NULL, metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            last_message_at TIMESTAMPTZ, latest_message_sequence INTEGER NOT NULL,
            version INTEGER NOT NULL, archived_at TIMESTAMPTZ, deleted_at TIMESTAMPTZ,
            purge_after_at TIMESTAMPTZ,
            CONSTRAINT ck_conversations_status CHECK (status IN ('active', 'archived', 'deleted')),
            CONSTRAINT ck_conversations_latest_sequence CHECK (latest_message_sequence >= 0),
            CONSTRAINT ck_conversations_version CHECK (version > 0),
            CONSTRAINT ck_conversations_title_source CHECK (title_source IS NULL OR title_source IN ('system', 'user')),
            CONSTRAINT ck_conversations_deleted_lifecycle CHECK ((status = 'deleted') = (deleted_at IS NOT NULL))
        )
        """,
        "CREATE INDEX ix_conversations_user_history ON app.conversations (user_id, last_message_at, id) WHERE deleted_at IS NULL",
        "CREATE INDEX ix_conversations_status_history ON app.conversations (status, last_message_at) WHERE deleted_at IS NULL",
        "CREATE INDEX ix_conversations_purge_after ON app.conversations (purge_after_at) WHERE deleted_at IS NOT NULL",
        """
        CREATE TABLE app.agent_runs (
            created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
            id UUID PRIMARY KEY, conversation_id UUID NOT NULL REFERENCES app.conversations(id),
            status VARCHAR(16) NOT NULL, model_alias VARCHAR(200), provider_model VARCHAR(200),
            request_metadata JSONB NOT NULL DEFAULT '{}'::jsonb, trace_id VARCHAR(255),
            input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER,
            estimated_cost NUMERIC(12, 6), started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ,
            error_code VARCHAR(100), error_details JSONB, interrupt_payload JSONB,
            CONSTRAINT ck_agent_runs_status CHECK (status IN ('queued', 'running', 'interrupted', 'completed', 'failed', 'cancelled'))
        )
        """,
        "CREATE UNIQUE INDEX uq_agent_runs_active_conversation ON app.agent_runs (conversation_id) WHERE status IN ('queued', 'running', 'interrupted')",
        "CREATE INDEX ix_agent_runs_conversation_created ON app.agent_runs (conversation_id, created_at)",
        "CREATE INDEX ix_agent_runs_status_created ON app.agent_runs (status, created_at)",
        "CREATE INDEX ix_agent_runs_terminal_completed ON app.agent_runs (completed_at) WHERE status IN ('completed', 'failed', 'cancelled')",
        """
        CREATE TABLE app.messages (
            created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
            id UUID PRIMARY KEY, conversation_id UUID NOT NULL REFERENCES app.conversations(id),
            sequence INTEGER NOT NULL, role VARCHAR(16) NOT NULL, content JSONB NOT NULL,
            rendered_text TEXT, content_status VARCHAR(16) NOT NULL,
            agent_run_id UUID REFERENCES app.agent_runs(id), model_alias VARCHAR(200),
            token_count INTEGER, deleted_at TIMESTAMPTZ,
            CONSTRAINT ck_messages_role CHECK (role IN ('user', 'assistant', 'system', 'tool')),
            CONSTRAINT ck_messages_content_status CHECK (content_status IN ('complete', 'partial', 'failed', 'redacted')),
            CONSTRAINT ck_messages_sequence CHECK (sequence > 0),
            CONSTRAINT ck_messages_content_array CHECK (jsonb_typeof(content) = 'array'),
            CONSTRAINT uq_messages_conversation_sequence UNIQUE (conversation_id, sequence)
        )
        """,
        "CREATE INDEX ix_messages_conversation_history ON app.messages (conversation_id, sequence) WHERE deleted_at IS NULL",
        "CREATE INDEX ix_messages_agent_run ON app.messages (agent_run_id) WHERE agent_run_id IS NOT NULL",
        """
        CREATE TABLE app.message_citations (
            id UUID PRIMARY KEY, message_id UUID NOT NULL REFERENCES app.messages(id),
            position INTEGER NOT NULL, source_type VARCHAR(64) NOT NULL,
            provider VARCHAR(100), title VARCHAR(500) NOT NULL, url VARCHAR(2048) NOT NULL,
            snippet VARCHAR(2000), retrieved_at TIMESTAMPTZ NOT NULL,
            published_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT ck_message_citations_position CHECK (position >= 0)
        )
        """,
        "CREATE UNIQUE INDEX uq_message_citations_position ON app.message_citations (message_id, position)",
        """
        CREATE TABLE app.attachments (
            id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES app.users(id),
            storage_provider VARCHAR(32) NOT NULL, bucket VARCHAR(255) NOT NULL,
            object_key VARCHAR(1024) NOT NULL, original_filename VARCHAR(512) NOT NULL,
            media_type VARCHAR(255) NOT NULL, byte_size INTEGER NOT NULL, sha256 BYTEA NOT NULL,
            kind VARCHAR(16) NOT NULL, upload_status VARCHAR(32) NOT NULL,
            scan_status VARCHAR(16) NOT NULL, scan_detail VARCHAR(1000),
            processing_status VARCHAR(32) NOT NULL, created_at TIMESTAMPTZ NOT NULL,
            uploaded_at TIMESTAMPTZ, expires_at TIMESTAMPTZ, deleted_at TIMESTAMPTZ,
            CONSTRAINT ck_attachments_kind CHECK (kind IN ('image', 'file')),
            CONSTRAINT ck_attachments_upload_status CHECK (upload_status IN ('pending_upload', 'uploaded', 'scanning', 'available', 'rejected', 'deleted')),
            CONSTRAINT ck_attachments_scan_status CHECK (scan_status IN ('pending', 'clean', 'infected', 'failed')),
            CONSTRAINT ck_attachments_processing_status CHECK (processing_status IN ('not_requested', 'queued', 'processed', 'failed')),
            CONSTRAINT ck_attachments_byte_size CHECK (byte_size >= 0),
            CONSTRAINT ck_attachments_deleted_lifecycle CHECK ((upload_status = 'deleted') = (deleted_at IS NOT NULL))
        )
        """,
        "CREATE UNIQUE INDEX uq_attachments_object_location ON app.attachments (storage_provider, bucket, object_key)",
        "CREATE INDEX ix_attachments_user_created ON app.attachments (user_id, created_at)",
        "CREATE INDEX ix_attachments_upload_expiry ON app.attachments (upload_status, expires_at)",
        "CREATE INDEX ix_attachments_scan_work ON app.attachments (scan_status) WHERE scan_status IN ('pending', 'failed')",
        """
        CREATE TABLE app.message_attachments (
            message_id UUID NOT NULL REFERENCES app.messages(id),
            attachment_id UUID NOT NULL UNIQUE REFERENCES app.attachments(id),
            position INTEGER NOT NULL, created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (message_id, attachment_id)
        )
        """,
        "CREATE UNIQUE INDEX uq_message_attachments_position ON app.message_attachments (message_id, position)",
        """
        CREATE TABLE app.tool_calls (
            id UUID PRIMARY KEY, agent_run_id UUID NOT NULL REFERENCES app.agent_runs(id),
            sequence INTEGER NOT NULL, tool_name VARCHAR(200) NOT NULL,
            provider_call_id VARCHAR(255), status VARCHAR(16) NOT NULL,
            input_redacted JSONB NOT NULL DEFAULT '{}'::jsonb,
            output_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
            source_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
            started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ, duration_ms INTEGER,
            error_code VARCHAR(100), error_details JSONB, created_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT ck_tool_calls_status CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'timed_out', 'cancelled')),
            CONSTRAINT ck_tool_calls_sequence CHECK (sequence > 0),
            CONSTRAINT ck_tool_calls_duration CHECK (duration_ms IS NULL OR duration_ms >= 0)
        )
        """,
        "CREATE UNIQUE INDEX uq_tool_calls_run_sequence ON app.tool_calls (agent_run_id, sequence)",
        "CREATE INDEX ix_tool_calls_name_created ON app.tool_calls (tool_name, created_at)",
        "CREATE INDEX ix_tool_calls_active ON app.tool_calls (status, created_at) WHERE status IN ('queued', 'running')",
        """
        CREATE TABLE app.idempotency_keys (
            id UUID PRIMARY KEY, http_method VARCHAR(10) NOT NULL, route VARCHAR(255) NOT NULL,
            idempotency_key VARCHAR(255) NOT NULL, request_fingerprint BYTEA NOT NULL,
            conversation_id UUID REFERENCES app.conversations(id),
            agent_run_id UUID REFERENCES app.agent_runs(id), status VARCHAR(16) NOT NULL,
            response_status INTEGER, response_snapshot JSONB, created_at TIMESTAMPTZ NOT NULL,
            completed_at TIMESTAMPTZ, expires_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT ck_idempotency_keys_status CHECK (status IN ('processing', 'completed', 'failed'))
        )
        """,
        "CREATE UNIQUE INDEX uq_idempotency_keys_request ON app.idempotency_keys (http_method, route, idempotency_key)",
        "CREATE INDEX ix_idempotency_keys_expiry ON app.idempotency_keys (expires_at)",
        "CREATE INDEX ix_idempotency_keys_conversation ON app.idempotency_keys (conversation_id) WHERE conversation_id IS NOT NULL",
        """
        CREATE TABLE app.security_audit_events (
            id SERIAL PRIMARY KEY, user_id UUID REFERENCES app.users(id),
            event_type VARCHAR(100) NOT NULL, outcome VARCHAR(16) NOT NULL,
            request_id UUID, ip_hash BYTEA, user_agent VARCHAR(512),
            details JSONB NOT NULL DEFAULT '{}'::jsonb, occurred_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT ck_security_audit_events_outcome CHECK (outcome IN ('success', 'failure', 'denied'))
        )
        """,
        "CREATE INDEX ix_security_audit_events_user_occurred ON app.security_audit_events (user_id, occurred_at) WHERE user_id IS NOT NULL",
        "CREATE INDEX ix_app_security_audit_events_request_id ON app.security_audit_events (request_id)",
        "CREATE INDEX ix_security_audit_events_type_occurred ON app.security_audit_events (event_type, occurred_at)",
        "CREATE INDEX ix_security_audit_events_occurred ON app.security_audit_events (occurred_at)",
        """
        CREATE TABLE app.data_deletion_requests (
            id UUID PRIMARY KEY, requested_by_user_id UUID REFERENCES app.users(id),
            target_type VARCHAR(16) NOT NULL, target_id UUID NOT NULL, reason VARCHAR(16) NOT NULL,
            status VARCHAR(16) NOT NULL, requested_at TIMESTAMPTZ NOT NULL,
            purge_after_at TIMESTAMPTZ NOT NULL, started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ, failure_code VARCHAR(100),
            failure_detail VARCHAR(1000), created_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT ck_data_deletion_requests_target_type CHECK (target_type IN ('conversation', 'user', 'attachment')),
            CONSTRAINT ck_data_deletion_requests_reason CHECK (reason IN ('user_request', 'retention', 'admin')),
            CONSTRAINT ck_data_deletion_requests_status CHECK (status IN ('scheduled', 'running', 'completed', 'failed', 'cancelled'))
        )
        """,
        "CREATE INDEX ix_data_deletion_requests_due ON app.data_deletion_requests (status, purge_after_at)",
        "CREATE INDEX ix_data_deletion_requests_target ON app.data_deletion_requests (target_type, target_id)",
        "CREATE INDEX ix_data_deletion_requests_completed ON app.data_deletion_requests (completed_at)",
        """
        CREATE TABLE app.travel_preferences (
            created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
            id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES app.users(id),
            category VARCHAR(64) NOT NULL, value JSONB NOT NULL,
            source_message_id UUID REFERENCES app.messages(id), status VARCHAR(16) NOT NULL,
            confirmed_at TIMESTAMPTZ, expires_at TIMESTAMPTZ, deleted_at TIMESTAMPTZ,
            CONSTRAINT ck_travel_preferences_status CHECK (status IN ('confirmed', 'revoked', 'expired'))
        )
        """,
        "CREATE UNIQUE INDEX uq_travel_preferences_confirmed_category ON app.travel_preferences (user_id, category) WHERE status = 'confirmed' AND deleted_at IS NULL",
        "CREATE INDEX ix_travel_preferences_user_status ON app.travel_preferences (user_id, status)",
        "CREATE INDEX ix_travel_preferences_expiry ON app.travel_preferences (expires_at) WHERE status = 'confirmed'",
    ):
        op.execute(statement)


def downgrade() -> None:
    """Drop the complete application schema; this destroys all application data."""

    op.execute("DROP SCHEMA IF EXISTS app CASCADE")
