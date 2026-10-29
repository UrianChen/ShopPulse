"""Agent v2: action tracking, merchant notes, schedules, protocols and run tracing."""

import sqlalchemy as sa
from alembic import op

revision = "0002_agent_v2"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "merchant_notes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_exclusive", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("text", sa.String(length=300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_merchant_notes_workspace_id"), "merchant_notes", ["workspace_id"], unique=False
    )
    op.create_table(
        "report_schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=150), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=True),
        sa.Column("model_config_id", sa.Uuid(), nullable=True),
        sa.Column("period_days", sa.Integer(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("language", sa.String(length=5), nullable=False),
        sa.Column("webhook_ciphertext", sa.Text(), nullable=True),
        sa.Column("webhook_key_version", sa.Integer(), nullable=True),
        sa.Column("webhook_format", sa.String(length=20), nullable=False),
        sa.Column("series_id", sa.Uuid(), nullable=True),
        sa.Column("last_report_id", sa.Uuid(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=40), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["dataset_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["model_config_id"],
            ["model_configs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_report_schedules_next_run_at"), "report_schedules", ["next_run_at"], unique=False
    )
    op.create_index(
        op.f("ix_report_schedules_workspace_id"), "report_schedules", ["workspace_id"], unique=False
    )
    op.create_table(
        "action_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=500), nullable=False),
        sa.Column("verification_metric", sa.String(length=40), nullable=False),
        sa.Column("review_window", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.String(length=10), nullable=False),
        sa.Column("effort", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("evaluation", sa.JSON(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reports.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_id", "position"),
    )
    op.create_index(op.f("ix_action_items_report_id"), "action_items", ["report_id"], unique=False)
    op.create_index(
        op.f("ix_action_items_workspace_id"), "action_items", ["workspace_id"], unique=False
    )
    op.add_column("agent_runs", sa.Column("trace_id", sa.String(length=32), nullable=True))
    op.add_column("agent_runs", sa.Column("debug", sa.JSON(), nullable=True))
    op.add_column(
        "model_configs",
        sa.Column("protocol", sa.String(length=30), server_default="openai_chat", nullable=False),
    )
    op.add_column(
        "reports", sa.Column("language", sa.String(length=5), server_default="zh", nullable=False)
    )
    op.add_column("reports", sa.Column("schedule_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_reports_schedule_id"), "reports", ["schedule_id"], unique=False)
    op.create_foreign_key(
        "fk_reports_schedule_id", "reports", "report_schedules", ["schedule_id"], ["id"]
    )
    op.create_index(
        "ix_tool_results_cache", "tool_results", ["report_id", "tool", "args_hash"], unique=False
    )


def downgrade():
    op.drop_index("ix_tool_results_cache", table_name="tool_results")
    op.drop_constraint("fk_reports_schedule_id", "reports", type_="foreignkey")
    op.drop_index(op.f("ix_reports_schedule_id"), table_name="reports")
    op.drop_column("reports", "schedule_id")
    op.drop_column("reports", "language")
    op.drop_column("model_configs", "protocol")
    op.drop_column("agent_runs", "debug")
    op.drop_column("agent_runs", "trace_id")
    op.drop_index(op.f("ix_action_items_workspace_id"), table_name="action_items")
    op.drop_index(op.f("ix_action_items_report_id"), table_name="action_items")
    op.drop_table("action_items")
    op.drop_index(op.f("ix_report_schedules_workspace_id"), table_name="report_schedules")
    op.drop_index(op.f("ix_report_schedules_next_run_at"), table_name="report_schedules")
    op.drop_table("report_schedules")
    op.drop_index(op.f("ix_merchant_notes_workspace_id"), table_name="merchant_notes")
    op.drop_table("merchant_notes")
