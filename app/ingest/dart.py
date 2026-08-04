"""DART(전자공시) 소스 어댑터 — company·financials의 writer (AD-3).

OpenDART REST API(requests)를 사용한다:
  - company.json          : 기업개황(회사명·종목코드·시장구분·업종)
  - fnlttSinglAcntAll.json : 단일회사 전체 재무제표(계정명→금액)

프로덕션 하드닝: 재시도/백오프, rate-limit(100/min), 키 redaction, connect/read timeout 분리.
fetch: REST 호출(키 필요). normalize: 계정명 매핑(순수, 테스트 가능). upsert: 멱등 적재.
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)
from app.repositories.financials import upsert_company, upsert_financial

_BASE = "https://opendart.fss.or.kr/api"
_TIMEOUT = (3.05, 20)  # (connect, read)
_MIN_INTERVAL = 0.65  # 100 req/min 여유(초당 <2)

_MARKET = {"Y": "KOSPI", "K": "KOSDAQ", "N": "KONEX", "E": "기타"}
_REPRT_QUARTER = {"11013": 1, "11012": 2, "11014": 3, "11011": 4}
_YEAR_RE = re.compile(r"^\d{4}$")

# 단일 값 계정(첫 매칭). 총차입금은 별도 합산 규칙 사용.
_ACCOUNT_MAP: dict[str, tuple[str, ...]] = {
    "revenue": ("매출액", "수익(매출액)", "영업수익", "ifrs-full_Revenue"),
    "net_income": ("당기순이익", "당기순이익(손실)", "분기순이익"),
    "operating_income": ("영업이익", "영업이익(손실)"),
    "depreciation": ("감가상각비", "유형자산감가상각비"),
    "equity": ("자본총계", "ifrs-full_Equity"),
    "total_assets": ("자산총계", "ifrs-full_Assets"),
    "total_liabilities": ("부채총계", "ifrs-full_Liabilities"),
    "cash": ("현금및현금성자산", "ifrs-full_CashAndCashEquivalents",
             "dart_CashAndCashEquivalentsAtEndOfPeriodCf"),
}
# 총차입금(이자성 부채) = 아래 라벨에 매칭되는 '모든 행'의 합.
# 회사마다 라벨이 다르고(삼성: 단기/장기차입금·사채, 하이닉스: 차입금),
# 같은 라벨이 유동/비유동에 중복 등장하므로 dedup이 아니라 전체 합산해야 한다.
_DEBT_LABELS = (
    "차입금", "단기차입금", "장기차입금", "유동성장기부채", "사채", "리스부채",
    # [2026-08-04] total_debt 결측 33개사 전수 조사에서 나온 '차입 명시' 라벨 변형.
    # 이름에 차입/사채/리스가 명시된 것만 추가한다 — '유동금융부채'·'기타금융부채' 같은
    # 총액·잡동사니 라벨은 차입 아닌 항목(미지급금·보증금 등)이 섞여 있어 넣지 않는다
    # (한전 '유동금융부채' 44조를 차입금으로 적재하면 과대계상 — null 유지가 NFR2).
    "차입금및사채",            # 현대엘리베이터('차입금 및 사채' 공백 변형 포함 — _norm 비교)
    "유동차입금및사채", "비유동차입금및비유동사채",  # 한화시스템
    "유동차입금", "비유동차입금",  # SBS
    "차입부채", "유동차입부채", "비유동차입부채",  # 세아제강·세아제강지주(메리츠형)
    "유동성리스부채", "비유동리스부채", "장기리스부채", "단기리스부채",  # 삼영전자·사조씨푸드
)

# [2026-07-31] 총차입금 커버리지 67.5% → 개선. 라벨 완전일치만으로는 대부분을 놓쳤다.
#
# 실측(라이브 DART): 현대모비스의 차입 계정은 "유동 차입금 및 비유동차입금(사채 포함)의
# 유동성 대체 부분 합계"·"비유동성리스부채"처럼 회사마다 문구가 다르고, 메리츠금융지주는
# "차입부채" 하나뿐이다. 위 6개 완전일치로는 셋 다 못 잡는다.
#
# 그렇다고 "차입"을 부분일치로 잡으면 **틀린 값**이 나온다 — 같은 응답에 "장기차입금의
# 상환"·"차입금의 순증감" 같은 **현금흐름표 항목**(잔액이 아니라 유출입)이 섞여 있다.
# 그래서 (1) 재무상태표(sj_div='BS')로 한정하고 (2) IFRS 표준 태그로 매칭한다.
# 표준계정코드를 안 쓰는 회사(삼성전자 '단기차입금')를 위해 기존 라벨 완전일치를 남긴다.
_DEBT_ACCOUNT_IDS = frozenset({
    "ifrs-full_Borrowings",
    "ifrs-full_ShorttermBorrowings",
    "ifrs-full_LongtermBorrowings",
    "ifrs-full_CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings",
    "ifrs-full_CurrentLeaseLiabilities",
    "ifrs-full_NoncurrentLeaseLiabilities",
    "ifrs-full_BondsIssued",
    "ifrs-full_NoncurrentPortionOfNoncurrentBondsIssued",
    "ifrs-full_NoncurrentPortionOfNoncurrentLoansReceived",
    # [2026-08-04] 33개사 전수 조사에서 실측된 차입 명시 태그(한국특강·SBS·삼영전자).
    "ifrs-full_CurrentPortionOfLongtermBorrowings",
    "dart_LongTermBorrowingsGross",
    "dart_CurentPortionOfFinanceLeaseLiabilities",  # (DART 원문 오타 그대로: Curent)
    "dart_NonCurrentFinanceLeaseLiabilities",
})


# [2026-08-03] revenue 커버리지(P1-6a): 라벨('매출액'·'영업수익')만으로는 '매출'(LG CNS·
# 한일홀딩스 등)·'총 수익'(롯데이노베이트)을 놓쳤다 — 6개사 실측 전부 ifrs-full_Revenue
# 총계 행은 있었다. total_debt와 같은 처방: IFRS 표준 태그 매칭. 단, **손익계산서(IS/CIS)로
# 한정**한다 — 하위 태그(RevenueFromConstructionContracts 등)는 여기 없으므로 총계만 잡히고,
# sj_div 게이트가 다른 재무제표의 동계열 행 오염을 차단한다. 라벨 완전일치가 항상 우선
# (_ACCOUNT_MAP 튜플 순서 = _pick 우선순위).
_TAGGED_SINGLE_ACCOUNTS: dict[str, tuple[str, ...]] = {
    "ifrs-full_Revenue": ("IS", "CIS"),
    # 한섬: 계정명이 '자본 총계'(공백) — 완전일치 실패, 태그로 구제. BS 한정.
    "ifrs-full_Equity": ("BS",),
    # [2026-08-03] total_liabilities 결측 16행(12개사)의 정체도 같았다: 총계 행은 있는데
    # 라벨이 '자산 총계'(공백)·'총자산'·'자산'으로 갈린다(LG화학·LG생활건강·한화솔루션·
    # 코오롱인더 등). 부채도 같은 방식으로 갈린다('부채 총계'·'총부채'·'부채').
    # 표준 태그는 BS 총계 행에만 붙으므로 BS 한정이면 하위 항목 오염이 없다.
    "ifrs-full_Assets": ("BS",),
    "ifrs-full_Liabilities": ("BS",),
    # [2026-08-04] cash 결측 45행이 두 계열이었다(백로그 "15"는 낡은 수).
    # ①비금융 2행: BS 라벨이 '현금 및 현금성자산'(공백) — 위와 같은 라벨 갈림, BS 태그로 구제.
    # ②금융 43행(증권·은행·보험·카드·지주): BS에 이 개념이 없고 '현금및예치금'
    #   (dart_CashAndDuefromBanks)뿐인데 그건 예치금 포함이라 다른 개념이다(대신증권
    #   예치금 2.41조 vs 진짜 현금 1.27조 — 대입하면 2배 과대). 대신 **현금흐름표의
    #   '기말 현금및현금성자산'**이 표본 8/8에서 이 태그로 실재 — 연간보고서의 기말
    #   잔액은 BS가 보여줄 그 수치다. 단 같은 태그가 '기초' 행에 붙으면 전년 현금이
    #   올해로 적재되는 1년 오프바이원이라, CF에서는 이름 가드('기말')를 추가로 요구한다
    #   (_collect_accounts의 _CF_NAME_GUARDS).
    "ifrs-full_CashAndCashEquivalents": ("BS", "CF"),
    # 신영증권형: 기말 행에 이쪽 태그를 쓴다 — 태그 이름 자체가 기말이라 가드 불요.
    "dart_CashAndCashEquivalentsAtEndOfPeriodCf": ("CF",),
}

# CF에서 태그를 주입할 때 계정명에 반드시 있어야 하는 문자열(태그만으로 모호한 경우).
# '기말'은 '당기말'·'분기말'·'기말의'를 전부 포함하고 '기초'를 배제한다(실측 8곳 검증).
_CF_NAME_GUARDS: dict[str, str] = {
    "ifrs-full_CashAndCashEquivalents": "기말",
}


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
        accounts, total_debt, buyback_krw, used_fs_div = self._fetch_accounts(
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
                    rows = bb.get("list")
                    if rows is None:
                        rows = []
                    # `or []`는 falsy dict/str도 미공시로 세탁하므로 금지(일괄리뷰 Med)
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
                rows = dv.get("list")
                if rows is None:
                    rows = []
                # `or []`는 falsy dict/str도 미공시로 세탁하므로 금지(일괄리뷰 Med)
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
                    "buyback_amount_krw": buyback_krw,
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
    ) -> tuple[dict[str, int], int | None, int | None, str | None]:
        """(단일값 계정 dict, 총차입금 합, 자사주 취득액, 사용한 fs_div) 반환."""
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
                accounts = _collect_accounts(rows)
                # 총차입금은 dedup 전 '모든 행'에서 합산(중복 라벨·유동/비유동 포함)
                total_debt = _sum_debt(rows)
                # 자사주 취득액도 같은 응답의 현금흐름표에서 나온다(별도 호출 없음)
                buyback_krw = _buyback_amount_krw(rows)
                return accounts, total_debt, buyback_krw, div
        return {}, None, None, None

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
            # total_debt는 fetch에서 '모든 차입 행' 합산(중복 라벨 포함)해 넘겨받음.
            # 정합성 게이트(2026-07-31): 총차입금이 총부채를 넘으면 합계·소계를 이중으로
            # 더했을 가능성이 크다(ifrs-full_Borrowings 총계와 개별 항목이 함께 오는 경우).
            # 그때는 **틀린 값 대신 null**을 남긴다 — 이 프로젝트의 NFR2("null > 틀린 값").
            rec["total_debt"] = period.get("total_debt")
            liabilities = rec.get("total_liabilities")
            if (
                rec["total_debt"] is not None
                and liabilities is not None
                and rec["total_debt"] > liabilities
            ):
                logger.warning(
                    "총차입금(%s) > 총부채(%s) — 이중 합산 의심으로 null 처리 corp_code=%s %s",
                    rec["total_debt"], liabilities, corp_code, period.get("year"),
                )
                rec["total_debt"] = None
            # 배당총액(1.9): alotMatter 행에서 집계(백만원→KRW 스케일). rows None/[] → null.
            rec["dividend_total"] = _dividend_total(period.get("dividend_rows"))
            # 자사주 취득/소각 신호(1.8): tesstkAcqsDspsSttus 행에서 집계(수량, 액 아님).
            # buyback_rows None(미상/실패)·[](표 자체가 안 옴) → (None, None) 기존값 보존.
            # 행이 오면 수치가 전무해도 0(활동 없음)으로 확정한다(2026-07-31).
            rec["buyback_amount"], rec["buyback_retired_amount"] = _buyback_totals(
                period.get("buyback_rows")
            )
            # 자사주 취득 '금액'(KRW) — 수량과 다른 열·다른 원천(현금흐름표).
            # 취득 **수량이 0으로 확정**됐는데 CF에 취득 행이 없다면, 그건 결측이 아니라
            # 금액도 0이다(같은 사건을 두 표가 같은 말로 말하고 있다). 반대로 수량이
            # 0보다 큰데 금액 행을 못 찾으면 **null** — 매입은 했는데 액수를 모른다.
            # (실측: 수량>0인 40곳 표본 중 36곳에서 CF 취득 행을 찾았다.)
            krw = period.get("buyback_amount_krw")
            if krw is None and rec["buyback_amount"] == 0:
                krw = 0
            rec["buyback_amount_krw"] = krw
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


def _collect_accounts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """응답 rows → 계정명(첫 등장) 딕셔너리 + 화이트리스트된 표준 태그 키 주입.

    태그 키는 라벨 미스 시 _pick의 폴백 경로다(_ACCOUNT_MAP 튜플 순서가 우선순위).
    sj_div 게이트로 다른 재무제표의 동계열 행을 차단하되, sj_div가 아예 없는
    응답(구형·테스트 픽스처)은 게이트를 적용하지 않는다(_sum_debt와 동일 원칙).
    """
    accounts: dict[str, int] = {}
    for row in rows:
        name = row.get("account_nm", "")
        val = _parse_amount(row.get("thstrm_amount"))
        if val is None:
            continue
        if name not in accounts:
            accounts[name] = val
        aid = row.get("account_id") or ""
        allowed_sj = _TAGGED_SINGLE_ACCOUNTS.get(aid)
        sj = row.get("sj_div")
        if (
            allowed_sj is not None
            and (not sj or sj in allowed_sj)
            and aid not in accounts
        ):
            # CF 이름 가드: 같은 태그가 기초/기말 양쪽에 붙을 수 있는 표에서는
            # 이름이 그 행의 정체를 말한다(기말 잔액만 당기 값이다).
            guard = _CF_NAME_GUARDS.get(aid)
            if sj == "CF" and guard is not None and guard not in _norm_label(name):
                continue
            accounts[aid] = val
    return accounts


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


# 배당 사실의 표 내부 반증 재료(2026-08-04). 총액 칸이 '-'일 때 "정말 안 준 것"인지
# "총액 칸만 빈 것"인지를 가르는 같은 표의 다른 행들 — 하나라도 양수면 배당은 있었다.
# 주식배당은 현금이 아니므로 넣지 않는다.
_DIVIDEND_EVIDENCE_LABELS = (
    "주당현금배당금(원)",
    "현금배당수익률(%)",
    "(연결)현금배당성향(%)",
    "(별도)현금배당성향(%)",
)


def _parse_ratio(raw: Any) -> float | None:
    """소수점 있는 표 값('3.10')을 float으로. _parse_amount는 정수 전용이라 별도.

    반증 판정 전용이므로 부호·소수만 보면 된다. 실패는 None(반증 못 함).
    """
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "").replace(" ", "")
    if s in ("", "-", "△", "-"):
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    if s and s[0] in "△-−":
        neg, s = True, s[1:]
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def _dividend_total(rows: Sequence[Any] | None) -> int | None:
    """alotMatter 행 → 현금배당금총액(KRW). 라벨 정확일치 + 명시 스케일만.

    rows None(미상/실패)·[](미공시) → null(기존값 보존). 파싱값 0은 확정 0(배당 없음).
    코드리뷰(2026-07-13) 반영:
    - 비-Mapping 행은 건너뜀(malformed 행이 AttributeError로 재무 적재 전체를 죽이지 않게).
    - 동일 라벨 다중 후보는 **전원 일치할 때만** 확정 — 상충값·음수 혼입은 오염 신호 → null.

    [2026-08-04] 결측 19곳(흑자)의 원문을 열어 두 형태를 확인하고 각각 규칙을 세웠다.

    ① **18곳: 총액 칸이 `-`** — 표도 행도 왔는데 당기 칸만 비었다. 자사주 잔고와 같은 계열로,
       미공시가 아니라 **당기 무배당(0)**이다. 실측한 4곳 모두 주당배당금·배당수익률·배당성향까지
       전 행이 `-`였다(전기엔 값이 있는 곳도 있다 — 배당 중단이지 미공시가 아니다).
       다만 이번에는 **반증 재료가 표 안에 있다**: 주당현금배당금이나 배당수익률이 양수면
       배당은 했는데 총액 칸만 빈 것이므로 0이 아니라 **null**(모른다)이다. 그래서 게이트를
       DB가 아니라 이 순수 함수 안에서 닫는다(자사주는 재무 대조가 필요해 upsert로 갔었다).

    ② **1곳: 값 상충** — 25,026 vs 32,365였는데 `rcept_no`를 보니 **서로 다른 공시 두 벌**
       (2024-09-02 접수 · 2025-03-12 접수)이었다. 한 공시 안의 모순이 아니라 재공시다.
       → **최신 접수번호의 공시만 읽는다.** 한 공시 안에서 상충하면 그때는 기존대로 null.
    """
    if not rows:
        return None
    valid = [r for r in rows if isinstance(r, Mapping)]  # malformed 행 격리
    if not valid:
        return None
    # 재공시 분리: 같은 사업연도에 공시가 두 벌 이상이면 나중 것이 앞선 것을 대체한다.
    latest = max((str(r.get("rcept_no") or "") for r in valid), default="")
    scoped = [r for r in valid if str(r.get("rcept_no") or "") == latest]

    candidates: list[int | None] = []
    saw_total_row = False
    for row in scoped:
        scale = _DIVIDEND_TOTAL_LABELS.get(_norm_label(row.get("se")))
        if scale is None:
            continue
        saw_total_row = True
        v = _parse_amount(row.get("thstrm"))
        if v is None:
            continue
        candidates.append(v * scale if v >= 0 else None)  # 음수=오염 표식
    if candidates:
        if any(c is None for c in candidates):
            return None
        if len(set(candidates)) > 1:  # 한 공시 안의 상충 → 확정 금지(null > 틀린 값)
            return None
        return candidates[0]
    if not saw_total_row:
        return None  # 총액 행 자체가 없음 = 표가 그 말을 한 적이 없다
    # 총액 행은 있는데 값이 비었다 → 반증이 없을 때만 '배당 없음(0)'으로 확정
    for row in scoped:
        if _norm_label(row.get("se")) in _DIVIDEND_EVIDENCE_LABELS:
            ev = _parse_ratio(row.get("thstrm"))
            if ev is not None and ev > 0:
                return None  # 배당은 했다 — 총액만 모른다
    return 0


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
      4) [2026-07-31] 행은 정상인데 이 필드에 **수치가 하나도 없으면 0**(활동 없음).

    4)의 근거(라이브 대조): 삼성전자·기아·경농이 모두 **같은 18행 표**를 제출했고,
    차이는 수치 유무뿐이다(삼성 6행·기아 3행에 값, 경농 0행). DART 표에서 '-'는
    "그 기간에 해당 활동 없음"이지 미공시가 아니다. 이전엔 이를 None(미상)으로 두어
    **"약속하고 안 했다"가 "판단 불가"로 세탁**됐고, buyback을 약속한 종목의
    execution_score가 통째로 죽었다(실측 28건).
    표가 **아예 오지 않은 경우**(요청 실패·미제출)는 호출자가 rows=None/[]로 넘기므로
    여기 오지 않는다 — 그쪽은 계속 미상이다.
    """
    totals: list[tuple[str, int]] = []
    leaves: list[int] = []
    subtotal_seen = False
    field_present = False  # 이 필드 칼럼이 응답에 실제로 왔나('-'여도 온 것)
    for row in rows:
        if not isinstance(row, Mapping):  # 형태 이탈 요소(비dict) 방어
            continue
        if field in row:
            field_present = True
        v = _parse_quantity(row.get(field))
        if v is None:
            continue
        kind = _buyback_row_kind(row)
        if kind == "total":
            totals.append((_norm_label(row.get("stock_knd", "")), v))
        elif kind == "leaf":
            leaves.append(v)
        else:
            subtotal_seen = True
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
    if subtotal_seen:
        return None  # 소계만 있음 → 계층 불명, 합산 불가(기존 계약 유지)
    if field_present:
        return 0  # 칼럼은 왔는데 수치가 전무 → '활동 없음'이라는 사실
    return None  # 칼럼 자체가 없음 → 미상(응답 형태 이상·구버전)


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


