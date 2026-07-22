# Story 4-1 — 스코어링 배치 CLI (`run()` 첫 실호출자)

- **에픽**: 4 운영·배치 (v1 이후 신규)
- **상태**: review (구현·라이브 검증 완료, GPT 교차리뷰 대기)
- **작성일**: 2026-07-22
- **선행**: PR #1(`gap_engine` 트랜잭션 정책 확정 + `progress_rate` 일 단위 정합화, main `2ed33ef`)

## 배경

`gap_engine.run()`은 2026-07-21 party 코드리뷰에서 트랜잭션 정책이 확정되며
`ScoreRunResult(scored/deleted/succeeded/failed/complete)`를 반환하도록 바뀌었다.
그런데 **프로덕션 호출자가 없다** — 테스트만 호출한다. 그 결과 두 가지가 미결로 남았다.

1. `ScoreRunResult.complete`(부분 실패 스냅샷 여부)를 **확인하는 주체가 없다**
   (deferred-work.md, 트리거: "run() 실호출자 스토리")
2. 재계산 수단이 없다 — 2026-07-22 `progress_rate` 산식 변경분 반영은
   `python -c "from app.analysis import gap_engine; gap_engine.run(...)"` 인라인 호출로 때웠다.
   이 스토리가 그 임시 수단을 대체한다.

## 범위

**`gap_engine`만.** `mna_engine.run()`도 구식 시그니처(`session` 인자 + `int` 반환)로 남아 있고
deferred-work.md에 "mna 배치 실호출자 스토리" 트리거가 걸려 있으나, mna는 **cross-sectional**
(모집단을 루프 전 1회 구성)이라 부분 실패의 의미가 gap과 다르다 — 종목별 커밋이 옳은지 자체가
별도 판단이다. 같은 스토리에 끼워넣으면 두 개의 무관한 결정이 한 번에 승인되므로 분리한다.
**후속: Story 4-2(mna 배치 호출자 + 정책 판단).**

## 결정

### D1. `complete` 소비 = 종료 코드 + 경고 로그 (테이블 아님)

`score_run` 배치 메타데이터 테이블은 2026-07-14 리드 결정으로 **이미 닫혔다**
(v2 백로그 "멀티유저·운영 서비스화 시" 트리거, README 한계 §2). 그러므로 이 스토리에서
재론하지 않는다. CLI 네이티브 해법을 쓴다.

| 종료 코드 | 의미 |
|---|---|
| 0 | `complete=True` — 전 종목 동일 시점 스냅샷 |
| 1 | `complete=False` — 부분 실패, 같은 as_of에 실행분이 섞여 있음 |
| 2 | 사용법·입력 오류(argparse 관례, 잘못된 `--as-of` 포함) |

근거: 배치의 1차 소비자는 사람이 아니라 **셸·스케줄러**다. 종료 코드는 그 계층이 이미
이해하는 유일한 신호이고, "N건 완료"만 찍고 0을 반환하면 엔진이 애써 노출한 `complete`가
정확히 그 지점에서 다시 숨겨진다. 실패 목록은 `(corp_code, reason)` 전건을 로그로 출력한다
(잘라내지 않는다 — 무엇이 왜 실패했는지가 종목별 커밋 정책을 택한 이유이므로).

### D2. `--as-of` 필수 (시스템 시계 미사용)

기본값을 `date.today()`로 두지 않는다. `progress_rate`가 as_of에 직접 의존하므로
암묵적 오늘 날짜는 **재현 불가능한 실행**을 만든다. 3-1에서 매크로 as_of 기본값을 정할 때도
같은 이유로 시스템 시계를 배제했다(자체 최신 관측일 사용) — 그 원칙을 잇는다.

### D3. `--corp-codes` 부분 실행은 허용하되 경고

엔진 docstring이 "게시용 점수는 전체 실행"을 계약으로 명시한다. CLI도 부분 실행을 막지는
않되(디버깅에 필요) **경고 로그로 게시 부적합을 알린다**. `complete=True`여도 부분 실행이면
스냅샷은 여전히 부분적이다 — 두 개념이 다르다는 점을 로그가 구분해서 말해야 한다.

## 인수 조건

