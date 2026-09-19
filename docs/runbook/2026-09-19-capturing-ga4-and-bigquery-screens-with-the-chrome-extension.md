# 구글 로그인이 필요한 화면 (GA4 · BigQuery) 을 Chrome 확장으로 찍기

README 와 소개 자료에 GA4 · BigQuery 캡처를 넣은 회차 (2026-09-18) 에서 쓴 절차다.
헤드리스 Playwright 는 구글 로그인을 못 지나므로 사용자의 Chrome 에 붙는 확장 (`claude-in-chrome`) 으로 찍는다.

## 1. 무엇을 찍었나

| 캡처 | 화면 | 주소 요령 |
| --- | --- | --- |
| 공개 주간 사용자 | GA4 보고서 개요 | `reports/reportinghub?params=_u..nav%3Dmaui%26_u.date00%3D20260829%26_u.date01%3D20260904` 처럼 기간을 주소에 넣는다 |
| 이벤트 목록 | GA4 보고서 → 이벤트 (`r=top-events`) | 같은 방식으로 기간 지정 · 스크롤해 표만 |
| `card_hash` 매개변수 | GA4 실시간 개요 → 이벤트 이름 클릭 → 매개변수 키 목록 | 30분 안의 이벤트가 있어야 뜬다 (§3) |
| BigQuery 링크 | GA4 관리 → BigQuery 링크 → 행 클릭 | 내보내기 유형 「매일」 · 위치가 보이는 자리까지 |
| 일별 표 목록 | BigQuery 콘솔 데이터셋 `analytics_<속성ID>` | `?ws=!1m4!1m3!3m2!1s<프로젝트>!2s<데이터셋>` |

## 2. 절차

1. `tabs_context_mcp` 뒤 `resize_window` 1440 × 900.
2. 페이지가 SPA 라 `navigate` 뒤 5 ~ 8초 기다린 뒤 `screenshot(scale=0.6)` 으로 자리를 본다.
3. 두 블록을 한 장에 넣어야 하면 `javascript_tool` 로 `document.body.style.zoom = '0.7'` 을 준다 (데이터는 안 바뀐다 · 배율만).
4. 커서를 헤더의 빈 곳으로 `hover` 한 뒤 `computer(action="zoom", region=[0,0,1200,797], save_to_disk=true)` 로 받는다.
   `screenshot` 은 1200 폭 JPEG 이고 `zoom` 은 1349 × 896 PNG 라 후자를 쓴다.
   커서가 찍히므로 마지막 `hover` 자리가 곧 커서 자리다.
5. 저장 경로는 결과에 찍히는 임시 폴더다.
   스크래치패드로 바로 복사한다.
6. 가림은 Pillow 로 회색 상자를 그린다 (계정 이메일 · 프로젝트 ID · 프로젝트 번호).
   좌표는 1349 × 896 PNG 기준으로 재고, 가리기 전 원본은 `*.raw.png` 로 남긴다.

## 3. 함정

- **`card_hash` 는 맞춤 측정기준이 아니라 표준 보고서에 카드가 없다.**
  실시간 개요의 「이벤트 이름별 이벤트 수」 에서 이벤트를 누르면 매개변수 키 목록이 나오는데, 30분 안의 이벤트가 있어야 한다.
  사이트에서 카드를 하나 누르면 되는데, 클릭 추적 선택자는 `a.item · sameline · mitem · pcard · tltitle` 이라 홈의 대표 기사 링크는 안 잡힌다.
  그 클릭 1건은 운영 GA 데이터에 남으므로 보고에 적는다.
- **macOS `screencapture` 는 못 쓴다.**
  창 위치를 AppleScript 로 물으면 권한 대화상자에 걸려 시간 초과다.
- **주소의 보고서 id 는 짐작하지 않는다.**
  틀리면 홈으로 돌아간다.
  사이드바에서 한 번 눌러 주소를 얻은 뒤 기간 매개변수만 붙인다.
- **GA4 화면의 사용자 수는 대시보드 · BigQuery 와 같은 창으로 대 본다.**
  이번에 그 대조가 890 → 827 정정을 냈다 (`docs/troubleshooting/2026-09-19-the-launch-week-number-was-the-whole-table.md`).
