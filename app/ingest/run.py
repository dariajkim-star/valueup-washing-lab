"""수집 실행 진입점 (간단 함수형; 라우터 POST /ingest/run은 후속 스토리).

트랜잭션 정책(결정): **종목별 커밋 + 실패 목록**. 한 종목의 네트워크/파싱 실패가
이미 성공한 다른 종목의 적재를 되돌리지 않도록 부분 성공을 허용한다.
fetch(네트워크)는 짧은 DB 트랜잭션 밖에서 수행해 DB 커넥션 점유를 최소화한다.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.db import SessionLocal
from app.ingest.dart import DartAdapter, DartAdapterError
from app.ingest.dart_ownership import DartOwnershipAdapter
from app.ingest.dart_valueup import DartValueupAdapter
from app.ingest.ecos import EcosAdapter
from app.ingest.krx import KrxAdapter
from app.models import Company

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    ingested: int = 0
    succeeded: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (corp_code, reason)
    degraded: list[str] = field(default_factory=list)  # 부분성공(예: 시총·거래대금 미수집)


def ingest_financials(
    corp_codes: Sequence[str],
    bsns_year: str,
    reprt_code: str = "11011",
) -> IngestResult:
    """종목별로 fetch→normalize→upsert. 실패는 건너뛰고 목록에 담는다."""
    adapter = DartAdapter()
    result = IngestResult()
    for corp_code in corp_codes:
        try:
            raw = adapter.fetch(corp_code, bsns_year, reprt_code)  # 네트워크(트랜잭션 밖)
            records = adapter.normalize(raw)
            with SessionLocal() as session:  # 종목당 짧은 트랜잭션
                with session.begin():
                    n = adapter.upsert(session, records)
            result.ingested += n
            result.succeeded.append(corp_code)
            if not raw.get("buyback_ok", True):  # 자사주 현황 실패 → 부분성공(1.8, krx cap_ok 패턴)
                logger.warning("자기주식 현황 미수집(degraded) corp_code=%s", corp_code)
                result.degraded.append(corp_code)
            if not raw.get("dividend_ok", True):  # 배당 현황 실패 → 부분성공(1.9, 동일 패턴)
                logger.warning("배당 현황 미수집(degraded) corp_code=%s", corp_code)
                if corp_code not in result.degraded:
                    result.degraded.append(corp_code)
        except (DartAdapterError, Exception) as e:  # noqa: BLE001 (부분성공 정책)
            logger.warning("수집 실패 corp_code=%s: %s", corp_code, type(e).__name__)
            result.failed.append((corp_code, str(e)))
    return result


def ingest_valueup_plans(
    corp_codes: Sequence[str], date_from: str, date_to: str
) -> IngestResult:
    """종목별 밸류업 계획공시(DART) 수집. [date_from, date_to]는 YYYYMMDD(bgn_de/end_de).

    한 종목이 예고·본공시·정정 등 여러 공시를 내면 각각 valueup_plan 행이 된다.
    실패는 건너뛰고 목록에 담는다(부분성공). fetch(네트워크)는 짧은 트랜잭션 밖.
    """
    adapter = DartValueupAdapter()
    result = IngestResult()
    for corp_code in corp_codes:
        try:
            raw = adapter.fetch(corp_code, date_from, date_to)  # 네트워크(트랜잭션 밖)
            records = adapter.normalize(raw)
            with SessionLocal() as session:  # 종목당 짧은 트랜잭션
                with session.begin():
                    n = adapter.upsert(session, records)
            result.ingested += n
            result.succeeded.append(corp_code)
            # 문서별 실패(무효 날짜·문서 다운로드 실패 등)는 종목 전체를 막지 않고 degraded 표시
            if raw.get("failed"):
                result.degraded.append(corp_code)
                for doc_id, reason in raw["failed"]:
                    logger.warning(
                        "밸류업 문서 실패 corp_code=%s doc=%s: %s",
                        corp_code, doc_id, reason,
                    )
        except Exception as e:  # noqa: BLE001 (부분성공 정책)
            logger.warning(
                "밸류업 공시 수집 실패 corp_code=%s: %s", corp_code, type(e).__name__
            )
            result.failed.append((corp_code, str(e)))
    return result


def ingest_ownership(
    corp_codes: Sequence[str], bsns_year: str, reprt_code: str = "11011"
) -> IngestResult:
    """종목별 지분구조(DART hyslrSttus+stockTotqySttus) 수집.

    완전 미공시(양 엔드포인트 데이터 없음)는 행을 만들지 않고 failed에 사유로 분리한다.
    실패는 건너뛰고 목록에 담는다(부분성공). fetch(네트워크)는 짧은 트랜잭션 밖.
    """
    adapter = DartOwnershipAdapter()
    result = IngestResult()
    for corp_code in corp_codes:
        try:
            raw = adapter.fetch(corp_code, bsns_year, reprt_code)  # 네트워크(트랜잭션 밖)
            records = adapter.normalize(raw)
            with SessionLocal() as session:  # 종목당 짧은 트랜잭션
                with session.begin():
                    n = adapter.upsert(session, records)
            result.ingested += n
            if records:
                result.succeeded.append(corp_code)
            else:
                # 미공시(에러 아님) → degraded로 분리(진짜 실패와 구분)
                logger.info("지분공시 데이터 없음 corp_code=%s", corp_code)
                result.degraded.append(corp_code)
        except Exception as e:  # noqa: BLE001 (부분성공 정책)
            logger.warning(
                "지분구조 수집 실패 corp_code=%s: %s", corp_code, type(e).__name__
            )
            result.failed.append((corp_code, str(e)))
    return result


def ingest_macro(date_from: str, date_to: str) -> IngestResult:
    """ECOS 매크로 지표(4종)를 [date_from, date_to](YYYYMMDD) 수집·적재.

    지표별 실패는 격리(fetch가 지표별로 잡아 raw['failed'] 반환) → result.failed에 표시.
    """
    adapter = EcosAdapter()
    result = IngestResult()
    try:
        raw = adapter.fetch(date_from, date_to)
        records = adapter.normalize(raw)
        with SessionLocal() as session:
            with session.begin():
                result.ingested = adapter.upsert(session, records)
        for indicator, reason in raw.get("failed", []):
            logger.warning("매크로 지표 실패 %s: %s", indicator, reason)
            result.failed.append((indicator, reason))
        # 성공한(=실패 목록에 없는) 지표
        failed_names = {i for i, _ in raw.get("failed", [])}
        result.succeeded.extend(
            i for i in ("base_rate", "bond_3y", "usd_krw", "leading_index")
            if i not in failed_names
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("매크로 수집 실패: %s", type(e).__name__)
        result.failed.append(("ecos", str(e)))
    return result


def ingest_prices(
    corp_codes: Sequence[str], date_from: str, date_to: str
) -> IngestResult:
    """종목별 시세·시총·거래대금 수집. stock_code는 company에서 조회(AD-5).

    - preflight: company/stock_code 매핑 부재는 먼저 failed로 분리.
    - degraded: 종가는 적재됐으나 시총·거래대금(cap 로그인) 실패 시 corp_code를 degraded에 표시.
    """
    adapter = KrxAdapter()
    result = IngestResult()
    # preflight: stock_code 매핑 확인
    stock_map: dict[str, str] = {}
    with SessionLocal() as session:
        for corp_code in corp_codes:
            company = session.get(Company, corp_code)
            sc = company.stock_code if company else None
            if not sc:
                result.failed.append((corp_code, "company.stock_code 없음(먼저 1.2 수집)"))
            else:
                stock_map[corp_code] = sc

    for corp_code, stock_code in stock_map.items():
        try:
            raw = adapter.fetch(stock_code, corp_code, date_from, date_to)
            records = adapter.normalize(raw)
            with SessionLocal() as session:
                with session.begin():
                    n = adapter.upsert(session, records)
            result.ingested += n
            result.succeeded.append(corp_code)
            if not raw.get("cap_ok"):  # 시총·거래대금 원천 실패 → 부분성공
                logger.warning("시총·거래대금 미수집(degraded) corp_code=%s", corp_code)
                result.degraded.append(corp_code)
        except Exception as e:  # noqa: BLE001 (부분성공 정책)
            logger.warning("시세 수집 실패 corp_code=%s: %s", corp_code, type(e).__name__)
            result.failed.append((corp_code, str(e)))
    return result
