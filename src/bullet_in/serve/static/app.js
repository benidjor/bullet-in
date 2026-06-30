// DOM contract: a.card[data-outlet][data-tier][data-stage][data-published][data-confidence][data-text]

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

const enabledBoxes = () => [...side.querySelectorAll('input[type=checkbox]:not([disabled])')];
const checkedValues = (group) =>
  enabledBoxes().filter(c => c.dataset.group === group && c.checked).map(c => c.dataset.value);

function applyFilters() {
  const q = (searchInput.value || '').trim().toLowerCase();
  const outlets = checkedValues('outlet');
  const tiers = checkedValues('tier');
  const stages = checkedValues('stage');
  let shown = 0;
  for (const card of cards) {
    const okText = !q || (card.dataset.text || '').includes(q);
    const okOutlet = outlets.length === 0 || outlets.includes(card.dataset.outlet);
    const okTier = tiers.length === 0 || tiers.includes(card.dataset.tier);
    const okStage = stages.length === 0 || stages.includes(card.dataset.stage);
    const visible = okText && okOutlet && okTier && okStage;
    card.style.display = visible ? '' : 'none';
    if (visible) shown++;
  }
  sortCards();
  const sort = side.querySelector('input[name=sort]:checked').dataset.value;
  const conds = outlets.length + tiers.length + stages.length + (q ? 1 : 0);
  fstatus.textContent = conds || q
    ? `적용됨 · 조건 ${conds}개 · ${shown}건`
    : `미적용 · 전체 ${shown}건`;
  applyBtn.classList.remove('dirty');
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
  sortCards(); // 초기 정렬(최신순)
} else {
  // 상세 페이지: 카드 없음 → 검색/필터는 상태만(목업 동작 유지)
  if (applyBtn) applyBtn.onclick = () => applyBtn.classList.remove('dirty');
  if (side) side.addEventListener('change', () => applyBtn && applyBtn.classList.add('dirty'));
}
