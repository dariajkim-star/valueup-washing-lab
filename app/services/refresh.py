"""단건 종목 새로고침 — DART 재수집 + 재채점 (화면의 '업데이트' 버튼 백엔드).

왜 필요한가:
    화면이 보여주는 목표값은 수집 시점에 굳은 값이다. 회사가 새 공시를 냈거나 우리가
    파서를 고쳐도, 재수집 전까지 화면은 옛 숫자를 계속 보여준다. 지금까지 그 갱신 경로는
    CLI뿐이었고, 화면에서 "이 값 언제 것인가"를 본 사용자가 할 수 있는 일이 없었다.

    특히 rcept_no(0015) 신설 이후 **기존 행은 전부 rcept_no가 null**이라, 재수집이
    출처를 채우는 유일한 수단이다.

세 단계를 한 번에 묶는 이유와 **각 단계의 범위가 다른 이유**:
    1) DART 재수집  — 해당 종목만. 공시는 종목별 독립 사실이다.
    2) gap_engine   — 해당 종목만. execution_score는 **절대 측정치**라 한 종목만 다시
                      계산해도 나머지가 틀려지지 않는다.
    3) opacity_engine — **전체**(corp_codes=None). opacity_rank는 모집단 안의 **백분위**라
                      한 종목만 갱신하면 서로 다른 모집단 기준의 등수가 한 표에 섞인다.
                      opacity_engine.run 문서가 명시한 '부분 실행 주의'가 바로 이것이다.
                      한 종목을 눌렀는데 전체 순위가 움직이는 것은 부작용이 아니라 정의다.

mna_engine은 돌리지 않는다 — 밸류업 공시 재수집은 M&A 점수의 입력(재무·지분·매크로)을
바꾸지 않는다. 상관없는 순위표를 흔들지 않기 위해 의도적으로 뺐다.

⚠️ as_of는 **오늘이 아니라 기존 최신 세대**를 기본값으로 쓴다 (2026-07-29 실측으로 확정).
    처음엔 `date.today()`를 기본값으로 뒀는데, 버튼 한 번에 아래가 벌어졌다:

        valueup_score  [('2026-07-13', 26), ('2026-07-29', 1)]   ← 누른 1종목만
        mna_score      [('2026-07-13', 31)]                      ← 새 세대 없음
        opacity_score  [('2026-07-13', 20), ('2026-07-29', 20)]

    화면은 최신 as_of로 수렴하므로(3.4 as_of 체이닝), 새 세대가 생기는 순간 M&A가 **전
    종목에서 사라지고** 밸류업은 1종목만 남는다. 이 버튼은 mna를 돌리지 않기 때문에
    새 세대를 만들 자격이 없다.

    그래서 이 버튼의 역할을 못 박는다: **"이 세대를 최신 공시로 갱신"이지 "새 세대 생성"이
    아니다.** 새 스냅숏 날짜를 여는 것은 전 엔진을 함께 돌리는 배치(run_scoring)의 몫이다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from app.analysis import gap_engine, opacity_engine
from app.ingest.run import ingest_valueup_plans

logger = logging.getLogger(__name__)

# 밸류업 공시 제도 시행 이전은 조회할 것이 없다(2024년 시작). 하한을 고정해두면
# "언제부터"를 호출자가 매번 정하지 않아도 되고, 재수집 결과가 호출 시점에 좌우되지 않는다.
_DISCLOSURE_EPOCH = "20240101"


def _current_generation() -> str:
    """현재 화면이 보고 있는 스냅숏 날짜(= valueup_score의 최신 as_of).

    이 버튼은 그 세대를 제자리에서 갱신한다. 스코어가 하나도 없는 초기 상태에서만
    오늘 날짜로 첫 세대를 연다(그땐 섞일 기존 세대가 없으므로 안전).
    """
    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import ValueupScore

    with SessionLocal() as session:
        latest = session.scalar(select(func.max(ValueupScore.as_of)))
    return latest or date.today().isoformat()


@dataclass
class RefreshResult:
    """무엇이 실제로 바뀌었는지를 단계별로 보고한다 — '성공' 한 단어로 뭉치지 않는다.

    부분 성공이 정상 경로다(수집은 됐는데 채점이 실패하는 등). 화면이 그 차이를
    말할 수 있어야 사용자가 다시 눌러야 할지 판단한다.
    """

    corp_code: str
    as_of: str
    plans_ingested: int = 0
    ingest_ok: bool = False
    ingest_error: str | None = None
    scored: bool = False
    score_error: str | None = None
    opacity_reranked: bool = False
    opacity_error: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.ingest_ok and self.scored and self.opacity_reranked


def refresh_company(corp_code: str, as_of: str | None = None) -> RefreshResult:
    """한 종목의 밸류업 공시를 DART에서 다시 받고, 그 결과로 점수·순위를 재계산한다.

    단계별로 격리한다: 수집이 실패해도 재채점은 시도한다(기존 공시로라도 점수를 최신
    엔진 로직에 맞춰 다시 매기는 것이 사용자에게 의미 있으므로). 대신 무엇이 실패했는지
    RefreshResult에 남긴다 — 조용히 성공으로 보이게 하지 않는다.
    """
    resolved_as_of = as_of or _current_generation()
    result = RefreshResult(corp_code=corp_code, as_of=resolved_as_of)
    today = date.today().strftime("%Y%m%d")

    # 1) DART 재수집(해당 종목만)
    try:
        ingest = ingest_valueup_plans([corp_code], _DISCLOSURE_EPOCH, today)
        result.plans_ingested = ingest.ingested
        result.ingest_ok = corp_code in ingest.succeeded
        if ingest.failed:
            result.ingest_error = ingest.failed[0][1]
        if corp_code in ingest.degraded:
            # 문서 일부 실패 = 이 종목의 공시 중 일부만 읽혔다. 성공으로 뭉개면
            # 사용자는 왜 목표가 여전히 비어 있는지 알 수 없다.
            result.warnings.append("일부 공시 문서를 읽지 못했습니다(부분 수집).")
    except Exception as e:  # noqa: BLE001 — 단계 격리(수집 실패가 재채점을 막지 않는다)
        logger.warning("재수집 실패 corp_code=%s: %s", corp_code, type(e).__name__)
        result.ingest_error = type(e).__name__

    # 2) 재채점(해당 종목만 — 절대 측정치)
    try:
        score_run = gap_engine.run(resolved_as_of, [corp_code])
        result.scored = score_run.complete
        if not score_run.complete:
            result.score_error = "일부 종목 채점 실패"
    except Exception as e:  # noqa: BLE001
        logger.warning("재채점 실패 corp_code=%s: %s", corp_code, type(e).__name__)
        result.score_error = type(e).__name__

    # 3) 불투명도 재계산(**전체** — 백분위라 부분 실행 시 세대가 섞인다)
    try:
        opacity_run = opacity_engine.run(resolved_as_of, None)
        result.opacity_reranked = opacity_run.complete
        if not opacity_run.complete:
            result.opacity_error = "불투명도 순위 일부 실패"
    except Exception as e:  # noqa: BLE001
        logger.warning("불투명도 재계산 실패: %s", type(e).__name__)
        result.opacity_error = type(e).__name__

    return result
