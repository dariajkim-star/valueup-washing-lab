# Review Bundle — Story 4.2: M&A 배치 호출자 + 전량 원자성 정책 (2026-07-22)

PR: #4 (`feat/mna-batch-caller`, main `6663cac`에 머지됨). 선행: Story 4-1(PR #3).

## 이 스토리의 쟁점

`mna_engine.run()`은 `session.flush(); return count` 형태로, gap_engine이 2026-07-21에 고친
결함(**호출자가 커밋을 잊으면 "N건 완료"를 반환하며 조용히 유실**)이 그대로였습니다.
deferred-work.md는 이것을 미루면서 **"같은 정책을 그대로 옮길지, 모집단 특성상 전량 원자성이
맞는지는 별도 판단 필요"**라고 적어뒀습니다. 이 스토리는 그 판단입니다.

**결론: gap과 반대인 전량 원자성 + 실패 보고.** 이 판단이 이 리뷰의 1순위 검토 대상입니다.

## 판단 근거 (반박 환영)

1. **점수의 의미가 다르다.** `valueup_score`는 종목별 절대 측정치(목표 대비 달성률)라 한 종목이
   낡아도 나머지는 여전히 옳다. `mna_target_score`는 **백분위 순위**로 모집단 안의 상대 위치가
   곧 점수다 — 세대가 섞인 표는 "일부만 오래된 값"이 아니라 **순위 자체가 무의미한 표**다.
2. **부분 실패의 발생 여지가 애초에 작다.** 읽기(`all_latest_metrics`·`all_latest_ownership`·
   macro·sectors)가 전부 루프 이전에 끝나고, 루프 안은 in-memory 데이터로 하는 순수 계산 +
   upsert뿐이다. gap에서 종목별 커밋을 정당화했던 실패 유형이 구조적으로 거의 없다.
3. **gap에서 원자성을 기각한 사유가 여기선 해소된다.** 당시 기각 사유는 "1종목 실패로 전량
   소실 + **어느 종목이 왜 실패했는지 정보까지 소실**"이었다. 실패 목록을 DB가 아니라
   `MnaRunResult`·로그로 남기면 롤백되는 건 **점수뿐**이고 **실패 사실은 보고된다**.

## AC 요약

- **AC1** `mna_engine.run()`이 세션을 소유하고 전량 원자적으로 커밋
- **AC2** 한 종목이라도 실패하면 전량 롤백, `mna_score`는 실행 이전 상태 유지
- **AC3** 실패해도 `(corp_code, 사유)`는 `MnaRunResult.failed`·로그에 남음
- **AC4** `MnaRunResult`는 `scored`/`deleted`/`failed`/`complete` (gap의 `ScoreRunResult`와 동형)
- **AC5** `--engine {gap,mna,all}` 동작, 기본값 `all`
- **AC6** 둘 중 하나라도 불완전하면 종료 코드 1
- **AC7** 한 엔진이 실패해도 다른 엔진은 실행되고 둘 다 요약 출력
- **AC8** 기존 테스트 전건 통과(261) + 신규 (→ **274 passed**)

## 아키텍처 제약

- **AD-10**: `mna_score`의 유일 writer는 `mna_engine`.
- **AD-8**: `as_of` 명시. 시스템 시계 의존 금지.
- 세션 소유권: 넘겨받은 세션에 커밋하면 호출자의 미저장 작업까지 커밋되므로 엔진이 소유.
- 백분위 모집단은 `corp_codes` 부분집합과 무관하게 **전체 시장** 기준(부분 실행이어도 순위
  기준이 흔들리면 안 됨) — 2.3/2.7에서 확립된 기존 계약이며 이번에 바뀌지 않았다.

## 설계상 의도된 선택 (재보고 불필요)

1. **두 엔진의 정책이 다르다.** 일관성 결여로 지적하지 말아주세요 — 이유는 위 "판단 근거"이고,
   양쪽 `run()` docstring에 **상호 참조**로 남겼습니다. 다만 *근거 자체가 틀렸다*는 반박은 환영합니다.
2. **순수 계산 오류는 루프를 끝까지 돌며 사유를 모으고, DB 오류는 즉시 중단합니다.**
   후자는 세션이 사용 불가가 되어 이후 종목이 전부 "closed transaction"으로 실패하기 때문입니다
   — 그 목록은 정보가 아니라 노이즈입니다(아래 "자체 발견" 참조). 중단 시 `aborted_early=True`로
   **목록이 불완전함**을 표시합니다.
3. **`_IncompleteRun`은 내부 신호**라 정보를 나르지 않습니다(사유는 이미 result에 있음).
   트랜잭션을 되돌리는 것이 유일한 역할입니다.
4. **롤백 시 `scored`/`succeeded`를 0/빈 리스트로 되돌립니다.** 계산은 됐지만 DB에 없으므로,
   '성공했다'는 숫자를 남기지 않는 편이 정직하다고 판단했습니다.
5. **`--engine` 기본값 `all`.** 재계산의 정상 경로가 '둘 다'이고 한쪽만 돌리는 것이 예외입니다
   (`--as-of` 필수와 같은 방향 — 안전한 쪽이 기본값).
6. **`POST /scoring/run` 라우터 미구현** — 전 엔드포인트 무인증이라 배포 스토리의 보안 게이트와
   함께 다뤄야 합니다.

## 알려진 것 (재보고 불필요)

- **mna N+1 없음 / gap N+1 있음** — gap의 종목당 3쿼리는 유니버스 확대 스토리의 선행 조건으로
  이미 defer됨(deferred-work.md).
- **`latest_as_of`가 단순 MAX(as_of)** — score_run 메타데이터 defer와 같은 항목. 2026-07-14
  리드 결정으로 v2 백로그에 닫혀 있습니다.
- **select-then-insert 동시성 미보장** — 단일 프로세스 배치 전제. 병렬화 시 `ON CONFLICT` 전환.
- **부분 실행(`--corp-codes`) 시 population snapshot 혼재** — 2.3부터 docstring에 문서화된
  기존 한계. 이번 변경은 여기에 손대지 않았습니다(전량 원자성은 '한 번의 실행'을 원자화할 뿐,
  부분 실행이 남기는 이전 세대 행까지 정리하지는 않습니다).

## 특히 봐주셨으면 하는 것

1. **판단 자체.** 백분위 순위라서 원자성이라는 논리에 구멍이 있는지. 특히 `--corp-codes` 부분
   실행이 여전히 세대 혼재를 만든다면, "원자성을 택한 이유"가 부분 실행 경로에서는 지켜지지
   않는 것 아닌지 — 이 긴장을 어떻게 보시는지 궁금합니다.
2. **`except Exception` → `_IncompleteRun` 흐름.** 종목 루프의 광범위한 except가 삼키면 안 될
   것을 삼키고 있는지. 세션 오염 문제는 아래 "자체 발견"에서 실측·수정했으나, `SQLAlchemyError`
   분기가 잡아야 할 것을 다 잡는지(예: DBAPI 예외가 래핑되지 않고 새는 경로)는 봐주세요.
3. **`_score_one` 분리 시 회귀.** 기존 루프 본문을 헬퍼로 옮기며 `basis`/`macro_score` 처리가
   그대로인지(특히 `_Populations` 도입으로 인한 값 전달 누락).
4. **테스트가 계약을 고정하는지, 구현을 고정하는지.** 특히 `repo.upsert_mna_score`를 monkeypatch
   하는 원자성 테스트가 구현 세부에 지나치게 묶여 있지 않은지.
5. **사고 재발 방지책이 충분한지** (아래 참조).

## 자체 발견 및 수정 — DB 오류 시 실패 목록이 노이즈가 되던 문제

이 번들의 "특히 봐주셨으면" 2번(세션 오염)을 넘기지 않고 직접 실측한 결과, **판단 근거 하나가
틀렸음**이 드러나 수정했습니다.

`IntegrityError`를 주입하니 첫 종목만 실제 사유가 남고 나머지 3종목은 전부
`InvalidRequestError: Can't operate on closed transaction`이었습니다. 롤백·0행·`complete=False`는
정상이었지만, **"끝까지 돌아 전 종목의 사유를 모은다"는 이점은 순수 계산 오류에만 성립**하고
DB 오류에는 성립하지 않았습니다 — 그 목록은 어느 종목이 진짜 문제였는지를 오히려 가립니다.

수정: `SQLAlchemyError`는 사유를 담고 즉시 중단, `aborted_early=True`로 목록이 불완전함을 표시.
CLI도 이때 "위 목록은 완전하지 않다"를 별도로 알립니다. 두 축을 각각 테스트로 고정했습니다.
**271 → 274 passed.**

## 사고 기록 — 테스트가 실 DB를 오염시킴

`--engine` 기본값을 `all`로 두자, gap만 monkeypatch하던 **4-1 테스트가 mna 엔진을 실 DB에 돌려**
`mna_score`에 `as_of=2025-12-31` 31행을 만들었습니다. **테스트는 통과했습니다** — 오염이 어떤
단언에도 걸리지 않았기 때문입니다. 재계산 전 백업(당일 09:22)과 대조해 산물임을 확인·삭제하고,
남은 `2026-07-13` 31행이 백업과 완전히 일치함을 검증했습니다.

대응은 autouse 픽스처(`_never_touch_real_db`)로 해당 테스트 모듈의 `SessionLocal`을 빈 in-memory
DB로 까는 것이었습니다. **이 방어가 충분한지, 다른 테스트 모듈에도 같은 구멍이 있는지**
봐주시면 좋겠습니다(예: `SessionLocal`을 직접 import해 쓰는 다른 경로).

## 검증 결과

- **274 passed** (261 + mna 원자성 4종 + CLI 엔진 6종 + DB오류 중단 3종). 기존 mna 테스트 12개 호출부를 새
  시그니처로 갱신(25 → 29 passed).
- 원자성: `repo.upsert_mna_score`에 실패 주입 — **첫 종목이 실제로 upsert까지 간 뒤** 두 번째에서
  터뜨려도 DB엔 0행, 이전 실행 스냅숏 보존 확인.
- 라이브(실 DB 33종목): `[gap] scored=26 deleted=7 failed=0 complete=True` /
  `[mna] scored=31 deleted=2 failed=0 complete=True`, 종료 코드 0.
- 멱등성: 실행 전/후 `valueup_score` 해시 `4fb79360…`(26행), `mna_score` 해시 `5d01027d…`(31행)
  **둘 다 불변**.

## 파일 (verbatim)

### `docs/implementation-artifacts/4-2-mna-batch-caller.md` (138행)

스토리 문서

````markdown
# Story 4-2 — M&A 배치 호출자 + cross-sectional 트랜잭션 정책

- **에픽**: 4 운영·배치
- **상태**: review (구현·라이브 검증 완료)
- **작성일**: 2026-07-22
- **선행**: Story 4-1(스코어링 배치 CLI, main `1ea1a28`)

