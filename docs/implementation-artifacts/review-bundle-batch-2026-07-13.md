# 코드 리뷰 요청 — 밸류업 워싱 스크리너 **일괄 4스토리** (1-9 배당수집 · 1-10 파서튜닝 · 2-7 sector peer · 2-4 랭킹 API)

너는 엄격한(adversarial) 시니어 코드 리뷰어야. 아래 4개 스토리의 AC와 **전체 코드(verbatim, 파일 원문 그대로 삽입)**를 보고
버그·규약 위반·엣지케이스를 찾아줘. 출력: `[High/Med/Low] 스토리번호 파일:라인 — 문제 — 근거/재현 — 제안수정`. 없으면 "clean".

## 배경 요약

드레스 리허설(KOSPI 33종목 라이브 end-to-end)의 발견에 따라 4개 스토리를 연속 구현:
- **1-9**: `dividend_total`이 구조적 100% null(수집 경로 미구현)이던 것을 DART `alotMatter.json`(현금배당금총액, **백만원 단위 → ×1e6**)로 수집. 1-8 격리 패턴 미러(보조 원천 실패가 재무 수집을 막지 않음). 라이브: 0%→85%.
- **1-10**: 실샘플 79건 분석으로 실증된 파서 개선 4종 — (a) report_nm 부정필터(이행현황·철회 제외, 정정 유지), (b) 괄호 한정어 gap(`ROE 목표(\`24~\`30년 평균) : 15%`), (c) 화살표 체인 우변 채택(`1.8% → 8.3%`), (d) 백틱 2자리 연도(`\`24~\`30년`). 라이브: 문서 79→60(비계획 배제), target_roe 24%→42%, period 13%→28%.
- **2-7**: M&A 백분위 모집단을 KSIC 2자리 버킷(company.sector=induty_code 앞 2자리)으로 분리, peer<`mna_peer_min`(config, 기본 5)이면 전체시장 폴백, `population_basis`(sector:XX/market_fallback/market) 저장. ownership·macro는 업종 무관 유지. 라이브: 금융지주 버킷(64) 활성.
- **2-4**: `/valueup/gap-analysis`·`/valueup/washing-ranking`. 목표·실제·갭(target_roe/actual_roe/roe_gap)을 **엔진 계산 시점에 동결 저장**(서빙 재계산 금지), null-last 명시 정렬, washing null="판단 불가" 계약을 OpenAPI에 명문화. 라이브 스모크 OK.

pytest **178 passed**(신규 21 + 회귀 0). 마이그레이션 0010(population_basis)·0011(gap 동결 3컬럼).

## 아키텍처 제약(공통)

- AD-2: routers→services→repositories, SQL은 repository만. AD-3: 원천 테이블 writer=어댑터 1개(financials=DartAdapter). AD-4/AD-10: valueup_score=gap_engine, mna_score=mna_engine 유일 writer. AD-6: 목록 봉투 {items,total,page,size}. AD-7: 자연키 멱등 upsert. NFR2: 애매하면 null(틀린 non-null 금지). NFR3: 임계치·가중치 config.
- 확립된 계약: null≠0(1-8), Kleene 3치 washing(2-1), look-ahead 부분차단=같은 해 사업보고서 배제(2-1/2-3), mid-rank 백분위·엄격 null·전체실행 권장(2-3).

## 이미 알려진 것 / 의도된 결정 (중복 지적 불필요)

- 가격 point-in-time 미보장(뷰가 전역 최신가 — 2-3 defer), available_at 부재(분기·전년Q4 시차 — 공통 defer), market universe/생존편향(상장·상폐일 데이터 없음 — defer), select-then-insert 동시성(v1 공통 defer), 날짜 String(10) 컨벤션(공통 defer).
- 금융주 valuation null은 2-7로도 안 풀림(자기 지표가 null — 레벨2 변수세트 몫, 스토리에 명시).
- 주주환원율-only 공시 미매핑(배당성향≠주주환원율 의미 결정 — 별도 필드는 후속).
- target_pbr 계산 미사용(리드 결정).
- washing-ranking이 null(판단불가)을 제외하는 것은 의도(전체는 gap-analysis).

## 특히 답해줘 (스토리별 핵심 질문)

1. **[1-9]** `_dividend_total`의 (라벨,스케일) 정확일치 정책 — 실제 DART alotMatter 라벨 변형("현금배당금총액 (백만원)" 공백, "현금배당금총액(원)" 등)에서 놓치는 게 있나? `_norm_label`이 공백을 전부 제거하니 "(백만원)" 변형은 흡수되나, 다른 단위 라벨은 의도적으로 null — 맞는 정책인가?
2. **[1-10]** `_LABEL_GAP`의 괄호 한정어 허용이 새로운 오탐 표면을 여나(괄호 안 25자 제한·개행 금지가 충분한가)? `_ARROW_TAIL`의 좌변 gap 30자(숫자 허용)가 인접 지표의 %를 좌변으로 오인할 경로는?
3. **[2-7]** 버킷 폴백 판정이 metrics 보유 종목 수 기준인데, 버킷 내 특정 지표만 희소한 경우(예: 버킷 6종목인데 ev_ebitda는 2개만 유효) mid-rank의 peer<2 가드와 조합하면 어떤 동작이 되나 — basis 문자열(sector:XX)이 사실과 어긋나는 케이스가 있나?
4. **[2-4]** 동결 저장(target/actual/gap) vs 서빙 재계산 트레이드오프에서 놓친 정합 문제는? `list_scores`의 `is_(None)` 정렬·subquery COUNT가 PostgreSQL에서도 동일 동작하나?

---

## Story 1-9 + 1-8 공유 코드

### `app/ingest/dart.py` (전체, verbatim)

