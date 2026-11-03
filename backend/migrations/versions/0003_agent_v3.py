"""Agent v3: optional review model on model configurations."""

import sqlalchemy as sa
from alembic import op

revision = "0003_agent_v3"
down_revision = "0002_agent_v2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "model_configs",
        sa.Column("review_model_name", sa.String(length=200), nullable=True),
    )


def downgrade():
    op.drop_column("model_configs", "review_model_name")
