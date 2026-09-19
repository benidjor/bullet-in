# 글자가 벡터뿐인 PDF 이력서를 HTML 로 다시 만들기

피그마에서 내보낸 이력서 PDF 는 텍스트가 없다 (`pypdf` 추출 2자 · 폰트 0).
원본을 피그마에서 텍스트나 SVG 로 다시 내보낼 수 없을 때, 소개 자료와 같은 방식 (Pretendard HTML → Playwright) 으로 다시 만든 절차다.
산출물은 저장소 밖 (`01-04 이력서/resume_build/`) 에 둔다.

## 1. 재료

```bash
uv run --with pymupdf --no-project python - <<'PY'
import fitz; doc = fitz.open("이력서.pdf")
for i, page in enumerate(doc, 1):
    page.get_pixmap(dpi=200).save(f"src/page-{i}.png")            # 옮겨 적을 렌더
    for j, img in enumerate(page.get_images(full=True), 1):       # 안에 든 그림은 원본 그대로
        info = doc.extract_image(img[0]); open(f"src/p{i}-img{j}.{info['ext']}", "wb").write(info["image"])
PY
```

- 글은 렌더 이미지를 Read 도구로 읽어 옮겨 적는다.
  쪽마다 한 번씩 읽고, 옮긴 뒤 렌더를 나란히 놓고 대조한다.
- 그림은 추출본을 쓴다 (PDF 안의 PNG 가 원본 해상도다).
- Pretendard 는 사용자 폰트 폴더에 있어야 한다 (`fc-list | grep -i pretendard`).

## 2. 조립과 측정

- 쪽은 `.page{width:794px;height:1123px;overflow:hidden}` 고정이고 `@page{size:A4;margin:0}` 다.
- `build.py` 가 쪽마다 PNG 를 찍고 `page.pdf(format="A4")` 로 PDF 를 만들며, 자식 요소의 마지막 바닥으로 넘침을 잰다.
  넘침이 0 이하가 될 때까지 여백 · 그림 폭 · 절 배치를 조정한다.
- 잘 듣는 순서 = 그림 폭 → 소제목 여백 → 절을 다음 쪽으로 → 내용 삭제 (마지막은 사용자 결정).

## 3. 이번 회차의 값

- 원본 3쪽에 Bullet-in 절을 더하면 5쪽이 됐고, 사용자가 「3쪽 · E-commerce 는 빼도 된다」 로 정해 3쪽으로 돌아왔다.
- 대시보드 캡처는 위 520px 만 잘라 넣었다 (전체 캡처는 세로 1500 이라 한 쪽을 다 먹는다).
- 값은 저장소 · 소개 자료 · 같은 날 실측에 닿는 것만 넣는다.