```python
"""DART(전자공시) 소스 어댑터 — company·financials의 writer (AD-3).

OpenDART REST API(requests)를 사용한다:
  - company.json          : 기업개황(회사명·종목코드·시장구분·업종)
  - fnlttSinglAcntAll.json : 단일회사 전체 재무제표(계정명→금액)

프로덕션 하드닝: 재시도/백오프, rate-limit(100/min), 키 redaction, connect/read timeout 분리.
fetch: REST 호출(키 필요). normalize: 계정명 매핑(순수, 테스트 가능). upsert: 멱등 적재.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Mapping, Sequence
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from sqlalchemy.orm import Session
from urllib3.util.retry import Retry

from app.config import settings
from app.ingest.base import SourceAdapter
from app.repositories.financials import upsert_company, upsert_financial

_BASE = "https://opendart.fss.or.kr/api"
_TIMEOUT = (3.05, 20)  # (connect, read)
_MIN_INTERVAL = 0.65  # 100 req/min 여유(초당 <2)

_MARKET = {"Y": "KOSPI", "K": "KOSDAQ", "N": "KONEX", "E": "기타"}
_REPRT_QUARTER = {"11013": 1, "11012": 2, "11014": 3, "11011": 4}
_YEAR_RE = re.compile(r"^\d{4}$")

# 단일 값 계정(첫 매칭). 총차입금은 별도 합산 규칙 사용.
_ACCOUNT_MAP: dict[str, tuple[str, ...]] = {
    "revenue": ("매출액", "수익(매출액)", "영업수익"),
    "net_income": ("당기순이익", "당기순이익(손실)", "분기순이익"),
    "operating_income": ("영업이익", "영업이익(손실)"),
    "depreciation": ("감가상각비", "유형자산감가상각비"),
    "equity": ("자본총계",),
    "total_assets": ("자산총계",),
    "total_liabilities": ("부채총계",),
    "cash": ("현금및현금성자산",),
}
# 총차입금(이자성 부채) = 아래 라벨에 매칭되는 '모든 행'의 합.
# 회사마다 라벨이 다르고(삼성: 단기/장기차입금·사채, 하이닉스: 차입금),
# 같은 라벨이 유동/비유동에 중복 등장하므로 dedup이 아니라 전체 합산해야 한다.
_DEBT_LABELS = (
    "차입금", "단기차입금", "장기차입금", "유동성장기부채", "사채", "리스부채",
)


class DartAdapterError(RuntimeError):
    """DART 어댑터 오류(키 미설정·API 오류·네트워크 실패 등). 키/URL을 메시지에 넣지 않는다."""


class _RateLimiter:
    """단순 최소간격 rate limiter(스레드 안전)."""

    def __init__(self, min_interval: float) -> None:
        self._min = min_interval
        self._last = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            wait = self._min - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()


class DartAdapter(SourceAdapter):
    source = "dart"

    def __init__(self) -> None:
        self._session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        self._session.mount("https://", HTTPAdapter(max_retries=retry))
        self._limiter = _RateLimiter(_MIN_INTERVAL)

    # ── fetch (라이브, 키 필요) ──
    def fetch(
        self,
        corp_code: str,
        bsns_year: str,
        reprt_code: str = "11011",
        fs_div: str = "CFS",
        include_buyback: bool = True,
    ) -> dict[str, Any]:
        key = settings.dart_api_key.get_secret_value()
        if not key:
            raise DartAdapterError(
                "DART_API_KEY가 설정되지 않았습니다. .env에 DART_API_KEY를 넣으세요."
            )
        if reprt_code not in _REPRT_QUARTER:
            raise DartAdapterError(f"지원하지 않는 reprt_code: {reprt_code}")
        if not _YEAR_RE.match(str(bsns_year)):
            raise DartAdapterError(f"잘못된 bsns_year(YYYY 아님): {bsns_year!r}")

        company = self._fetch_company(key, corp_code)
        accounts, total_debt, used_fs_div = self._fetch_accounts(
            key, corp_code, bsns_year, reprt_code, fs_div
        )
        periods: list[dict[str, Any]] = []
        buyback_ok = True  # buyback 시도 실패 시 False(재무는 계속, run.py가 degraded 표시)
        dividend_ok = True  # 배당(1.9) 동일 격리 — 보조 원천 실패가 재무를 막지 않음
        # 데이터 없음(빈 accounts)과 계정 누락을 구분: 데이터 없으면 재무 period를 만들지 않음.
        # buyback만 있고 accounts 없는 종목은 period 미생성 → buyback 미적재(드묾, 한계 문서화).
        if accounts:
            # 자기주식 취득/처분 현황(1.8) — buyback_amount·buyback_retired_amount 신호원.
            # financials 단일 writer(AD-3) 유지: 별도 어댑터 아니라 이 fetch가 함께 수집.
            # 재무 period가 생길 때만 호출(빈 accounts에 rate-limit 호출 낭비 방지, 리뷰 Med).
            # 보조 원천이라 실패해도 재무 수집을 막지 않는다(리뷰 High: 쿼터 020 등에서
            # 이미 성공한 재무까지 유실되던 회귀 격리). None=미상/실패, []=미공시(013).
            buyback_rows: list[Any] | None = None
            if include_buyback:
                try:
                    bb = self._get(
                        "tesstkAcqsDspsSttus.json",
                        {
                            "crtfc_key": key,
                            "corp_code": corp_code,
                            "bsns_year": bsns_year,
                            "reprt_code": reprt_code,
                        },
                        allow_no_data=True,
                    )
                    rows = bb.get("list") or []
                    if isinstance(rows, list):
                        buyback_rows = rows
                    else:  # 형태 이탈(list가 dict/str 등) → unknown 처리(리뷰 Med)
                        buyback_ok = False
                except DartAdapterError:
                    buyback_ok = False  # 보조 원천 실패 → 재무는 계속(degraded)
            # 배당에 관한 사항(1.9) — dividend_total(현금배당금총액) 신호원. buyback과
            # 동일 격리 패턴: 실패해도 재무 수집 계속, None=미상/실패, []=미공시(013).
            dividend_rows: list[Any] | None = None
            try:
                dv = self._get(
                    "alotMatter.json",
                    {
                        "crtfc_key": key,
                        "corp_code": corp_code,
                        "bsns_year": bsns_year,
                        "reprt_code": reprt_code,
                    },
                    allow_no_data=True,
                )
                rows = dv.get("list") or []
                if isinstance(rows, list):
                    dividend_rows = rows
                else:
                    dividend_ok = False
            except DartAdapterError:
                dividend_ok = False
            periods.append(
                {
                    "year": int(bsns_year),
                    "quarter": _REPRT_QUARTER[reprt_code],
                    "accounts": accounts,
                    "total_debt": total_debt,
                    "fs_div": used_fs_div,
                    "buyback_rows": buyback_rows,
                    "dividend_rows": dividend_rows,
                }
            )
        return {
            "company": company,
            "periods": periods,
            "buyback_ok": buyback_ok,
            "dividend_ok": dividend_ok,
        }

    def _fetch_company(self, key: str, corp_code: str) -> dict[str, Any]:
        data = self._get("company.json", {"crtfc_key": key, "corp_code": corp_code})
        return {
            "corp_code": corp_code,
            "stock_code": data.get("stock_code") or None,
            "corp_name": data.get("corp_name", ""),
            "market": _MARKET.get(data.get("corp_cls", ""), None),
            "sector": data.get("induty_code") or None,
        }

    def _fetch_accounts(
        self, key: str, corp_code: str, bsns_year: str, reprt_code: str, fs_div: str
    ) -> tuple[dict[str, int], int | None, str | None]:
        """(단일값 계정 dict, 총차입금 합, 사용한 fs_div) 반환."""
        for div in (fs_div, "OFS" if fs_div == "CFS" else None):
            if div is None:
                break
            params = {
                "crtfc_key": key,
                "corp_code": corp_code,
                "bsns_year": bsns_year,
                "reprt_code": reprt_code,
                "fs_div": div,
            }
            data = self._get(
                "fnlttSinglAcntAll.json", params, allow_no_data=True
            )
            rows = data.get("list") or []
            if rows:
                accounts: dict[str, int] = {}
                for row in rows:
                    name = row.get("account_nm", "")
                    val = _parse_amount(row.get("thstrm_amount"))
                    if val is not None and name not in accounts:
                        accounts[name] = val
                # 총차입금은 dedup 전 '모든 행'에서 합산(중복 라벨·유동/비유동 포함)
                total_debt = _sum_debt(rows)
                return accounts, total_debt, div
        return {}, None, None

    def _get(
        self, endpoint: str, params: Mapping[str, Any], allow_no_data: bool = False
    ) -> dict[str, Any]:
        self._limiter.acquire()
        try:
            resp = self._session.get(
                f"{_BASE}/{endpoint}", params=params, timeout=_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            # 예외 메시지에 params(crtfc_key 포함 URL)를 넣지 않는다 — 키 노출 방지.
            # ValueError = 비JSON 200(HTML 점검페이지 등)의 resp.json() 실패(공통 defer 해소).
            raise DartAdapterError(
                f"DART 요청 실패: endpoint={endpoint} ({type(e).__name__})"
            ) from None
        if not isinstance(data, dict):  # JSON이지만 dict 아님(배열/문자열) → 명확한 에러
            raise DartAdapterError(f"DART 응답 형태 오류: endpoint={endpoint}")
        status = data.get("status")
        if status == "000":
            return data
        if allow_no_data and status == "013":  # 조회된 데이터 없음
            return {"list": []}
        raise DartAdapterError(
            f"DART API 오류: endpoint={endpoint}, status={status}, msg={data.get('message')}"
        )

    # ── normalize (순수, 테스트 가능) ──
    def normalize(
        self, raw: Mapping[str, Any]
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        company = dict(raw["company"])
        corp_code = company["corp_code"]
        fin_recs: list[dict[str, Any]] = []
        for period in raw.get("periods", []):
            accounts: Mapping[str, Any] = period.get("accounts", {})
            rec: dict[str, Any] = {
                "corp_code": corp_code,
                "year": period["year"],
                "quarter": period["quarter"],
                "fs_div": period.get("fs_div"),
            }
            for col, labels in _ACCOUNT_MAP.items():
                rec[col] = _pick(accounts, labels)
            # total_debt는 fetch에서 '모든 차입 행' 합산(중복 라벨 포함)해 넘겨받음
            rec["total_debt"] = period.get("total_debt")
            # 배당총액(1.9): alotMatter 행에서 집계(백만원→KRW 스케일). rows None/[] → null.
            rec["dividend_total"] = _dividend_total(period.get("dividend_rows"))
            # 자사주 취득/소각 신호(1.8): tesstkAcqsDspsSttus 행에서 집계(수량, 액 아님).
            # buyback_rows None(미상/실패)·[](미공시) 모두 (None, None) → 기존값 보존.
            rec["buyback_amount"], rec["buyback_retired_amount"] = _buyback_totals(
                period.get("buyback_rows")
            )
            fin_recs.append(rec)
        return company, fin_recs

    # ── upsert (멱등) ──
    def upsert(
        self, session: Session, records: tuple[dict[str, Any], Sequence[dict[str, Any]]]
    ) -> int:
        company_rec, fin_recs = records
        upsert_company(session, company_rec)
        for rec in fin_recs:
            upsert_financial(session, rec)
        session.flush()
        return len(fin_recs)


def _parse_amount(raw: Any) -> int | None:
    """DART 금액 문자열을 정수로. 회계 음수(괄호·△·유니코드 마이너스) 처리. 빈값/'-'는 None."""
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "").replace(" ", "")
    if s in ("", "-", "△", "-"):
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):  # (3000) = -3000
        negative, s = True, s[1:-1]
    if s and s[0] in "△-−":  # 삼각형·하이픈·유니코드 마이너스
        negative, s = True, s[1:]
    if not s.isdigit():
        return None
    val = int(s)
    return -val if negative else val


def _pick(accounts: Mapping[str, Any], labels: tuple[str, ...]) -> int | None:
    """후보 라벨 중 처음 '유효하게 파싱되는' 값을 반환. 실패하면 다음 후보로 계속."""
    for label in labels:
        if label in accounts:
            v = accounts[label]
            if isinstance(v, int):
                return v
            parsed = _parse_amount(v)
            if parsed is not None:
                return parsed
    return None


# 자기주식 취득/처분 행 분류(코드리뷰 2026-07-10: 자체+GPT 교차검증 반영).
# 총계/합계 = 최상위 총계(권위 소스), 소계 = 중간 집계(계층 검증 불가 → 단독으론 미사용).
_BUYBACK_TOTAL_LABELS = ("총계", "합계")
_BUYBACK_SUBTOTAL_LABELS = ("소계",)
_BUYBACK_MTH_KEYS = ("acqs_mth1", "acqs_mth2", "acqs_mth3")


# 배당총액 라벨(1.9): 단위가 라벨에 박혀 있어 (라벨, 스케일) 쌍으로만 인정 —
# 단위 미확인 변형에 값을 만들면 100만 배 축소가 조용히 payout_ratio를 오염(null>틀린값).
_DIVIDEND_TOTAL_LABELS: dict[str, int] = {
    "현금배당금총액(백만원)": 1_000_000,
}


def _dividend_total(rows: Sequence[Mapping[str, Any]] | None) -> int | None:
    """alotMatter 행 → 현금배당금총액(KRW). 라벨 정확일치 + 명시 스케일만.

    rows None(미상/실패)·[](미공시) → null(기존값 보존). 파싱값 0은 확정 0(배당 없음),
    음수는 도메인 밖 → null. 주당배당금·배당성향·주식배당 행은 미사용.
    """
    if not rows:
        return None
    for row in rows:
        label = _norm_label(row.get("se"))
        scale = _DIVIDEND_TOTAL_LABELS.get(label)
        if scale is None:
            continue
        v = _parse_amount(row.get("thstrm"))
        if v is None:
            continue
        if v < 0:  # 배당총액 음수는 도메인 밖(회계 괄호 오파싱 등) → null
            return None
        return v * scale
    return None


def _norm_label(v: Any) -> str:
    """라벨 정규화: 모든 공백 제거('총 계' 표기 변형 대응) 후 비교.

    정확일치 원칙 유지(1.6 "특수관계인"의 "계" 부분일치 오탐 교훈) —
    공백 제거는 _parse_amount의 수치 정규화와 동일한 수준의 표기 방어일 뿐.
    """
    return "".join(str(v).split())


def _buyback_row_kind(row: Mapping[str, Any]) -> str:
    """행 분류: 'total'(총계/합계) / 'subtotal'(소계) / 'leaf'(개별 취득방법)."""
    for k in _BUYBACK_MTH_KEYS:
        label = _norm_label(row.get(k, ""))
        if label in _BUYBACK_TOTAL_LABELS:
            return "total"
        if label in _BUYBACK_SUBTOTAL_LABELS:
            return "subtotal"
    return "leaf"


def _parse_quantity(raw: Any) -> int | None:
    """수량(주) 파싱. 음수는 수량 도메인에 없음 → None(null>오값).

    _parse_amount는 KRW용이라 회계 음수 표기(△·괄호)를 음수로 해석하는데,
    수량 합산에서 음수가 섞이면 상쇄로 '활동 없음(0)'이 조작될 수 있어(GPT 리뷰) 거부.
    """
    v = _parse_amount(raw)
    return v if v is not None and v >= 0 else None


def _buyback_field_total(
    rows: Sequence[Any], field: str
) -> int | None:
    """한 필드(change_qy_acqs/change_qy_incnr)의 기간 수량 합계. 필드별 독립 판정.

    우선순위(이중집계·부분손실 방지, 애매하면 null — AC3):
      1) 총계/합계 행이 있으면 그것이 권위 소스:
         - 유일하면 그 값.
         - 여러 행이고 stock_knd가 전부 다르면(보통주/우선주 등 종류별 파티션) 합산.
         - 여러 행이고 값이 전부 같으면(합계·총계 중복 표기) 그 값.
         - 그 외(상충 총계) → None.
      2) 총계 없으면 leaf 행 합(0 가능 → '활동 0' 확정).
      3) 소계만 있으면 None — 소계 중첩/부분 계층을 검증할 수 없어 합산하지 않는다.
    """
    totals: list[tuple[str, int]] = []
    leaves: list[int] = []
    for row in rows:
        if not isinstance(row, Mapping):  # 형태 이탈 요소(비dict) 방어
            continue
        v = _parse_quantity(row.get(field))
        if v is None:
            continue
        kind = _buyback_row_kind(row)
        if kind == "total":
            totals.append((_norm_label(row.get("stock_knd", "")), v))
        elif kind == "leaf":
            leaves.append(v)
        # subtotal은 수집하지 않음(계층 불명 → 단독 사용 금지)
    if totals:
        if len(totals) == 1:
            return totals[0][1]
        kinds = [k for k, _ in totals]
        if all(kinds) and len(set(kinds)) == len(kinds):
            return sum(v for _, v in totals)  # 종류별 총계 파티션 합
        values = {v for _, v in totals}
        if len(values) == 1:
            return values.pop()  # 중복 표기 일치(합계=총계)
        return None  # 상충 총계 → 애매 → null
    if leaves:
        return sum(leaves)
    return None  # 소계만/파싱값 전무 → null(미공시·불명과 동일 취급)


def _buyback_totals(
    rows: Sequence[Any] | None,
) -> tuple[int | None, int | None]:
    """tesstkAcqsDspsSttus 행 → (취득 수량, 소각 수량). 수량(주), 액 아님.

    필드별 독립 판정(취득은 leaf에, 소각은 총계에만 있어도 각각 채움 — 리뷰 High 반영).
    None(미공시/실패/애매)과 0(공시된 활동 없음)을 구분(NFR2 "null > 틀린 값").
    """
    safe_rows = rows or []
    return (
        _buyback_field_total(safe_rows, "change_qy_acqs"),
        _buyback_field_total(safe_rows, "change_qy_incnr"),
    )


def _sum_debt(rows: Sequence[Mapping[str, Any]]) -> int | None:
    """총차입금 = 차입 라벨에 매칭되는 '모든 행'의 합(중복 라벨·유동/비유동 포함).

    dedup dict가 아니라 원본 rows에서 계산 — 같은 '차입금'이 유동/비유동에 각각
    등장하는 경우(하이닉스 등)를 모두 합산한다. 하나도 없으면 None.
    """
    total = 0
    found = False
    for row in rows:
        name = row.get("account_nm", "")
        if name in _DEBT_LABELS:
            v = _parse_amount(row.get("thstrm_amount"))
            if v is not None:
                total += v
                found = True
    return total if found else None
```