## 배경

`mna_engine.run()`은 `session.flush(); return count` 형태로 남아 있다 — 2026-07-21 코드리뷰가
`gap_engine`에서 고친 바로 그 결함(**호출자가 커밋을 잊으면 "N건 완료"를 반환하며 조용히 유실**)이
그대로 있고, 프로덕션 호출자도 없다. deferred-work.md는 이것을 "mna 배치 실호출자 스토리,
또는 gap_engine 정책 안정화 후"로 미뤘고, 4-1로 gap 정책이 실호출로 안정화되며 트리거가 발동했다.

핵심 질문은 CLI 배선이 아니라 **cross-sectional 엔진에 gap과 같은 정책이 맞는가**다.

## 결정

### D1. 전량 원자성 + 실패 보고 (gap과 **반대**)

`gap_engine`은 종목별 커밋 + 실패 목록을 택했다. `mna_engine`은 **전량 원자성**을 택한다.
같은 프로젝트 안에서 두 엔진의 정책이 다른 것은 일관성 결여가 아니라 **점수의 성질이 다르기
때문**이며, 그 이유를 두 엔진 docstring에 상호 참조로 남긴다.

**근거 1 — 점수의 의미가 다르다.** `valueup_score`는 종목별 절대 측정치다(목표 대비 달성률).
한 종목의 값이 낡아도 다른 종목의 값은 여전히 옳다. `mna_target_score`는 **백분위 순위**로,
모집단 안에서의 상대 위치가 곧 점수다. 세대가 섞인 mna 테이블은 "일부만 오래된 값"이 아니라
**순위 자체가 무의미한 표**다 — 서로 다른 모집단 기준으로 매겨진 등수를 한 줄에 세운 것이므로.

**근거 2 — 부분 실패의 발생 여지가 애초에 작다.** 읽기(`all_latest_metrics`·`all_latest_ownership`·
macro·sectors)가 **전부 루프 이전에** 끝나고, 루프 안은 in-memory 데이터로 하는 순수 계산 +
upsert뿐이다. gap에서 종목별 커밋을 정당화했던 실패 유형(종목별 조회 실패, 특정 종목의 입력
이상)이 여기엔 구조적으로 거의 없다. 즉 종목별 커밋이 사는 값은 작고, 깨뜨리는 것은 크다.

**근거 3 — 원자성을 gap에서 기각한 이유는 여기서 해소된다.** 당시 기각 사유는 "1종목 실패로
전량 소실 + **어느 종목이 왜 실패했는지 정보까지 소실**"이었다. 실패 목록을 DB가 아니라
`MnaRunResult`·로그로 남기면 정보는 지워지지 않는다. 롤백되는 것은 **점수**뿐이고
**실패 사실은 보고된다** — 2026-07-21의 "섞임을 없애는 대신 숨기지 않는다" 원칙과 어긋나지 않는다.
숨기지 않는 방식이 이 엔진에서는 '섞어서 노출'이 아니라 '롤백하고 보고'일 뿐이다.

### D2. 세션 소유권을 엔진으로 (gap과 **동일**)

`run(as_of, corp_codes=None, *, session_factory=SessionLocal) -> MnaRunResult`.
호출자가 넘긴 세션에 커밋하면 호출자의 미저장 작업까지 함께 커밋되므로, 4-1과 같은 이유로
세션을 함수가 소유한다. 단 gap과 달리 **전체가 단일 트랜잭션**이다.

프로덕션 호출자가 없어(테스트·문서만) 시그니처 변경 비용이 낮은 지금이 바꿀 시점이다.

### D3. CLI는 4-1 모듈을 확장 (`--engine`)

별도 진입점을 만들지 않고 `app/analysis/run_scoring.py`에 `--engine {gap,mna,all}`을 더한다.
기본값 `all` — 재계산의 정상 경로는 "둘 다"이고, 한쪽만 돌리는 것이 예외이기 때문이다
(`--as-of`를 필수로 둔 것과 같은 방향: 안전한 쪽이 기본값).

종료 코드는 4-1 계약 유지 — 두 엔진 중 **하나라도** 불완전하면 1. 한 엔진이 실패해도 다른
엔진은 실행하고 **둘 다 보고한 뒤** 종료 코드를 정한다(먼저 실패한 쪽만 보고하고 끝내면
두 번 돌려야 전체 상태를 알 수 있다).

## 인수 조건

- **AC1** `mna_engine.run()`이 세션을 소유하고 전량 원자적으로 커밋한다.
- **AC2** 한 종목이라도 실패하면 **전량 롤백**되고 `mna_score`는 실행 이전 상태로 남는다.
- **AC3** 실패해도 `(corp_code, 사유)`는 `MnaRunResult.failed`와 로그에 남는다.
- **AC4** `MnaRunResult`는 `scored`/`deleted`/`failed`/`complete`를 싣는다(gap의 `ScoreRunResult`와 동형).
- **AC5** `python -m app.analysis.run_scoring --as-of ... --engine {gap,mna,all}`이 동작하고, 기본값은 `all`.
- **AC6** 두 엔진 중 하나라도 불완전하면 종료 코드 1, 둘 다 완전하면 0.
- **AC7** 한 엔진이 실패해도 다른 엔진은 실행되고 둘 다 요약이 출력된다.
- **AC8** 기존 테스트 전건 통과(261) + mna 원자성·CLI 테스트 신규.

## 비범위

- 모집단 스냅숏 자체의 영속화(`population_basis`는 이미 행에 기록됨) → score_run defer와 동일 계열
- `POST /scoring/run` HTTP 라우터 → 배포 스토리(보안 게이트 선행)
- mna N+1·유니버스 확대 → 기존 defer 유지

## 검증 계획

- 단위: 마지막 종목에서 예외를 주입해 **전량 롤백** 확인(부분 커밋 0건), `failed`에 사유 존재
- 통합: SQLite in-memory + `session_factory` 주입(2.1/4-1 seam 재사용)
- 라이브: 실 DB `--engine all --as-of 2026-07-13` → `mna_score` 해시 불변(멱등) + 종료 코드 0

## 검증 결과 (2026-07-22)

**261 → 271 passed** (mna 원자성 4종 + CLI 엔진 선택 6종). 기존 mna 테스트 12개 호출부를
새 시그니처로 갱신(25 → 29 passed).

**라이브(실 DB 33종목)**:

```
[gap] as_of=2026-07-13 scored=26 deleted=7 failed=0 complete=True
[mna] as_of=2026-07-13 scored=31 deleted=2 failed=0 complete=True
종료 코드: 0
```

멱등성: 실행 전/후 `valueup_score` 해시 `4fb79360…`(26행), `mna_score` 해시 `5d01027d…`(31행)
**둘 다 불변**.

원자성 테스트는 `repo.upsert_mna_score`에 실패를 주입해 확인했다 — 첫 종목이 실제로 upsert까지
간 뒤 두 번째에서 터뜨려도 **DB엔 한 줄도 남지 않고**, 이전 실행의 스냅숏이 그대로 보존된다.

## 사고 기록 — 테스트가 실 DB를 오염시킴

`--engine` 기본값을 `all`로 두자, gap만 monkeypatch하던 4-1 테스트가 **mna 엔진을 실 DB에
돌려** `mna_score`에 `as_of=2025-12-31` 31행을 만들었다. **테스트는 통과했다** — 오염이 어떤
단언에도 걸리지 않았기 때문이다. 재계산 전 백업(당일 09:22)과 대조해 해당 31행이 테스트
산물임을 확인하고 삭제, 남은 `2026-07-13` 31행이 백업과 완전히 일치함을 검증했다.

교훈은 "테스트에 `--engine gap`을 붙였어야 했다"가 아니다. **기본값 변경이 기존 테스트의
부작용 범위를 넓혔는데 아무 신호도 나지 않았다**는 것이다. 개별 테스트가 무엇을 패치하는지에
기대는 대신, autouse 픽스처로 이 모듈의 `SessionLocal`을 빈 in-memory DB로 깔아 **사고 자체를
불가능하게** 했다(`_never_touch_real_db`). 2026-07-13의 "확인 없는 파일 삭제 금지"와 같은 계열 —
파괴적 기본값은 규율이 아니라 구조로 막는다.

## 후속 정정 (2026-07-22, 리뷰 번들 작성 중 자체 발견)

번들에 "특히 봐주셨으면"으로 적어둔 우려(**세션이 깨진 뒤 다음 종목 upsert를 계속 시도해도
안전한가**)를 넘기지 않고 직접 실측한 결과, **근거 하나가 틀렸음이 드러났다.**

진짜 DB 오류(`IntegrityError`)를 주입하니 첫 종목만 실제 사유가 남고 나머지 3종목은 전부
`InvalidRequestError: Can't operate on closed transaction`이었다. 롤백·0행·`complete=False`는
정상이었지만, **"실패해도 끝까지 돌아 전 종목의 사유를 모은다"는 이점은 순수 계산 오류에만
성립하고 DB 오류에는 성립하지 않는다** — 그 목록은 정보가 아니라 노이즈이고, 어느 종목이
진짜 문제였는지를 오히려 가린다.

수정: `SQLAlchemyError`는 사유를 담고 **즉시 중단**하며 `MnaRunResult.aborted_early=True`로
**목록이 불완전함을 표시**한다(남은 종목은 시도조차 되지 않았으므로 성공 여부를 알 수 없다).
CLI도 이때 "위 목록은 완전하지 않다"를 별도로 알린다. 순수 계산 오류는 종전대로 끝까지 모은다.
두 축을 각각 테스트로 고정(`test_db_error_aborts_loop_instead_of_logging_noise`,
`test_non_db_error_still_collects_all_reasons`). **274 passed**.

교훈: 리뷰 번들의 "봐주셨으면" 항목은 남에게 넘길 질문 목록이 아니라 **내가 먼저 확인할
체크리스트**다. 이번엔 넘기기 직전에 실측해서 잡았다.

## 인계

- 두 엔진의 정책이 다른 이유는 각 `run()` docstring에 상호 참조로 남겼다. 한쪽만 읽고
  "일관성이 없다"고 판단하는 것을 막기 위함이다.
- `POST /scoring/run` 라우터는 여전히 배포 스토리 몫(보안 게이트 선행).
````

### `app/analysis/mna_engine.py` (387행)

**이번 스토리의 핵심 변경**

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

import logging
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.analysis.gap_engine import _validate_as_of  # as_of 검증 재사용(중복 정의 금지)
from app.config import settings
from app.db import SessionLocal
from app.repositories import mna_score as repo

logger = logging.getLogger(__name__)

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


class _IncompleteRun(Exception):
    """전량 롤백을 일으키기 위한 내부 신호. run() 밖으로 새지 않는다.

    실패 사유는 이미 MnaRunResult.failed에 담겨 있으므로 이 예외 자체는 정보를 나르지 않는다.
    트랜잭션을 되돌리는 것이 유일한 역할이다.
    """