# 자사주 취득 '금액'(KRW) 매칭 규칙 — 2026-08-04 파티 승인.
#
# 왜 이름이 권위인가: 오전의 자산·부채 총계는 라벨이 갈려서 **태그로 구제**했는데, 여기선
# 정반대다. 실측 40곳 표본에서 계정명이 '자기주식의 취득'(26)·'자기주식의 취득으로 인한
# 현금의 유출'(7)·'자기주식 취득'(2)·'자기주식 등의 취득'(1)로 갈리는 반면, 태그는
# dart_AcquisitionOfTreasuryShares·ifrs-full_PurchaseOfTreasuryShares·
# ifrs-full_PaymentsToAcquireOrRedeemEntitysShares·'-표준계정코드 미사용-'(4건)로 흩어지고,
# **계정명이 '자기주식의 취득'인데 태그가 처분(ProceedsFromSaleOrIssue...)인 행까지 있다.**
# → 열마다 권위가 다르다: 재무상태표 총계는 태그, 현금흐름 항목은 이름.
#
# 제외 라벨이 규칙의 절반이다. '취득' 부분일치만 하면 다음이 딸려 들어온다:
#   - '종속기업의 자기주식 취득' = 자회사 주식이지 우리 주주에게 간 돈이 아니다
#   - '자기주식의 소각 비용' = 소각 수수료이지 취득이 아니다
#   - '자기주식의 처분 및 발행 현금흐름' = 반대 방향
_BUYBACK_KRW_REQUIRED = ("자기주식", "자사주")
_BUYBACK_KRW_EXCLUDE = ("처분", "소각", "종속기업", "자회사", "관계기업")


