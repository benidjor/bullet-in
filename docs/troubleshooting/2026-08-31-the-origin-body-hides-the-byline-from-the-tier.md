# 원문 본문을 채택하면 바이라인이 등급 판정에서 사라진다 (2026-08-31)

fmkorea 전재글의 기자 이름은 제대로 저장되는데 공신력만 매체 기본값으로 떨어지는 자리가 있었다.
사용자가 준 Mundo Deportivo 두 건을 손으로 회수하다가 실물로 봤고, 소급에서 같은 고장이 BBC 까지 뻗어 있었다.

## 증상

- 화면의 기자 이름은 맞다.
- 공신력만 매체 기본값이다 — 그 기자의 등급이 더 높은데도 안 붙는다.
- **오류가 없다.** 로그도 안 남고 게이트도 안 걸린다.

```
articles.journalist = 'Roger Torelló'   ← 정확
articles.tier       = 2.0               ← Mundo Deportivo 기본값 (기자 등급은 1.5)
```

## 원인

`resolve_tier` 의 fmkorea 갈래는 기자 이름을 **제목 + 본문 텍스트에서 훑는다.**
그런데 어댑터가 원문 URL 접속에 성공하면 **원문 본문을 채택한다** (`body_level 2`).
그 순간 게시자가 적어 둔 **한글 바이라인이 `body` 에서 사라진다** — 본문이 원문 언어로 바뀌기 때문이다.

```
raw_payload["authors"] = ['Roger Torelló']            ← 원문에서 뽑음
raw_payload["body"]    = "Jefe de sección | Barça…"   ← 스페인어 · 이름 없음
→ 사전에 걸리는 별칭 0 → 매체 칸 MD 로 폴백 → 2.0
```

확정된 저자는 `journalist` 인자로 `resolve_tier` 에 **넘어오고 있었다.**
다만 그 인자를 쓰는 곳이 고정 소스 갈래뿐이었고 fmkorea 갈래는 보지 않았다.

## 고침

fmkorea 갈래가 확정 저자를 사전에 **정확 일치**로 조회해 등급 후보에 더한다 (PR #404).
순서 규칙은 그대로 두고 `min` 에 후보 하나를 얹는 형태다.

정확 일치라 별칭 부분 문자열 함정과 성격이 다르다
(`2026-07-15-credibility-registry-curation-traps.md` 함정 ④).
저장된 이름을 키로 쓰므로 미등재 이름은 아무 영향이 없다.

## 규모는 처음 본 것보다 넓었다

소급에서 6행이 바뀌었는데 **넷이 BBC 의 Sami Mokbel 이었다** (공신력 상 → 최상).

| 매체 | 기자 | 전 | 후 |
| --- | --- | --- | --- |
| Mundo Deportivo | Roger Torelló | 중 | 상 |
| Mundo Deportivo | Fernando Polo | 중 | 상 |
| BBC | Sami Mokbel | 상 | 최상 |

- 처음에는 스페인 매체 두 건만 보고 **매체 축 문제로 읽었다.**
  실제로는 **원문 본문을 채택하는 모든 소스**에서 일어난다.
- 전담 기자가 등재된 매체일수록 손해가 크다 — 매체 기본값과 기자 등급의 차이가 그대로 손실이다.
- **범위를 매체 이름으로 짐작하지 말 것** — 소급 dry-run 이 실제 범위를 알려 준다.

## 소급할 때 옛 동작을 재현하는 법

이 회차는 설정이 아니라 **코드**를 바꿨다 (`config/credibility.yaml` 무변경).
그래서 `2026-07-23-tier-recompute-stale-drift.md` 의 「old 설정 대 new 설정」 절차를 그대로 못 쓴다.

- **옛 동작 = 현재 코드에 `journalist=None`** — 그 갈래가 인자를 무시했으므로 정확히 재현된다.
- 소급 대상이 `fmkorea` · `x_afcstuff` 뿐이라 안전하다 (`journalist` 를 원래 쓰던 것은 고정 소스 갈래다).
- **판정 함수를 건드린 회차는 old 쪽도 코드까지 되돌려 재현해야 한다.**
  안 그러면 코드 변경분이 「설정 델타」 로 잘못 집계된다.

## 참고

- 고침 = PR #404 · 등재는 PR #402 · #403.
- 별칭 함정 정본 = `docs/troubleshooting/2026-07-15-credibility-registry-curation-traps.md`.
- 소급 스코프 규칙 = `docs/troubleshooting/2026-07-23-tier-recompute-stale-drift.md`.
