"""company + financials tables

Revision ID: 0002_company_financials
Revises: 0001_baseline
Create Date: 2026-07-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_company_financials"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "company",
        sa.Column("corp_code", sa.String(length=8), primary_key=True),
        sa.Column("stock_code", sa.String(length=6), index=True),
        sa.Column("corp_name", sa.String(length=200), nullable=False),
        sa.Column("market", sa.String(length=10)),
        sa.Column("sector", sa.String(length=100)),
        sa.CheckConstraint("length(corp_code) = 8", name="ck_company_corp_code_len"),
    )
    op.create_table(
        "financials",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "corp_code",
            sa.String(length=8),
            sa.ForeignKey("company.corp_code"),
            nullable=False,
            index=True,
        ),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("quarter", sa.Integer, nullable=False),
        sa.Column("fs_div", sa.String(length=3)),
        sa.Column("revenue", sa.BigInteger),
        sa.Column("net_income", sa.BigInteger),
        sa.Column("operating_income", sa.BigInteger),
        sa.Column("depreciation", sa.BigInteger),
        sa.Column("equity", sa.BigInteger),
        sa.Column("total_assets", sa.BigInteger),
        sa.Column("total_liabilities", sa.BigInteger),
        sa.Column("cash", sa.BigInteger),
        sa.Column("total_debt", sa.BigInteger),
        sa.Column("dividend_total", sa.BigInteger),
        sa.Column("buyback_amount", sa.BigInteger),
        sa.Column("buyback_retired_amount", sa.BigInteger),
        sa.UniqueConstraint(
            "corp_code", "year", "quarter", name="uq_fin_corp_year_q"
        ),
        sa.CheckConstraint("quarter BETWEEN 1 AND 4", name="ck_fin_quarter"),
    )


def downgrade() -> None:
    op.drop_table("financials")
    op.drop_table("company")
