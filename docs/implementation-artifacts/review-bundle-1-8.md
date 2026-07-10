# 코드 리뷰 요청 — 밸류업 워싱 스크리너 Story 1.8 (자기주식 취득/소각 수집, DART tesstkAcqsDspsSttus)

너는 엄격한(adversarial) 시니어 코드 리뷰어야. 아래 스토리/AC, 아키텍처 제약, **변경 코드(verbatim, 축약 없음)**를 보고
버그·규약 위반·엣지케이스·집계 정확성·데이터 의미 문제를 찾아줘.
출력: `[High/Med/Low] 파일:라인 — 문제 — 근거/재현 — 제안수정`. 칭찬 생략, 없으면 "clean".

**이번 핵심 = 외부 API 수량 집계의 정확성 + 데이터 의미(수량을 '액' 필드에 저장) + AD-3 단일 writer**라 특히:
- `_buyback_totals` 집계 정확성: 요약행(총계/소계/합계) 제외 leaf 합산 vs 폴백, 이중집계·데이터손실 경계
- **수량을 `buyback_amount`/`buyback_retired_amount`(BigInteger, 원래 의미 '액')에 저장**하는 설계의 타당성/위험(다운스트림 `>0`로만 소비 주장 검증)
- 미공시(None) vs 활동0(정수 0) 구분이 실제로 성립하는지(`_parse_amount("-")`→None, `"0"`→0 의존)
- `change_qy_incnr`(소각 수량)가 washing_flag `NOT buyback_retired`의 근거로 충분한지(부호·기간·누적 이슈)
- AD-3: financials 단일 writer 유지 위해 별도 어댑터 대신 `DartAdapter.fetch` 확장 — 적절한가
- fetch가 buyback을 재무 period에만 부착(`if accounts:`)하는 경계, `include_buyback` 게이팅
- 키 미노출·`_get` ValueError 포착(T5)·rate-limit(요청 3건으로 증가)

## 스토리 & AC (verbatim)

- As a 애널리스트, DART 자기주식 취득·처분 현황(`tesstkAcqsDspsSttus`)의 취득·소각 신호가 `financials`에 채워지는 것 — 워싱 판정(2.2 `NOT buyback_retired`)·실행점수(2.1) 자사주 신호를 실데이터로.
- **배경**: 1-2 재무제표엔 자사주 라인이 없어 `buyback_amount`·`buyback_retired_amount`가 구조적 100% null이었다(fetch가 그 키를 만든 적 없음). 2.1/2.2가 이 필드에 의존 → 데이터 없이 엔진 붙이면 워싱 항이 조용한 상수.
- **AC1**: `DartAdapter`(financials 유일 writer, AD-3)가 fetch 시 `tesstkAcqsDspsSttus.json`도 호출(별도 어댑터 신설 금지).
- **AC2**: normalize가 해당 period의 `buyback_amount`(취득=`change_qy_acqs` 합)·`buyback_retired_amount`(소각=`change_qy_incnr` 합)를 채운다.
- **AC3**: `acqs_mth1/2/3`에 총계/소계/합계 요약행이 섞일 수 있음 → 요약행 제외 leaf만 합산(이중집계 방지). 애매하면 null.
- **AC4**: 미공시(status 013/빈 응답)→null(기존값 보존), 공시+활동0→정수 0, 행은 있으나 전부 파싱실패→null(NFR2 "null>틀린값").
- **AC5**: 자연키 `(corp_code, year, quarter)` 멱등 upsert, buyback 필드 갱신·타 재무필드 보존(`upsert_financial` None-safe 재사용).
- **AC6**: `DART_API_KEY` 미설정 시 키/URL 미노출 `DartAdapterError`.
- **AC7**: fixture 단위 테스트로 집계·요약행 제외·미공시null·활동0·멱등 검증, 기존 78 회귀 0.

## 아키텍처 제약

