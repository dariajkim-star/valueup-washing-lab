"""테스트 스위트 전역 안전장치.

**왜 있는가**: 2026-07-22에 테스트가 실 DB(valueup.db)를 오염시킨 사고가 있었다. CLI의
`--engine` 기본값이 `all`로 바뀌면서, gap만 monkeypatch하던 테스트가 mna 엔진을 실 DB에 돌려
`mna_score`에 존재하지 않아야 할 as_of 행 31건을 만들었다. **테스트는 통과했다** — 오염이
어떤 단언에도 걸리지 않았기 때문이다.

당시 대응은 해당 테스트 모듈의 autouse 픽스처였지만, 그건 모듈 로컬이라 다른 모듈에서
`gap_engine.run(...)`/`mna_engine.run(...)`을 factory 없이 호출하면 그대로 뚫린다
(코드리뷰 2026-07-22 Med). 여기서 스위트 전역으로 올린다.

같이 적용된 구조 변경: 두 엔진의 `session_factory` 기본값을 `None`으로 바꾸고 호출 시점에
`SessionLocal`을 조회하도록 했다. 기본 인자는 **함수 정의 시점에 객체가 고정**되므로,
모듈 속성만 monkeypatch해선 이미 바인딩된 실 factory를 바꿀 수 없기 때문이다.
그 변경이 없으면 아래 픽스처도 무력하다 — 둘은 한 쌍이다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture(autouse=True)
def _block_real_db(monkeypatch):
    """기본 `SessionLocal`을 빈 in-memory DB로 갈아끼운다.

    테이블조차 없는 DB라, 실수로 기본 factory를 쓰는 코드는 조용히 실 데이터를 건드리는 대신
    **즉시 OperationalError로 터진다**. 조용한 오염보다 시끄러운 실패가 낫다.

    자체 DB를 주입하는 테스트(대부분)는 영향을 받지 않는다 — 그쪽은 `session_factory=`로
    명시하므로 이 기본값을 거치지 않는다.
    """
    throwaway = sessionmaker(
        bind=create_engine(
            "sqlite:///:memory:", future=True, poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
    )
    for module in ("app.db", "app.analysis.gap_engine", "app.analysis.mna_engine",
                   "app.analysis.run_scoring"):
        monkeypatch.setattr(f"{module}.SessionLocal", throwaway, raising=False)
