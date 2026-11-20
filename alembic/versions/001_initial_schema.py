"""Create CRM tables and concurrency constraints."""

import sqlalchemy as sa

from alembic import op

revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "managers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
    )
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("bin", sa.String(length=12), nullable=False, unique=True),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="new", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('new', 'no_answer', 'refused', 'meeting_set')",
            name="ck_companies_status",
        ),
        sa.CheckConstraint("bin ~ '^[0-9]{12}$'", name="ck_companies_bin_format"),
    )
    op.create_table(
        "meetings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "manager_id",
            sa.Integer(),
            sa.ForeignKey("managers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("initial_start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default="scheduled", nullable=False
        ),
        sa.Column(
            "rescheduled_count", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'cancelled')", name="ck_meetings_status"
        ),
        sa.CheckConstraint("end_time > start_time", name="ck_meetings_time_order"),
    )
    op.execute(
        "ALTER TABLE meetings ADD CONSTRAINT ex_meetings_manager_time "
        "EXCLUDE USING gist (manager_id WITH =, "
        "tstzrange(start_time, end_time, '[)') WITH &&) "
        "WHERE (status = 'scheduled')"
    )
    op.create_index(
        "uq_meetings_active_company",
        "meetings",
        ["company_id"],
        unique=True,
        postgresql_where=sa.text("status = 'scheduled'"),
    )
    op.create_table(
        "calls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "manager_id",
            sa.Integer(),
            sa.ForeignKey("managers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("result", sa.String(length=20), nullable=False),
        sa.Column(
            "meeting_id",
            sa.Integer(),
            sa.ForeignKey("meetings.id", ondelete="RESTRICT"),
            unique=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "result IN ('meeting_set', 'no_answer', 'refused')", name="ck_calls_result"
        ),
    )
    op.execute(
        "INSERT INTO managers (id, name) VALUES "
        "(1, 'Manager 1'), (2, 'Manager 2'), (3, 'Manager 3')"
    )
    op.execute("SELECT setval(pg_get_serial_sequence('managers', 'id'), 3, true)")


def downgrade() -> None:
    op.drop_table("calls")
    op.drop_index("uq_meetings_active_company", table_name="meetings")
    op.execute("ALTER TABLE meetings DROP CONSTRAINT ex_meetings_manager_time")
    op.drop_table("meetings")
    op.drop_table("companies")
    op.drop_table("managers")