def _buyback_amount_krw(rows: Sequence[Mapping[str, Any]]) -> int | None:
    """현금흐름표의 자사주 취득액(KRW). 없으면 None(수량 0 처리는 호출자 몫).

    부호는 크기로 읽는다 — 실측 표본에서 양수 32·음수 1로 회사마다 유출 표기 규약이
    갈렸다(같은 사건을 어떤 곳은 -136,699,000,000, 어떤 곳은 820,000,000,000으로 쓴다).
    sj_div 게이트는 CF 한정이되, sj_div가 없는 응답(구형·픽스처)엔 적용하지 않는다
    (_sum_debt·_collect_accounts와 동일 원칙).
    """
    total: int | None = None
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        sj = row.get("sj_div")
        if sj and sj != "CF":
            continue
        name = row.get("account_nm") or ""
        if not any(k in name for k in _BUYBACK_KRW_REQUIRED):
            continue
        if "취득" not in name:
            continue
        if any(k in name for k in _BUYBACK_KRW_EXCLUDE):
            continue
        v = _parse_amount(row.get("thstrm_amount"))
        if v is None:
            continue
        total = abs(v) if total is None else total + abs(v)
    return total


def _sum_debt(rows: Sequence[Mapping[str, Any]]) -> int | None:
    """총차입금 = **재무상태표**의 차입 계정 합(유동/비유동·리스·사채 포함). 없으면 None.

    dedup dict가 아니라 원본 rows에서 계산 — 같은 '차입금'이 유동/비유동에 각각
    등장하는 경우(하이닉스 등)를 모두 합산한다.

    매칭은 두 경로다(2026-07-31):
      1) IFRS 표준 태그(account_id) — 회사마다 다른 한글 문구에 흔들리지 않는다.
      2) 한글 라벨 완전일치 — 표준계정코드를 쓰지 않는 회사(삼성전자 '단기차입금')용.

    **sj_div='BS'로 한정하는 것이 이 함수의 안전장치다.** 같은 응답에 "장기차입금의 상환"
    같은 현금흐름 항목이 있어, 걸러내지 않으면 잔액에 유출입을 더한 틀린 값이 나온다.
    sj_div가 아예 없는 응답(구형·테스트 픽스처)은 필터를 적용하지 않는다 — 필터가 데이터를
    통째로 날려 기존 동작을 깨뜨리는 쪽이 더 나쁘다.
    """
    has_sj_div = any(row.get("sj_div") for row in rows)
    total = 0
    found = False
    for row in rows:
        if has_sj_div and row.get("sj_div") != "BS":
            continue
        # 라벨은 공백 제거 후 비교(2026-08-04) — '차입금 및 사채'(한국특강)가 공백 때문에
        # '차입금및사채'를 비껴갔다. _norm_label은 정확일치 원칙을 바꾸지 않는다(1.6 교훈).
        matched = (
            row.get("account_id") in _DEBT_ACCOUNT_IDS
            or _norm_label(row.get("account_nm", "")) in _DEBT_LABELS
        )
        if not matched:
            continue
        v = _parse_amount(row.get("thstrm_amount"))
        if v is not None:
            total += v
            found = True
    return total if found else None
