"""FastAPI 엔트리포인트.

레이어 구조(AD-2): routers → services → repositories → models/DB.
이 스토리는 골격 + /health 만 제공한다.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import __version__
from app.config import settings
from app.db import check_db
from app.routers import metrics as metrics_router
from app.routers import mna as mna_router
from app.routers import valueup as valueup_router

logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name, version=__version__)
app.include_router(metrics_router.router)
app.include_router(valueup_router.router)
app.include_router(mna_router.router)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """422를 AD-6 에러 계약 {detail, code}로 변환(2-5 GPT 리뷰 Med).

    FastAPI 기본 응답은 detail만 있고 code가 없어 계약 위반 — 전 라우터 공통 적용.
    """
    # jsonable_encoder: pydantic v2 errors()의 ctx에 예외 객체 등 비직렬화 값이 섞일 수
    # 있음(FastAPI 기본 핸들러와 동일 처리) — 없으면 422 만들다 500이 됨.
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(exc.errors()), "code": "VALIDATION_ERROR"},
    )


@app.get("/health", tags=["system"])
def health() -> JSONResponse:
    """헬스체크: 앱 기동 + DB 왕복(SELECT 1) 확인.

    DB 정상 → 200 {status:ok, db:ok}
    DB 실패 → 503 {status:degraded, db:down} (모니터링이 상태를 읽게)
    """
    try:
        check_db()
    except Exception:
        # 원인 추적용 로깅. 시크릿(DB URL·키)은 SecretStr이라 예외 메시지에 원문 노출 안 됨.
        logger.exception("DB health check failed")
        return JSONResponse(
            status_code=503, content={"status": "degraded", "db": "down"}
        )
    return JSONResponse(status_code=200, content={"status": "ok", "db": "ok"})
