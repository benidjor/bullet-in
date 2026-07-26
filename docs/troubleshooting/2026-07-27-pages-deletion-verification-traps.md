# 배포판에서 "지웠는지" 를 확인할 때의 함정 (Cloudflare Pages)

중복 행 2건을 지우고 재렌더 · 배포한 뒤, 삭제된 상세 페이지가 계속 살아 있는 것처럼 보여 두 번 헛다리를 짚었다 (2026-07-27).
원인은 Pages 의 두 가지 동작이다.
둘 다 **HTTP 응답 코드로는 구분되지 않는다**.

## 1. 없는 경로도 200 을 준다

존재하지 않는 해시로 요청해도 404 가 아니라 **200 + 인덱스 페이지**가 돌아온다.

```bash
# 완전히 없는 해시
curl -s -o /dev/null -w '%{http_code}\n' -L \
  "https://bullet-in.pages.dev/article/deadbeef0000000000000000000000000000000000000000000000000000"
# → 200
```

그래서 `%{http_code}` 로 존재 여부를 판정하면 항상 "있다" 가 나온다.
**본문의 `<title>` 로 판정한다** — 인덱스로 폴백되면 `Bullet-in · 아스날 이적 뉴스` 가 나오고 상세가 살아 있으면 그 기사 제목이 나온다.

## 2. 확장자 없는 경로는 엣지 캐시에 오래 남는다

같은 삭제 대상을 두 형태로 요청하면 결과가 갈린다.

| 요청 형태 | 결과 |
|---|---|
| `/article/<hash>.html` | 인덱스 폴백 (정상 — 지워짐) |
| `/article/<hash>` (무확장) | **삭제된 기사 제목** (옛 응답) |

캐시 헤더를 보면 원인이 분명하다.

```bash
curl -sI -L "https://bullet-in.pages.dev/article/<hash>" | grep -i "cf-cache-status\|age:"
# cf-cache-status: HIT
# age: 4582            ← 약 76분째 캐시된 응답
```

Pages 는 확장자 없는 경로를 리다이렉트로 처리하는데, 그 응답이 엣지에 캐시돼 **배포본에서 사라진 페이지를 계속 내어준다**.
캐시를 우회하면 곧바로 인덱스 폴백이 나온다.

## 3. 삭제 검증 절차

세 층을 순서대로 본다.
셋이 일치하면 정상이고 최상위 도메인의 무확장 경로만 다르면 캐시 탓이다.

```bash
# ① VM 산출물 — 파일 자체가 사라졌는지
ls site/article/<hash>.html          # No such file 이면 렌더 단계 정상

# ② 방금 만든 배포본 — deploy-site.sh 출력 마지막 줄의 프리뷰 주소
curl -sL "https://<배포해시>.bullet-in.pages.dev/article/<hash>" | grep -o '<title>[^<]*'

# ③ 최상위 도메인 — 캐시 우회 (쿼리 + no-cache)
curl -sL -H 'Cache-Control: no-cache' \
  "https://bullet-in.pages.dev/article/<hash>?cb=$RANDOM" | grep -o '<title>[^<]*'
```

- ①이 남아 있으면 렌더가 아직 그 행을 읽고 있다 (DB 삭제 누락 · 재렌더 미실행).
- ②가 기사 제목이면 그 페이지가 배포본에 실제로 들어갔다.
- ③만 다르면 기다리면 풀린다 — 조치할 것이 없다.

## 4. 배포 게이트에 넣을 것

삭제 작업에서는 "새 값이 있는가" 만 보면 부족하다.
**옛 값이 사라졌는지도 함께 확인**하고 둘 다 만족할 때만 배포한다.

```bash
d=$(grep -rl "<지운 해시>" site/ | wc -l)
k=$(grep -rl "<남긴 해시>" site/ | wc -l)
[ "$d" -eq 0 ] && [ "$k" -ge 1 ] && ./infra/deploy-site.sh
```

## 5. 참고

- 배포 직후 최상위 도메인의 캐시 지연 (기존 사례): `docs/runbook/2026-07-20-vm-cohost-bootstrap.md` §8
- 행 삭제 · 복구 절차: `docs/runbook/2026-07-27-row-recovery-cleanup.md`
