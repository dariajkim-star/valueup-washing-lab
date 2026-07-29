# attachments/ — 밸류업 계획 첨부(PDF) 보관소

여기에 둔 파일은 `python -m app.ingest.run_attachments`가 읽어 `plan_attachment` 테이블에 적재한다.

## 왜 수동으로 받는가

DART의 `robots.txt`가 첨부에 닿는 경로를 **전부** 금지한다(2026-07-29 확인):

```
Disallow: /dsaf001/main.do        ← 공시 뷰어
Disallow: /report/viewer.do
Disallow: /report/download.do     ← 첨부 다운로드
Disallow: /pdf/download/          ← PDF 다운로드
Disallow: /dsae001/selectPopup.ax ← 첨부 팝업
```

운영자가 기계가독 형식으로 명시한 지시이므로 자동 취득을 하지 않는다.
사람이 브라우저로 받는 것은 여기 해당하지 않는다 — **취득은 사람이, 파싱은 코드가** 한다.

이 분업으로 잃는 것은 없다. 파이프라인의 값은 취득이 아니라 파싱·목표추출·출처기록에 있고,
그쪽은 전혀 막히지 않았다.

## 파일 이름 규약

둘 중 하나로 저장한다. 이름이 곧 "어느 공시의 첨부인가"를 말하므로 규약을 벗어나면
배치가 사유와 함께 건너뛴다(조용히 추측하지 않는다).

| 형식 | 예시 | 비고 |
|---|---|---|
| `{접수번호}.pdf` | `20241127800702.pdf` | **권장** — 접수번호가 공시의 신원(0015) |
| `{corp_code}_{공시일}.pdf` | `00164779_2024-11-27.pdf` | 접수번호를 아직 모를 때 |

접수번호는 화면(종목 상세 → 출처 → DART 원문)이나 `valueup_plan.rcept_no`에서 확인할 수 있다.
`rcept_no`가 비어 있으면 상세 화면의 **업데이트** 버튼을 눌러 재수집하면 채워진다.

## 실행

```bash
python -m app.ingest.run_attachments --dry-run   # DB에 쓰지 않고 결과만
python -m app.ingest.run_attachments             # 적재
python -m app.ingest.run_attachments --force     # 내용이 같아도 재파싱
```

같은 파일을 다시 돌려도 안전하다(sha256 비교로 건너뛴다). 파일 내용이 바뀌면 자동으로 다시 읽는다.

## 못 읽는 경우

`parse_error`에 사유가 남고, **"목표 미공시"로 취급하지 않는다.**

| 사유 | 뜻 |
|---|---|
| `unsupported_format:hwp` | HWP는 순정 파서가 없다 |
| `no_text_layer` | 스캔 이미지 PDF — 텍스트 레이어 없음 |
| `parse_error:...` | 파일 손상 등 |

"회사가 공시하지 않았다"와 "우리가 읽지 못했다"는 다른 범주다. 이 구분이 무너지면
`is_unrankable`에서 지킨 원칙("못 읽은 걸 벌하지 않는다")이 첨부 층에서 되살아난다.

## git 추적 안 함

PDF는 타사 저작물이고 용량이 크다. `.gitignore`가 이 폴더의 파일을 제외하며,
이 README와 폴더 구조만 추적한다. 파싱 결과(목표·근거 페이지·원문 텍스트)는 DB에 남으므로
파일을 지워도 분석 결과는 보존된다.
