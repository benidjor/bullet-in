# 자리를 옮겼더니 기사가 아예 안 보이게 됐다 (2026-08-28)

홈 카드 접기 (안건 π) 는 접혀 있던 기사를 꺼내 자기 날짜에 카드로 세운다.
그런데 **꺼낸 자리에서 안 보이는 기사**가 있었고, 꺼내면서 원래 자리에서도 빼기 때문에
그 기사는 **아무 데서도 안 보이게 됐다.**

배포하고 나서 브라우저로 숨은 카드를 세다가 발견했다.

## 1. 무슨 일이었나

꺼내기는 두 가지를 함께 한다.

1. 접힌 기사를 낱개 카드로 세운다
2. **원래 카드의 관련 보도에서 그 기사를 뺀다** — 안 그러면 같은 기사가 두 자리에 나오고 날짜 머리글 건수도 두 번 센다

2번이 맞는 처리인데, 1번이 **실패할 수 있다는 것을 안 봤다.**

| 자리 | 그 기사가 보이나 |
| --- | --- |
| 관련 보도 안 (원래 자리) | **보인다** — 필터가 없으면 접힘 안의 항목은 전부 그려진다 |
| 낱개 카드 (옮긴 자리) | **안 보인다** — 단계가 「기타」 면 `app.js` 가 카드를 감춘다 (`isOther`) |

배포된 화면에서 실제로 한 장이 그렇게 사라져 있었다.
Marca 「줄리안 알바레스, 컨디션 난조로 아틀레티코 마드리드 훈련 이틀 연속 결장」.

## 2. 두 자리의 규칙이 달랐다

`app.js` 는 필터가 없을 때 **단계가 비었거나 「기타」 인 카드를 감춘다.**

```javascript
const isOther = (!d.stage || d.stage === 'other');
const okStage = isOther ? (showOther || ...) : ...;
```

그런데 **접힘 안의 항목 (`.relitem`) 에는 그 규칙이 안 걸린다.**
필터가 없으면 접힘을 펼쳤을 때 전부 그려진다.

브라우저에서 확인한 값이다.

```
관련 보도 항목 51 · 그중 기타 단계 2
기타 항목의 computed display: flex, flex     ← 필터 없이도 그려짐
```

**같은 기사가 자리에 따라 보이기도 하고 안 보이기도 한다.**
그 차이를 모르고 옮기면 조용히 사라진다.

## 3. 같은 모양이 하나 더 있었다 — 공신력 최하

고치고 보니 **공신력 최하도 같은 자리**였다.

꺼내기 이전에는 최신 소식에 최하 카드가 설 수 없었다 (세 자리가 막고 있었다 —
`docs/troubleshooting/2026-08-28-we-measured-one-screen-and-talked-about-another.md` §4).
꺼내기가 접힘에서 직접 카드를 만들면서 그 셋을 우회했고, 최하가 첫 화면에 서기 시작했다.

이쪽은 **사라지는 것이 아니라 없던 것이 나타난 것**이라 방향이 반대지만,
원인은 같다 — **옮긴 자리의 규칙을 안 봤다.**

## 4. 처방

꺼낼 수 있는지 묻는 함수를 하나 두고 두 조건을 함께 넣었다.

```python
def _promotable(row: dict) -> bool:
    stage = row.get("transfer_stage")
    if not stage or stage == "other":
        return False                    # 카드로는 감춰진다 — 접힌 채로 둔다
    tier = row.get("tier")
    return tier is None or float(tier) < 4.0   # 최하는 원래 카드가 안 됐다
```

실측은 이렇다 — 되돌아간 기사 1건 (기타 단계) · 안 꺼내게 된 기사 9건 (최하) ·
최신 소식 블록 113개 중 대표 카드가 최하인 것 0개.

## 5. 교훈

**자리를 옮기는 변경은 「옮기기 전 자리에서 보이던 조건」 과 「옮긴 자리에서 보이는 조건」 을 함께 본다.**

이 저장소의 홈은 같은 기사를 세 가지 모양으로 그린다.

| 모양 | 감추는 규칙 |
| --- | --- |
| 카드 (`.item`) | 단계가 「기타」 면 필터 없이는 감춤 · 밴드 재출현이면 감춤 |
| 접힘 항목 (`.relitem`) | 필터가 없으면 전부 그림 |
| 가십 카드 | 주 단위 컷 (`_gwk`) 으로 초기 7일만 |

**옮기기 전에 그 셋 중 어디에서 어디로 가는지 적어 보면 이 사고가 안 난다.**

확인은 브라우저에서 한다 — 마크업에 있는 것과 그려지는 것이 다르다.

```javascript
// 감춰진 카드와 그 이유
[...document.querySelectorAll('.daygroup .block')]
  .filter(b => b.style.display === 'none')
  .map(b => { const it = b.querySelector('.item');
              return [it?.dataset.stage, it?.classList.contains('dupcard')]; })
```

## 함께 볼 것

- `docs/troubleshooting/2026-08-28-we-measured-one-screen-and-talked-about-another.md` — 같은 회차의 계수 · 배포 상태 오보
- `docs/superpowers/specs/2026-07-21-credibility-hierarchy-event-clustering-design.md` §7 — 상위 묶음 안의 최하를 그대로 두는 이유
- `docs/troubleshooting/2026-08-12-serving-rule-swap-with-unfilled-field.md` — 규칙을 바꾼 회차와 값이 채워지는 회차가 갈릴 때