@dataclass
class MnaRunResult:
    """run()의 결과. gap_engine의 ScoreRunResult와 **동형**이되 의미가 하나 다르다.

    `complete=False`는 gap에서는 "이 as_of에 실행분이 섞여 있다"였지만, 여기서는
    **"아무것도 쓰이지 않았다"**(전량 롤백)를 뜻한다. 트랜잭션 정책이 다르기 때문이며
    그 이유는 run() docstring 참조.
    """

    scored: int = 0  # upsert된 종목 수(롤백 시 DB에 남지 않음 — 계산된 수)
    deleted: int = 0  # 근거를 잃어 정리된 종목 수
    succeeded: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (corp_code, reason)
    # DB 오류로 세션이 죽어 루프를 중단했는가. True면 failed는 **완전한 목록이 아니다** —
    # 남은 종목은 시도조차 되지 않았다(성공했을지 실패했을지 알 수 없음).
    aborted_early: bool = False

    @property
    def complete(self) -> bool:
        """실패 0건 = 스냅숏이 커밋됐고 전 종목이 동일 모집단 기준임을 보장."""
        return not self.failed


def run(
    as_of: str,
    corp_codes: Sequence[str] | None = None,
    *,
    session_factory: Callable[[], Session] = SessionLocal,
) -> MnaRunResult:
    """as_of 기준 corp별 mna_score를 계산·upsert. MnaRunResult 반환.

    트랜잭션 정책(결정, Story 4-2): **전량 원자성 + 실패 보고**. gap_engine의 종목별 커밋과
    의도적으로 **반대**다 — 일관성 결여가 아니라 점수의 성질이 다르기 때문이다.

    `valueup_score`는 종목별 절대 측정치라 한 종목이 낡아도 나머지는 여전히 옳다. 반면
    `mna_target_score`는 **백분위 순위**로 모집단 안의 상대 위치가 곧 점수다. 세대가 섞인
    mna 테이블은 "일부만 오래된 값"이 아니라 **순위 자체가 무의미한 표**가 된다 — 서로 다른
    모집단 기준으로 매긴 등수를 한 줄에 세운 것이므로. 게다가 읽기가 전부 루프 이전에 끝나
    루프 안은 순수 계산 + upsert뿐이라, 종목별 커밋이 방어할 실패 유형 자체가 구조적으로 적다.

    gap에서 원자성을 기각한 사유("어느 종목이 왜 실패했는지 정보까지 소실")는 여기서
    해소된다 — 실패 목록을 DB가 아니라 MnaRunResult·로그로 남기므로 롤백되는 것은 **점수**뿐,
    **실패 사실은 보고된다**. "섞임을 없애는 대신 숨기지 않는다"(2026-07-21)와 어긋나지 않는다.
    이 엔진에서 숨기지 않는 방식이 '섞어서 노출'이 아니라 '롤백하고 보고'일 뿐이다.

    세션은 이 함수가 소유한다(gap_engine과 동일 이유 — 넘겨받은 세션에 커밋을 걸면 호출자의
    미저장 작업까지 함께 커밋된다). 단 gap과 달리 **전체가 단일 트랜잭션**이다.

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
    result = MnaRunResult()
    # 전량 원자성: 읽기·계산·쓰기 전부가 하나의 트랜잭션. _IncompleteRun이 오르면
    # session.begin() 블록이 롤백하고, 그 신호는 여기서 삼킨다(사유는 result에 있다).
    try:
        with session_factory() as session, session.begin():
            _run_in_session(session, as_of, corp_codes, result)
    except _IncompleteRun:
        logger.error(
            "M&A 스코어 %d종목 실패 → 전량 롤백(mna_score는 실행 이전 상태). as_of=%s",
            len(result.failed), as_of,
        )
        # 롤백됐으므로 '계산된 수'는 DB에 없다 — 결과가 쓰이지 않은 것을 숫자로도 드러낸다.
        result.scored = 0
        result.deleted = 0
        result.succeeded.clear()
    return result


def _run_in_session(
    session: Session,
    as_of: str,
    corp_codes: Sequence[str] | None,
    result: MnaRunResult,
) -> None:
    """run()의 본문. 트랜잭션 경계 밖으로 빼서 롤백 책임을 호출부 한 곳에 둔다.

    실패는 result.failed에 담고 루프를 계속 돈다 — 순위표는 부분적으로 옳을 수 없으므로
    어차피 전량 롤백되지만, 그 전에 **진짜 사유를 최대한 모으는** 편이 재실행에 쓸모 있다.
    루프가 끝나면 예외를 올려 롤백시킨다(사유는 result에 이미 담겼다).

    **예외 — DB 오류는 즉시 중단한다**(2026-07-22 실측). SQLAlchemy 오류가 나면 세션이
    사용 불가 상태가 되어 이후 종목은 전부 "Can't operate on closed transaction"으로 실패한다.
    그 사유들은 정보가 아니라 **노이즈**이고(해당 종목이 실제로 성공했을지는 알 수 없다),
    계속 도는 이유 자체가 사라진다. 이때는 `aborted_early=True`로 **목록이 불완전함을 표시**한다.
    """
    if corp_codes is None:
        corp_codes = repo.list_all_corp_codes(session)

    # 1단계: 전체 모집단 배치 구성(cross-sectional — corp 루프 전에 끝나야 함)
    metrics = repo.all_latest_metrics(session, as_of)
    ownership = repo.all_latest_ownership(session, as_of)
    if not metrics and not ownership:
        return  # 입력 전무 — 업스트림 장애 가능성, reconciliation 오삭제 방어
    current_rate, rate_history = repo.latest_macro_percentile_basis(session, as_of)
    sectors = repo.all_company_sectors(session)

    # 시장 모집단(폴백·sector 미상·ownership용) + sector 버킷 모집단(2.7, valuation·capacity용)
    market_pops = _build_populations(metrics, group_of=lambda c: _WHOLE_MARKET)
    sector_pops = _build_populations(
        metrics, group_of=lambda c: _sector_bucket(sectors.get(c)) or _WHOLE_MARKET
    )
    # 버킷 sector 승격 판정(일괄리뷰 High: '행 개수'가 아니라 **지표별 유효값 개수** 기준 —
    # 행은 6개인데 ev_ebitda 유효값이 2개면 mna_peer_min의 small-N 방어가 우회되던 문제).
    # valuation·capacity의 5개 서브지표 전부가 peer_min 이상일 때만 sector 사용(단일
    # basis의 의미 보존), 하나라도 미달이면 그 버킷 전체를 시장 폴백.
    _factor_indicators = tuple(
        name for name, _ in _VALUATION_INDICATORS + _CAPACITY_INDICATORS
    )
    sector_ready: dict[str, bool] = {}
    for b, pops in sector_pops.items():
        if b == _WHOLE_MARKET:
            continue
        sector_ready[b] = all(
            len(pops.get(name, [])) >= settings.mna_peer_min
            for name in _factor_indicators
        )
    # ownership은 업종 무관(절대적 취약성 신호, epics 2.7 AC) — 시장 모집단 유지
    owner_pops = _build_populations(ownership, group_of=lambda c: _WHOLE_MARKET)
    # macro_score: 종목 무관, as_of당 1회(낮은 금리 = 차입인수 유리 → 역백분위)
    macro_score = _pct_rank_low(current_rate, rate_history)

    pops = _Populations(
        market=market_pops, sector=sector_pops, owner=owner_pops,
        sector_ready=sector_ready, sectors=sectors, macro_score=macro_score,
    )
    for corp_code in corp_codes:
        try:
            upserted = _score_one(
                session, corp_code, as_of, metrics, ownership, pops
            )
        except SQLAlchemyError as e:
            # DB 오류는 세션을 못 쓰게 만든다 — 이후 종목은 전부 "closed transaction"으로
            # 실패해 **사유가 노이즈**가 되고, 그 종목들이 실제로 성공했을지는 알 수 없게 된다.
            # 계속 도는 이유(진짜 사유를 모은다)가 사라지므로 여기서 멈춘다.
            logger.warning(
                "M&A 스코어 DB 오류 corp_code=%s: %s — 세션 사용 불가로 중단",
                corp_code, type(e).__name__,
            )
            result.failed.append((corp_code, str(e)))
            result.aborted_early = True
            break
        except Exception as e:  # noqa: BLE001 (사유를 담고 계속 — 끝에서 전량 롤백)
            logger.warning(
                "M&A 스코어 계산 실패 corp_code=%s: %s", corp_code, type(e).__name__
            )
            result.failed.append((corp_code, str(e)))
            continue
        if upserted:
            result.scored += 1
        else:
            result.deleted += 1
        result.succeeded.append(corp_code)

    if result.failed:
        # 루프를 끝까지 돌고 나서 올린다 — 첫 실패에서 멈추면 실패 목록이 1건으로 잘려
        # "무엇이 왜 실패했는지"를 남기려던 이유가 사라진다(사유는 result에 이미 담겼다).
        raise _IncompleteRun


@dataclass
class _Populations:
    """_score_one에 넘길 모집단 묶음. 루프 이전에 확정되며 종목별로 바뀌지 않는다."""

    market: dict[str, dict[str, list[float]]]
    sector: dict[str, dict[str, list[float]]]
    owner: dict[str, dict[str, list[float]]]
    sector_ready: dict[str, bool]
    sectors: Mapping[str, str | None]
    macro_score: float | None


def _score_one(
    session: Session,
    corp_code: str,
    as_of: str,
    metrics: Mapping[str, Any],
    ownership: Mapping[str, Any],
    pops: _Populations,
) -> bool:
    """한 종목의 점수를 계산·upsert. upsert했으면 True, 근거가 없어 정리했으면 False."""
    bucket = _sector_bucket(pops.sectors.get(corp_code))
    if bucket is None:
        pop, basis = pops.market.get(_WHOLE_MARKET, {}), "market"
    elif pops.sector_ready.get(bucket, False):
        pop, basis = pops.sector.get(bucket, {}), f"sector:{bucket}"
    else:  # 버킷 지표별 peer 미달 → 시장 폴백(small-N 노이즈 방어)
        pop, basis = pops.market.get(_WHOLE_MARKET, {}), "market_fallback"

    valuation = _factor_score(_VALUATION_INDICATORS, metrics.get(corp_code), pop)
    capacity = _factor_score(_CAPACITY_INDICATORS, metrics.get(corp_code), pop)
    owner = _factor_score(
        _OWNERSHIP_INDICATORS, ownership.get(corp_code),
        pops.owner.get(_WHOLE_MARKET, {}),
    )
    if valuation is None and capacity is None:
        # basis 과장 방지(일괄리뷰 Med): 이 종목의 valuation·capacity에 모집단이
        # 실제로 쓰이지 않았으면(둘 다 null) basis를 기록하지 않는다.
        basis = None
    if valuation is None and capacity is None and owner is None:
        repo.delete_mna_score(session, corp_code, as_of)  # 근거 없는 기존 행 정리
        return False

    total = _mna_target_score(
        valuation, capacity, owner, pops.macro_score,
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
            "macro_score": pops.macro_score,
            "population_basis": basis,
        },
    )
    return True
```

### `app/analysis/run_scoring.py` (134행)

CLI (`--engine` 추가)

```python
"""스코어링 배치 진입점 (Story 4-1) — `gap_engine.run()`의 첫 프로덕션 호출자.

