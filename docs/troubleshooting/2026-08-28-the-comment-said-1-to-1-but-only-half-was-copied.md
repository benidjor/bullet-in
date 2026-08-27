# 「1:1」 이라 적어 둔 함수가 반만 베끼고 있었다 (2026-08-28)

선수 확정 도구가 끝에 사이트를 다시 만든다.
그 재렌더가 **서빙 필터를 안 거쳐서**, 수집 필터 도입 전 적재분이 산출물로 돌아왔다.

```
확정 도구가 만든 site/article HTML   907개
서빙 대상 행                        838행
   → fmkorea 무관 글 50건 · 옛 글 19건이 되살아나 있었다
```

배포 전에 발견해 운영 화면에는 안 나갔다.

## 1. 함수의 주석이 정확히 반대로 적혀 있었다

```python
def _render(engine) -> None:
    """run.py 서빙 경로와 1:1 재렌더 (SERVING_SELECT_SQL import — 런북 스니펫 드리프트 방지)."""
    ...
    rows = [dict(r) for r in c.execute(text(SERVING_SELECT_SQL)).mappings().all()]
    write_site(rows, ...)
```

**드리프트를 막겠다고 적어 둔 자리에서 드리프트가 났다.**

`SERVING_SELECT_SQL` 은 `run.py` 에서 import 해 진짜로 공유했다.
그런데 `run.py` 는 그 SELECT 뒤에 한 단계를 더 태운다.

```python
rows, hidden, stale = serving_rows(rows, relevance_terms=fm.relevance_terms,
                                   player_names=fm.player_names, linked=linked)
```

**공유한 것은 SELECT 문자열뿐이고, 그 뒤 단계는 각자 베껴 갔다.**
베낀 쪽이 한 줄을 빠뜨렸는데 주석은 「1:1」 이라고 말하고 있어서, 읽는 사람이 확인할 이유를 잃었다.

## 2. 같은 누락이 런북 스니펫에도 있었다

같은 회차에 재렌더 절차를 쓰려고 런북을 열었더니 거기도 같은 모양이었다
(`docs/runbook/2026-07-27-row-recovery-cleanup.md` §5).

```python
rows = [dict(r) for r in c.execute(text(SERVING_SELECT_SQL)).mappings().all()]
write_site(rows, load_sources("config/sources.yaml"), "site", ...)
```

**같은 누락이 두 자리에 있었다** — 코드 하나 · 문서 하나.
둘 다 SELECT 만 공유하고 그 뒤를 안 맞춘 결과다.

## 3. 왜 눈에 안 띄었나

산출물이 조용히 커진다.
오류도 경고도 안 나고, **행이 늘어난 쪽으로만 틀린다.**

이번에도 확정 도구의 출력 줄 하나가 유일한 단서였다.

```
site 재생성: 907 행        ← 838 이어야 하는 자리
```

**그 숫자를 안 봤으면 그대로 배포했다.**

## 4. 처방

`_render` 를 `run.py` 와 같은 순서로 맞추고, 제외 건수를 로그로 남겼다.

```python
rows, hidden, stale = serving_rows(rows, relevance_terms=fm.relevance_terms,
                                   player_names=fm.player_names, linked=linked)
log.info("서빙 제외 — 무관 %d건 · 옛 글 %d건", hidden, stale)
```

## 5. 교훈

**「1:1 이다」 는 주석이 아니라 검사로 말한다.**
주석은 코드가 바뀌어도 안 따라온다.

**손으로 베낀 절차는 원본이 늘어날 때 안 따라온다.**
이 저장소는 SELECT 를 import 로 공유해 그 축은 막았는데, 그 뒤 단계는 여전히 손으로 베끼는 구조다.

재렌더를 손으로 돌릴 일이 있으면 순서를 이렇게 맞춘다.

1. `SERVING_SELECT_SQL` 로 SELECT
2. `LINKED_HASHES_SQL` 로 귀속 해시
3. `build_adapters` 로 fmkorea 어댑터를 만들고 `serving_rows` 로 무관 글 · 옛 글 제외
4. 단계가 빈 행이 0인지 확인 (`2026-08-02-rerender-during-reclassification.md`)
5. `write_site`

**산출물 파일 수를 세는 것이 가장 싼 검사다.**

```bash
ls site/article/*.html | wc -l      # 서빙 행 수와 같아야 한다
```

## 함께 볼 것

- `docs/runbook/2026-08-28-rendering-the-home-page-before-you-deploy-it.md` — 배포 전 재현 절차 (같은 순서를 담았다)
- `docs/runbook/2026-07-27-row-recovery-cleanup.md` §5 — 같은 누락이 있던 스니펫
- `docs/troubleshooting/2026-08-02-rerender-during-reclassification.md` — 수동 재렌더의 다른 함정 (중간 상태)
