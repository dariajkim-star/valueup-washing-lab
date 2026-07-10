"""/metrics 라우터 — 밸류에이션 지표 조회 (HTTP 경계, AD-2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import MetricOut, Page
from app.services import metrics as service

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=Page[MetricOut])
def list_metrics(
    market: str | None = None,
    sector: str | None = None,
    # 수치 필터는 NaN/inf 거부(DB별 비교 규칙이 갈리고 필터가 무력화됨) → 422
    max_pbr: float | None = Query(None, allow_inf_nan=False),
    min_roe: float | None = Query(None, allow_inf_nan=False),
    max_debt_ratio: float | None = Query(None, allow_inf_nan=False),
    min_payout_ratio: float | None = Query(None, allow_inf_nan=False),
    sort: str | None = Query(
        None,
        description="정렬 필드(공통 규약). `-field`는 내림차순. "
        "예: `-pbr`, `roe`. 허용: roe·roa·pbr·per·ev_ebitda·debt_ratio·"
        "payout_ratio·year 등(화이트리스트).",
    ),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[MetricOut]:
    filters = {
        "market": market, "sector": sector, "max_pbr": max_pbr,
        "min_roe": min_roe, "max_debt_ratio": max_debt_ratio,
        "min_payout_ratio": min_payout_ratio,
    }
    try:
        return service.list_metrics(db, filters, page, size, sort)
    except ValueError as e:
        # 화이트리스트 밖 sort 필드 → 400 (인젝션 시도도 여기서 차단)
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{corp_code}", response_model=list[MetricOut])
def metrics_by_corp(corp_code: str, db: Session = Depends(get_db)) -> list[MetricOut]:
    return service.metrics_by_corp(db, corp_code)