`python -m app.analysis.run_scoring --as-of 2026-07-13`

**이 모듈이 존재하는 이유**: `gap_engine.run()`은 종목별 커밋 + 실패 목록 정책이라
부분 성공이 가능하고, 그 사실을 `ScoreRunResult.complete`로 **숨기지 않고 노출**한다.
호출자가 없으면 그 노출은 아무도 읽지 않는 값일 뿐이다. 이 모듈이 그것을 읽어
종료 코드로 번역한다 — 배치의 1차 소비자는 사람이 아니라 셸·스케줄러이고,
종료 코드는 그 계층이 이해하는 유일한 신호다.

종료 코드: 0=완전(complete), 1=부분 실패, 2=사용법·입력 오류(argparse 관례).
"""

from __future__ import annotations

import argparse
import logging

from app.analysis import gap_engine, mna_engine
from app.db import SessionLocal

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_INCOMPLETE = 1
EXIT_USAGE = 2

ENGINES = ("gap", "mna", "all")


def _parse_corp_codes(raw: str | None) -> list[str] | None:
    """쉼표 구분 corp_code 목록. 미지정(None)은 '전체 실행'을 뜻하므로 그대로 None을 넘긴다.

    빈 문자열·공백만 있는 입력을 빈 리스트로 넘기면 엔진이 '대상 0종목'으로 조용히 성공한다
    (`complete=True`, scored=0). 전체 실행과 구분되지 않는 조용한 무작업이라 사용법 오류로 막는다.
    """
    if raw is None:
        return None
    codes = [c.strip() for c in raw.split(",") if c.strip()]
    if not codes:
        raise ValueError("--corp-codes에 유효한 corp_code가 없습니다(전체 실행은 옵션 생략)")
    return codes


def _report(name: str, as_of: str, result) -> bool:
    """엔진 실행 결과를 로그로 옮기고 완전성 여부를 돌려준다.

    두 엔진의 결과 타입(ScoreRunResult / MnaRunResult)은 동형이라 같은 코드로 읽는다.
    다만 `complete=False`의 뜻은 다르다 — gap은 "실행분이 섞였다", mna는 "전량 롤백됐다".
    그 차이는 실패 안내 문구로 구분한다(정책은 각 엔진 docstring 참조).
    """
    logger.info(
        "[%s] as_of=%s scored=%d deleted=%d failed=%d complete=%s",
        name, as_of, result.scored, result.deleted, len(result.failed), result.complete,
    )
    if not result.failed:
        return True
    # 전건 출력(자르지 않는다) — 무엇이 왜 실패했는지가 이 정책들을 택한 이유다.
    logger.error("[%s] 실패 %d종목:", name, len(result.failed))
    for corp_code, reason in result.failed:
        logger.error("  %s: %s", corp_code, reason)
    if name == "gap":
        logger.error(
            "[gap] 이 as_of에는 이번 실행분과 이전 실행분이 섞여 있다 — 게시 전 재실행할 것."
        )
    else:
        if getattr(result, "aborted_early", False):
            logger.error(
                "[mna] DB 오류로 중단 — 위 목록은 **완전하지 않다**(남은 종목은 시도되지 않음)."
            )
        logger.error(
            "[mna] 전량 롤백됐다 — mna_score는 실행 이전 상태 그대로다(순위표는 부분적으로 "
            "옳을 수 없으므로). 원인 해소 후 재실행할 것."
        )
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.analysis.run_scoring",
        description="valueup_score 재계산 배치 (gap_engine)",
    )
    parser.add_argument(
        "--as-of", dest="as_of", required=True,
        help="기준일(YYYY-MM-DD). **필수** — progress_rate가 as_of에 직접 의존하므로 "
             "암묵적 오늘 날짜는 재현 불가능한 실행을 만든다(D2).",
    )
    parser.add_argument(
        "--corp-codes", dest="corp_codes", default=None,
        help="쉼표 구분 corp_code(디버깅용 부분 실행). 생략 시 전체 종목 — "
             "게시용 점수는 반드시 전체 실행이어야 한다.",
    )
    parser.add_argument(
        "--engine", choices=ENGINES, default="all",
        help="실행할 엔진 (기본 all). 재계산의 정상 경로는 '둘 다'이고 한쪽만 돌리는 것이 "
             "예외이므로 안전한 쪽을 기본값으로 둔다.",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        corp_codes = _parse_corp_codes(args.corp_codes)
    except ValueError as e:
        logger.error("입력 오류: %s", e)
        return EXIT_USAGE

    if corp_codes is not None:
        # complete=True여도 부분 실행 스냅샷은 여전히 부분적 — 두 개념은 다르다(D3).
        logger.warning(
            "부분 실행(%d종목): 나머지 종목은 이전 실행분이 그대로 남는다. **게시용 아님**.",
            len(corp_codes),
        )

    engines = ("gap", "mna") if args.engine == "all" else (args.engine,)
    runners = {"gap": gap_engine.run, "mna": mna_engine.run}

    complete = True
    for name in engines:
        try:
            result = runners[name](
                args.as_of, corp_codes, session_factory=SessionLocal
            )
        except ValueError as e:  # as_of fail-fast — 트레이스백 대신 사용법 오류로(AC6)
            logger.error("입력 오류: %s", e)
            return EXIT_USAGE
        # 한 엔진이 불완전해도 나머지는 돌린다 — 먼저 실패한 쪽만 보고하고 끝내면
        # 전체 상태를 알기 위해 두 번 돌려야 한다.
        complete &= _report(name, args.as_of, result)

    return EXIT_OK if complete else EXIT_INCOMPLETE


if __name__ == "__main__":
    raise SystemExit(main())
```

### `app/analysis/gap_engine.py` (296행)

비교 대상 — '정책이 왜 달라야 하는가' 판단에 필요

```python
"""Value-up 갭 스코어링 엔진 (writer = 이 모듈, AD-4).

Epic 1(수집)과 다른 새 패턴: HTTP 어댑터가 아니라 **순수 계산**. 입력은 이미 DB에 있다
(valuation_metrics 뷰 + valueup_plan + financials.buyback_*). 산식은 scoring.md 참조.

null 전파가 핵심 계약(2026-07-10 코드리뷰로 scoring.md 강화): 입력이 애매/누락이면
0이나 False로 강제하지 않고 해당 스코어도 null로 전파한다(NFR2 "null > 틀린 값").
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.repositories import valueup_score as repo

logger = logging.getLogger(__name__)

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
    period_start: str | None, period_end: str | None, as_of: date
) -> float | None:
    """계획기간 대비 진척률, [0,1] 클램프. **일 단위 정밀도**(코드리뷰 2026-07-21 결정 B).

    scoring.md 원식은 `(today - period_start) / (period_end - period_start)` — 처음부터
    날짜 기반이었고, 이전 연 단위 구현이 스펙 이탈이었다(연도가 바뀌는 1/1에 진척률이
    1/(end-start)만큼 점프 → washing_flag 임계 0.5를 하루 사이에 넘는 종목 발생).

    입력이 연도 문자열뿐이므로 경계 규약: 시작 = 시작연도 1/1, 종료 = 종료연도 12/31.
    end <= start는 계속 None — 0나눗셈은 이제 아니지만(단년 계획도 분모 364일), 단년 계획
    수용은 AC3 계약("null·end<=start 무효") 변경이라 별도 결정으로 defer(deferred-work.md).
    """
    if period_start is None or period_end is None:
        return None
    try:
        start, end = int(period_start), int(period_end)
    except (TypeError, ValueError):
        return None
    if end <= start:
        return None
    period_begin = date(start, 1, 1)
    period_close = date(end, 12, 31)
    raw = (as_of - period_begin).days / (period_close - period_begin).days
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


@dataclass
class ScoreRunResult:
    """run()의 결과. 부분 성공을 허용하므로 '몇 건'뿐 아니라 '무엇이 실패했는지'를 함께 싣는다.

    수집 레이어의 IngestResult(app/ingest/run.py)와 동형 — 두 레이어의 트랜잭션 정책이
    같으므로 결과 표현도 같게 유지한다(코드리뷰 2026-07-21).
    """

    scored: int = 0  # upsert된 종목 수
    deleted: int = 0  # 근거(plan)를 잃어 정리된 종목 수
    succeeded: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (corp_code, reason)

    @property
    def complete(self) -> bool:
        """실패 0건 = 이 as_of 스냅샷이 전 종목 동일 시점 기준임을 보장.

        False면 valueup_score의 해당 as_of에는 이번 실행분과 이전 실행분이 **섞여 있다**.
        게시·비교 용도로 쓰기 전에 반드시 확인할 것(트레이드오프는 아래 run() docstring).
        """
        return not self.failed


def _score_one(session: Session, corp_code: str, as_of: str, as_of_date: date) -> bool:
    """한 종목의 스코어를 계산·저장. upsert면 True, 근거 없어 정리했으면 False.

    호출자(run)가 종목당 트랜잭션을 소유한다 — 이 함수는 커밋하지 않는다.
    """
    plan = repo.latest_valueup_plan(session, corp_code, as_of)
    if plan is None:
        repo.delete_valueup_score(session, corp_code, as_of)
        return False

    metrics = repo.latest_metrics(session, corp_code, as_of)
    buyback = repo.latest_financial_buyback(session, corp_code, as_of)
    actual_roe = metrics.get("roe") if metrics else None
    actual_payout = metrics.get("payout_ratio") if metrics else None
    amount = buyback.get("buyback_amount") if buyback else None
    retired_amount = buyback.get("buyback_retired_amount") if buyback else None

    progress_rate = _progress_rate(plan["period_start"], plan["period_end"], as_of_date)
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
    return True


