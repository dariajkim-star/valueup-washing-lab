"""Story 1.1 — 헬스체크 + 설정 로딩 검증."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pytest import approx

from app.config import settings
from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    """AC1·AC3: /health가 200과 status=ok, DB 왕복 확인을 반환한다."""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"


def test_config_loads_thresholds_and_weights() -> None:
    """AC2: 워싱 임계치·가중치가 설정으로 로드된다(하드코딩 금지)."""
    assert settings.washing_progress_min == 0.5
    assert settings.washing_achievement_max == 0.6
    # Value-up 가중치 합 = 1.0 (부동소수점 허용오차 비교)
    assert (
        settings.score_w_achievement
        + settings.score_w_buyback
        + settings.score_w_payout
    ) == approx(1.0)
    # M&A 가중치 합 = 1.0
    assert (
        settings.mna_w_valuation
        + settings.mna_w_capacity
        + settings.mna_w_ownership
        + settings.mna_w_macro
    ) == approx(1.0)


def test_health_reports_db_down(monkeypatch) -> None:
    """리뷰 반영: DB 실패 시 /health가 503 + db:down을 반환한다(죽은코드 아님)."""
    import app.main as main

    def _boom() -> bool:
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(main, "check_db", _boom)
    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json() == {"status": "degraded", "db": "down"}


def test_openapi_docs_available() -> None:
    """AC1: OpenAPI 스키마(/docs 소스)가 노출된다."""
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    assert resp.json()["info"]["title"]


def test_swagger_docs_renders() -> None:
    """AC1(리뷰 반영): Swagger UI(/docs) HTML이 실제로 렌더된다."""
    resp = client.get("/docs")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_config_loads_from_env(monkeypatch) -> None:
    """AC2(리뷰 반영): 값이 기본값이 아니라 환경변수에서 로드된다."""
    from app.config import Settings

    monkeypatch.setenv("DATABASE_URL", "sqlite:///./from_env.db")
    monkeypatch.setenv("DART_API_KEY", "dart-xyz")
    monkeypatch.setenv("ECOS_API_KEY", "ecos-abc")
    monkeypatch.setenv("WASHING_PROGRESS_MIN", "0.7")
    # _env_file=None: 파일 무시하고 환경변수만으로 로드되는지 확인
    s = Settings(_env_file=None)
    assert s.database_url.get_secret_value() == "sqlite:///./from_env.db"
    assert s.dart_api_key.get_secret_value() == "dart-xyz"
    assert s.ecos_api_key.get_secret_value() == "ecos-abc"
    assert s.washing_progress_min == 0.7


def test_config_rejects_bad_weight_sum(monkeypatch) -> None:
    """AC2(리뷰 반영): 가중치 합이 1.0이 아니면 검증 실패."""
    import pytest

    from app.config import Settings

    monkeypatch.setenv("SCORE_W_ACHIEVEMENT", "0.9")  # 0.9+0.3+0.2 = 1.4
    with pytest.raises(Exception):
        Settings(_env_file=None)


def test_alembic_upgrade_head(tmp_path) -> None:
    """AC4(리뷰 반영): alembic upgrade head가 임시 SQLite에서 성공한다."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{tmp_path / 'migtest.db'}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
