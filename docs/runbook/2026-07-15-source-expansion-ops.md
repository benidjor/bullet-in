# 소스 확장 3종 (goal · guardian · skysports) 운영 런북 (2026-07-15)

PR #41 로 등재된 3종 소스의 키 관리 · 배포 체크 · 라이브 검증 · 드리프트 대응 절차.
guardian 은 이 파이프라인의 **첫 API 상시 소스**라 키라는 새 운영 축이 생겼다 — 이 런북이 그 축의 SoT.

## 1. 구성 요약

| 소스 | 어댑터 | tier | 스코프 · 셀렉터 | 본문 |
|---|---|---|---|---|
| goal | html | 2 | 남자팀 슬러그 URL + `a[href^='/en/news/']:not([aria-label]), a[href^='/en/lists/']:not([aria-label])` | `article` |
| guardian | guardian_api | 1.5 | `tag=football/arsenal` (셀렉터 없음) | API `bodyText` |
| skysports | html | 1.5 | `h3.sdc-site-tile__headline a[href*='/football/news/']` | `div.sdc-article-body` |

- 3종 공통 `title_contains` 이적 키워드 20개 (bbc_sport 와 동일 리스트) — 무필터 대비 goal 26→12건 수준으로 걸러짐 (2026-07-15 실측).
- 여자팀 필터 별도 불요: goal 여자팀은 슬러그가 달라 URL 스코프로 완결.

## 2. GUARDIAN_API_KEY 관리

- **발급** — https://open-platform.theguardian.com/ developer 키 (무료 · 즉시 발급, 이메일 수신).
- **주입** — 이 프로젝트는 dotenv 미사용: `.env` 에 `GUARDIAN_API_KEY=...` 추가 후 `set -a; source .env; set +a`.
  Airflow 운영은 워커 컨테이너 env 주입 필요 (DISCORD_WEBHOOK_URL 과 같은 축 — 배포 시 함께 확인).
- **미설정 동작** — factory 가 guardian 만 skip + `WARNING` 로깅, 나머지 소스는 정상 수집 (파이프라인 안 죽음).
  ⚠️ 단, 한 번도 적재된 적 없는 상태의 스킵은 SLO-5 알림 사각 — `docs/troubleshooting/2026-07-15-guardian-api-payload-traps.md` §3.
- **한도** — developer 키 500 calls/day, 사이클당 1콜 (하루 4회 스케줄 기준 사용률 ~1%).
- **키 위생** — `.env` 만 (gitignore 확인됨), spec · 커밋 · 테스트 픽스처 금지.

## 3. 배포 체크 (신규 소스 첫 가동 시 필수)

SLO-5 는 첫 적재 전 구간을 못 지키므로 (§2 사각) 사람이 확인한다.

```bash
# 1) 환경에 키 존재 확인
env | grep -c GUARDIAN_API_KEY    # 1 이어야 함

# 2) 첫 운영 회차 후 source_counts 확인 (MariaDB)
SELECT source_counts FROM pipeline_runs ORDER BY started_at DESC LIMIT 1;
# → JSON 에 "goal" · "guardian" · "skysports" 키 등장 확인 (0건이어도 키는 있어야 정상)
```

- guardian 키가 JSON 에 아예 없으면: 키 미주입 (WARNING 로그 확인) 또는 factory 배선 회귀.
- 있는데 지속 0건이면: 이적 비수기 (정상) vs 필터 과차단 — §4 라이브 검증으로 판별.

## 4. 어댑터 단독 라이브 검증

머지 전 게이트이자 드리프트 의심 시 1차 진단 (모킹 테스트는 셀렉터 · 응답 특성을 못 잡는다).

```bash
set -a; source .env; set +a
uv run python -c "
import asyncio, yaml
from bullet_in.adapters.factory import build_adapters
cfg = yaml.safe_load(open('config/sources.yaml'))
targets = {'goal', 'guardian', 'skysports'}
for a in build_adapters(cfg):
    if a.source_id not in targets:
        continue
    items = asyncio.run(a.fetch())
    bodies = [len(i.raw_payload.get('body') or '') for i in items]
    imgs = sum(1 for i in items if i.raw_payload.get('image_url'))
    print(a.source_id, 'items:', len(items), 'body_lens:', bodies[:5], 'imgs:', imgs)
    for i in items[:3]:
        print('  -', i.raw_payload['title'][:60], '|', i.url[:70])"
```

- **수용 기준 (2026-07-15 기준 실측: goal 12 · guardian 3 · skysports 9)**
  - 3종 모두 예외 없이 완료, 통과 항목 제목이 실제 이적 뉴스.
  - goal · skysports 본문 길이 수백 자 이상, guardian body · image 채워짐.
  - skysports 에 네비 링크 (멤버십 Q&A 등 비기사) 0건.
- 0건 소스는 config 의 `title_contains` 를 잠시 빼고 재실행 — 링크 자체가 안 잡히면 셀렉터 드리프트, 잡히면 필터 정상 (비수기).

## 5. 드리프트 대응

| 증상 | 원인 후보 | 처방 |
|---|---|---|
| goal 404 (SLO-5 알림 · errors) | 팀 슬러그 ID 재변경 (전례: 2026-07 확인) | goal.com/en 홈에서 Arsenal 링크의 신규 슬러그 확인 → `list_url` 갱신 |
| goal 0건 · HTML 은 200 | 기사 앵커 구조 변경 (class 없는 앵커 + `aria-label` 이미지 앵커 전제) | §4 스크립트로 앵커 인벤토리 재조사 → `item_selector` 갱신 |
| skysports 0건 | 타일 클래스 (`sdc-site-tile`) 개편 | 차선 셀렉터 = 섹션 id 필터 (`a[href*='/football/news/11670/']` 류), 단 섹션 id 는 주제별 상이 — 컨테이너 스코프 우선 재설계 |
| guardian 급감 · 401 | 키 만료 · 폐기 | §2 재발급 · 재주입 |
| guardian 에 타 구단 기사 | `tag` 파라미터 회귀 (q= 로 되돌아감) | 트러블슈팅 §1 — `tag=football/arsenal` 확인 |
| 카드에 `<strong>` 리터럴 | trailText 태그 제거 회귀 | 트러블슈팅 §2 — `get_text` 경로 확인 |

- 지속 실패 감시는 SLO-5 (48h) · 수집량 급변은 SLO-6 이 커버 — 이 표는 알림 수신 후의 진단표.

## 6. 롤백

- 3종 등재는 코드 · config 원자적 (PR #41 squash `dee706f`) — `git revert dee706f` 1회로 전체 철회.
- guardian 만 끄려면 `sources.yaml` 의 `enabled: false` (수집만 중단, 코드 무영향).

## 7. 후속 (이 트랙에서 제외된 것)

- README §소스 표 3종 반영 (SLO-1 트랙 머지 완료로 차단 해제).
- `title_contains` 키워드 리스트 5중복 → YAML 앵커 (`&transfer_kw`) 통합 (최종 리뷰 Minor).
- telegraph: Akamai 403 + 페이월로 제외 — RSS 등 대체 경로 확인 시만 재검토 (spec §2).
