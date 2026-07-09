"""FastAPI 엔트리포인트.

레이어 구조(AD-2): routers → services → repositories → models/DB.
이 스토리는 골격 + /health 만 제공한다.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app import __version__
from app.config import settings
from app.db import check_db
from app.routers import metrics as metrics_router

logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name, version=__version__)
app.include_router(metrics_router.router)


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
