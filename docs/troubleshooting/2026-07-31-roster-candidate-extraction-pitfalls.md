# 후보 명단 검토에서 드러난 추출 오류 유형 (2026-07-31)

링크 선수 명단 DB 트랙 (#170~#182) 이 2026-07-31 에 운영을 시작했다.
첫날 백필 419행을 처리해 신규 후보 90명이 등재됐다 (총 92명 · 확정 41 · 보관 8).
그 목록을 사람이 검토하는 과정에서 모델 추출의 오류 유형이 여러 개 드러났다.
검토로 걸러낸 오류는 10건, 약 11% 였다.
유형별로 실제 사례와 판별법 · 처리를 남긴다.

## 1. 표기 변형으로 같은 사람이 두 행 (실제 8건)

매칭 (`roster.record_article_players`) 은 접힌 영문 풀네임의 정확 일치를 먼저 보고, 성 단독 폴백은 모델이 한 단어만 냈을 때에만 쓴다.
성 폴백을 넓히면 동성 타인 기사가 기존 선수에게 붙는 오연결이 생기기 때문에 의도적으로 좁혀 둔 것이다.
그 대가로 철자 변형은 구조적으로 못 잡는다.

사례:

- `Junior Kroupi` (id 120) 와 `Eli Junior Kroupi` (121)
- `Vinicius Jr` (199) · `Vinícius José Paixão de Oliveira Júnior` (208) 와 확정된 `Vinicius Junior` (118)
- `Axel Dontchev` (200) 와 `Axel Donczew` (182)
- `Miles Lewis-Skelly` (155) 와 `Myles Lewis-Skelly` (125)
- `Mali Salmon` (156) 와 `Marli Salmon` (154)
- `Ilan Meslier` (209) 와 확정된 `Illan Meslier` (16)

처리: 런북 §5 의 병합 절차를 따른다 — 연결을 남길 행으로 옮긴 뒤 없앨 행을 보관 처리한다.

## 2. 그림자 행 — 이미 확정된 선수가 다른 이름으로 다시 등재 (실제 1건)

`Gabriel` (id 195) 이 확정된 `Gabriel Magalhaes` (20) 와 별개 행으로 생겼다.
모델이 성 없이 이름만 내면 추출된 성 (`Gabriel`) 이 확정 행의 성 (`Magalhaes`) 과 달라 매칭이 실패한다.

판별: 연결된 기사 본문을 읽어 누구인지 확정한다.
이 건은 원문에 "They also have Gabriel, Riccardo Calafiori, Cristhian Mosquera, Jurrien Timber and Ben White as centre-back options" 가 있어 마갈량이스로 특정됐다.

## 3. 한글 표기와 영문명이 어긋난 행 (실제 1건)

한글 `크루피` 에 영문 `Milos Kerkez` 가 붙은 행 (id 129) 이 생겼다.
근거 기사는 크루피를 다룬 한국어 게시글이고, 원문 전체에 Kerkez 언급이 0건이다.
둘 다 본머스 소속이라 모델이 혼동한 것으로 보인다.

판별: 근거 기사 원문에서 영문명을 검색해 없으면 오결합이다.
처리: 잘못 붙은 기사 연결을 올바른 선수로 옮기고, 행 자체는 표기를 바로잡아 후보로 남겼다.

## 4. 동명이인

`Neco Williams` (노팅엄 포레스트 · 웨일스) 와 `Nico Williams` (스페인) 가 둘 다 `니코 윌리엄스` 라는 같은 한글 표기로 등재돼 있었다.
정정: Neco 는 `니코 윌리엄스`, Nico 는 `니코 윌리암스` 로 사용자가 확정했다.

판별: 풀네임만으로는 부족하고 국적 · 소속을 함께 확인해야 한다.
성 단독 표기로 확정하면 두 선수가 충돌한다.

## 5. 접미어가 영문 성으로 잡힘

`Charles Sagoe Jr` 의 성이 `Jr` 로, `Vinicius Junior` 의 성이 `Junior` 로 추출됐다 (성 = 영문명의 마지막 토막).
후자는 확정된 상태라 실제로 오탐을 냈다.
인명 누락 검출 축이 원문 제목의 `\bJunior\b` 를 비니시우스 근거로 보고, `Eli Junior Kroupi` 가 든 기사 제목을 "비니시우스가 원문에 있는데 번역에서 빠졌다" 로 판정해 불필요한 재번역을 유발했다.
실측 대상 1건이었다 (원문 제목에 Junior 가 든 기사 16건 중 비니시우스가 아닌 것 1건).

처리: 성을 `Sagoe` · `Vinicius` 로 정정했다.
확정 전 점검 절차는 런북 §3.2 에 있다.

재발 방지 후속 후보 (미구현): 후보 등재 시 접미어 (`Jr` · `Sr` · `Jnr` · `II` · `III`) 를 성 추출에서 제외하는 코드 개선이다.
지금은 사람이 확정 전에 확인하는 것으로 막고 있다.

## 6. 검토에 쓸 수 있는 확인 쿼리

아래 두 검사를 실제로 돌려 병합 누락 0건을 확인했다.
재사용 가능한 형태로 남긴다.

### 6.1. 확정 선수와 영문 성이 같은 후보 찾기 — 병합 누락 의심

성 비교는 `Júnior` 대 `Junior` 처럼 분음부호 차이로 SQL 문자열 비교가 놓치는 쌍이 있어, 파이프라인과 같은 접힌 비교 (`enrich._fold_latin`) 가 필요하다.
런북 §2.3 이 안내하는 관례대로 여러 줄 스크립트는 파일로 만들어 실행한다.

```python
"""확정 선수와 영문 성이 같은 후보를 찾는다 — 병합 누락 의심.
casefold + 분음부호 제거 비교라 SQL LIKE 로는 못 잡는 쌍까지 걸러낸다."""
import os
from sqlalchemy import create_engine, text
from bullet_in.enrich import _fold_latin

engine = create_engine(os.environ["MARIADB_URL"])
with engine.connect() as c:
    rows = c.execute(text("SELECT id, full_name, surname, status FROM players")).all()

grouped: dict[str, list[tuple[int, str, str]]] = {}
for pid, full_name, surname, status in rows:
    grouped.setdefault(_fold_latin(surname), []).append((pid, full_name, status))

for surname, group in grouped.items():
    statuses = {status for _, _, status in group}
    if "candidate" in statuses and statuses - {"candidate"}:
        print(surname, group)
```

### 6.2. 한글 표기가 다른 표기 안에 부분 포함되는 쌍 찾기 — 검출 겹침

```sql
SELECT a.id AS a_id, a.ko_name AS a_ko, b.id AS b_id, b.ko_name AS b_ko
FROM players a
JOIN players b ON a.id != b.id AND b.ko_name LIKE CONCAT('%', a.ko_name, '%')
WHERE a.status IN ('confirmed','archived') AND b.status IN ('confirmed','archived')
  AND a.ko_name IS NOT NULL AND b.ko_name IS NOT NULL;
```

실측 2건 — `사카` 가 `아론 완-비사카` 안에, `화이트` 가 `모건 깁스-화이트` 안에 부분 포함된다.
이 둘은 게이트가 원문의 영문 철자도 함께 보기 때문에 오탐으로 이어지지는 않는다.
다만 검출 관점에서는 두 선수가 구분되지 않는다는 뜻이라는 점은 남겨 둔다.

## 7. 남는 교훈

모델 추출은 연결 (기사 ↔ 선수) 에는 충분히 쓸 만하지만, 이름 자체는 사람이 확정하기 전까지 신뢰할 수 없다.
후보를 게이트 · 서빙 사전에서 빼 두는 설계 (스펙 §3.2) 가 이 오류들이 검출 · 화면에 새지 않게 막았다.
오류 대부분은 확정 전에 목록을 훑는 것만으로 걸러진다.

## 8. 참고

- 설계 스펙: `docs/superpowers/specs/2026-07-31-player-roster-db-design.md`
- 운영 런북: `docs/runbook/2026-07-31-player-roster-ops.md`
- 매칭 로직: `src/bullet_in/roster.py` (`record_article_players`)
- 접힌 비교 함수: `src/bullet_in/enrich.py` (`_fold_latin`)