### `app/ingest/run.py` — ingest_financials(dividend_ok 반영) (verbatim 발췌)

```python
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
```

## Story 1-10

### `app/ingest/dart_valueup.py` (전체, verbatim)

```python
"""DART 밸류업 계획공시 어댑터 — valueup_plan의 writer (AD-3, source="dart").

"기업가치 제고 계획"은 구조화 재무 API가 없는 **자유서식 공시**라 2단계로 수집한다:
  1) list.json(공시검색, JSON)  → report_nm 매칭으로 밸류업 공시 발견(다중·다중페이지)
  2) document.xml(ZIP 바이너리) → 압축 해제·태그 스트립으로 원문 raw_text 확보

정확성 계약의 핵심 = **raw_text 보존 + 멱등 upsert**. 목표 필드(ROE·배당성향·PBR·기간·자사주)는
best-effort 정규식이며 **애매하면 null**(틀린 non-null 값 금지 — 코드리뷰 반영).

설계 규약(코드리뷰 반영):
- **문서별 격리**: 한 문서/후반 페이지 실패가 그 종목의 이미 모은 공시를 날리지 않는다.
- **성공/실패 구분**: 유효 문서를 파싱한 결과만 upsert(권위) → repository가 목표필드를 null 포함
  전체 교체. 문서 fetch 실패(비ZIP·HTTP오류·빈 응답)는 upsert하지 않아 기존 레코드를 보존한다.
- ⚠️ document.xml은 ZIP 바이너리 → dart.py의 `_get`(resp.json) 재사용 금지. `_fetch_document`는
  `resp.content`를 쓰고, 실패는 DartDocumentError로 격리. HTTP 하드닝·키 미노출은 dart.py 재사용.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from sqlalchemy.orm import Session
from urllib3.util.retry import Retry

from app.config import settings
from app.ingest.base import SourceAdapter
from app.ingest.dart import (
    _BASE,
    _MIN_INTERVAL,
    _TIMEOUT,
    DartAdapterError,
    _RateLimiter,
)
from app.repositories.valueup_plan import upsert_valueup_plan

# report_nm 매칭(공백 제거 후 부분일치). pblntf_ty로 좁히지 않는다(과대필터 방지).
_REPORT_KEYWORD = "기업가치제고계획"
# 계획이 아닌 공시 제외(1.10, F9 실증): 이행현황(사후보고)·철회는 목표 공시가 아님.
# 정정([기재정정] 등)은 유지 — 최신 정정이 권위 있는 목표(2.1 최신공시 채택 규칙과 정합).
_REPORT_EXCLUDE = ("이행현황", "철회")


def _is_plan_report(report_nm: str | None) -> bool:
    """report_nm이 '계획' 공시인지 판정(공백 제거 부분일치 + 부정 키워드 제외)."""
    compact = str(report_nm or "").replace(" ", "")
    if _REPORT_KEYWORD not in compact:
        return False
    return not any(kw in compact for kw in _REPORT_EXCLUDE)
_MAX_PAGES = 50  # 페이지네이션 상한(과대 total_page 방어)
_MAX_ZIP_BYTES = 20 * 1024 * 1024  # 문서 ZIP 원본 크기 상한
_MAX_MEMBER_BYTES = 10 * 1024 * 1024  # 멤버 압축해제 크기 상한(zip-bomb 방어)
_TEXT_EXTS = (".xml", ".html", ".htm", ".txt")  # 텍스트 멤버만(바이너리 오탐 방지)
_PBR_MAX = 100.0  # 현실적 PBR 상한(연도·페이지번호 오탐 배제)

# ── best-effort 파싱 패턴 ──
# 값 뒤에 p/P/포(인트)가 오면 '퍼센트포인트'(증감)라 절대목표 아님 → 제외.
_PCT = r"(\d+(?:\.\d+)?)\s*%(?![pP포])"
# ROE 별칭(1.10, 실샘플 6건: '자기자본이익률' 표기).
_ROE_LABEL = r"(?:ROE|자기자본이익률)"
# 라벨-값 gap은 **개행을 넘지 못한다**(표 셀/문단 경계 보존 → 인접 지표 % 침범 방지).
# 1.10: 괄호 한정어 허용 — 실샘플 `ROE 목표(`24~`30년 평균) : 15%`의 괄호 안 숫자가
# 기존 gap([^0-9%\n])을 깨던 케이스. 괄호 밖 gap은 여전히 숫자 금지(인접 지표 방어 유지).
_LABEL_GAP = r"[^0-9%\n(]{0,15}(?:\([^)\n]{0,25}\)\s*[:：]?\s*)?[^0-9%\n]{0,10}?"
_ROE_RE = re.compile(_ROE_LABEL + _LABEL_GAP + _PCT, re.IGNORECASE)
# '배당성향'만 매칭(주주환원율은 다른 지표라 target_payout_ratio에 넣지 않음).
_PAYOUT_RE = re.compile(r"배당성향" + _LABEL_GAP + _PCT)
# 1.10(F3/G2, 실샘플 실증): "현재 X% → 목표 Y%" 화살표 체인은 **우변(목표)** 채택.
# 좌변 gap은 숫자 허용(연도·기준일 서술 통과), 개행은 금지(같은 문장/셀 안에서만).
_ARROW_TAIL = (
    r"[^%\n]{0,30}?(\d+(?:\.\d+)?)\s*%"
    r"[^\n%]{0,25}?(?:→|⇒|➔)\s*[^\n%]{0,25}?(\d+(?:\.\d+)?)\s*%(?![pP포])"
)
_ROE_ARROW_RE = re.compile(_ROE_LABEL + _ARROW_TAIL, re.IGNORECASE)
_PAYOUT_ARROW_RE = re.compile(r"배당성향" + _ARROW_TAIL)
# PBR은 '배' 단위 **필수**(연도·페이지번호를 PBR로 오탐하는 것 차단).
_PBR_RE = re.compile(r"PBR[^0-9\n]{0,15}?(\d+(?:\.\d+)?)\s*배", re.IGNORECASE)
_PERIOD_RE = re.compile(r"(20\d{2})\s*년?\s*[~\-–∼]\s*(20\d{2})")
# 1.10: 백틱/따옴표 표식이 붙은 2자리 연도 범위(실샘플 `24~`30년) → 20xx 확장.
# 표식·'년' 필수(24~26개월 같은 비연도 오탐 방지).
_PERIOD2_RE = re.compile(r"[`'‘’]\s*(\d{2})\s*[~\-–∼]\s*[`'‘’]?\s*(\d{2})\s*년")
_BUYBACK_RE = re.compile(r"(자기주식|자사주)[^\n]{0,15}?(취득|매입|소각)")
# 부정·과거(계획 아님) 문맥 → False 판정.
_BUYBACK_NEG_RE = re.compile(r"(없음|없이|아니|않|미실시|미계획|계획\s*없|완료|기실시)")


class DartDocumentError(DartAdapterError):
    """문서(document.xml) 다운로드/해제 실패 — 종목 전체가 아니라 그 문서만 격리."""