def run(
    as_of: str,
    corp_codes: Sequence[str] | None = None,
    *,
    session_factory: Callable[[], Session] = SessionLocal,
) -> ScoreRunResult:
    """as_of 기준으로 corp별 valueup_score를 계산·upsert. ScoreRunResult 반환.

    트랜잭션 정책(결정, 코드리뷰 2026-07-21): **종목별 커밋 + 실패 목록**. 한 종목의
    계산·저장 실패가 이미 성공한 다른 종목의 결과를 되돌리지 않도록 부분 성공을 허용한다.
    수집 레이어(app/ingest/run.py)와 동일한 정책·동일한 결과 표현(IngestResult)을 쓴다 —
    두 레이어가 다른 규칙을 가지면 읽는 사람이 매번 어느 쪽인지 확인해야 한다.

    트레이드오프(명시): 부분 성공은 같은 as_of 안에 **이번 실행분과 이전 실행분이 섞일 수**
    있다는 뜻이다. 전량 원자성(하나 실패 시 전량 롤백)은 이 섞임을 없애지만, 실패한 종목이
    무엇이었는지도 함께 지운다. 섞임을 없애는 대신 **숨기지 않는** 쪽을 택했다 —
    `ScoreRunResult.complete`가 False면 그 스냅샷은 불완전하다(게시 전 확인 필요).

    세션은 이 함수가 소유한다(종목당 짧은 트랜잭션). 호출자가 세션을 넘기지 않는 것은
    의도된 설계 — 넘겨받은 세션에 커밋을 걸면 호출자의 다른 미저장 작업까지 함께 커밋된다.
    테스트는 session_factory로 자체 엔진을 주입한다.

    valueup_plan이 없는 종목은 목표가 없어 갭을 정의할 수 없으므로 행을 만들지 않는다
    (1-6 no-data 교훈과 동일 원칙). 이전에 plan이 있어 score가 생성됐다가 이후 plan이
    삭제/정정된 경우, 근거를 잃은 기존 score도 함께 정리한다(코드리뷰 High, GPT: gap_engine이
    valueup_score의 유일 writer(AD-4)이므로 정합성 유지 책임도 이 모듈에 있음).

    as_of는 YYYY-MM-DD 형식만 허용(fail-fast) — 비표준 포맷은 disclosure_date와의 문자열
    비교(사전식)를 실제 날짜 비교와 어긋나게 만들 수 있다(코드리뷰 High, GPT).
    """
    _validate_as_of(as_of)
    as_of_date = date.fromisoformat(as_of)  # _validate_as_of 통과 직후라 안전

    if corp_codes is None:
        with session_factory() as session:
            corp_codes = repo.list_all_corp_codes(session)

    result = ScoreRunResult()
    for corp_code in corp_codes:
        try:
            with session_factory() as session, session.begin():  # 종목당 짧은 트랜잭션
                upserted = _score_one(session, corp_code, as_of, as_of_date)
        except Exception as e:  # noqa: BLE001 (부분성공 정책 — ingest/run.py와 동일)
            logger.warning(
                "스코어 계산 실패 corp_code=%s: %s", corp_code, type(e).__name__
            )
            result.failed.append((corp_code, str(e)))
            continue
        if upserted:
            result.scored += 1
        else:
            result.deleted += 1
        result.succeeded.append(corp_code)
    return result
```

### `tests/test_mna_engine.py` (572행)

**신규 원자성 테스트 + 기존 호출부 갱신**

```python
"""Story 2.3 — M&A Target Score 엔진 검증 (순수 함수 + cross-sectional 통합)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.analysis.mna_engine import (
    _avg_scores,
    _build_populations,
    _mna_target_score,
    _pct_rank_high,
    _pct_rank_low,
    _percentile_rank,
    run,
)
from app.models import (
    Base,
    Company,
    Financial,
    MacroIndicator,
    MnaScore,
    Ownership,
    Price,
)
from app.sql_views import CREATE_VALUATION_METRICS


# ── T3: 순수 함수 단위 테스트 ──

def test_percentile_rank_min_zero_max_one() -> None:
    pop = [10.0, 20.0, 30.0, 40.0]
    assert _percentile_rank(10.0, pop) == 0.0
    assert _percentile_rank(40.0, pop) == 1.0
    assert _percentile_rank(20.0, pop) == pytest.approx(1 / 3)


def test_percentile_rank_ties_use_mid_rank() -> None:
    """[리뷰 High] 동점은 mid-rank — (below + (equal-1)/2) / (N-1). 최하위 몰림 방지."""
    pop = [10.0, 10.0, 30.0]
    # 10.0: below=0, equal=2 → (0 + 0.5)/2 = 0.25 (min-rank 0.0이 아님)
    assert _percentile_rank(10.0, pop) == pytest.approx(0.25)
    assert _percentile_rank(30.0, pop) == 1.0


def test_percentile_rank_all_equal_is_neutral() -> None:
    """[리뷰 High] 전원 동일값 → 전원 0.5(중립). min-rank였다면 0.0(→pct_low 1.0)로
    '모두 똑같은데 최고점' 왜곡 — 기준금리처럼 장기 동결되는 시계열에서 실제로 터지는 케이스."""
    assert _percentile_rank(5.0, [5.0, 5.0, 5.0]) == pytest.approx(0.5)
    assert _pct_rank_low(5.0, [5.0, 5.0, 5.0]) == pytest.approx(0.5)


def test_percentile_rank_rejects_nonfinite() -> None:
    """[리뷰 Med] NaN/Inf는 모집단·대상값 모두에서 배제(비교 연산이 조용히 왜곡됨)."""
    nan, inf = float("nan"), float("inf")
    # NaN이 대상값 → None (모든 < 비교가 False라 min-rank처럼 보이는 오류 방지)
    assert _percentile_rank(nan, [1.0, 2.0, 3.0]) is None
    # NaN/Inf가 모집단에 → 제외하고 계산 (분모 오염 방지)
    assert _percentile_rank(2.0, [1.0, nan, 2.0, inf]) == pytest.approx(1.0)


def test_percentile_rank_small_population_is_none() -> None:
    """peer<2면 순위가 무의미 → None."""
    assert _percentile_rank(10.0, [10.0]) is None
    assert _percentile_rank(10.0, []) is None


def test_percentile_rank_none_value_is_none() -> None:
    assert _percentile_rank(None, [1.0, 2.0, 3.0]) is None


def test_percentile_rank_ignores_none_in_population() -> None:
    pop = [10.0, None, 30.0, None]
    assert _percentile_rank(30.0, pop) == 1.0


def test_pct_rank_directions() -> None:
    pop = [1.0, 2.0, 3.0]
    # low: 낮을수록 좋은 지표(EV/EBITDA 등) → 최솟값이 1.0
    assert _pct_rank_low(1.0, pop) == 1.0
    assert _pct_rank_low(3.0, pop) == 0.0
    # high: 높을수록 좋은 지표(net_cash 등) → 최댓값이 1.0
    assert _pct_rank_high(3.0, pop) == 1.0
    assert _pct_rank_high(1.0, pop) == 0.0


def test_avg_scores_strict_null() -> None:
    """AC6(리드 결정 1, 엄격): 하나라도 None이면 요소 점수 전체 None."""
    assert _avg_scores(0.5, 0.7) == pytest.approx(0.6)
    assert _avg_scores(0.5, None) is None
    assert _avg_scores(None, None) is None


def test_mna_target_score_weighted_sum() -> None:
    score = _mna_target_score(
        valuation=1.0, capacity=0.5, ownership=0.0, macro=1.0,
        w_valuation=0.35, w_capacity=0.25, w_ownership=0.25, w_macro=0.15,
    )
    # 100*(0.35*1 + 0.25*0.5 + 0.25*0 + 0.15*1) = 100*0.625 = 62.5
    assert score == pytest.approx(62.5)


def test_mna_target_score_null_when_any_factor_missing() -> None:
    assert _mna_target_score(
        valuation=None, capacity=0.5, ownership=0.5, macro=0.5,
        w_valuation=0.35, w_capacity=0.25, w_ownership=0.25, w_macro=0.15,
    ) is None


def test_build_populations_single_group_v1() -> None:
    """grouping seam: v1은 전체시장 한 그룹 — 모든 종목 값이 같은 population에."""
    rows = {
        "A": {"pbr": 1.0, "net_cash": 100},
        "B": {"pbr": 2.0, "net_cash": None},
        "C": {"pbr": None, "net_cash": 300},
    }
    pops = _build_populations(rows, group_of=lambda c: "_all")
    assert sorted(pops["_all"]["pbr"]) == [1.0, 2.0]  # None 제외
    assert sorted(pops["_all"]["net_cash"]) == [100, 300]


def test_build_populations_custom_grouping_seam() -> None:
    """grouping seam: group_of를 갈아끼우면(2-7 sector) population이 그룹별로 분리."""
    rows = {
        "A": {"pbr": 1.0}, "B": {"pbr": 2.0},  # 은행 버킷
        "C": {"pbr": 5.0}, "D": {"pbr": 6.0},  # 반도체 버킷
    }
    sector = {"A": "bank", "B": "bank", "C": "semi", "D": "semi"}
    pops = _build_populations(rows, group_of=lambda c: sector[c])
    assert sorted(pops["bank"]["pbr"]) == [1.0, 2.0]
    assert sorted(pops["semi"]["pbr"]) == [5.0, 6.0]


# ── Story 2.7: sector peer-group ──

def test_sector_bucket_two_digit_prefix() -> None:
    from app.analysis.mna_engine import _sector_bucket

    assert _sector_bucket("64191") == "64"  # 은행업
    assert _sector_bucket("26121") == "26"  # 반도체
    assert _sector_bucket(None) is None
    assert _sector_bucket("") is None
    assert _sector_bucket("A1") is None  # 숫자 아님 → 분류 불가(값 안 만듦)


# ── T4: 통합 테스트 (cross-sectional, SQLite in-memory + 뷰) ──

@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(text(CREATE_VALUATION_METRICS))
    return eng


def _seed_corp(
    s: Session, code: str, *, market_cap: int, net_income: int = 100,
    cash: int = 500, total_debt: int = 200, largest: float = 40.0,
    treasury: float = 5.0,
) -> None:
    """FY2024(사업보고서) 실적 + 최신가 + 지분구조 시드. as_of=2025-*에서 look-ahead 안전."""
    s.add(Company(corp_code=code, corp_name=f"기업{code}", market="KOSPI"))
    s.add(Financial(
        corp_code=code, year=2024, quarter=4,
        revenue=1000, net_income=net_income, operating_income=150, depreciation=50,
        equity=1000, total_assets=2000, total_liabilities=800,
        cash=cash, total_debt=total_debt, dividend_total=20,
    ))
    s.add(Price(corp_code=code, date="2025-06-30", close=100,
                market_cap=market_cap, volume=10, trading_value=1000))
    s.add(Ownership(corp_code=code, as_of="2024-12-31",
                    largest_shareholder_pct=largest, treasury_stock_pct=treasury))


def _seed_macro(s: Session) -> None:
    # 과거 금리 시계열: 3.5 → 3.0 → 2.5 (현재 2.5 = 역사적 최저 → macro_score 1.0)
    for d, v in (("2024-01-31", 3.5), ("2024-07-31", 3.0), ("2025-01-31", 2.5)):
        s.add(MacroIndicator(indicator="base_rate", date=d, value=v, frequency="M"))


def test_run_cross_sectional_relative_ranking(engine) -> None:
    """AC2/3/4/5: 가장 저평가(시총 최소)가 valuation 1.0, 최고평가가 0.0 — 상대 순위."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_corp(s, "00000001", market_cap=1000, largest=20.0, treasury=10.0)  # 싸고 뺏기쉬움
        _seed_corp(s, "00000002", market_cap=3000, largest=40.0, treasury=5.0)
        _seed_corp(s, "00000003", market_cap=9000, largest=60.0, treasury=1.0)  # 비싸고 방어적
        _seed_macro(s)
        s.commit()

        result = run("2025-12-31", session_factory=Session_)
        assert result.scored == 3
        assert result.complete is True  # 실패 0 → 스냅숏이 커밋됐다

        rows = {r.corp_code: r for r in s.scalars(select(MnaScore)).all()}
        # 시총 최소 → pbr·ev_ebitda 최소 → 역백분위 1.0
        assert rows["00000001"].valuation_score == pytest.approx(1.0)
        assert rows["00000003"].valuation_score == pytest.approx(0.0)
        # 지배구조: 최대주주 최저+자사주 최고 → 1.0
        assert rows["00000001"].ownership_score == pytest.approx(1.0)
        assert rows["00000003"].ownership_score == pytest.approx(0.0)
        # 매크로: 현재 금리 2.5가 역사적 최저 → 전 종목 공통 1.0
        assert rows["00000001"].macro_score == pytest.approx(1.0)
        assert rows["00000002"].macro_score == pytest.approx(1.0)
        # 총점: 최저평가+뺏기쉬움 종목이 최고점
        assert rows["00000001"].mna_target_score > rows["00000003"].mna_target_score