- **AD-3**: 각 원천 테이블은 정확히 하나의 소스 어댑터가 소유·기록. financials writer=`DartAdapter`. → buyback을 별도 클래스로 financials에 쓰면 이중 writer 위반이라 **기존 어댑터 확장** 선택.
- **AD-7**: 멱등 upsert 자연키 `(corp_code, year, quarter)`.
- **NFR2**: 미공시·파싱 실패 시 null 허용, 수집 실패 금지.

## DART 엔드포인트 사실 (조사)

`GET /api/tesstkAcqsDspsSttus.json` (DS002, apiId 2019006). params=`crtfc_key`·`corp_code`·`bsns_year`·`reprt_code`.
응답 `list[]` 필드는 **전부 수량(주), 금액 없음**: `acqs_mth1/2/3`(취득방법 대/중/소분류), `stock_knd`, `bsis_qy`(기초), `change_qy_acqs`(취득), `change_qy_dsps`(처분), `change_qy_incnr`(**소각**), `trmend_qy`(기말), `rm`, `stlm_dt`.

## 변경 코드 (verbatim, 축약 없음)

### `app/ingest/dart.py` — `DartAdapter.fetch` (buyback 호출 추가)

```python
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
        # 자기주식 취득/처분 현황(1.8) — buyback_amount·buyback_retired_amount 신호원.
        # financials 단일 writer(AD-3) 유지: 별도 어댑터 아니라 이 fetch가 함께 수집.
        buyback_rows: list[dict[str, Any]] = []
        if include_buyback:
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
            buyback_rows = bb.get("list") or []
        periods: list[dict[str, Any]] = []
        # 데이터 없음(빈 accounts)과 계정 누락을 구분: 데이터 없으면 재무 period를 만들지 않음.
        # buyback만 있고 accounts 없는 종목은 period 미생성 → buyback 미적재(드묾, 한계 문서화).
        if accounts:
            periods.append(
                {
                    "year": int(bsns_year),
                    "quarter": _REPRT_QUARTER[reprt_code],
                    "accounts": accounts,
                    "total_debt": total_debt,
                    "fs_div": used_fs_div,
                    "buyback_rows": buyback_rows,
                }
            )
        return {"company": company, "periods": periods}
```

### `app/ingest/dart.py` — `_get` (T5: ValueError 포착 추가)

```python
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
        status = data.get("status")
        if status == "000":
            return data
        if allow_no_data and status == "013":  # 조회된 데이터 없음
            return {"list": []}
        raise DartAdapterError(
            f"DART API 오류: endpoint={endpoint}, status={status}, msg={data.get('message')}"
        )
```

### `app/ingest/dart.py` — `normalize` (buyback 집계 라인)

```python
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
            # 환원 항목은 전체 재무제표에 없음 → best-effort(있으면 사용, 없으면 null)
            rec["dividend_total"] = period.get("dividend_total")
            # 자사주 취득/소각 신호(1.8): tesstkAcqsDspsSttus 행에서 집계(수량, 액 아님)
            rec["buyback_amount"], rec["buyback_retired_amount"] = _buyback_totals(
                period.get("buyback_rows", [])
            )
            fin_recs.append(rec)
        return company, fin_recs
```

### `app/ingest/dart.py` — 신규 헬퍼 `_is_buyback_summary` · `_buyback_totals`

