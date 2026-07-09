"""지표 조회 유스케이스 (routers→services→repositories, AD-2)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.repositories import metrics as repo
from app.schemas import MetricOut, Page


def list_metrics(
    session: Session, filters: dict[str, Any], page: int, size: int,
    sort: str | None = None,
) -> Page[MetricOut]:
    rows, total = repo.list_metrics(session, filters, page, size, sort)
    return Page(
        items=[MetricOut(**r) for r in rows], total=total, page=page, size=size
    )


def metrics_by_corp(session: Session, corp_code: str) -> list[MetricOut]:
    return [MetricOut(**r) for r in repo.metrics_by_corp(session, corp_code)]
