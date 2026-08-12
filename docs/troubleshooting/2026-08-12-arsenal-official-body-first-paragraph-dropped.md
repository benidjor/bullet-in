# 공홈 기사 본문에서 첫 문단이 통째로 빠지고 있었다 (2026-08-12)

구단 공식 발표 기사를 두 달 넘게 수집해 왔는데, 그 본문에서 이적 사실을 말하는 문장이 빠져 있었다.
빠진 줄 몰랐던 이유와 발견 경위를 남긴다.

## 1. 증상

겉으로 드러나는 증상이 없었다.
기사는 정상적으로 수집되고 번역되고 화면에 실렸으며 본문도 비어 보이지 않았다.

실제로 빠진 것은 **첫 문단 하나**였고 하필 그 문단이 이적 사실을 진술하는 문장이었다.

```
Bruno Guimaraes joins Arsenal — 수집된 본문의 시작
  Bruno joins us from Newcastle United, where he made 250 appearances...

  실제 원문의 첫 문단 (수집에서 빠짐)
  We are delighted to announce that Brazil international Bruno Guimaraes has joined us
  from Newcastle United on a long-term contract.
```

## 2. 원인

어댑터의 `_body_payload` 는 `articleBody` 블록 중 `type == "TEXT"` 인 것의 `innerText` 를 이어 붙인다.

```python
texts = [b["innerText"] for b in blocks
         if b.get("type") == "TEXT" and b.get("innerText")]
```

문제는 arsenal.com GraphQL 응답의 구조다.
문단에 링크 (`<a>`) 나 볼드 (`<strong>`) 가 들어 있으면 **그 블록의 `innerText` 가 빈 문자열이고 내용은 `html` 과 `childNodes` 에만 있다.**

```
type=TEXT · tagName=P
  innerText = ""
  html      = <p><strong id="...">We are delighted to announce that ...</strong></p>
  childNodes = [{tagName: STRONG, innerText: "We are delighted to announce that ..."}]
```

구단 발표문은 첫 문단을 볼드로 강조하는 편집 관행이 있어 하필 가장 중요한 문장이 매번 걸렸다.

## 3. 규모 (2026-08-12 실측)

sitemap 전체 619건을 조회해 채택 기사 전량 + 뇌르고르 2건 = 12건을 재보았다.

| 기사 | 현재 수집 | html 기준 | 누락 |
| --- | --- | --- | --- |
| Bruno Guimaraes joins Arsenal | 2,181자 | 2,341자 | 160자 |
| Christos Tzolis signs for Arsenal | 2,853자 | 2,935자 | 82자 |
| Piero Hincapie joins Arsenal in permanent deal | 1,432자 | 1,765자 | 333자 |
| Illan Meslier signs for Arsenal | 1,644자 | 1,907자 | 263자 |
| Christian Norgaard joins Everton | 1,630자 | 1,694자 | 64자 |
| Terms agreed with Besiktas for Trossard transfer | 251자 | 363자 | **112자 (본문의 44%)** |
| Leandro Trossard joins Besiktas | 1,675자 | 1,675자 | 0자 |

**12건 중 11건에서 누락**이 있었고 빠진 문단은 대부분 리드 문장이었다.
「Terms agreed with Besiktas」 처럼 짧은 발표문은 본문의 절반 가까이가 사라진다.

## 4. 왜 오래 보이지 않았나

- **본문이 비지 않는다** — 두 번째 문단부터는 정상적으로 들어오므로 길이 게이트나 빈 본문 검사에 걸리지 않는다.
- **번역 · 요약도 성공한다** — Gemini 는 받은 본문으로 그럴듯한 요약을 만든다.
이적 사실 문장이 없어도 나머지 문단에 이적 정황이 흩어져 있어 요약이 크게 틀리지 않는다.
- **화면에서도 티가 안 난다** — 사람이 원문과 나란히 놓고 보지 않는 한 문단 하나가 빠진 것을 알 수 없다.
- **단위 테스트는 모킹이라 못 잡는다** — 테스트가 쓰는 가짜 블록은 `innerText` 를 항상 채워 두었다.

## 5. 파급 — 다른 판단까지 틀리게 만들었다

이 결함은 본문 품질에만 그치지 않고 **제품 판단 하나를 뒤집을 뻔했다.**

Club 태그가 붙은 이적 정리 기사 (「Arsenal transfers: All the ins and outs」 등) 를 수집할지 검토하면서
본문을 받아 보니 소제목만 남고 명단이 없어 "껍데기라 수용 실익이 없다" 고 판단했다.

블록 구조를 열어 보니 **명단은 응답에 다 있었다.**

```
ins and outs 2026/27 — 현재 파서 234자 → html 기준 1,549자
  Bruno Guimaraes - Newcastle United (undisclosed)
  Piero Hincapie - Bayer Leverkusen (undisclosed)
  Christian Norgaard - Everton (undisclosed) ...
```

명단이 링크 (`<a>`) 로 되어 있어 같은 이유로 빠졌다.
파서 결함을 모른 채였다면 "내용이 없는 기사" 라는 잘못된 근거로 수용을 기각했을 것이다.

## 6. 발견 경위

공홈 태그 누락 (뇌르고르) 을 조사하다 Club 태그 기사의 본문이 유난히 짧은 것이 걸렸다.
`ARTICLE_QUERY` 로 받은 블록 전체를 덤프해 키를 하나씩 찍어 보니 `innerText` 가 빈 블록에 `html` 이 차 있었다.

**"내용이 없다" 는 판단을 우리가 읽는 필드만 보고 내렸던 것이 원인이다.**
외부 API 응답에서 기대한 필드가 비어 있으면, 없는 것이 아니라 다른 필드에 있을 수 있다.

## 7. 대응

설계는 `docs/superpowers/specs/2026-08-12-arsenal-official-collection-revision-design.md` §3.1 에 있다.
`innerText` 가 비면 같은 블록의 `html` 에서 태그를 벗겨 쓴다.

기존 7건은 본문이 바뀌므로 배포 후 재번역한다 (호출 7~14회 · 약 ₩10).

## 8. 같은 함정을 피하려면

- 어댑터를 새로 붙이거나 응답 구조가 바뀌면 **블록 전체를 한 번 덤프해 키를 눈으로 확인한다.**
- 모킹 테스트의 가짜 응답을 실제 응답에서 복사해 온다 — 손으로 지어내면 실제 구조의 함정이 재현되지 않는다.
- 수집 본문의 길이를 원문과 대조하는 점검을 어댑터 라이브 검증에 넣는다 (`docs/runbook/2026-07-19-arsenal-official-api-adapter-ops.md`).