```python
_BUYBACK_SUMMARY = ("총계", "소계", "합계")  # acqs_mth 계층 요약행(leaf 합산에서 제외)


def _is_buyback_summary(row: Mapping[str, Any]) -> bool:
    """취득방법 대/중/소분류 중 하나라도 요약 라벨과 정확일치하면 요약행.

    부분일치 금지(1.6 "특수관계인"의 "계" 오탐 교훈) → strip 완전일치만.
    """
    for k in ("acqs_mth1", "acqs_mth2", "acqs_mth3"):
        if str(row.get(k, "")).strip() in _BUYBACK_SUMMARY:
            return True
    return False


def _buyback_totals(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[int | None, int | None]:
    """tesstkAcqsDspsSttus 행 → (취득 수량 합, 소각 수량 합). 수량(주), 액 아님.

    - 요약행(총계/소계/합계) 제외한 leaf 행만 합산 → 이중집계 방지(1.6 소계 교훈).
    - leaf 데이터가 전무하면 요약행으로 폴백(총계만 오는 응답에서 데이터 손실 방지).
    - 필드별로 파싱 가능한 값이 하나도 없으면 None(미공시/unknown), 있으면 합(0 가능).
      → 미공시(None, 기존값 보존)와 '활동 0'(정수 0, >0=False)을 구분(NFR2).
    """

    def _collect(want_summary: bool) -> tuple[int | None, int | None]:
        acqs: list[int] = []
        incnr: list[int] = []
        for row in rows:
            if _is_buyback_summary(row) != want_summary:
                continue
            a = _parse_amount(row.get("change_qy_acqs"))
            if a is not None:
                acqs.append(a)
            i = _parse_amount(row.get("change_qy_incnr"))
            if i is not None:
                incnr.append(i)
        return (sum(acqs) if acqs else None, sum(incnr) if incnr else None)

    leaf_acqs, leaf_incnr = _collect(want_summary=False)
    if leaf_acqs is None and leaf_incnr is None:
        return _collect(want_summary=True)  # leaf 없음 → 총계행 폴백
    return leaf_acqs, leaf_incnr
```

### `app/ingest/dart.py` — `_parse_amount` (기존, 참조용 — buyback도 이걸로 파싱)

```python
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
```

### `app/models.py` — financials buyback 필드 (주석 정정, 스키마 무변경)

```python
    # 환원 (별도 공시 기반, best-effort; 없으면 null)
    dividend_total: Mapped[int | None] = mapped_column(BigInteger)
    # 자사주(1.8, tesstkAcqsDspsSttus): 취득/소각 수량(주) — 워싱 presence 신호(>0), KRW 액 아님
    buyback_amount: Mapped[int | None] = mapped_column(BigInteger)  # 자사주 취득 수량(주)
    buyback_retired_amount: Mapped[int | None] = mapped_column(BigInteger)  # 자사주 소각 수량(주)
```

### `app/repositories/financials.py` — `upsert_financial` (기존, 무변경 — buyback 필드 이미 처리)

```python
def upsert_financial(session: Session, rec: dict) -> Financial:
    """(corp_code, year, quarter) 자연키 기준 financials upsert."""
    stmt = select(Financial).where(
        Financial.corp_code == rec["corp_code"],
        Financial.year == rec["year"],
        Financial.quarter == rec["quarter"],
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        obj = Financial(
            corp_code=rec["corp_code"], year=rec["year"], quarter=rec["quarter"]
        )
        session.add(obj)
    # fs_div(연결/개별 출처)는 항상 반영
    if "fs_div" in rec:
        obj.fs_div = rec["fs_div"]
    # 값 필드는 None이 아닌 경우에만 갱신 — 매핑 실패로 기존 non-null이 지워지지 않게
    for field in (
        "revenue", "net_income", "operating_income", "depreciation",
        "equity", "total_assets", "total_liabilities", "cash", "total_debt",
        "dividend_total", "buyback_amount", "buyback_retired_amount",
    ):
        if rec.get(field) is not None:
            setattr(obj, field, rec[field])
    return obj
```

### `tests/test_dart_ingest.py` — 신규 테스트 9종 (verbatim)

