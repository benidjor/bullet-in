# 사다리 줄 단계가 기사 상세 배지와 다른 것은 결함이 아니다 — 이중 해상도

2026-08-07 사다리 배포 직후 사용자가 실제로 결함으로 의심한 사례다.
같은 질문이 다시 나올 수 있어 진단 절차까지 적는다.

## 1. 증상

기마랑이스 선수 페이지의 사다리에서 `루머` 줄 대표 기사 ("브루노 기마랑이스, 아스날 이적 가능성 증폭") 를 열면, 기사 상세 페이지의 배지는 `협상 중` 이다.
같은 기사가 화면 두 곳에서 다른 단계로 보인다.

## 2. 원인 — 단계 값이 두 계층에 따로 있다

2026-08-02 이중 해상도 결정의 결과다.
한 기사가 여러 선수를 서로 다른 단계로 언급할 수 있어, 기사 단위 값과 선수 귀속 값을 따로 저장한다.

| 계층 | 컬럼 | 소비하는 화면 |
| --- | --- | --- |
| 기사 단위 | `articles.transfer_stage` | 기사 상세 · 목록 카드의 단계 배지 · 사이드바 집계 |
| 선수 귀속 | `article_players.stage` | 선수 페이지 사다리 · 색인 배지 · 머리 현재 단계 |

사다리는 귀속 값으로 묶으므로, 이 기사는 기마랑이스의 `루머` 묶음에 들어가 그 줄의 대표가 됐다.
화면은 두 곳 다 자기 계층의 값을 정확히 보여 준다.

## 3. 이 사례에서 실제로 틀린 것 — 귀속 값 자체

해시 `e5ad5c1a58f04ee8ea1c1ff2a70936ec7f3c052ca70393ddefce406644a348c6` 의 실측 (2026-08-07 VM DB).

- `articles.transfer_stage` = `negotiating`
- `article_players.stage` (기마랑이스) = `rumour`

제목에 선수가 한 명뿐인 기사인데도 두 값이 갈라졌다.
다주제 라운드업이라 갈라진 것이 아니라, 귀속 추출이 기사에 근거하지 않은 값을 냈다.
이 값 정정은 선수별 단계 재추출 트랙 소관이다.
이 기사는 그 트랙의 dry-run 대조군 예시로 등록돼 있다 (세션 메모리 player-stage-not-grounded-track).

## 4. 진단 절차 — 사다리를 의심하기 전에 두 계층 값을 대조한다

```sql
SELECT a.transfer_stage AS 기사단계, ap.stage AS 귀속단계, p.full_name
FROM articles a
LEFT JOIN article_players ap ON ap.content_hash = a.content_hash
LEFT JOIN players p ON p.id = ap.player_id
WHERE a.content_hash = '<해시>';
```

- 두 값이 다르고 화면이 각자 자기 값을 보여 주면 — 표시 계층은 정상 · 귀속 값 문제 (재추출 트랙).
- 화면이 자기 계층의 값과 다르면 — 그때가 렌더 결함이다.

## 5. 참조

- 이중 해상도 결정: `docs/superpowers/specs/2026-08-03-serve-player-pages-resume-design.md` 계보 · 단계 재분류 트랙 (2026-08-02)
- 귀속 값 미근거 문제: `docs/troubleshooting/2026-08-03-player-stage-not-grounded-in-article.md`
- 정의를 안 읽고 결함으로 오진한 전례 모음: `docs/troubleshooting/2026-08-04-called-design-a-defect-without-reading-it.md`
