"""애플리케이션 설정 (pydantic-settings).

임계치·가중치는 절대 코드에 하드코딩하지 않는다(NFR3, AD-4/AD-10).
gap_engine·mna_engine 등 후속 스토리가 여기서 값을 읽는다.

시크릿(API 키·DB URL)은 SecretStr로 감싸 로그·에러·model_dump에 원문이 노출되지 않게 한다.
.env 경로는 실행 위치(cwd)에 의존하지 않도록 프로젝트 루트로 고정한다.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 프로젝트 루트(app/의 부모) 기준 .env — pytest·alembic·uvicorn 어디서 실행해도 동일
_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,  # 검증 에러에 입력값(시크릿) 노출 방지
    )

    # ── 앱 ──
    app_name: str = "밸류업 워싱 스크리너"
    debug: bool = False

    # ── DB ── (PostgreSQL 기본, 로컬 개발은 SQLite 폴백). URL에 비밀번호 포함 가능 → SecretStr
    database_url: SecretStr = SecretStr("sqlite:///./valueup.db")

    # ── 외부 소스 API 키 (소스 3종: DART · KRX · ECOS) ──
    # v1 스캐폴딩은 빈 기본값 허용(부팅 가능). 실제 필수화는 수집 스토리(1.2~)에서.
    dart_api_key: SecretStr = SecretStr("")
    ecos_api_key: SecretStr = SecretStr("")
    # KRX는 시가총액·거래대금 조회에 로그인 필요(pykrx가 KRX_ID/KRX_PW 환경변수 사용)
    krx_id: SecretStr = SecretStr("")
    krx_pw: SecretStr = SecretStr("")

    # ── 워싱 판정 임계치 (scoring.md), 0~1 범위 ──
    washing_progress_min: float = Field(0.5, ge=0.0, le=1.0)
    washing_achievement_max: float = Field(0.6, ge=0.0, le=1.0)

    # ── Value-up 실행점수 가중치 (합 1.0) ──
    score_w_achievement: float = Field(0.5, ge=0.0, le=1.0)
    score_w_buyback: float = Field(0.3, ge=0.0, le=1.0)
    score_w_payout: float = Field(0.2, ge=0.0, le=1.0)

    # ── M&A Target Score 가중치 (합 1.0) ──
    mna_w_valuation: float = Field(0.35, ge=0.0, le=1.0)
    mna_w_capacity: float = Field(0.25, ge=0.0, le=1.0)
    mna_w_ownership: float = Field(0.25, ge=0.0, le=1.0)
    mna_w_macro: float = Field(0.15, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_weight_sums(self) -> "Settings":
        """가중치 그룹 합이 1.0인지 검증(오설정 조기 발견)."""
        vu = self.score_w_achievement + self.score_w_buyback + self.score_w_payout
        mna = (
            self.mna_w_valuation
            + self.mna_w_capacity
            + self.mna_w_ownership
            + self.mna_w_macro
        )
        if abs(vu - 1.0) > 1e-6:
            raise ValueError(f"Value-up 가중치 합이 1.0이 아님: {vu}")
        if abs(mna - 1.0) > 1e-6:
            raise ValueError(f"M&A 가중치 합이 1.0이 아님: {mna}")
        return self


settings = Settings()