```python
# ── Story 1.8: 자기주식 취득/소각 (tesstkAcqsDspsSttus) ──

# 가짜 tesstkAcqsDspsSttus: 직접취득 3M주 취득 + 소각 1M주. 총계행 포함(이중집계 유발).
BUYBACK_ROWS = [
    {"acqs_mth1": "직접 취득", "acqs_mth2": "장내직접취득", "acqs_mth3": "-",
     "stock_knd": "보통주", "change_qy_acqs": "3,000,000",
     "change_qy_dsps": "0", "change_qy_incnr": "1,000,000"},
    {"acqs_mth1": "총계", "acqs_mth2": "-", "acqs_mth3": "-",
     "stock_knd": "보통주", "change_qy_acqs": "3,000,000",
     "change_qy_dsps": "0", "change_qy_incnr": "1,000,000"},  # 요약행 → 제외돼야
]


def test_buyback_totals_sums_leaf_excludes_summary() -> None:
    """AC2/AC3: leaf만 합산, 총계행 제외(이중집계 방지)."""
    from app.ingest.dart import _buyback_totals

    acqs, incnr = _buyback_totals(BUYBACK_ROWS)
    assert acqs == 3_000_000  # 6,000,000 아님(총계 이중가산 방지)
    assert incnr == 1_000_000


def test_buyback_totals_no_disclosure_is_none() -> None:
    """AC4: 미공시(빈 리스트) → (None, None). 기존값 안 덮게."""
    from app.ingest.dart import _buyback_totals

    assert _buyback_totals([]) == (None, None)


def test_buyback_totals_zero_activity_is_zero() -> None:
    """AC4: 공시했으나 활동 0(모든 change_qy='0') → 정수 0(>0=False), None 아님."""
    from app.ingest.dart import _buyback_totals

    rows = [{"acqs_mth1": "직접 취득", "acqs_mth2": "-", "acqs_mth3": "-",
             "change_qy_acqs": "0", "change_qy_incnr": "0"}]
    assert _buyback_totals(rows) == (0, 0)


def test_buyback_totals_dash_is_none_per_field() -> None:
    """AC4: '-'/빈값(파싱불가)만 있는 필드는 None(unknown). 취득만 있고 소각은 '-'."""
    from app.ingest.dart import _buyback_totals

    rows = [{"acqs_mth1": "직접 취득", "acqs_mth2": "-", "acqs_mth3": "-",
             "change_qy_acqs": "3,000,000", "change_qy_incnr": "-"}]
    assert _buyback_totals(rows) == (3_000_000, None)


def test_buyback_totals_summary_only_fallback() -> None:
    """AC3: leaf 없이 총계행만 오면 총계로 폴백(데이터 손실 방지)."""
    from app.ingest.dart import _buyback_totals

    rows = [{"acqs_mth1": "합계", "acqs_mth2": "-", "acqs_mth3": "-",
             "change_qy_acqs": "5,000,000", "change_qy_incnr": "2,000,000"}]
    assert _buyback_totals(rows) == (5_000_000, 2_000_000)


def test_normalize_fills_buyback_from_rows() -> None:
    """AC2: normalize가 period['buyback_rows']에서 두 필드를 채운다."""
    raw = {
        "company": {"corp_code": "00000001", "corp_name": "테스트"},
        "periods": [
            {"year": 2025, "quarter": 4, "fs_div": "CFS",
             "accounts": {"매출액": 100}, "total_debt": None,
             "buyback_rows": BUYBACK_ROWS},
        ],
    }
    _, fins = DartAdapter().normalize(raw)
    assert fins[0]["buyback_amount"] == 3_000_000
    assert fins[0]["buyback_retired_amount"] == 1_000_000


def test_normalize_no_buyback_rows_is_none() -> None:
    """회귀: buyback_rows 없는 period(기존 fixture)는 두 필드 null."""
    company, fins = DartAdapter().normalize(DART_RAW_SAMSUNG)
    assert fins[0]["buyback_amount"] is None
    assert fins[0]["buyback_retired_amount"] is None


def test_upsert_buyback_none_safe(session: Session) -> None:
    """AC5: 이후 buyback None으로 재적재해도 기존 수량 보존(None-safe)."""
    from app.ingest.dart import _buyback_totals

    adapter = DartAdapter()
    raw = {
        "company": {"corp_code": "00000001", "corp_name": "테스트"},
        "periods": [{"year": 2025, "quarter": 4, "fs_div": "CFS",
                     "accounts": {"매출액": 100}, "total_debt": None,
                     "buyback_rows": BUYBACK_ROWS}],
    }
    adapter.upsert(session, adapter.normalize(raw))
    session.commit()
    # 미공시로 재적재(buyback_rows 없음) → 기존 3M/1M 유지
    raw["periods"][0].pop("buyback_rows")
    adapter.upsert(session, adapter.normalize(raw))
    session.commit()
    obj = session.scalars(select(Financial)).one()
    assert obj.buyback_amount == 3_000_000  # 안 덮임
    assert obj.buyback_retired_amount == 1_000_000


def test_get_json_value_error_wrapped(monkeypatch) -> None:
    """T5: 비JSON 200(resp.json ValueError)도 DartAdapterError로 래핑(키 미노출)."""
    adapter = DartAdapter()

    class _Resp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            raise ValueError("No JSON could be decoded")

    monkeypatch.setattr(adapter._session, "get", lambda *a, **k: _Resp())
    with pytest.raises(DartAdapterError, match="DART 요청 실패") as ei:
        adapter._get("tesstkAcqsDspsSttus.json", {"crtfc_key": "SECRETKEY"})
    assert "SECRETKEY" not in str(ei.value)
```