- **AC1** `python -m app.analysis.run_scoring --as-of YYYY-MM-DD`로 전 종목 재계산이 실행된다.
- **AC2** 실행 결과 요약(scored/deleted/failed/complete)이 로그로 출력된다.
- **AC3** `complete=True`면 종료 코드 0, `complete=False`면 1을 반환한다.
- **AC4** 실패 종목은 `(corp_code, 사유)` 전건이 로그에 출력된다.
- **AC5** `--as-of` 미지정 시 종료 코드 2로 실패한다(시스템 시계로 대체하지 않는다).
- **AC6** 잘못된 `--as-of`(형식·달력 무효)는 트레이스백이 아니라 종료 코드 2 + 사람이 읽을 수
  있는 메시지로 실패한다.
- **AC7** `--corp-codes` 부분 실행 시 "게시용 아님" 경고가 출력된다.
- **AC8** 기존 테스트 전건 통과(251 passed) + CLI 테스트 신규.

## 비범위

- `mna_engine` 배치 호출자 → Story 4-2
- `POST /scoring/run` HTTP 라우터 → 배포 스토리(현재 전 엔드포인트 무인증, deferred 보안 게이트)
- `score_run` 메타데이터 테이블 → v2 백로그(리드 결정으로 닫힘)
- gap_engine N+1 최적화 → 유니버스 확대 스토리의 선행 조건으로 이미 defer됨

## 검증 계획

- 단위: `main(argv)` 반환값으로 종료 코드 3종(0/1/2) 검증, 부분 실행 경고 검증
- 통합: SQLite in-memory + `session_factory` 주입(2.1 테스트 seam 재사용)으로 실제 스코어 기록 확인
- 라이브: 실 DB에 `--as-of 2026-07-13` 재실행 → 2026-07-22 인라인 호출 결과와 **동일**해야 함
  (멱등성 실증: scored 26 / deleted 7 / failed 0 / complete True)

## 검증 결과 (2026-07-22)

**테스트**: 251 → **261 passed** (CLI 10종 신규). 실패 주입은 `ScoreRunResult`를 직접 만들어
넣는다 — 엔진이 실패를 *어떻게* 만드는지는 2.1의 관심사고, 이 모듈의 관심사는 실패가 있을 때
**조용히 0을 반환하지 않는다**는 것뿐이기 때문이다.

**라이브(실 DB, valueup.db 33종목)**:

| 실행 | 출력 | 종료 코드 |
|---|---|---|
| `--as-of 2026-07-13` | `scored=26 deleted=7 failed=0 complete=True` | 0 |
| (미지정) | argparse `required` 오류 | 2 |
| `--as-of 2026-02-30` | `입력 오류: as_of가 달력상 유효한 날짜가 아닙니다` | 2 |
| `--as-of 2026-07-13 --corp-codes 00106641` | `부분 실행(1종목) … **게시용 아님**` + `scored=1 complete=True` | 0 |
| `--corp-codes " , "` | `입력 오류: 유효한 corp_code가 없습니다` (엔진 미도달) | 2 |

**멱등성 실증**: 전체 실행 전/후 `valueup_score` 전 행 해시 `2d84c01a5a5ef5b0`(26행) **불변**,
2026-07-22 인라인 호출 결과(26/7/0/True)와 정확히 동일. 부분 실행 후에도 동일 해시.

**설계 중 발견**: 빈 `--corp-codes`가 엔진에 `[]`로 도달하면 "대상 0종목"으로 `complete=True`,
`scored=0`, 종료 코드 0이 된다 — 전체 실행과 구분되지 않는 **조용한 무작업**이고, 이 스토리가
만들려는 신호 자체가 거짓이 되는 경로다. `_parse_corp_codes`에서 엔진 도달 전에 차단했다
(테스트가 `called is False`로 차단 지점을 고정한다).

## 인계

- **Story 4-2(mna 배치 호출자)**: gap 정책이 실호출로 안정화됐으므로 deferred-work.md의
  `mna_engine.run()` 트리거가 발동 상태. cross-sectional 특성상 종목별 커밋이 맞는지부터 판단 필요.
- **재계산 표준 절차**: 스코어 산식이 바뀌면 `run_scoring` → `app.export.tableau` →
  `.twbx` 재패키징 순서로 세 레이어를 정렬해야 한다(2026-07-22 실증). CSV에 `progress_rate`가
  있고 `.twbx`는 CSV를 임베드하므로 어느 하나만 갱신하면 레이어 간 값이 어긋난다.