def test_run_null_factor_propagates_to_total(engine) -> None:
    """AC6(엄격): ownership 미공시 종목은 ownership_score null → mna_target_score도 null."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_corp(s, "00000001", market_cap=1000)
        _seed_corp(s, "00000002", market_cap=3000)
        # 3번: ownership 없이(재무·가격만)
        s.add(Company(corp_code="00000003", corp_name="지분미공시", market="KOSPI"))
        s.add(Financial(
            corp_code="00000003", year=2024, quarter=4,
            revenue=1000, net_income=100, operating_income=150, depreciation=50,
            equity=1000, total_assets=2000, total_liabilities=800,
            cash=500, total_debt=200, dividend_total=20,
        ))
        s.add(Price(corp_code="00000003", date="2025-06-30", close=100,
                    market_cap=5000, volume=10, trading_value=1000))
        _seed_macro(s)
        s.commit()

        run("2025-12-31", session_factory=Session_)
        row = s.scalars(
            select(MnaScore).where(MnaScore.corp_code == "00000003")
        ).one()
        assert row.ownership_score is None
        assert row.mna_target_score is None  # 요소 하나라도 null → 전체 null
        assert row.valuation_score is not None  # 계산 가능한 요소는 채워짐


def test_run_lookahead_excludes_same_year_annual(engine) -> None:
    """2.1 look-ahead 패턴 재사용: 같은 해(2025) 사업보고서는 as_of=2025에서 안 보임."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_corp(s, "00000001", market_cap=1000)
        _seed_corp(s, "00000002", market_cap=3000)
        # FY2025 사업보고서만 있는 종목(2024 없음) → as_of=2025-12-31에서 지표 없음
        s.add(Company(corp_code="00000003", corp_name="당해만", market="KOSPI"))
        s.add(Financial(
            corp_code="00000003", year=2025, quarter=4,
            revenue=1000, net_income=100, operating_income=150, depreciation=50,
            equity=1000, total_assets=2000, total_liabilities=800,
            cash=500, total_debt=200, dividend_total=20,
        ))
        s.add(Price(corp_code="00000003", date="2025-06-30", close=100,
                    market_cap=5000, volume=10, trading_value=1000))
        _seed_macro(s)
        s.commit()

        run("2025-12-31", session_factory=Session_)
        row = s.scalars(
            select(MnaScore).where(MnaScore.corp_code == "00000003")
        ).one_or_none()
        # 지표·지분 전무 → 전 요소 null(매크로만 남음) → 행 미생성 or 전부 null
        if row is not None:
            assert row.valuation_score is None
            assert row.mna_target_score is None


def test_run_is_idempotent(engine) -> None:
    """AC7: 재실행 시 중복 없음."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_corp(s, "00000001", market_cap=1000)
        _seed_corp(s, "00000002", market_cap=3000)
        _seed_macro(s)
        s.commit()
        run("2025-12-31", session_factory=Session_)
        run("2025-12-31", session_factory=Session_)
        rows = s.scalars(select(MnaScore)).all()
        assert len(rows) == 2


def test_run_rejects_malformed_as_of(engine) -> None:
    """2.1 패턴 재사용: as_of 포맷 fail-fast."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            run("2025-7-1", session_factory=Session_)


def test_run_macro_latest_null_propagates_not_substituted(engine) -> None:
    """[리뷰 High] 최신 macro 관측이 null이면 과거 non-null로 몰래 대체하지 않고
    macro_score도 null(AC6 엄격 null). 요소별 점수는 채워지되 총점은 null."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_corp(s, "00000001", market_cap=1000)
        _seed_corp(s, "00000002", market_cap=3000)
        s.add(MacroIndicator(indicator="base_rate", date="2024-06-30", value=3.0, frequency="M"))
        s.add(MacroIndicator(indicator="base_rate", date="2025-01-31", value=2.5, frequency="M"))
        s.add(MacroIndicator(indicator="base_rate", date="2025-06-30", value=None, frequency="M"))  # 최신=null
        s.commit()

        run("2025-12-31", session_factory=Session_)
        row = s.scalars(select(MnaScore)).first()
        assert row.macro_score is None  # 2.5로 대체되면 안 됨
        assert row.valuation_score is not None
        assert row.mna_target_score is None


def test_run_rejects_calendar_invalid_as_of(engine) -> None:
    """[리뷰 Med] 정규식은 통과하지만 달력상 무효한 날짜(2025-02-30) 거부."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        with pytest.raises(ValueError):
            run("2025-02-30", session_factory=Session_)


def test_run_guards_against_mass_delete_on_empty_inputs(engine) -> None:
    """[리뷰 Med] metrics·ownership이 통째로 비면(업스트림 장애 가능성) 기존 점수를
    삭제하지 않고 스킵 — reconciliation 대량 오삭제 방어."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(Company(corp_code="00000001", corp_name="기존점수"))
        s.add(MnaScore(corp_code="00000001", as_of="2025-12-31",
                       mna_target_score=70.0, valuation_score=0.7,
                       capacity_score=0.7, ownership_score=0.7, macro_score=0.7))
        s.commit()

        result = run("2025-12-31", session_factory=Session_)  # 입력 데이터 전무
        assert result.scored == 0
        assert s.scalars(select(MnaScore)).one_or_none() is not None  # 안 지워짐


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
            run("2025-12-31", session_factory=Session_)
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
        run("2025-12-31", session_factory=Session_)
        rows = s.scalars(select(MnaScore)).all()
        assert all(r.population_basis == "market" for r in rows)


def test_run_macro_uses_only_history_before_as_of(engine) -> None:
    """AC4: as_of 이후 금리는 백분위 모집단에서 제외(look-ahead 방지)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_corp(s, "00000001", market_cap=1000)
        _seed_corp(s, "00000002", market_cap=3000)
        # as_of=2024-12-31 기준: 2024년 관측 2개(3.5, 3.0)만 유효, 2025-01의 2.5는 미래
        for d, v in (("2024-01-31", 3.5), ("2024-07-31", 3.0), ("2025-01-31", 2.5)):
            s.add(MacroIndicator(indicator="base_rate", date=d, value=v, frequency="M"))
        s.commit()

        run("2024-12-31", session_factory=Session_)
        row = s.scalars(select(MnaScore)).first()
        # 유효 모집단 [3.5, 3.0], 현재값 3.0(최저) → pct_rank_low = 1.0
        # (미래의 2.5가 포함됐다면 3.0은 최저가 아니어서 1.0이 안 나옴)
        assert row.macro_score == pytest.approx(1.0)


# ── Story 4-2: 전량 원자성 (gap_engine의 종목별 커밋과 의도적으로 반대) ──

def test_run_rolls_back_entirely_on_any_failure(engine, monkeypatch) -> None:
    """AC2: 한 종목이라도 실패하면 **전량 롤백** — 부분 커밋이 0건이어야 한다.

    백분위 순위는 부분적으로 옳을 수 없다. 두 종목 중 하나만 새 모집단 기준으로 쓰이면
    남은 한 줄과 등수를 견줄 수 없으므로, 그런 표는 만들지 않는 쪽을 택했다.
    """
    from app.analysis import mna_engine

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_corp(s, "00000001", market_cap=1000)
        _seed_corp(s, "00000002", market_cap=3000)
        _seed_macro(s)
        s.commit()

    real_upsert = mna_engine.repo.upsert_mna_score
    calls: list[str] = []

    def flaky_upsert(session, rec):
        calls.append(rec["corp_code"])
        if len(calls) == 2:  # 첫 종목은 성공시키고 두 번째에서 터뜨린다
            raise RuntimeError("boom")
        return real_upsert(session, rec)

    monkeypatch.setattr(mna_engine.repo, "upsert_mna_score", flaky_upsert)
    result = run("2025-12-31", session_factory=Session_)

    assert len(calls) == 2  # 실제로 첫 종목은 upsert까지 갔다
    assert result.complete is False
    with Session_() as s:
        assert s.scalars(select(MnaScore)).all() == []  # 그럼에도 DB엔 한 줄도 없다


def test_run_reports_failures_even_though_rolled_back(engine, monkeypatch) -> None:
    """AC3: 롤백돼도 (corp_code, 사유)는 남는다 — gap에서 원자성을 기각한 사유의 해소책."""
    from app.analysis import mna_engine

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_corp(s, "00000001", market_cap=1000)
        _seed_corp(s, "00000002", market_cap=3000)
        _seed_macro(s)
        s.commit()

    def always_fail(session, rec):
        raise RuntimeError(f"실패-{rec['corp_code']}")

    monkeypatch.setattr(mna_engine.repo, "upsert_mna_score", always_fail)
    result = run("2025-12-31", session_factory=Session_)

    # 첫 실패에서 멈추지 않고 전 종목의 사유를 모은다
    assert [c for c, _ in result.failed] == ["00000001", "00000002"]
    assert all("실패-" in reason for _, reason in result.failed)
    # 롤백됐으므로 '성공했다'는 숫자를 남기지 않는다
    assert result.scored == 0
    assert result.succeeded == []


