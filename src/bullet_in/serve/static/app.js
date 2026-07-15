// DOM contract: a.card[data-outlet][data-tier][data-stage][data-published][data-confidence][data-text][data-journalist]
// URL contract: ?outlet=..&tier=..&stage=..&bucket=other&journalist=..&sort=confidence&q=..  (다중 선택은 키 반복)

// 테마 토글 (목업 이식: localStorage 영속, 페이지 간 유지)
const root = document.documentElement, themeBtn = document.getElementById('themeBtn');
const saved = localStorage.getItem('theme'); if (saved) root.setAttribute('data-theme', saved);
const syncTheme = () => { themeBtn.textContent = root.getAttribute('data-theme') === 'dark' ? '☀️' : '🌙'; };
syncTheme();
themeBtn.onclick = () => {
  const n = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  root.setAttribute('data-theme', n); localStorage.setItem('theme', n); syncTheme();
};

// 사이드바 + 검색 + 필터/정렬 (인덱스에서만 카드에 작용)
const side = document.querySelector('.side');
const fstatus = document.getElementById('fstatus');
const applyBtn = document.getElementById('applyBtn');
const resetBtn = document.getElementById('resetBtn');
const searchInput = document.getElementById('q');
const grid = document.querySelector('.grid');
const cards = grid ? [...grid.querySelectorAll('.card')] : [];

// URL 직렬화 대상 그룹 (team 은 항상 arsenal — 제외)
const URL_GROUPS = ['outlet', 'tier', 'stage', 'journalist', 'bucket'];

const enabledBoxes = () => [...side.querySelectorAll('input[type=checkbox]:not([disabled])')];
const checkedValues = (group) =>
  enabledBoxes().filter(c => c.dataset.group === group && c.checked).map(c => c.dataset.value);

// 기자 더보기 토글 — 미등재 기자는 접힌 채 시작
const jmore = document.getElementById('jmore'), jmoreBtn = document.getElementById('jmoreBtn');
const expandMore = () => { if (jmore) jmore.hidden = false; if (jmoreBtn) jmoreBtn.hidden = true; };
if (jmoreBtn) jmoreBtn.onclick = expandMore;

function filterParams() {
  const p = new URLSearchParams();
  for (const g of URL_GROUPS) for (const v of checkedValues(g)) p.append(g, v);
  const sort = side.querySelector('input[name=sort]:checked')?.dataset.value;
  if (sort && sort !== 'latest') p.set('sort', sort);
  const q = (searchInput?.value || '').trim();
  if (q) p.set('q', q);
  return p;
}

function restoreFromQuery() {
  const p = new URLSearchParams(location.search);
  if (![...p.keys()].length) return false;
  const want = {};
  for (const g of URL_GROUPS) want[g] = p.getAll(g);
  enabledBoxes().forEach(c => {
    const g = c.dataset.group;
    if (URL_GROUPS.includes(g)) c.checked = want[g].includes(c.dataset.value);
  });
  const sort = p.get('sort') === 'confidence' ? 'confidence' : 'latest';
  const sortBox = side.querySelector(`input[name=sort][data-value=${sort}]`);
  if (sortBox) sortBox.checked = true;
  if (searchInput) searchInput.value = p.get('q') || '';
  // 접힌 더보기 안의 기자가 선택돼 있으면 펼친다 (보이지 않는 필터 방지)
  if (jmore && jmore.querySelector('input:checked')) expandMore();
  return true;
}

function applyFilters() {
  const q = (searchInput.value || '').trim().toLowerCase();
  const outlets = checkedValues('outlet');
  const tiers = checkedValues('tier');
  const stages = checkedValues('stage');
  const journalists = checkedValues('journalist');
  const showOther = !!side.querySelector('input[data-group=bucket][data-value=other]')?.checked;
  let shown = 0;
  for (const card of cards) {
    const okText = !q || (card.dataset.text || '').includes(q);
    const okOutlet = outlets.length === 0 || outlets.includes(card.dataset.outlet);
    const okTier = tiers.length === 0 || tiers.includes(card.dataset.tier);
    const okJournalist = journalists.length === 0 || journalists.includes(card.dataset.journalist);
    const st = card.dataset.stage;
    const isOther = !st || st === 'other';
    const okStage = isOther
      ? showOther
      : (stages.length === 0 || stages.includes(st));
    const visible = okText && okOutlet && okTier && okJournalist && okStage;
    card.style.display = visible ? '' : 'none';
    if (visible) shown++;
  }
  sortCards();
  const conds = outlets.length + tiers.length + stages.length + journalists.length
    + (showOther ? 1 : 0) + (q ? 1 : 0);
  fstatus.textContent = conds || q
    ? `적용됨 · 조건 ${conds}개 · ${shown}건`
    : `미적용 · 전체 ${shown}건`;
  applyBtn.classList.remove('dirty');
  // 필터된 뷰를 북마크·공유·뒤로가기로 되살릴 수 있게 상태를 URL에 남긴다
  const qs = filterParams().toString();
  history.replaceState(null, '', qs ? `?${qs}` : location.pathname);
}

function sortCards() {
  if (!grid) return;
  const key = side.querySelector('input[name=sort]:checked').dataset.value;
  const ordered = [...cards].sort((a, b) => {
    if (key === 'confidence') {
      return parseFloat(b.dataset.confidence || 0) - parseFloat(a.dataset.confidence || 0);
    }
    return (b.dataset.published || '').localeCompare(a.dataset.published || ''); // 최신순
  });
  for (const c of ordered) grid.appendChild(c);
}

if (grid) {
  side.addEventListener('change', () => applyBtn.classList.add('dirty'));
  applyBtn.onclick = applyFilters;
  resetBtn.onclick = () => {
    enabledBoxes().forEach(c => { c.checked = (c.dataset.value === 'arsenal'); });
    side.querySelector('input[name=sort][data-value=latest]').checked = true;
    if (searchInput) searchInput.value = '';
    applyFilters();
  };
  if (searchInput) searchInput.addEventListener('input', applyFilters);
  if (restoreFromQuery()) applyFilters();  // 상세에서 넘어온 필터 상태 복원 · 적용
  else sortCards();                        // 초기 정렬(최신순)
} else {
  // 상세 페이지: 카드가 없다 → 필터 적용은 필터된 인덱스로 이동 (spec ③).
  // 인덱스 경로는 로고 링크에서 얻는다 (Jinja root 를 JS 로 넘기지 않기 위함).
  const indexHref = document.querySelector('.logo')?.getAttribute('href') || 'index.html';
  if (side) side.addEventListener('change', () => applyBtn && applyBtn.classList.add('dirty'));
  if (applyBtn) applyBtn.onclick = () => {
    const qs = filterParams().toString();
    location.href = qs ? `${indexHref}?${qs}` : indexHref;
  };
  if (resetBtn) resetBtn.onclick = () => {
    enabledBoxes().forEach(c => { c.checked = (c.dataset.value === 'arsenal'); });
    side.querySelector('input[name=sort][data-value=latest]').checked = true;
    if (searchInput) searchInput.value = '';
    applyBtn && applyBtn.classList.remove('dirty');
  };
}