def _safe_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _parse_date(yyyymmdd: str | None) -> str | None:
    """YYYYMMDD → ISO YYYY-MM-DD. strptime으로 엄격 검증, 무효면 None(적재 제외용)."""
    s = (yyyymmdd or "").strip()
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return datetime.strptime(s, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _strip_tags(s: str) -> str:
    """DART 전용 XML 마크업 태그 제거. 태그 자리를 **개행으로 치환**해 셀/문단 경계를 보존한다
    (라벨과 인접 지표 값이 한 줄로 뭉쳐 오탐되는 것 방지)."""
    text = re.sub(r"<[^>]+>", "\n", s)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)  # 공백류만 축약(개행은 유지)
    text = re.sub(r"\n[ \t]*", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _zip_to_text(content: bytes) -> str:
    """document.xml ZIP → 평문. 비ZIP/빈/추출실패는 DartDocumentError(성공값과 구분).

    텍스트 멤버(.xml/.html/.txt)만, 사이즈 상한으로 읽는다(바이너리 오탐·zip-bomb 방어).
    """
    if not content:
        raise DartDocumentError("빈 문서 응답")
    if len(content) > _MAX_ZIP_BYTES:
        raise DartDocumentError("문서 ZIP 크기 상한 초과")
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        # 비ZIP = DART 오류 HTML/XML 응답 → 실패로 격리(빈 원문으로 오인 금지)
        raise DartDocumentError("ZIP 아님(오류 응답 가능)") from None
    parts: list[str] = []
    with zf:
        for info in zf.infolist():
            if not info.filename.lower().endswith(_TEXT_EXTS):
                continue
            if info.file_size > _MAX_MEMBER_BYTES:
                continue
            parts.append(_decode(zf.read(info)))
    text = _strip_tags("\n".join(parts))
    if not text:
        raise DartDocumentError("문서에서 텍스트 추출 실패")
    return text


def parse_targets(raw_text: str | None) -> dict[str, Any]:
    """유효 문서 원문에서 목표 필드 best-effort 추출. 못 찾으면 해당 필드 None.

    보수적: 애매하면 null(틀린 non-null 값 금지). 값 뒤 p(포인트)·단위없는 PBR·범위이상·부정 자사주 배제.
    """
    text = raw_text or ""

    def _num(rx: re.Pattern[str]) -> float | None:
        m = rx.search(text)
        return float(m.group(1)) if m else None

    def _num_with_arrow(arrow_rx: re.Pattern[str], plain_rx: re.Pattern[str]) -> float | None:
        """화살표 체인(현재→목표)이 있으면 우변(목표), 없으면 기존 첫 매칭(1.10 F3/G2)."""
        am = arrow_rx.search(text)
        if am:
            return float(am.group(2))
        return _num(plain_rx)

    pbr = _num(_PBR_RE)
    if pbr is not None and not (0 < pbr <= _PBR_MAX):
        pbr = None  # 연도·비현실적 값 배제

    period_start = period_end = None
    pm = _PERIOD_RE.search(text)
    if pm and int(pm.group(1)) <= int(pm.group(2)):  # start<=end만 인정
        period_start, period_end = pm.group(1), pm.group(2)
    else:  # 1.10: 백틱 2자리 연도(`24~`30년) 폴백 → 20xx 확장
        pm2 = _PERIOD2_RE.search(text)
        if pm2:
            start, end = f"20{pm2.group(1)}", f"20{pm2.group(2)}"
            if int(start) <= int(end):
                period_start, period_end = start, end

    buyback: bool | None = None
    bm = _BUYBACK_RE.search(text)
    if bm:
        window = text[max(0, bm.start() - 10) : bm.end() + 15]
        buyback = False if _BUYBACK_NEG_RE.search(window) else True

    return {
        "target_roe": _num_with_arrow(_ROE_ARROW_RE, _ROE_RE),
        "target_payout_ratio": _num_with_arrow(_PAYOUT_ARROW_RE, _PAYOUT_RE),
        "target_pbr": pbr,
        "period_start": period_start,
        "period_end": period_end,
        "buyback_planned": buyback,
    }


class DartValueupAdapter(SourceAdapter):
    source = "dart"

    def __init__(self) -> None:
        self._session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        self._session.mount("https://", HTTPAdapter(max_retries=retry))
        self._limiter = _RateLimiter(_MIN_INTERVAL)

    # ── fetch (라이브, 키 필요) ──
    def fetch(self, corp_code: str, bgn_de: str, end_de: str) -> dict[str, Any]:
        key = settings.dart_api_key.get_secret_value()
        if not key:
            raise DartAdapterError(
                "DART_API_KEY가 설정되지 않았습니다. .env에 DART_API_KEY를 넣으세요."
            )
        plans: list[dict[str, Any]] = []
        failed: list[tuple[str | None, str]] = []
        page_no = 1
        while page_no <= _MAX_PAGES:
            try:
                data = self._get_json(
                    "list.json",
                    {
                        "crtfc_key": key,
                        "corp_code": corp_code,
                        "bgn_de": bgn_de,
                        "end_de": end_de,
                        "page_no": page_no,
                        "page_count": 100,
                    },
                    allow_no_data=True,
                )
            except DartAdapterError as e:
                # 후반 페이지 실패 시 이미 모은 plan은 보존하고 중단(부분결과 보존)
                failed.append((f"list.json#p{page_no}", type(e).__name__))
                break
            for item in data.get("list") or []:
                report_nm = str(item.get("report_nm") or "")
                if not _is_plan_report(report_nm):  # 1.10: 이행현황·철회 제외(F9)
                    continue
                disclosure_date = _parse_date(item.get("rcept_dt"))
                rcept_no = item.get("rcept_no")
                if disclosure_date is None:
                    failed.append((rcept_no, "무효 rcept_dt"))
                    continue
                if not rcept_no:
                    failed.append((None, "rcept_no 없음"))
                    continue
                try:
                    raw_text = self._fetch_document(key, rcept_no)  # 문서별 격리
                except DartDocumentError as e:
                    failed.append((rcept_no, type(e).__name__))
                    continue
                plans.append(
                    {
                        "disclosure_date": disclosure_date,
                        "report_nm": report_nm,
                        "raw_text": raw_text,
                    }
                )
            total_page = _safe_int(data.get("total_page"), 1)
            if page_no >= total_page:
                break
            page_no += 1
        return {"corp_code": corp_code, "plans": plans, "failed": failed}

    def _get_json(
        self, endpoint: str, params: Mapping[str, Any], allow_no_data: bool = False
    ) -> dict[str, Any]:
        """list.json 등 JSON 엔드포인트. dart.py `_get`과 동일한 status 처리. 키 미노출."""
        self._limiter.acquire()
        try:
            resp = self._session.get(
                f"{_BASE}/{endpoint}", params=params, timeout=_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            raise DartAdapterError(
                f"DART 요청 실패: endpoint={endpoint} ({type(e).__name__})"
            ) from None
        status = data.get("status")
        if status == "000":
            return data
        if allow_no_data and status == "013":  # 조회된 데이터 없음
            return {"list": []}
        raise DartAdapterError(
            f"DART API 오류: endpoint={endpoint}, status={status}, "
            f"msg={data.get('message')}"
        )

    def _fetch_document(self, key: str, rcept_no: str) -> str:
        """document.xml(ZIP 바이너리) 다운로드 → 평문. 실패는 DartDocumentError로 격리."""
        self._limiter.acquire()
        try:
            resp = self._session.get(
                f"{_BASE}/document.xml",
                params={"crtfc_key": key, "rcept_no": rcept_no},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            content = resp.content  # 바이너리(ZIP) — resp.json 금지
        except requests.RequestException as e:
            raise DartDocumentError(
                f"문서 다운로드 실패 ({type(e).__name__})"
            ) from None
        return _zip_to_text(content)  # 비ZIP/빈/추출실패 → DartDocumentError

    # ── normalize (순수, 테스트 가능) ──
    def normalize(self, raw: Mapping[str, Any]) -> list[dict[str, Any]]:
        corp_code = raw["corp_code"]
        recs: list[dict[str, Any]] = []
        for plan in raw.get("plans", []):
            rec: dict[str, Any] = {
                "corp_code": corp_code,
                "disclosure_date": plan["disclosure_date"],
                "raw_text": plan.get("raw_text"),
            }
            rec.update(parse_targets(plan.get("raw_text")))
            recs.append(rec)
        return recs

    # ── upsert (멱등, 유효 문서 기반 전체 교체) ──
    def upsert(self, session: Session, records: Sequence[dict[str, Any]]) -> int:
        for rec in records:
            upsert_valueup_plan(session, rec)
        session.flush()
        return len(records)
```

## Story 2-7 · 2-3 공유 코드

### `app/analysis/mna_engine.py` (전체, verbatim)

```python
"""M&A Target Score 엔진 (writer = 이 모듈, AD-10).

2.1(gap_engine, 종목별 독립 계산)과 다른 아키텍처: **cross-sectional 백분위** — 한 종목의
점수가 전체 모집단 분포에 의존한다. 따라서 (1) 전체 모집단을 배치로 먼저 구성하고,
(2) 그 안에서 각 종목의 백분위를 계산하는 2단계 구조. 산식은 scoring.md M&A 섹션 참조.

null 규칙(엄격, 리드 결정 2026-07-10): 요소의 서브지표가 하나라도 null이면 요소 점수 null,
요소가 하나라도 null이면 mna_target_score null — "일부만 알면서 평균 내서 숫자 만들기" 금지
(2.1 execution_score와 동일 원칙, NFR2 "null > 틀린 값").

grouping seam(리드 결정, finance 스코프 분리): 백분위 모집단은 `_build_populations`의
`group_of` 콜러블이 결정한다. v1 = 전체시장 단일 그룹. 후속 2-7이 `company.sector` 기반
peer-group으로 갈아끼울 이음새 — 백분위 계산부는 population 출처를 모른다.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from sqlalchemy.orm import Session

from app.analysis.gap_engine import _validate_as_of  # as_of 검증 재사용(중복 정의 금지)
from app.config import settings
from app.repositories import mna_score as repo

# 전체시장 그룹키(폴백·sector 미상 종목용)
_WHOLE_MARKET = "_all"


def _sector_bucket(sector: str | None) -> str | None:
    """DART induty_code → KSIC 2자리 버킷(2.7 택소노미 v1 — 수작업 매핑 없이 결정적).

    2자리 미만·비숫자는 None(분류 불가 → market 모집단, 값을 만들지 않음).
    """
    if not sector:
        return None
    prefix = str(sector).strip()[:2]
    return prefix if len(prefix) == 2 and prefix.isdigit() else None

# (지표명, 방향) — 요소별 서브지표 정의. low=낮을수록 좋음, high=높을수록 좋음.
_VALUATION_INDICATORS = (("ev_ebitda", "low"), ("pbr", "low"))
_CAPACITY_INDICATORS = (("debt_ratio", "low"), ("net_cash", "high"), ("ebitda_margin", "high"))
_OWNERSHIP_INDICATORS = (("largest_shareholder_pct", "low"), ("treasury_stock_pct", "high"))


def _percentile_rank(value: float | None, population: Sequence[float | None]) -> float | None:
    """population 내 value의 백분위(0~1), **mid-rank** — (below + (equal-1)/2) / (N-1).

    동점을 최하위에 몰지 않고 구간 중앙에 배치(코드리뷰 2026-07-10 High): min-rank였다면
    전원 동일값에서 전원 rank 0 → pct_low 1.0("모두 똑같은데 최고점") — 기준금리처럼 장기
    동결되는 시계열에서 실제로 발생. mid-rank는 전원 동일 → 0.5(중립), 고유 최솟값 0·최댓값 1.
    NaN/Inf는 대상값·모집단 모두 배제(비교 연산 왜곡 방지, 리뷰 Med). 유효 peer<2 → None.
    """
    if value is None or not math.isfinite(value):
        return None
    pop = [v for v in population if v is not None and math.isfinite(v)]
    if len(pop) < 2:
        return None
    below = sum(1 for v in pop if v < value)
    equal = sum(1 for v in pop if v == value)
    return (below + max(equal - 1, 0) / 2) / (len(pop) - 1)


def _pct_rank_low(value: float | None, population: Sequence[float | None]) -> float | None:
    """낮을수록 좋은 지표(EV/EBITDA·PBR·부채비율·최대주주지분율·기준금리) → 역백분위."""
    rank = _percentile_rank(value, population)
    return None if rank is None else 1.0 - rank


def _pct_rank_high(value: float | None, population: Sequence[float | None]) -> float | None:
    """높을수록 좋은 지표(순현금·EBITDA마진·자사주비중) → 백분위 그대로."""
    return _percentile_rank(value, population)


def _avg_scores(*scores: float | None) -> float | None:
    """서브지표 점수 평균. 하나라도 None이면 전체 None(엄격, 리드 결정 — 결측이 잦은
    지표가 은근히 가중치를 왜곡하는 '있는 것만 평균' 부작용 방지)."""
    if any(s is None for s in scores):
        return None
    return sum(scores) / len(scores)


def _mna_target_score(
    valuation: float | None,
    capacity: float | None,
    ownership: float | None,
    macro: float | None,
    w_valuation: float,
    w_capacity: float,
    w_ownership: float,
    w_macro: float,
) -> float | None:
    """가중합 0~100. 요소 하나라도 None이면 전체 None(NFR2)."""
    if valuation is None or capacity is None or ownership is None or macro is None:
        return None
    return 100 * (
        w_valuation * valuation
        + w_capacity * capacity
        + w_ownership * ownership
        + w_macro * macro
    )


def _build_populations(
    rows: Mapping[str, Mapping[str, Any]],
    group_of: Callable[[str], str],
) -> dict[str, dict[str, list[float]]]:
    """corp별 지표 dict → 그룹별·지표별 population(유효값 리스트).

    grouping seam: `group_of(corp_code) -> 그룹키`. v1은 상수(전체시장), 2-7에서
    sector 버킷으로 교체. 백분위 계산부는 이 함수가 준 population만 소비한다.
    """
    pops: dict[str, dict[str, list[float]]] = {}
    for corp_code, indicators in rows.items():
        group = group_of(corp_code)
        bucket = pops.setdefault(group, {})
        for name, value in indicators.items():
            if value is not None:
                bucket.setdefault(name, []).append(value)
    return pops


def _factor_score(
    indicators: tuple[tuple[str, str], ...],
    corp_row: Mapping[str, Any] | None,
    population: Mapping[str, list[float]],
) -> float | None:
    """요소 점수 = 서브지표 백분위들의 평균(엄격 null). corp 데이터 자체가 없으면 None."""
    if corp_row is None:
        return None
    scores: list[float | None] = []
    for name, direction in indicators:
        value = corp_row.get(name)
        pop = population.get(name, [])
        rank = _pct_rank_low(value, pop) if direction == "low" else _pct_rank_high(value, pop)
        scores.append(rank)
    return _avg_scores(*scores)


def run(
    session: Session, as_of: str, corp_codes: Sequence[str] | None = None
) -> int:
    """as_of 기준 corp별 mna_score를 계산·upsert. 적재 행 수 반환.

    - 백분위 모집단은 corp_codes 부분집합과 무관하게 **전체 시장**(all_latest_* 배치 결과)
      기준 — 부분 실행이어도 순위 기준이 흔들리면 안 된다.
    - 종목별 3요소(valuation/capacity/ownership)가 전부 None이면 행을 만들지 않는다
      (macro는 전 종목 공통이라 그것만으론 종목별 정보가 없음 — all-null 행 방지, 1-6 교훈).
      기존 행이 있으면 정리(2.1 reconciliation 패턴). 단, **metrics·ownership이 통째로
      비면**(업스트림 수집 장애/ETL 중간 상태 가능성) 오삭제를 막기 위해 계산·삭제 모두
      스킵하고 0을 반환한다(코드리뷰 2026-07-10 Med 가드).
    - **부분 실행 주의(문서화된 한계, 리뷰 High)**: corp_codes 부분집합 실행은 대상 종목만
      최신 모집단 기준으로 갱신하고 나머지 행은 과거 모집단 점수로 남긴다 — 같은 as_of
      테이블 안에 서로 다른 population snapshot이 섞일 수 있다. **게시용 점수는 반드시
      전체 실행(corp_codes=None)으로 재계산**할 것. 부분 실행은 테스트/디버깅 용도.
    """
    _validate_as_of(as_of)
    if corp_codes is None:
        corp_codes = repo.list_all_corp_codes(session)

    # 1단계: 전체 모집단 배치 구성(cross-sectional — corp 루프 전에 끝나야 함)
    metrics = repo.all_latest_metrics(session, as_of)
    ownership = repo.all_latest_ownership(session, as_of)
    if not metrics and not ownership:
        return 0  # 입력 전무 — 업스트림 장애 가능성, reconciliation 오삭제 방어
    current_rate, rate_history = repo.latest_macro_percentile_basis(session, as_of)
    sectors = repo.all_company_sectors(session)

    # 시장 모집단(폴백·sector 미상·ownership용) + sector 버킷 모집단(2.7, valuation·capacity용)
    market_pops = _build_populations(metrics, group_of=lambda c: _WHOLE_MARKET)
    sector_pops = _build_populations(
        metrics, group_of=lambda c: _sector_bucket(sectors.get(c)) or _WHOLE_MARKET
    )
    # 버킷별 peer 수(해당 버킷에서 metrics 행을 가진 종목 수) — 폴백 판정용
    bucket_sizes: dict[str, int] = {}
    for c in metrics:
        b = _sector_bucket(sectors.get(c))
        if b is not None:
            bucket_sizes[b] = bucket_sizes.get(b, 0) + 1
    # ownership은 업종 무관(절대적 취약성 신호, epics 2.7 AC) — 시장 모집단 유지
    owner_pops = _build_populations(ownership, group_of=lambda c: _WHOLE_MARKET)
    # macro_score: 종목 무관, as_of당 1회(낮은 금리 = 차입인수 유리 → 역백분위)
    macro_score = _pct_rank_low(current_rate, rate_history)

    count = 0
    for corp_code in corp_codes:
        bucket = _sector_bucket(sectors.get(corp_code))
        if bucket is None:
            pop, basis = market_pops.get(_WHOLE_MARKET, {}), "market"
        elif bucket_sizes.get(bucket, 0) >= settings.mna_peer_min:
            pop, basis = sector_pops.get(bucket, {}), f"sector:{bucket}"
        else:  # 버킷 peer 미달 → 시장 폴백(small-N 노이즈 방어)
            pop, basis = market_pops.get(_WHOLE_MARKET, {}), "market_fallback"

        valuation = _factor_score(_VALUATION_INDICATORS, metrics.get(corp_code), pop)
        capacity = _factor_score(_CAPACITY_INDICATORS, metrics.get(corp_code), pop)
        owner = _factor_score(
            _OWNERSHIP_INDICATORS, ownership.get(corp_code),
            owner_pops.get(_WHOLE_MARKET, {}),
        )
        if valuation is None and capacity is None and owner is None:
            repo.delete_mna_score(session, corp_code, as_of)  # 근거 없는 기존 행 정리
            continue

        total = _mna_target_score(
            valuation, capacity, owner, macro_score,
            settings.mna_w_valuation, settings.mna_w_capacity,
            settings.mna_w_ownership, settings.mna_w_macro,
        )
        repo.upsert_mna_score(
            session,
            {
                "corp_code": corp_code,
                "as_of": as_of,
                "mna_target_score": total,
                "valuation_score": valuation,
                "capacity_score": capacity,
                "ownership_score": owner,
                "macro_score": macro_score,
                "population_basis": basis,
            },
        )
        count += 1

    session.flush()
    return count
```

### `app/repositories/mna_score.py` (전체, verbatim)

```python
"""mna_score 배치 입력 조회 + 멱등 upsert 저장소 (AD-2: SQL은 여기서만).

mna_engine(app/analysis/mna_engine.py)의 유일한 DB 접근 지점. 2.1(gap_engine, 종목별 단건
조회)과 달리 **cross-sectional 백분위**라 전체 모집단을 배치로 한 번에 가져온다 — 종목 루프
안에서 단건 쿼리하면 N+1이자 설계 오류(한 종목의 점수가 전체 분포에 의존).

look-ahead 부분차단은 2.1(valueup_score.py)과 동일 규칙: 같은 연도의 사업보고서(quarter=4)는
그 해 안에 공시될 수 없으므로(통상 다음해 3월) 배제 — `year<yr OR (year=yr AND quarter<4)`.
1~3분기 동일연도 시차는 공통 defer(deferred-work.md 2-1 섹션).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Company, MacroIndicator, MnaScore, Ownership


def list_all_corp_codes(session: Session) -> list[str]:
    """전 종목 corp_code 목록(run()의 corp_codes 기본값)."""
    return list(session.scalars(select(Company.corp_code)).all())


def all_company_sectors(session: Session) -> dict[str, str | None]:
    """전 종목 corp_code → sector(DART induty_code). 2.7 버킷 택소노미 입력."""
    rows = session.execute(select(Company.corp_code, Company.sector)).all()
    return {code: sector for code, sector in rows}


def all_latest_metrics(session: Session, as_of: str) -> dict[str, dict[str, Any]]:
    """전 종목의 as_of 시점 최신 (year,quarter) valuation_metrics 행(배치).

    corp_code → {ev_ebitda, pbr, debt_ratio, net_cash, ebitda_margin}.
    look-ahead 배제 후 corp별 최신 1행을 Python에서 선택(정렬된 결과 첫 등장 유지 —
    SQLite/PostgreSQL 양쪽에서 동일 동작, 데이터 규모상 충분).
    """
    as_of_year = int(as_of[:4])
    rows = session.execute(
        text(
            "SELECT corp_code, ev_ebitda, pbr, debt_ratio, net_cash, ebitda_margin "
            "FROM valuation_metrics "
            "WHERE year < :yr OR (year = :yr AND quarter < 4) "
            "ORDER BY corp_code, year DESC, quarter DESC"
        ),
        {"yr": as_of_year},
    ).mappings().all()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = row["corp_code"]
        if code not in latest:  # 정렬상 corp별 첫 행 = 최신
            latest[code] = {
                "ev_ebitda": row["ev_ebitda"],
                "pbr": row["pbr"],
                "debt_ratio": row["debt_ratio"],
                "net_cash": row["net_cash"],
                "ebitda_margin": row["ebitda_margin"],
            }
    return latest


def all_latest_ownership(session: Session, as_of: str) -> dict[str, dict[str, Any]]:
    """전 종목의 as_of 이전(포함) 최신 ownership 행(배치).

    corp_code → {largest_shareholder_pct, treasury_stock_pct}.
    as_of 근사치(비12월 결산 라벨오류)는 1-6 known-limitation 그대로.
    """
    stmt = (
        select(Ownership)
        .where(Ownership.as_of <= as_of)
        .order_by(Ownership.corp_code, Ownership.as_of.desc())
    )
    latest: dict[str, dict[str, Any]] = {}
    for obj in session.scalars(stmt):
        if obj.corp_code not in latest:
            latest[obj.corp_code] = {
                "largest_shareholder_pct": obj.largest_shareholder_pct,
                "treasury_stock_pct": obj.treasury_stock_pct,
            }
    return latest


def latest_macro_percentile_basis(
    session: Session, as_of: str, indicator: str = "base_rate"
) -> tuple[float | None, list[float]]:
    """(as_of 이전 최신 지표값, as_of 이전 전체 역사 시계열) — 매크로 백분위 기준.

    모집단 = as_of 이전 전체 관측값(리드 결정: 롤링 윈도우 아님, ECOS 수집 기간 길어지면
    후속 재검토). as_of 이후 관측은 look-ahead라 제외.
    """
    stmt = (
        select(MacroIndicator)
        .where(MacroIndicator.indicator == indicator, MacroIndicator.date <= as_of)
        .order_by(MacroIndicator.date.desc())
    )
    objs = list(session.scalars(stmt))
    # 현재값 = 최신 '관측 행'의 값(null이면 null 그대로 — 과거 non-null로 몰래 대체 금지,
    # 코드리뷰 2026-07-10 High: AC6 엄격 null 위반이었음). history 정제와 현재값 선택은 분리.
    current = objs[0].value if objs else None
    history = [o.value for o in objs if o.value is not None]
    return current, history


def upsert_mna_score(session: Session, rec: dict[str, Any]) -> MnaScore:
    """(corp_code, as_of) 자연키 기준 mna_score upsert.

    2.1 upsert_valueup_score와 동일 정책: 권위 있는 전체 재계산 결과이므로 null 포함 전체
    교체 + `rec[field]` 직접 인덱싱(키 누락은 프로그래밍 오류 → KeyError로 즉시 노출).
    """
    stmt = select(MnaScore).where(
        MnaScore.corp_code == rec["corp_code"], MnaScore.as_of == rec["as_of"],
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        obj = MnaScore(corp_code=rec["corp_code"], as_of=rec["as_of"])
        session.add(obj)
    for field in (
        "mna_target_score", "valuation_score", "capacity_score",
        "ownership_score", "macro_score", "population_basis",
    ):
        setattr(obj, field, rec[field])
    return obj


def delete_mna_score(session: Session, corp_code: str, as_of: str) -> None:
    """근거(입력 데이터)를 잃은 (corp_code, as_of)의 오래된 score 정리(2.1 reconciliation
    패턴). 없으면 no-op(멱등)."""
    stmt = select(MnaScore).where(
        MnaScore.corp_code == corp_code, MnaScore.as_of == as_of,
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is not None:
        session.delete(obj)
```

### `app/config.py` — 임계치·가중치(mna_peer_min 포함) (verbatim 발췌)

```python
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
    # sector peer 버킷 최소 종목 수(2.7) — 미달 버킷은 전체시장 폴백(small-N 노이즈 방어)
    mna_peer_min: int = Field(5, ge=2)
```

### `alembic/versions/0010_mna_population_basis.py` (전체, verbatim)

```python
"""mna_score.population_basis (2.7 sector peer-group)

Revision ID: 0010_mna_population_basis
Revises: 0009_mna_score
Create Date: 2026-07-13
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_mna_population_basis"
down_revision: str | None = "0009_mna_score"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mna_score", sa.Column("population_basis", sa.String(length=20)))


def downgrade() -> None:
    op.drop_column("mna_score", "population_basis")
```

## Story 2-4 · 2-1 공유 코드

### `app/analysis/gap_engine.py` (전체, verbatim)

```python
"""Value-up 갭 스코어링 엔진 (writer = 이 모듈, AD-4).

Epic 1(수집)과 다른 새 패턴: HTTP 어댑터가 아니라 **순수 계산**. 입력은 이미 DB에 있다
(valuation_metrics 뷰 + valueup_plan + financials.buyback_*). 산식은 scoring.md 참조.

null 전파가 핵심 계약(2026-07-10 코드리뷰로 scoring.md 강화): 입력이 애매/누락이면
0이나 False로 강제하지 않고 해당 스코어도 null로 전파한다(NFR2 "null > 틀린 값").
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date

from sqlalchemy.orm import Session

from app.config import settings
from app.repositories import valueup_score as repo

_AS_OF_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_as_of(as_of: str) -> None:
    """as_of가 zero-padded YYYY-MM-DD **이자 달력상 유효**한지 fail-fast.

    정규식만으론 2025-02-30이 통과(코드리뷰 2026-07-10 Med) — 세 입력원(metrics 연도,
    ownership·macro 문자열 비교)이 무효 날짜를 서로 다르게 해석하는 것을 진입점에서 차단.
    gap_engine·mna_engine 공용(중복 정의 금지).
    """
    if not _AS_OF_RE.match(as_of):
        raise ValueError(f"as_of는 YYYY-MM-DD 형식이어야 합니다: {as_of!r}")
    try:
        date.fromisoformat(as_of)
    except ValueError:
        raise ValueError(f"as_of가 달력상 유효한 날짜가 아닙니다: {as_of!r}") from None


def _safe_ratio(actual: float | None, target: float | None) -> float | None:
    """target이 없거나 0 이하면 계산 불가(0 나눗셈·역설 방어) → None."""
    if actual is None or target is None or target <= 0:
        return None
    return actual / target


def _progress_rate(
    period_start: str | None, period_end: str | None, as_of_year: int
) -> float | None:
    """계획기간(연도 문자열) 대비 진척률, [0,1] 클램프. 연 단위 정밀도만(입력이 연도뿐)."""
    if period_start is None or period_end is None:
        return None
    try:
        start, end = int(period_start), int(period_end)
    except (TypeError, ValueError):
        return None
    if end <= start:
        return None
    raw = (as_of_year - start) / (end - start)
    return max(0.0, min(1.0, raw))


def _achievement_rate(actual_roe: float | None, target_roe: float | None) -> float | None:
    """achievement_rate = 실제 ROE / 목표 ROE. ROE 단독(배당은 execution_score에서 별도 가중,
    이중반영 방지 — 2026-07-10 리드 결정). target_pbr은 산식 미사용."""
    return _safe_ratio(actual_roe, target_roe)


def _buyback_signals(
    amount: int | None, retired_amount: int | None
) -> tuple[bool | None, bool | None, str]:
    """(buyback_executed, buyback_retired, buyback_status). 수량 null=unknown, 0=확정 없음.

    음수는 수량 도메인에 없음(1.8 `_parse_quantity`가 상류에서 이미 걸러 DB엔 안 들어오지만,
    이 함수는 DB 값을 그대로 믿지 않고 자체 방어— 코드리뷰 High, GPT). 음수도 unknown 취급.
    """
    executed = None if amount is None or amount < 0 else amount > 0
    retired = None if retired_amount is None or retired_amount < 0 else retired_amount > 0
    if executed is None or retired is None:
        status = "unknown"
    elif retired:
        status = "retired"
    elif executed:
        status = "purchased_only"
    else:
        status = "none"
    return executed, retired, status


def _execution_score(
    achievement_rate: float | None,
    buyback_executed: bool | None,
    actual_payout: float | None,
    target_payout: float | None,
    w_achievement: float,
    w_buyback: float,
    w_payout: float,
) -> float | None:
    """execution_score = 100*clamp(w_a*min(achv,1) + w_b*(executed?1:0) + w_p*min(payout,1)).

    세 항 중 하나라도 계산 불가면 0으로 메우지 않고 전체 null(AC5).
    """
    payout_ratio = _safe_ratio(actual_payout, target_payout)
    if achievement_rate is None or buyback_executed is None or payout_ratio is None:
        return None
    raw = (
        w_achievement * min(achievement_rate, 1.0)
        + w_buyback * (1.0 if buyback_executed else 0.0)
        + w_payout * min(payout_ratio, 1.0)
    )
    return 100 * max(0.0, min(1.0, raw))


def _washing_flag(
    progress_rate: float | None,
    achievement_rate: float | None,
    buyback_planned: bool | None,
    buyback_retired: bool | None,
    progress_min: float,
    achievement_max: float,
) -> bool | None:
    """3치(Kleene) AND. 네 항 중 하나라도 **확정 False**면 나머지가 unknown이어도 전체 False
    (예: 소각이 확정 이뤄졌으면[buyback_retired=True] 진척률을 몰라도 워싱 아님이 확정된다).
    확정 False가 없고 하나라도 None이면 None(판단 불가). 전부 확정 True면 True.

    (코드리뷰 2026-07-10 Med, GPT) 이전엔 "하나라도 None→전체 None"이라 과잉보수적이었다
    — false positive는 없었지만 확정 가능한 케이스까지 불필요하게 '판단 불가'로 만들었다.
    scoring.md·AC6도 이 3치 논리로 함께 갱신(2026-07-10).
    """
    terms = (
        None if progress_rate is None else progress_rate >= progress_min,
        None if achievement_rate is None else achievement_rate < achievement_max,
        buyback_planned,
        None if buyback_retired is None else not buyback_retired,
    )
    if any(term is False for term in terms):
        return False
    if any(term is None for term in terms):
        return None
    return True


def run(
    session: Session, as_of: str, corp_codes: Sequence[str] | None = None
) -> int:
    """as_of 기준으로 corp별 valueup_score를 계산·upsert. 적재 행 수 반환.

    valueup_plan이 없는 종목은 목표가 없어 갭을 정의할 수 없으므로 행을 만들지 않는다
    (1-6 no-data 교훈과 동일 원칙). 이전에 plan이 있어 score가 생성됐다가 이후 plan이
    삭제/정정된 경우, 근거를 잃은 기존 score도 함께 정리한다(코드리뷰 High, GPT: gap_engine이
    valueup_score의 유일 writer(AD-4)이므로 정합성 유지 책임도 이 모듈에 있음).

    as_of는 YYYY-MM-DD 형식만 허용(fail-fast) — 비표준 포맷은 disclosure_date와의 문자열
    비교(사전식)를 실제 날짜 비교와 어긋나게 만들 수 있다(코드리뷰 High, GPT).
    """
    _validate_as_of(as_of)
    if corp_codes is None:
        corp_codes = repo.list_all_corp_codes(session)
    as_of_year = int(as_of[:4])

    count = 0
    for corp_code in corp_codes:
        plan = repo.latest_valueup_plan(session, corp_code, as_of)
        if plan is None:
            repo.delete_valueup_score(session, corp_code, as_of)
            continue

        metrics = repo.latest_metrics(session, corp_code, as_of)
        buyback = repo.latest_financial_buyback(session, corp_code, as_of)
        actual_roe = metrics.get("roe") if metrics else None
        actual_payout = metrics.get("payout_ratio") if metrics else None
        amount = buyback.get("buyback_amount") if buyback else None
        retired_amount = buyback.get("buyback_retired_amount") if buyback else None

        progress_rate = _progress_rate(plan["period_start"], plan["period_end"], as_of_year)
        # AC3: 계획기간이 무효(null·end<=start)면 achievement_rate도 계산하지 않고 null로
        # 명시한다(코드리뷰 High, GPT — 이전 구현은 progress_rate만 null이 되고 achievement_rate는
        # 별개로 계산돼 AC3를 위반했다). execution_score는 achievement_rate가 None이면 이미 null.
        achievement_rate = (
            None if progress_rate is None
            else _achievement_rate(actual_roe, plan["target_roe"])
        )
        executed, retired, status = _buyback_signals(amount, retired_amount)
        execution_score = _execution_score(
            achievement_rate, executed, actual_payout, plan["target_payout_ratio"],
            settings.score_w_achievement, settings.score_w_buyback, settings.score_w_payout,
        )
        washing_flag = _washing_flag(
            progress_rate, achievement_rate, plan["buyback_planned"], retired,
            settings.washing_progress_min, settings.washing_achievement_max,
        )

        # 목표·실제·갭 동결(2.4 표시용): 엔진이 고른 값 그대로 저장(AC3 게이팅과 무관한 원값)
        target_roe = plan["target_roe"]
        roe_gap = (
            actual_roe - target_roe
            if actual_roe is not None and target_roe is not None
            else None
        )
        repo.upsert_valueup_score(
            session,
            {
                "corp_code": corp_code,
                "as_of": as_of,
                "target_roe": target_roe,
                "actual_roe": actual_roe,
                "roe_gap": roe_gap,
                "achievement_rate": achievement_rate,
                "progress_rate": progress_rate,
                "execution_score": execution_score,
                "washing_flag": washing_flag,
                "buyback_executed": executed,
                "buyback_retired": retired,
                "buyback_status": status,
            },
        )
        count += 1

    session.flush()
    return count
```

### `app/repositories/valueup_score.py` (전체, verbatim)

```python
"""valueup_score 입력 조회 + 멱등 upsert 저장소 (AD-2: SQL은 여기서만).

gap_engine(app/analysis/gap_engine.py)의 유일한 DB 접근 지점. 세 가지 읽기(공시 목표·
실적 지표·자사주 원천)와 한 가지 쓰기(스코어 upsert)로 구성. gap_engine 자체는 dict/스칼라만
다루고 SQL을 직접 실행하지 않는다(AD-2).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session

from app.models import Company, Financial, ValueupPlan, ValueupScore


def list_all_corp_codes(session: Session) -> list[str]:
    """전 종목 corp_code 목록(run()의 corp_codes 기본값). SQL은 여기서만(AD-2)."""
    return list(session.scalars(select(Company.corp_code)).all())


def latest_valueup_plan(
    session: Session, corp_code: str, as_of: str
) -> dict[str, Any] | None:
    """as_of 이전(포함) 최신 valueup_plan 1건. 여러 공시 중 as_of 직전 최신 것을 target으로 채택
    (2026-07-10 리드 결정 A: 기간-포함 판정 대신 단순·재현 가능한 규칙).

    동일 disclosure_date(원공시+정정공시 등) tie-break은 plan_id 내림차순(코드리뷰 Med,
    GPT) — 접수번호 등 진짜 우선순위 필드가 없어 "나중에 적재된 것"을 결정적으로 채택.
    """
    stmt = (
        select(ValueupPlan)
        .where(
            ValueupPlan.corp_code == corp_code,
            ValueupPlan.disclosure_date <= as_of,
        )
        .order_by(ValueupPlan.disclosure_date.desc(), ValueupPlan.plan_id.desc())
        .limit(1)
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        return None
    return {
        "target_roe": obj.target_roe,
        "target_payout_ratio": obj.target_payout_ratio,
        "target_pbr": obj.target_pbr,  # 계산 미사용, 참고 보관만(리드 결정)
        "period_start": obj.period_start,
        "period_end": obj.period_end,
        "buyback_planned": obj.buyback_planned,
    }


def latest_metrics(session: Session, corp_code: str, as_of: str) -> dict[str, Any] | None:
    """as_of 이전 최신 (year,quarter) valuation_metrics 행. look-ahead 부분 차단(코드리뷰 High,
    GPT): 같은 연도의 **사업보고서(quarter=4)는 그 해 안에 공시될 수 없음**(결산 후 통상 90일
    이내 = 다음 해)이므로 무조건 제외 — `year<as_of_year OR (year=as_of_year AND quarter<4)`.
    1~3분기 보고서의 동일연도 내 공시시차는 실제 공시일 데이터가 없어 잔여 리스크로 defer
    (deferred-work.md 2-1 섹션). AD-1: 뷰가 계산한 값을 읽기만.
    """
    as_of_year = int(as_of[:4])
    row = session.execute(
        text(
            "SELECT roe, payout_ratio FROM valuation_metrics "
            "WHERE corp_code = :cc AND (year < :yr OR (year = :yr AND quarter < 4)) "
            "ORDER BY year DESC, quarter DESC LIMIT 1"
        ),
        {"cc": corp_code, "yr": as_of_year},
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


def latest_financial_buyback(
    session: Session, corp_code: str, as_of: str
) -> dict[str, Any] | None:
    """as_of 이전 최신 (year,quarter) financials의 buyback 수량 필드.
    look-ahead 부분 차단은 latest_metrics와 동일 규칙(사업보고서 동일연도 제외)."""
    as_of_year = int(as_of[:4])
    stmt = (
        select(Financial)
        .where(
            Financial.corp_code == corp_code,
            or_(
                Financial.year < as_of_year,
                and_(Financial.year == as_of_year, Financial.quarter < 4),
            ),
        )
        .order_by(Financial.year.desc(), Financial.quarter.desc())
        .limit(1)
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        return None
    return {
        "buyback_amount": obj.buyback_amount,
        "buyback_retired_amount": obj.buyback_retired_amount,
    }


def upsert_valueup_score(session: Session, rec: dict[str, Any]) -> ValueupScore:
    """(corp_code, as_of) 자연키 기준 valueup_score upsert(AD-7 확장 패턴).

    gap_engine 산출값은 항상 그 as_of의 '권위 있는 재계산 결과'이므로 null 포함 전체
    교체한다(valueup_plan upsert와 동일 원칙 — 재계산 시 과거 오탐이 null로 정정되게).
    `rec[field]`(직접 인덱싱, 코드리뷰 Med, GPT): 키 누락은 프로그래밍 오류이므로
    `.get()`으로 조용히 None 넘기지 않고 KeyError로 즉시 드러낸다.
    """
    stmt = select(ValueupScore).where(
        ValueupScore.corp_code == rec["corp_code"],
        ValueupScore.as_of == rec["as_of"],
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        obj = ValueupScore(corp_code=rec["corp_code"], as_of=rec["as_of"])
        session.add(obj)
    for field in (
        "target_roe", "actual_roe", "roe_gap",
        "achievement_rate", "progress_rate", "execution_score", "washing_flag",
        "buyback_executed", "buyback_retired", "buyback_status",
    ):
        setattr(obj, field, rec[field])
    return obj


def latest_as_of(session: Session) -> str | None:
    """valueup_score의 최신 as_of(기본 조회 기준일, 2.4). 없으면 None."""
    from sqlalchemy import func

    return session.scalar(select(func.max(ValueupScore.as_of)))


def list_scores(
    session: Session, filters: dict[str, Any], page: int, size: int
) -> tuple[list[dict[str, Any]], int]:
    """갭분석/워싱랭킹 서빙 조회(2.4). company 조인 + 필터 + execution_score 오름차순.

    null 정렬은 방언(SQLite NULLS FIRST/PG NULLS LAST 기본 차이)을 타지 않도록
    명시적 2단 키(`IS NULL` 우선순위 → 값)로 처리(1.7 defer 교훈). 동순위는 corp_code로
    안정 정렬(페이지네이션 결정성).
    """
    from sqlalchemy import func

    from app.models import Company

    conds = [ValueupScore.as_of == filters["as_of"]]
    if filters.get("market"):
        conds.append(Company.market == filters["market"])
    if filters.get("min_progress") is not None:
        conds.append(ValueupScore.progress_rate >= filters["min_progress"])
    if filters.get("washing_only"):
        conds.append(ValueupScore.washing_flag.is_(True))

    base = select(ValueupScore, Company).join(
        Company, Company.corp_code == ValueupScore.corp_code
    ).where(*conds)

    total = session.scalar(
        select(func.count()).select_from(base.subquery())
    ) or 0
    rows = session.execute(
        base.order_by(
            ValueupScore.execution_score.is_(None),  # null last(명시적)
            ValueupScore.execution_score.asc(),
            ValueupScore.corp_code.asc(),
        ).limit(size).offset((page - 1) * size)
    ).all()

    items = []
    for score, company in rows:
        items.append({
            "corp_code": score.corp_code,
            "corp_name": company.corp_name,
            "market": company.market,
            "as_of": score.as_of,
            "target_roe": score.target_roe,
            "actual_roe": score.actual_roe,
            "roe_gap": score.roe_gap,
            "achievement_rate": score.achievement_rate,
            "progress_rate": score.progress_rate,
            "execution_score": score.execution_score,
            "washing_flag": score.washing_flag,
            "buyback_status": score.buyback_status,
        })
    return items, total


def delete_valueup_score(session: Session, corp_code: str, as_of: str) -> None:
    """plan이 사라진 (corp_code, as_of)의 오래된 score를 정리(코드리뷰 High, GPT: 정합성
    reconciliation). gap_engine이 valueup_score의 유일 writer(AD-4)이므로 근거가 사라진
    행을 제거할 책임도 이 모듈에 있다. 없으면 no-op(멱등)."""
    stmt = select(ValueupScore).where(
        ValueupScore.corp_code == corp_code, ValueupScore.as_of == as_of,
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is not None:
        session.delete(obj)
```

### `app/services/valueup.py` (전체, verbatim)

```python
"""갭분석/워싱랭킹 유스케이스 (routers→services→repositories, AD-2)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.repositories import valueup_score as repo
from app.schemas import GapAnalysisOut, Page


def _resolve_as_of(session: Session, as_of: str | None) -> str | None:
    return as_of or repo.latest_as_of(session)


def gap_analysis(
    session: Session, filters: dict[str, Any], page: int, size: int
) -> Page[GapAnalysisOut]:
    filters["as_of"] = _resolve_as_of(session, filters.get("as_of"))
    if filters["as_of"] is None:  # 스코어 미적재 → 빈 봉투(500 아님)
        return Page(items=[], total=0, page=page, size=size)
    rows, total = repo.list_scores(session, filters, page, size)
    return Page(items=[GapAnalysisOut(**r) for r in rows], total=total, page=page, size=size)


def washing_ranking(
    session: Session, filters: dict[str, Any], page: int, size: int
) -> Page[GapAnalysisOut]:
    return gap_analysis(session, {**filters, "washing_only": True}, page, size)
```

### `app/routers/valueup.py` (전체, verbatim)

```python
"""/valueup 라우터 — 갭분석·워싱랭킹 (HTTP 경계, AD-2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import GapAnalysisOut, Page
from app.services import valueup as service

router = APIRouter(prefix="/valueup", tags=["valueup"])


@router.get(
    "/gap-analysis",
    response_model=Page[GapAnalysisOut],
    description=(
        "밸류업 계획 대비 이행 갭 분석. execution_score 오름차순(이행 나쁜 순), null last. "
        "washing_flag: true=워싱 의심 / false=근거 없음 / null=판단 불가(데이터 부족) — "
        "UI에서 null을 빈칸이나 '아니오'로 표시하지 말고 '판단 불가'로 표시할 것."
    ),
)
def gap_analysis(
    market: str | None = None,
    min_progress: float | None = Query(None, ge=0.0, le=1.0),
    as_of: str | None = Query(None, description="기준일(YYYY-MM-DD), 기본=최신"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[GapAnalysisOut]:
    filters = {"market": market, "min_progress": min_progress, "as_of": as_of}
    return service.gap_analysis(db, filters, page, size)


@router.get(
    "/washing-ranking",
    response_model=Page[GapAnalysisOut],
    description=(
        "워싱 의심(washing_flag=true) 종목만, execution_score 오름차순. "
        "판단 불가(null)·근거 없음(false)은 제외 — 전체는 /valueup/gap-analysis 사용."
    ),
)
def washing_ranking(
    market: str | None = None,
    min_progress: float | None = Query(None, ge=0.0, le=1.0),
    as_of: str | None = Query(None, description="기준일(YYYY-MM-DD), 기본=최신"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[GapAnalysisOut]:
    filters = {"market": market, "min_progress": min_progress, "as_of": as_of}
    return service.washing_ranking(db, filters, page, size)
```

### `app/schemas.py` — GapAnalysisOut (verbatim 발췌)

```python
class GapAnalysisOut(BaseModel):
    """valueup_score + company 조인 결과 (2.4 갭분석/워싱랭킹).

    washing_flag 계약: true=워싱 의심 / false=워싱 근거 없음 / **null=판단 불가**
    (입력 데이터 부족 — UI에서 빈칸이나 '아니오'로 표시 금지, "판단 불가"로 표시할 것).
    """

    corp_code: str
    corp_name: str | None = None
    market: str | None = None
    as_of: str
    target_roe: float | None = None
    actual_roe: float | None = None
    roe_gap: float | None = None
    achievement_rate: float | None = None
    progress_rate: float | None = None
    execution_score: float | None = None
    washing_flag: bool | None = None
    buyback_status: str | None = None
```

### `app/models.py` — ValueupScore·MnaScore (verbatim 발췌)

```python
class ValueupScore(Base):
    """Value-up 갭 스코어 (writer = gap_engine, AD-4). 자연키 (corp_code, as_of), AD-8.

    achievement_rate·progress_rate·execution_score·washing_flag는 계산 불가(입력 애매/누락)
    시 null(NFR2, "null > 틀린 값"). washing_flag는 특히 null을 False로 강제하지 않는다
    (null=판단불가, scoring.md 2026-07-10 강화). Boolean 컬럼 전부 nullable — null 전파 필수.
    """

    __tablename__ = "valueup_score"
    __table_args__ = (
        UniqueConstraint("corp_code", "as_of", name="uq_valueup_score_corp_asof"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    corp_code: Mapped[str] = mapped_column(
        String(8), ForeignKey("company.corp_code"), index=True
    )
    as_of: Mapped[str] = mapped_column(String(10))  # ISO YYYY-MM-DD (progress_rate의 today)
    # 목표·실제·갭(2.4 표시용, 엔진 계산 시점 동결 — 서빙 재계산 시 as_of 정합 깨짐 방지)
    target_roe: Mapped[float | None] = mapped_column(Float)
    actual_roe: Mapped[float | None] = mapped_column(Float)
    roe_gap: Mapped[float | None] = mapped_column(Float)  # actual − target(둘 다 있을 때만)
    achievement_rate: Mapped[float | None] = mapped_column(Float)  # actual_roe/target_roe
    progress_rate: Mapped[float | None] = mapped_column(Float)  # 연도 단위, [0,1] 클램프
    execution_score: Mapped[float | None] = mapped_column(Float)  # 0~100
    washing_flag: Mapped[bool | None] = mapped_column(Boolean)
    buyback_executed: Mapped[bool | None] = mapped_column(Boolean)
    buyback_retired: Mapped[bool | None] = mapped_column(Boolean)
    buyback_status: Mapped[str | None] = mapped_column(String(20))  # retired/purchased_only/none/unknown


class MnaScore(Base):
    """M&A Target Score (writer = mna_engine, AD-10). 자연키 (corp_code, as_of).

    cross-sectional 백분위(시장 내 상대 순위) 기반 — 요소 서브지표가 하나라도 null이면
    요소 점수 null, 요소가 하나라도 null이면 mna_target_score null(엄격, 리드 결정 2026-07-10).
    macro_score는 종목 무관 공통값(as_of당 1회 계산).
    """

    __tablename__ = "mna_score"
    __table_args__ = (
        UniqueConstraint("corp_code", "as_of", name="uq_mna_score_corp_asof"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    corp_code: Mapped[str] = mapped_column(
        String(8), ForeignKey("company.corp_code"), index=True
    )
    as_of: Mapped[str] = mapped_column(String(10))  # ISO YYYY-MM-DD
    mna_target_score: Mapped[float | None] = mapped_column(Float)  # 0~100
    valuation_score: Mapped[float | None] = mapped_column(Float)  # 0~1 (저평가)
    capacity_score: Mapped[float | None] = mapped_column(Float)  # 0~1 (인수여력)
    ownership_score: Mapped[float | None] = mapped_column(Float)  # 0~1 (지배구조 취약성)
    macro_score: Mapped[float | None] = mapped_column(Float)  # 0~1, 종목 무관 공통
    # 백분위 모집단 식별(2.7): sector:{KSIC2} / market_fallback(peer 미달) / market(sector 없음)
    population_basis: Mapped[str | None] = mapped_column(String(20))
```

### `alembic/versions/0011_valueup_score_gap_fields.py` (전체, verbatim)

```python
"""valueup_score target/actual/gap 동결 컬럼 (2.4 갭분석 API)

Revision ID: 0011_valueup_score_gap_fields
Revises: 0010_mna_population_basis
Create Date: 2026-07-13
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_valueup_score_gap_fields"
down_revision: str | None = "0010_mna_population_basis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("valueup_score", sa.Column("target_roe", sa.Float))
    op.add_column("valueup_score", sa.Column("actual_roe", sa.Float))
    op.add_column("valueup_score", sa.Column("roe_gap", sa.Float))


def downgrade() -> None:
    op.drop_column("valueup_score", "roe_gap")
    op.drop_column("valueup_score", "actual_roe")
    op.drop_column("valueup_score", "target_roe")
```

## 테스트 (신규 전체)

### `tests/test_valueup_api.py` (전체, verbatim)

```python
"""Story 2.4 — 갭분석/워싱랭킹 API 검증 (SQLite in-memory + TestClient)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Company, ValueupScore


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    return eng


def _seed(s: Session) -> None:
    for code, name, market in (
        ("00000001", "워싱의심", "KOSPI"),
        ("00000002", "이행양호", "KOSPI"),
        ("00000003", "판단불가", "KOSDAQ"),
        ("00000004", "점수없음", "KOSPI"),
    ):
        s.add(Company(corp_code=code, corp_name=name, market=market))
    s.add(ValueupScore(
        corp_code="00000001", as_of="2026-07-13",
        target_roe=10.0, actual_roe=3.0, roe_gap=-7.0,
        achievement_rate=0.3, progress_rate=0.8, execution_score=25.0,
        washing_flag=True, buyback_status="purchased_only",
    ))
    s.add(ValueupScore(
        corp_code="00000002", as_of="2026-07-13",
        target_roe=10.0, actual_roe=11.0, roe_gap=1.0,
        achievement_rate=1.1, progress_rate=0.8, execution_score=95.0,
        washing_flag=False, buyback_status="retired",
    ))
    s.add(ValueupScore(
        corp_code="00000003", as_of="2026-07-13",
        achievement_rate=None, progress_rate=0.2, execution_score=None,
        washing_flag=None, buyback_status="unknown",
    ))
    s.add(ValueupScore(  # 다른 as_of(과거) — 최신 기본 조회에서 제외돼야
        corp_code="00000004", as_of="2025-12-31",
        execution_score=10.0, washing_flag=False,
    ))
    s.commit()


@pytest.fixture()
def client(engine, monkeypatch):
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    return TestClient(fastapi_app)


def test_gap_analysis_envelope_and_order(client) -> None:
    """AC1/3: 봉투 + execution_score 오름차순(null last) + 기본 as_of=최신."""
    r = client.get("/valueup/gap-analysis")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "total", "page", "size"}
    assert body["total"] == 3  # 최신 as_of(2026-07-13)만, 과거 행 제외
    codes = [i["corp_code"] for i in body["items"]]
    # 25.0 → 95.0 → null(판단불가 마지막)
    assert codes == ["00000001", "00000002", "00000003"]
    # 목표·실제·갭 동결값 노출
    assert body["items"][0]["roe_gap"] == -7.0
    # washing null은 null 그대로(false 강제 금지)
    assert body["items"][2]["washing_flag"] is None


def test_washing_ranking_only_true(client) -> None:
    """AC2: washing_flag=true만 — 판단불가(null)·근거없음(false) 제외."""
    r = client.get("/valueup/washing-ranking")
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["corp_code"] == "00000001"
    assert body["items"][0]["washing_flag"] is True


def test_filters_market_and_min_progress(client) -> None:
    """AC3: market·min_progress 필터."""
    r = client.get("/valueup/gap-analysis", params={"market": "KOSDAQ"})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000003"]
    r2 = client.get("/valueup/gap-analysis", params={"min_progress": 0.5})
    assert {i["corp_code"] for i in r2.json()["items"]} == {"00000001", "00000002"}


def test_explicit_as_of(client) -> None:
    """AC3: as_of 명시 조회(과거 스냅샷)."""
    r = client.get("/valueup/gap-analysis", params={"as_of": "2025-12-31"})
    assert [i["corp_code"] for i in r.json()["items"]] == ["00000004"]


def test_empty_scores_returns_empty_envelope(engine, monkeypatch) -> None:
    """스코어 미적재 → 빈 봉투(500 아님)."""
    from fastapi.testclient import TestClient

    import app.db as db_module
    from app.main import app as fastapi_app

    Session_ = sessionmaker(bind=engine)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    r = TestClient(fastapi_app).get("/valueup/gap-analysis")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "page": 1, "size": 20}
```

### `tests/test_valueup_ingest.py` — 1.10 신규 테스트 (verbatim 발췌)

```python
# ── Story 1.10: 실샘플(리허설 79건) 기반 파서 튜닝 ──

def test_roe_gap_allows_parenthesized_qualifier() -> None:
    """실샘플: `ROE 목표(`24~`30년 평균) : 15%+ α` — 괄호 안 숫자 때문에 기존 gap 규칙 실패."""
    t = parse_targets("ROE 목표(`24~`30년 평균) : 15%+ α")
    assert t["target_roe"] == 15.0


def test_roe_alias_자기자본이익률() -> None:
    """실샘플 6건: 'ROE' 대신 '자기자본이익률' 표기."""
    assert parse_targets("자기자본이익률 12% 달성")["target_roe"] == 12.0


def test_arrow_takes_target_side_not_current() -> None:
    """1.5 defer F3/G2: '현재 → 목표'에서 우변(목표)을 채택. 실샘플: 1.8% → ... 8.3%."""
    t = parse_targets("ROE : 2024년말 1.8% → 2025년말 8.3%")
    assert t["target_roe"] == 8.3
    t2 = parse_targets("배당성향 20% → 30% 확대")
    assert t2["target_payout_ratio"] == 30.0


def test_arrow_absent_keeps_first_match() -> None:
    """화살표 없으면 기존 동작(첫 매칭) 유지 — 회귀 방지."""
    assert parse_targets("ROE 10% 이상")["target_roe"] == 10.0


def test_period_backtick_two_digit_years() -> None:
    """실샘플: `24~`30년 (백틱/따옴표 2자리 연도) → 2024~2030 확장."""
    t = parse_targets("ROE 목표(`24~`30년 평균) : 15%")
    assert t["period_start"] == "2024"
    assert t["period_end"] == "2030"
    t2 = parse_targets("'25~'27년 주주환원 계획")
    assert t2["period_start"] == "2025"
    assert t2["period_end"] == "2027"


def test_period_two_digit_requires_marker() -> None:
    """2자리 연도는 백틱/따옴표 표식 필수 — '24~26개월' 같은 비연도 오탐 방지."""
    t = parse_targets("향후 24~26개월 내 실행")
    assert t["period_start"] is None


def test_report_nm_negative_filter() -> None:
    """1.5 defer F9: 이행현황·철회는 계획 아님 → 제외. 정정공시는 유지."""
    from app.ingest.dart_valueup import _is_plan_report

    assert _is_plan_report("기업가치 제고 계획") is True
    assert _is_plan_report("[기재정정]기업가치 제고 계획") is True
    assert _is_plan_report("기업가치 제고 계획 이행현황") is False
    assert _is_plan_report("기업가치 제고 계획 철회신고서") is False
    assert _is_plan_report("주요사항보고서") is False
```

### `tests/test_dart_ingest.py` — 1.9 신규 테스트 (verbatim 발췌)

```python
# ── Story 1.9: 배당총액 (alotMatter) ──

def test_dividend_total_scales_million_won() -> None:
    """AC2: '현금배당금총액(백만원)' 행 × 1,000,000 = KRW. 스케일 누락은 100만배 축소 오염."""
    from app.ingest.dart import _dividend_total

    rows = [
        {"se": "주당 현금배당금(원)", "stock_knd": "보통주", "thstrm": "361"},
        {"se": "현금배당금총액(백만원)", "thstrm": "2,452,153"},
        {"se": "현금배당성향(%)", "thstrm": "17.9"},
    ]
    assert _dividend_total(rows) == 2_452_153_000_000


def test_dividend_total_label_exact_match_only() -> None:
    """AC2: 라벨 정확일치(1-6 교훈) — 단위 미확인 변형은 값을 만들지 않고 null."""
    from app.ingest.dart import _dividend_total

    # 단위가 다른/없는 라벨 → 스케일을 확신할 수 없으므로 null
    assert _dividend_total([{"se": "현금배당금총액", "thstrm": "100"}]) is None
    assert _dividend_total([{"se": "현금배당금총액(억원)", "thstrm": "100"}]) is None
    # 주당배당금·성향만 있는 경우 → null
    assert _dividend_total([{"se": "주당 현금배당금(원)", "thstrm": "361"}]) is None


def test_dividend_total_none_and_negative_guard() -> None:
    """AC2/AC3: 미공시([])·미상(None)·파싱불가('-')·음수(도메인 밖) 전부 null."""
    from app.ingest.dart import _dividend_total

    assert _dividend_total([]) is None
    assert _dividend_total(None) is None
    assert _dividend_total([{"se": "현금배당금총액(백만원)", "thstrm": "-"}]) is None
    assert _dividend_total([{"se": "현금배당금총액(백만원)", "thstrm": "(500)"}]) is None


def test_dividend_total_zero_is_zero() -> None:
    """공시했으나 배당 0 → 확정 0(null 아님) — 1.8 null vs 0 구분과 동일 계약."""
    from app.ingest.dart import _dividend_total

    assert _dividend_total([{"se": "현금배당금총액(백만원)", "thstrm": "0"}]) == 0


def test_normalize_fills_dividend_from_rows() -> None:
    """AC2: normalize가 period['dividend_rows']에서 dividend_total을 채운다(fixture=2조)."""
    company, fins = DartAdapter().normalize(DART_RAW_SAMSUNG)
    assert fins[0]["dividend_total"] == 2_000_000_000_000
```

### `tests/test_mna_engine.py` — 2.7 순수 테스트 (verbatim 발췌)

```python
# ── Story 2.7: sector peer-group ──

def test_sector_bucket_two_digit_prefix() -> None:
    from app.analysis.mna_engine import _sector_bucket

    assert _sector_bucket("64191") == "64"  # 은행업
    assert _sector_bucket("26121") == "26"  # 반도체
    assert _sector_bucket(None) is None
    assert _sector_bucket("") is None
    assert _sector_bucket("A1") is None  # 숫자 아님 → 분류 불가(값 안 만듦)
```

### `tests/test_mna_engine.py` — 2.7 통합 테스트 (verbatim 발췌)

```python
def test_run_sector_peer_percentile_and_fallback(engine) -> None:
    """2.7 AC1/3/4: peer 충분한 버킷은 업종 내 백분위, 미달 버킷은 시장 폴백, basis 저장.

    mna_peer_min=2로 낮춰 반도체 버킷(2종목)은 sector, 단독 버킷(1종목)은 폴백을 검증.
    """
    from app.config import settings as cfg

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        # 반도체(26) 2종목: 시총 1000 vs 9000 — 시장 전체가 아니라 '둘 사이' 백분위여야 함
        _seed_corp(s, "00000001", market_cap=1000)
        _seed_corp(s, "00000002", market_cap=9000)
        # 유통(47) 1종목: 버킷 peer 1 < min → 시장 폴백
        _seed_corp(s, "00000003", market_cap=3000)
        s.commit()
        from app.models import Company as _C
        for code, sec in (("00000001", "26121"), ("00000002", "26299"), ("00000003", "47111")):
            s.get(_C, code).sector = sec
        _seed_macro(s)
        s.commit()

        import pytest as _pytest
        orig = cfg.mna_peer_min
        try:
            cfg.mna_peer_min = 2
            run(s, as_of="2025-12-31")
            s.commit()
        finally:
            cfg.mna_peer_min = orig

        rows = {r.corp_code: r for r in s.scalars(select(MnaScore)).all()}
        # 반도체 버킷 내 상대화: 1번(저평가)=1.0, 2번(고평가)=0.0
        assert rows["00000001"].valuation_score == _pytest.approx(1.0)
        assert rows["00000002"].valuation_score == _pytest.approx(0.0)
        assert rows["00000001"].population_basis == "sector:26"
        assert rows["00000002"].population_basis == "sector:26"
        # 유통 1종목: 버킷 미달 → 시장(3종목) 폴백 — 시총 3000은 시장 중간
        assert rows["00000003"].population_basis == "market_fallback"
        assert rows["00000003"].valuation_score == _pytest.approx(0.5)
        # ownership은 업종 무관(시장 모집단) 유지 — basis와 무관하게 계산됨
        assert rows["00000001"].ownership_score is not None


def test_run_sector_null_uses_market_basis(engine) -> None:
    """2.7 AC5: sector 없는 종목은 market basis(정직 분류)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_corp(s, "00000001", market_cap=1000)  # _seed_corp은 sector 미지정
        _seed_corp(s, "00000002", market_cap=9000)
        _seed_macro(s)
        s.commit()
        run(s, as_of="2025-12-31")
        s.commit()
        rows = s.scalars(select(MnaScore)).all()
        assert all(r.population_basis == "market" for r in rows)
```


## 출력 형식
`[High/Med/Low] 스토리 파일:라인 — 문제 — 근거/재현 — 제안수정`. 위 4개 질문에 명시적으로 답해줘. 없으면 "clean".