def test_run_preserves_prior_snapshot_on_failure(engine, monkeypatch) -> None:
    """AC2 보강: 실패 시 이전 실행의 점수가 그대로 보존된다(반쪽 갱신 금지)."""
    from app.analysis import mna_engine

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_corp(s, "00000001", market_cap=1000)
        _seed_corp(s, "00000002", market_cap=3000)
        _seed_macro(s)
        s.commit()

    run("2025-12-31", session_factory=Session_)  # 1차: 정상
    with Session_() as s:
        before = {r.corp_code: r.mna_target_score for r in s.scalars(select(MnaScore)).all()}
    assert len(before) == 2

    def always_fail(session, rec):
        raise RuntimeError("boom")

    monkeypatch.setattr(mna_engine.repo, "upsert_mna_score", always_fail)
    assert run("2025-12-31", session_factory=Session_).complete is False

    with Session_() as s:
        after = {r.corp_code: r.mna_target_score for r in s.scalars(select(MnaScore)).all()}
    assert after == before  # 1차 스냅숏 그대로


def test_run_owns_session_and_commits(engine) -> None:
    """AC1: 호출자가 커밋하지 않아도 저장된다 — flush만 하던 기존 결함의 회귀 테스트."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_corp(s, "00000001", market_cap=1000)
        _seed_corp(s, "00000002", market_cap=3000)
        _seed_macro(s)
        s.commit()

    run("2025-12-31", session_factory=Session_)  # 호출자는 아무 커밋도 하지 않는다

    with Session_() as s:  # 완전히 새 세션에서 보인다 = 정말 커밋됐다
        assert len(s.scalars(select(MnaScore)).all()) == 2


def test_db_error_aborts_loop_instead_of_logging_noise(engine) -> None:
    """DB 오류는 즉시 중단 — 세션이 죽은 뒤의 실패 사유는 정보가 아니라 노이즈다.

    실측(2026-07-22): 첫 종목에서 IntegrityError가 나면 나머지 종목은 전부
    "Can't operate on closed transaction"으로 실패한다. 그 목록은 어느 종목이 진짜
    문제였는지를 가리므로, 진짜 사유 1건만 남기고 목록이 불완전함을 aborted_early로 알린다.
    """
    from app.analysis import mna_engine

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        for i, cap in enumerate((1000, 3000, 5000, 7000), start=1):
            _seed_corp(s, f"0000000{i}", market_cap=cap)
        _seed_macro(s)
        s.commit()

    real = mna_engine.repo.upsert_mna_score
    calls = {"n": 0}

    def db_error_upsert(session, rec):
        calls["n"] += 1
        if calls["n"] == 1:  # NOT NULL 위반으로 진짜 DB 오류를 만든다
            session.add(MnaScore(corp_code=None, as_of=rec["as_of"]))
            session.flush()
        return real(session, rec)

    monkeypatch_target = mna_engine.repo
    original = monkeypatch_target.upsert_mna_score
    monkeypatch_target.upsert_mna_score = db_error_upsert
    try:
        result = run("2025-12-31", session_factory=Session_)
    finally:
        monkeypatch_target.upsert_mna_score = original

    assert result.aborted_early is True
    assert len(result.failed) == 1  # 노이즈 3건이 붙지 않는다
    assert "NOT NULL" in result.failed[0][1]
    assert calls["n"] == 1  # 세션이 죽은 뒤 다음 종목을 시도하지 않았다
    with Session_() as s:
        assert s.scalars(select(MnaScore)).all() == []  # 전량 롤백은 그대로


def test_non_db_error_still_collects_all_reasons(engine, monkeypatch) -> None:
    """반대 축: 순수 계산 오류는 세션을 망가뜨리지 않으므로 끝까지 사유를 모은다."""
    from app.analysis import mna_engine

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed_corp(s, "00000001", market_cap=1000)
        _seed_corp(s, "00000002", market_cap=3000)
        _seed_macro(s)
        s.commit()

    monkeypatch.setattr(
        mna_engine.repo, "upsert_mna_score",
        lambda session, rec: (_ for _ in ()).throw(RuntimeError(f"계산-{rec['corp_code']}")),
    )
    result = run("2025-12-31", session_factory=Session_)

    assert result.aborted_early is False
    assert [c for c, _ in result.failed] == ["00000001", "00000002"]
```

### `tests/test_run_scoring_cli.py` (268행)

**엔진 선택 테스트 + 사고 방지 픽스처**

```python
"""Story 4-1 — 스코어링 배치 CLI 검증.

핵심은 "계산이 맞나"가 아니라(그건 2.1이 검증한다) **엔진이 노출한 `complete`가
종료 코드로 번역되는가**다. 그 번역이 이 모듈의 존재 이유다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.analysis import run_scoring
from app.analysis.gap_engine import ScoreRunResult
from app.analysis.mna_engine import MnaRunResult
from app.analysis.run_scoring import EXIT_INCOMPLETE, EXIT_OK, EXIT_USAGE, main
from app.models import Base, Company, Financial, ValueupPlan, ValueupScore
from app.sql_views import CREATE_VALUATION_METRICS


@pytest.fixture(autouse=True)
def _never_touch_real_db(monkeypatch):
    """이 모듈의 어떤 테스트도 실 DB(valueup.db)에 닿지 못하게 막는다.

    실제 사고(2026-07-22): `--engine` 기본값이 `all`이 되면서, gap만 monkeypatch한
    테스트가 **mna 엔진을 실 DB에 돌려** mna_score에 as_of=2025-12-31 31행을 만들었다.
    테스트는 통과했다 — 오염이 단언에 걸리지 않았기 때문이다. 개별 테스트가 무엇을
    패치하는지에 기대지 않고, 기본값을 빈 in-memory DB로 깔아 사고 자체를 불가능하게 한다.
    """
    throwaway = sessionmaker(
        bind=create_engine("sqlite:///:memory:", future=True, poolclass=StaticPool)
    )
    monkeypatch.setattr(run_scoring, "SessionLocal", throwaway)


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(text(CREATE_VALUATION_METRICS))
    return eng


def _seed(session: Session, corp_code: str = "00000001") -> None:
    """2.1 통합 테스트와 동일한 최소 시드(계획 + 전년도 확정실적)."""
    session.add(Company(corp_code=corp_code, corp_name="테스트", market="KOSPI"))
    session.add(Financial(
        corp_code=corp_code, year=2024, quarter=4,
        revenue=1000, net_income=80, operating_income=100, depreciation=10,
        equity=1000, total_assets=2000, total_liabilities=1000, cash=100,
        total_debt=200, dividend_total=24,
        buyback_amount=3_000_000, buyback_retired_amount=0,
    ))
    session.add(ValueupPlan(
        corp_code=corp_code, disclosure_date="2024-03-01",
        target_roe=10.0, target_payout_ratio=30.0, target_pbr=1.2,
        period_start="2024", period_end="2027", buyback_planned=True,
    ))
    session.commit()


# ── 종료 코드 계약 (AC3) ──

def test_complete_run_exits_zero(engine, monkeypatch) -> None:
    """AC1/AC3: 전체 실행이 성공하면 종료 코드 0이고 실제로 점수가 기록된다."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
    monkeypatch.setattr(run_scoring, "SessionLocal", Session_)

    assert main(["--as-of", "2025-12-31", "--engine", "gap"]) == EXIT_OK

    with Session_() as s:
        row = s.scalars(select(ValueupScore)).one()
        assert row.corp_code == "00000001"
        assert row.as_of == "2025-12-31"


def test_partial_failure_exits_one(monkeypatch) -> None:
    """AC3의 핵심: complete=False가 종료 코드 1로 번역된다.

    여기서 실패를 '만들어' 주입하는 이유 — 엔진이 실패를 어떻게 만드는지는 2.1의 관심사고,
    이 모듈의 관심사는 실패가 있을 때 **조용히 0을 반환하지 않는다**는 것뿐이다.
    """
    def fake_run(as_of, corp_codes=None, *, session_factory=None):
        return ScoreRunResult(
            scored=2, deleted=0, succeeded=["00000001", "00000002"],
            failed=[("00000003", "boom")],
        )
    monkeypatch.setattr(run_scoring.gap_engine, "run", fake_run)

    assert main(["--as-of", "2025-12-31", "--engine", "gap"]) == EXIT_INCOMPLETE


def test_failed_corp_codes_are_all_logged(monkeypatch, caplog) -> None:
    """AC4: 실패 목록은 전건 출력된다(자르지 않는다)."""
    failed = [(f"0000000{i}", f"사유{i}") for i in range(1, 6)]

    def fake_run(as_of, corp_codes=None, *, session_factory=None):
        return ScoreRunResult(scored=0, failed=list(failed))
    monkeypatch.setattr(run_scoring.gap_engine, "run", fake_run)

    with caplog.at_level("ERROR"):
        assert main(["--as-of", "2025-12-31", "--engine", "gap"]) == EXIT_INCOMPLETE
    for corp_code, reason in failed:
        assert corp_code in caplog.text
        assert reason in caplog.text


def test_summary_is_logged(engine, monkeypatch, caplog) -> None:
    """AC2: 실행 요약(scored/deleted/failed/complete)이 남는다."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
    monkeypatch.setattr(run_scoring, "SessionLocal", Session_)

    with caplog.at_level("INFO"):
        assert main(["--as-of", "2025-12-31", "--engine", "gap"]) == EXIT_OK
    assert "scored=1" in caplog.text
    assert "complete=True" in caplog.text


# ── 입력 계약 (AC5, AC6) ──

def test_as_of_is_required(capsys) -> None:
    """AC5: --as-of 미지정은 종료 코드 2 — 시스템 시계로 대체하지 않는다(D2)."""
    with pytest.raises(SystemExit) as exc:  # argparse의 required 처리
        main([])
    assert exc.value.code == EXIT_USAGE


@pytest.mark.parametrize("bad", ["2025-7-1", "not-a-date", "2025-02-30"])
def test_invalid_as_of_exits_two_without_traceback(bad, monkeypatch, caplog) -> None:
    """AC6: 형식 오류(2025-7-1)·달력 무효(2025-02-30) 모두 트레이스백이 아니라 종료 코드 2.

    2025-02-30은 정규식만으론 통과하는 값 — 엔진의 달력 검증까지 CLI가 삼키는지 확인한다.
    """
    Session_ = sessionmaker(bind=create_engine("sqlite:///:memory:", future=True))
    monkeypatch.setattr(run_scoring, "SessionLocal", Session_)

    with caplog.at_level("ERROR"):
        assert main(["--as-of", bad, "--engine", "gap"]) == EXIT_USAGE
    assert "입력 오류" in caplog.text


# ── 부분 실행 (AC7) ──