## 다운스트림 소비 방식 (scoring.md 발췌 — 수량-proxy 타당성 판단용)

```
buyback_executed = financials.buyback_amount > 0
buyback_retired  = financials.buyback_retired_amount > 0
buyback_status   = retired / purchased_only / none
washing_flag = (progress_rate >= 0.5) AND (achievement_rate < 0.6)
            AND (buyback_planned AND NOT buyback_retired)
execution_score = 100 * clamp(0.5*min(achievement_rate,1) + 0.3*(buyback_executed?1:0)
                              + 0.2*min(actual_payout/target_payout,1), 0, 1)
```
→ buyback 두 필드는 오직 `>0` 불리언으로만 소비(액수 크기는 미사용). 이 때문에 '수량'을 '액' 필드에 저장해도 다운스트림 정확하다고 주장. 이 주장의 허점을 특히 봐줘.

## 이미 알려진 것 / 의도된 결정 (중복 지적 불필요, deferred 기록됨)

- **수량=액 프록시**: 엔드포인트가 금액 미제공. `>0` 신호로만 쓰여 다운스트림 정확. KRW 정밀액은 후속(수량×결산일 종가). 모델·db-schema 주석으로 명시.
- **AD-3 준수 위해 별도 어댑터 대신 `DartAdapter` 확장**: financials 단일 writer 유지(의도). run.py·upsert_financial·alembic 무변경(buyback이 ingest_financials에 편승).
- **buyback만 있고 accounts 없는 종목**: period 미생성 → buyback 미적재(드묾, 한계 문서화).
- **acqs_mth 계층 구조**: 실공시 샘플 없이 총계/소계/합계 정확일치 제외 + leaf 폴백으로 근사. raw 미보존이라 재파싱 불가 — 계층 확정은 실샘플 후 튜닝(deferred).
- **동시성 on_conflict**(v1 단일프로세스 보류), **원천 감사메타(ingested_at)**(전 원천 공통 후속), **rate-limit 200+status "020" 미재시도**(전 DART 공통) — 이미 deferred.
- **검증**: pytest 87 passed(buyback 9 신규 + 기존 78 회귀 0), 라이브 키 없이 fixture. 무마이그레이션.

## 출력 형식
`[High/Med/Low] 파일:라인 — 문제 — 근거/재현 — 제안수정`. 없으면 "clean".
특히 답해줘: (1) `change_qy_incnr` 합이 washing_flag 소각 신호로 **의미상** 맞나(소각은 누적 vs 기간, 부호), (2) 요약행 제외+leaf폴백 로직이 실제 DART 응답 구조에서 이중집계/손실을 정말 막나, (3) 수량-proxy가 2.1 `buyback_status`(retired/purchased_only/none) 도출에서 왜곡 가능성.
