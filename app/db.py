"""DB 엔진/세션 (SQLAlchemy 2.0).

레이어 규약(AD-2): repository만 이 세션으로 SQL을 실행한다.
PostgreSQL 기본, SQLite 폴백(로컬 개발·CI).
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

_url = settings.database_url.get_secret_value()
_is_sqlite = make_url(_url).get_backend_name() == "sqlite"

_engine_kwargs: dict = {"future": True}
if _is_sqlite:
    # SQLite는 스레드 체크 완화 필요
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # PostgreSQL: stale 커넥션으로 인한 헬스체크 false negative 방지
    _engine_kwargs["pool_pre_ping"] = True
    _engine_kwargs["pool_recycle"] = 1800

engine = create_engine(_url, **_engine_kwargs)

# expire_on_commit=False: commit 후 ORM 객체 반환 시 DetachedInstanceError 예방
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)


def get_db() -> Iterator[Session]:
    """FastAPI 의존성: 요청 스코프 DB 세션. 예외 시 롤백."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_db() -> bool:
    """헬스체크용 DB 왕복 (SELECT 1). 결과를 실제로 소비해 응답을 확인."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1")).scalar_one()
    return True