def test_partial_run_warns_not_publishable(engine, monkeypatch, caplog) -> None:
    """AC7: --corp-codes 실행은 complete=True여도 '게시용 아님' 경고를 남긴다(D3)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
    monkeypatch.setattr(run_scoring, "SessionLocal", Session_)

    with caplog.at_level("WARNING"):
        assert main(["--as-of", "2025-12-31", "--engine", "gap", "--corp-codes", "00000001"]) == EXIT_OK
    assert "게시용 아님" in caplog.text


def test_empty_corp_codes_is_usage_error(monkeypatch, caplog) -> None:
    """빈 --corp-codes는 '대상 0종목 조용한 성공'이 되므로 사용법 오류로 막는다.

    전체 실행(옵션 생략)과 구분되지 않는 무작업이 complete=True·exit 0으로 나가면,
    이 스토리가 만들려는 신호 자체가 거짓이 된다.
    """
    called = False

    def fake_run(*a, **kw):
        nonlocal called
        called = True
        return ScoreRunResult()
    monkeypatch.setattr(run_scoring.gap_engine, "run", fake_run)

    with caplog.at_level("ERROR"):
        assert main(["--as-of", "2025-12-31", "--engine", "gap", "--corp-codes", " , "]) == EXIT_USAGE
    assert called is False  # 엔진에 도달하기 전에 막혔다


# ── Story 4-2: 엔진 선택 (AC5/AC6/AC7) ──

def _fake_result(cls, *, failed=()):
    return cls(scored=1, deleted=0, succeeded=["00000001"], failed=list(failed))


def test_engine_defaults_to_all(monkeypatch) -> None:
    """AC5: 기본값은 all — 재계산의 정상 경로는 '둘 다'다."""
    ran: list[str] = []
    monkeypatch.setattr(run_scoring.gap_engine, "run",
                        lambda *a, **k: (ran.append("gap"), _fake_result(ScoreRunResult))[1])
    monkeypatch.setattr(run_scoring.mna_engine, "run",
                        lambda *a, **k: (ran.append("mna"), _fake_result(MnaRunResult))[1])

    assert main(["--as-of", "2025-12-31"]) == EXIT_OK
    assert ran == ["gap", "mna"]


@pytest.mark.parametrize("engine_arg,expected", [("gap", ["gap"]), ("mna", ["mna"])])
def test_engine_selects_single(engine_arg, expected, monkeypatch) -> None:
    ran: list[str] = []
    monkeypatch.setattr(run_scoring.gap_engine, "run",
                        lambda *a, **k: (ran.append("gap"), _fake_result(ScoreRunResult))[1])
    monkeypatch.setattr(run_scoring.mna_engine, "run",
                        lambda *a, **k: (ran.append("mna"), _fake_result(MnaRunResult))[1])

    assert main(["--as-of", "2025-12-31", "--engine", engine_arg]) == EXIT_OK
    assert ran == expected


def test_second_engine_runs_even_if_first_incomplete(monkeypatch, caplog) -> None:
    """AC7: gap이 불완전해도 mna는 돌고 **둘 다** 보고된다.

    먼저 실패한 쪽만 보고하고 끝내면 전체 상태를 알기 위해 두 번 돌려야 한다.
    """
    ran: list[str] = []
    monkeypatch.setattr(
        run_scoring.gap_engine, "run",
        lambda *a, **k: (ran.append("gap"),
                         _fake_result(ScoreRunResult, failed=[("00000009", "boom")]))[1],
    )
    monkeypatch.setattr(run_scoring.mna_engine, "run",
                        lambda *a, **k: (ran.append("mna"), _fake_result(MnaRunResult))[1])

    with caplog.at_level("INFO"):
        assert main(["--as-of", "2025-12-31"]) == EXIT_INCOMPLETE
    assert ran == ["gap", "mna"]
    assert "[gap]" in caplog.text and "[mna]" in caplog.text


def test_exit_one_if_either_engine_incomplete(monkeypatch) -> None:
    """AC6: 둘 중 하나라도 불완전하면 1 — mna 쪽이 실패해도 마찬가지."""
    monkeypatch.setattr(run_scoring.gap_engine, "run",
                        lambda *a, **k: _fake_result(ScoreRunResult))
    monkeypatch.setattr(
        run_scoring.mna_engine, "run",
        lambda *a, **k: _fake_result(MnaRunResult, failed=[("00000009", "boom")]),
    )
    assert main(["--as-of", "2025-12-31"]) == EXIT_INCOMPLETE


def test_mna_failure_message_says_rolled_back(monkeypatch, caplog) -> None:
    """두 엔진의 complete=False는 뜻이 다르다 — mna는 '섞였다'가 아니라 '전량 롤백됐다'."""
    monkeypatch.setattr(
        run_scoring.mna_engine, "run",
        lambda *a, **k: _fake_result(MnaRunResult, failed=[("00000009", "boom")]),
    )
    with caplog.at_level("ERROR"):
        assert main(["--as-of", "2025-12-31", "--engine", "mna"]) == EXIT_INCOMPLETE
    assert "전량 롤백" in caplog.text
    assert "섞여" not in caplog.text


def test_cli_flags_incomplete_failure_list_on_db_abort(monkeypatch, caplog) -> None:
    """DB 오류 중단 시 CLI가 '목록이 완전하지 않다'를 알린다 — 실패 1건만 보고 안심하면 안 된다."""
    monkeypatch.setattr(
        run_scoring.mna_engine, "run",
        lambda *a, **k: MnaRunResult(
            scored=0, failed=[("00000001", "NOT NULL constraint failed")],
            aborted_early=True,
        ),
    )
    with caplog.at_level("ERROR"):
        assert main(["--as-of", "2025-12-31", "--engine", "mna"]) == EXIT_INCOMPLETE
    assert "완전하지 않다" in caplog.text
```

### 문서 변경 (diff)

README 실행 안내와 deferred-work.md의 defer 해소 기록입니다.

```diff
diff --git a/README.md b/README.md
index dee4966..82a299a 100644
--- a/README.md
+++ b/README.md
@@ -37,8 +37,9 @@ cd dashboard && npm install && cd ..
 # 2) 프론트 대시보드  →  http://localhost:5175 (Vite proxy → :8000)
 cd dashboard && npm run dev
 
-# 3) valueup_score 재계산  →  종료 코드 0=완전 / 1=부분 실패 / 2=입력 오류
+# 3) 스코어 재계산(기본 두 엔진)  →  종료 코드 0=완전 / 1=부분 실패 / 2=입력 오류
 .venv/Scripts/python -m app.analysis.run_scoring --as-of 2026-07-13
+.venv/Scripts/python -m app.analysis.run_scoring --as-of 2026-07-13 --engine gap   # 한쪽만
 
 # 4) Tableau용 CSV 스냅숏  →  exports/tableau/*.csv + manifest.json
 .venv/Scripts/python -m app.export.tableau            # 두 엔진 공통 최신 기준일
@@ -53,19 +54,18 @@ cd dashboard && npm run dev
 > → `.twbx` 재패키징. CSV가 `progress_rate`를 담고 `.twbx`는 그 CSV를 임베드하므로, 하나만
 > 갱신하면 레이어 간 값이 어긋납니다.
 
-데이터 수집과 M&A 스코어링은 아직 Python API로 실행합니다(배치 CLI는 gap 엔진부터 도입 중):
+두 엔진의 **트랜잭션 정책은 의도적으로 다릅니다**. `valueup_score`는 종목별 절대 측정치라
+종목별 커밋 + 실패 목록(부분 성공 보존)이고, `mna_score`는 **백분위 순위**라 전량 원자성입니다 —
+세대가 섞인 순위표는 "일부만 오래된 값"이 아니라 순위 자체가 무의미해지기 때문입니다.
+그래서 mna는 한 종목만 실패해도 전량 롤백되며, 실패 종목·사유는 그래도 보고됩니다.
 
-```python
-from app.db import SessionLocal
-from app.ingest import run as ingest          # ingest_financials / prices / macro / valueup_plans / ownership
-from app.analysis import mna_engine
+데이터 수집은 아직 Python API로 실행합니다:
 
-with SessionLocal() as s:
-    with s.begin():
-        mna_engine.run(s, as_of="2026-07-13")  # mna_score 계산·upsert (유일 writer)
+```python
+from app.ingest import run as ingest   # ingest_financials / prices / macro / valueup_plans / ownership
 ```
 
-테스트: `pytest -q`(백엔드 261) · `cd dashboard && npm test`(프론트 56) · 마이그레이션 `alembic upgrade head`(0001~0011).
+테스트: `pytest -q`(백엔드 271) · `cd dashboard && npm test`(프론트 56) · 마이그레이션 `alembic upgrade head`(0001~0011).
 
 ## 아키텍처 (AD 요약)
 
diff --git a/docs/implementation-artifacts/deferred-work.md b/docs/implementation-artifacts/deferred-work.md
index 6148d11..407963a 100644
--- a/docs/implementation-artifacts/deferred-work.md
+++ b/docs/implementation-artifacts/deferred-work.md
@@ -150,13 +150,13 @@ buyback 집계는 실공시 샘플 없이 보수적 규칙(총계 우선·상충
   결정으로 이미 닫혀 있어 재론하지 않았고, API 노출은 배포 스토리 몫으로 남는다. 근거: 배치의
   1차 소비자는 셸·스케줄러이고 종료 코드가 그 계층이 이해하는 유일한 신호 — 요약만 찍고 0을
   반환하면 엔진이 애써 노출한 `complete`가 그 지점에서 다시 숨겨진다.
-- **`mna_engine.run()` 미적용** — 같은 `session.flush(); return count` 형태가 남아 있다. gap_engine과
-  달리 **cross-sectional**(모집단을 루프 전에 한 번 구성)이라 부분 실패의 의미가 다르고, 이미
-  "부분 실행 시 population snapshot 혼재" 한계가 docstring에 문서화돼 있다. 같은 정책을 그대로
-  옮길지, 모집단 특성상 전량 원자성이 맞는지는 별도 판단 필요.
-  **트리거: mna 배치 실호출자 스토리, 또는 gap_engine 정책 안정화 후.**
-  → 2026-07-22 Story 4-1에서 gap 정책이 실호출로 안정화됐으므로 **트리거 발동 상태**.
-  4-1은 두 개의 무관한 결정이 한 번에 승인되는 것을 피하려 gap만 다뤘다. **후속: Story 4-2.**
+- ~~**`mna_engine.run()` 미적용**~~ — **해소(2026-07-22, Story 4-2)**. 판단 결과는 gap과 **반대**인
+  **전량 원자성 + 실패 보고**였다. 근거: (1) `mna_target_score`는 백분위 순위라 세대가 섞이면
+  "일부만 오래된 값"이 아니라 순위 자체가 무의미해진다(gap은 종목별 절대 측정치라 다르다),
+  (2) 읽기가 전부 루프 이전에 끝나 루프 안은 순수 계산 + upsert뿐이라 종목별 커밋이 방어할
+  실패 유형 자체가 구조적으로 적다, (3) gap에서 원자성을 기각한 사유("실패 정보까지 소실")는
+  실패 목록을 DB가 아니라 `MnaRunResult`·로그로 남기면 해소된다 — 롤백되는 건 점수뿐이고
+  실패 사실은 보고된다. 세션 소유권도 엔진으로 이동(`run(as_of, corp_codes, *, session_factory)`).
 
 ## Deferred from: code review 전체 스캔 (2026-07-21, party 리뷰)
 
```
