// Bullet-in 서빙 인터랙션 — 필터 · 정렬 · 공신력 연동 · 테마.
// DOM 계약: a.item[data-hash][data-stage][data-tier][data-outlet][data-journalist][data-published][data-confidence][data-text]
//           사이드바 옵션 input[data-group][data-value][data-tier]
// URL 계약: ?outlet=&journalist=&tier=&stage=&bucket=other&sort=confidence|views&q=  (다중 선택은 키 반복)
// 결합 규칙 (§8): (소스 OR 기자) AND 공신력 AND 영입 단계 AND 검색어

// ── 조회 기록 (조회순 정렬용) ──────────────────────────────────────
const VIEWS_KEY = 'bulletin_views';
function readViews() {
  try { return JSON.parse(localStorage.getItem(VIEWS_KEY)) || {}; } catch { return {}; }
}
(function trackView() {
  const m = location.pathname.match(/article\/([0-9a-f]{64})\.html$/);
  if (!m) return;
  const v = readViews();
  v[m[1]] = (v[m[1]] || 0) + 1;
  try { localStorage.setItem(VIEWS_KEY, JSON.stringify(v)); } catch {}
})();

// ── 테마 토글 (첫 페인트 전 적용은 <head> 인라인 스크립트가 담당) ──────
const root = document.documentElement;
const themeBtn = document.getElementById('themeBtn');
if (themeBtn) themeBtn.onclick = () => {
  const cur = root.getAttribute('data-theme')
    || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  const next = cur === 'dark' ? 'light' : 'dark';
  root.setAttribute('data-theme', next);
  try { localStorage.setItem('theme', next); } catch {}
};

// ── 모바일 사이드바 ────────────────────────────────────────────────
const side = document.querySelector('.side');
const scrim = document.getElementById('scrim');
const hamb = document.getElementById('hambBtn');
const closeSide = () => { side?.classList.remove('open'); scrim?.classList.remove('open'); };
if (hamb) hamb.onclick = () => { side?.classList.toggle('open'); scrim?.classList.toggle('open'); };
if (scrim) scrim.onclick = closeSide;

// ── 접히는 사이드바 그룹 ───────────────────────────────────────────
document.querySelectorAll('.grp .grphead').forEach(h => {
  h.onclick = () => h.closest('.grp').classList.toggle('collapsed');
});
function expandGroup(name) {
  document.querySelector(`.grp[data-grp="${name}"]`)?.classList.remove('collapsed');
}

// ── 더보기 단계 (tier 그룹 소스 · 기자 안의 미등재 단계) ─────────────
function setupMore(scope) {
  const stages = [...scope.querySelectorAll('.morestage')];
  const btns = [...scope.querySelectorAll('.morebtn')];
  let open = 0;
  const sync = () => {
    stages.forEach((s, i) => { s.hidden = i >= open; });
    btns.forEach((b, i) => { b.hidden = i !== open; });
  };
  btns.forEach((b, i) => { b.onclick = () => { open = i + 1; sync(); }; });
  stages.forEach((s, i) => { if (s.querySelector('input:checked')) open = Math.max(open, i + 1); });
  sync();
}
const setupAllMore = () => document.querySelectorAll('.facetgroup').forEach(setupMore);

// ── 필터 요소 ──────────────────────────────────────────────────────
const fstatus = document.getElementById('fstatus');
const applyBtn = document.getElementById('applyBtn');
const resetBtn = document.getElementById('resetBtn');
const searchInput = document.getElementById('q');
const sortSel = document.getElementById('sortSel');
const daylists = [...document.querySelectorAll('.daylist')];
const items = [...document.querySelectorAll('.daylist .item, .gossiplist .item')];

// 관련 보도 펼치기 (사건 블록 안 접힌 갈래)
document.querySelectorAll('.reltoggle').forEach(btn => {
  btn.onclick = () => {
    const rel = btn.nextElementSibling;
    rel.hidden = !rel.hidden;
    btn.setAttribute('aria-expanded', rel.hidden ? 'false' : 'true');
  };
});

// ── 가십 — 주 단위 더보기 · 접기 (초기 = 최근 7일, 서버 gwk 표식) ────
const gossipList = document.querySelector('.gossiplist');
const gossipMore = document.getElementById('gossipMore');
const gossipCards = gossipList ? [...gossipList.querySelectorAll('.item:not(.dupcard)')] : [];
function gossipHiddenCount() {
  if (gossipList?.classList.contains('weekcut'))
    return gossipCards.filter(c => c.classList.contains('gwk')).length;
  return gossipCards.filter(c => c.classList.contains('wcut')).length;
}
function gossipSync() {
  if (!gossipMore) return;
  const n = gossipHiddenCount();
  gossipMore.textContent = n ? `이전 날짜 가십 더보기 · ${n}건` : '접기';
}
function gossipReveal() {
  const hidden = gossipCards.filter(c => gossipList.classList.contains('weekcut')
    ? c.classList.contains('gwk') : c.classList.contains('wcut'));
  if (!hidden.length) return;
  const anchor = new Date(hidden[0].dataset.published);
  anchor.setDate(anchor.getDate() - 6);
  if (gossipList.classList.contains('weekcut')) {
    gossipList.classList.remove('weekcut');
    gossipCards.forEach(c => { if (c.classList.contains('gwk')) c.classList.add('wcut'); });
  }
  gossipCards.forEach(c => {
    const d = c.dataset.published;
    if (!d || new Date(d) >= anchor) c.classList.remove('wcut');
  });
  gossipSync();
}
function gossipCollapse() {
  gossipCards.forEach(c => c.classList.remove('wcut'));
  gossipList.classList.add('weekcut');
  gossipSync();
  document.querySelector('.gossiphead')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
function expandGossip() {                        // 필터 활성 시 전체 전개 (기존 계약)
  gossipList?.classList.remove('weekcut');
  gossipCards.forEach(c => c.classList.remove('wcut'));
  if (gossipMore) gossipMore.hidden = true;
}
if (gossipMore) gossipMore.onclick = () =>
  gossipHiddenCount() ? gossipReveal() : gossipCollapse();
if (gossipMore) gossipSync();

// ── 최신 소식 · 전체 기사 — 주 단위 더보기 · 접기 (spec §4) ─────────
const latestWrap = document.querySelector('.latest');
const latestMore = document.getElementById('latestMore');
const dayGroups = latestWrap ? [...latestWrap.querySelectorAll('.daygroup')] : [];
const LATEST_INIT = 3;
function latestHiddenCount() {
  if (latestWrap?.classList.contains('latestcut'))
    return dayGroups.filter(g => g.classList.contains('dg-extra')).length;
  return dayGroups.filter(g => g.classList.contains('wcut')).length;
}
function latestSync() {
  if (!latestMore) return;
  const n = latestHiddenCount();
  latestMore.textContent = n
    ? (latestWrap.classList.contains('latestcut')
        ? `이전 날짜 더보기 · ${n}개 날짜` : `이전 7일 더보기 · ${n}개 날짜`)
    : '접기';
}
function latestReveal() {
  const hidden = dayGroups.filter(g => latestWrap.classList.contains('latestcut')
    ? g.classList.contains('dg-extra') : g.classList.contains('wcut'));
  if (!hidden.length) return;
  const anchor = new Date(hidden[0].dataset.date);          // 가장 최신의 숨은 그룹부터 7일 창
  anchor.setDate(anchor.getDate() - 6);
  if (latestWrap.classList.contains('latestcut')) {
    latestWrap.classList.remove('latestcut');
    dayGroups.forEach((g, i) => { if (i >= LATEST_INIT) g.classList.add('wcut'); });
  }
  dayGroups.forEach(g => { if (new Date(g.dataset.date) >= anchor) g.classList.remove('wcut'); });
  latestSync();
}
function latestCollapse() {
  dayGroups.forEach(g => g.classList.remove('wcut'));
  latestWrap.classList.add('latestcut');
  latestSync();
  latestWrap.previousElementSibling?.scrollIntoView({ behavior: 'smooth', block: 'start' });  // 구역 상단 (sechead) 보정
}
function expandLatest() {                                  // 필터 활성 시 전체 전개 (기존 계약)
  latestWrap?.classList.remove('latestcut');
  dayGroups.forEach(g => g.classList.remove('wcut'));
  if (latestMore) latestMore.hidden = true;
}
if (latestMore) latestMore.onclick = () =>
  latestHiddenCount() ? latestReveal() : latestCollapse();
if (latestMore) latestSync();

const URL_GROUPS = ['outlet', 'journalist', 'tier', 'stage', 'bucket'];
const box = (g) => [...side.querySelectorAll(`input[data-group="${g}"]`)];
const boxesOf = (g) => box(g).filter(c => !c.disabled);
const checkedVals = (g) => boxesOf(g).filter(c => c.checked).map(c => c.dataset.value);

// ── 공신력 ↔ 소스 · 기자 연동 (§7.2) ───────────────────────────────
// tier 를 고르면 그 등급 소스 · 기자를 자동 체크하고 접힌 그룹을 펼친다.
let userTouchedSrc = false;   // 자동 체크된 소스 · 기자를 사용자가 손댔는지
function tierMembers(tierVal) {
  return [...side.querySelectorAll('input[data-group="outlet"],input[data-group="journalist"]')]
    .filter(c => c.dataset.tier === tierVal);
}
function syncTierLinkage(changed) {
  if (changed.dataset.value === 'all') return;
  const members = tierMembers(changed.dataset.value);
  if (changed.checked) {
    let any = false;
    members.forEach(c => { c.checked = true; c.closest('.opt').classList.add('auto'); any = true; });
    if (any) { expandGroup('outlet'); expandGroup('journalist'); }
  } else {
    members.filter(c => c.closest('.opt').classList.contains('auto'))
      .forEach(c => { c.checked = false; c.closest('.opt').classList.remove('auto'); });
  }
}

// tier '전체' ↔ 개별 등급 배타 (§7.1)
const allBox = () => side.querySelector('input[data-group="tier"][data-value="all"]');
function syncTierAll(changed) {
  const all = allBox();
  if (!all) return;
  if (changed === all) {
    if (all.checked) box('tier').forEach(c => { if (c !== all) { c.checked = false; syncTierLinkage(c); } });
  } else {
    const anySpecific = box('tier').some(c => c !== all && c.checked);
    all.checked = !anySpecific;
  }
}

// ── 필터 적용 ──────────────────────────────────────────────────────
// 기사 단위 도달 (spec2 §6.3): 접힌 관련 보도 · 밴드 재출현 카드까지 판정한다.
// 블록은 구성 기사 중 하나라도 매칭이면 표시 — 대표가 조건 밖이면 흐림 (.ctxdim),
// 매칭 갈래는 자동 펼침. 필터 활성 시 밴드는 숨기고 재출현 카드 (.dupcard) 로 대체.
function applyFilters() {
  const q = (searchInput?.value || '').trim().toLowerCase();
  const outlets = checkedVals('outlet');
  const journalists = checkedVals('journalist');
  const tiers = checkedVals('tier').filter(v => v !== 'all');
  const stageSel = checkedVals('stage');                 // 각 값은 콤마로 이은 enum 집합
  const stageEnums = new Set(stageSel.flatMap(v => v.split(',')));
  const showOther = boxesOf('bucket').some(c => c.checked);
  const srcActive = outlets.length || journalists.length;
  const conds = outlets.length + journalists.length + tiers.length
    + stageSel.length + (showOther ? 1 : 0) + (q ? 1 : 0);
  const active = conds > 0;
  if (active) {
    expandGossip();                                      // 필터가 걸리면 가십 전체를 대상으로
    expandLatest();                                       // 이전 날짜 그룹도 필터 대상으로 편다
  } else {
    if (latestMore) { latestMore.hidden = false; latestSync(); }
    if (gossipMore) { gossipMore.hidden = false; gossipSync(); }
  }

  const match = (d) => {
    const okText = !q || (d.text || '').includes(q);
    const okSrc = !srcActive
      || outlets.includes(d.outlet) || journalists.includes(d.journalist);
    const okTier = tiers.length === 0 || tiers.includes(d.tier);
    const isOther = !d.stage || d.stage === 'other';
    const okStage = isOther ? showOther
      : (stageEnums.size === 0 || stageEnums.has(d.stage));
    return okText && okSrc && okTier && okStage;
  };

  let shown = 0;
  const selfHit = new Map();                             // 카드별 자기 매칭 (블록 판정용)
  for (const it of items) {
    const m = match(it.dataset);
    selfHit.set(it, m);
    if (it.classList.contains('dupcard')) {              // 밴드 · 가십 비대표 재출현 — 필터 활성 시에만
      const vis = active && m;
      it.style.display = vis ? '' : 'none';
      if (vis) shown++;
    } else if (!it.closest('.block')) {                  // 가십 등 낱개 카드
      it.style.display = m ? '' : 'none';
      if (m) shown++;
    }
  }
  for (const bl of document.querySelectorAll('.block')) {
    if (bl.querySelector('.dupcard')) continue;
    const cards = [...bl.querySelectorAll('.item')];     // 대표 + 결말
    const rels = [...bl.querySelectorAll('.relitem')];
    const relHits = active ? rels.filter(r => match(r.dataset)) : [];
    const blockHit = cards.some(c => selfHit.get(c)) || relHits.length > 0;
    shown += cards.filter(c => selfHit.get(c)).length + relHits.length;
    for (const c of cards) {
      // 조건 없음 = 기존 카드 단위 (기타 단계 숨김 유지) · 조건 있음 = 블록 단위
      c.style.display = (active ? blockHit : selfHit.get(c)) ? '' : 'none';
      c.classList.toggle('ctxdim', active && blockHit && !selfHit.get(c));
    }
    const rel = bl.querySelector('.related');
    const tog = bl.querySelector('.reltoggle');
    if (active) {
      rels.forEach(r => { r.style.display = relHits.includes(r) ? '' : 'none'; });
      if (rel) rel.hidden = relHits.length === 0;
      if (tog) {
        tog.style.display = relHits.length ? '' : 'none';
        tog.setAttribute('aria-expanded', relHits.length ? 'true' : 'false');
      }
      bl.querySelectorAll('.branchlabel').forEach(lb => {
        let n = lb.nextElementSibling, any = false;
        while (n && n.classList.contains('relitem')) {
          if (n.style.display !== 'none') any = true;
          n = n.nextElementSibling;
        }
        lb.style.display = any ? '' : 'none';
      });
    } else {                                             // 조건 없음 — 접힌 원상태로
      rels.forEach(r => { r.style.display = ''; });
      if (rel) rel.hidden = true;
      if (tog) { tog.style.display = ''; tog.setAttribute('aria-expanded', 'false'); }
      bl.querySelectorAll('.branchlabel').forEach(lb => { lb.style.display = ''; });
    }
  }
  const bandwrap = document.querySelector('.bandwrap');
  if (bandwrap) bandwrap.style.display = active ? 'none' : '';
  sortBlocks();
  hideEmpty();

  const touched = userTouchedSrc ? ' · 직접 고름' : '';
  if (fstatus) fstatus.textContent = active
    ? `조건 ${conds}개 · ${shown}건${touched}` : `전체 ${shown}건`;
  applyBtn?.classList.remove('dirty');
  const qs = filterParams().toString();
  history.replaceState(null, '', qs ? `?${qs}` : location.pathname);
}

function hideEmpty() {
  // 사건 블록 — 보이는 카드가 없으면 블록째 숨김
  document.querySelectorAll('.block').forEach(bl => {
    const vis = [...bl.querySelectorAll('.item')].some(i => i.style.display !== 'none');
    bl.style.display = vis ? '' : 'none';
  });
  for (const dl of daylists) {
    const vis = [...dl.querySelectorAll('.item')].some(i => i.style.display !== 'none');
    const div = dl.previousElementSibling;               // .daydiv
    if (div && div.classList.contains('daydiv')) div.style.display = vis ? '' : 'none';
    dl.style.display = vis ? '' : 'none';
  }
  const gl = document.querySelector('.gossiplist');
  if (gl) {
    const vis = [...gl.querySelectorAll('.item')].some(i => i.style.display !== 'none');
    document.querySelectorAll('.gossiphead, .gossipnote').forEach(e => { e.style.display = vis ? '' : 'none'; });
    gl.style.display = vis ? '' : 'none';
  }
}

// ── 정렬 (날짜 그룹 안에서 사건 블록 단위로) ─────────────────────────
function sortBlocks() {
  const key = sortSel?.value || 'latest';
  const views = key === 'views' ? readViews() : null;
  const rep = (bl) => bl.querySelector('.item');
  for (const dl of daylists) {
    const blocks = [...dl.querySelectorAll('.block')].sort((A, B) => {
      const a = rep(A), b = rep(B);
      if (!a || !b) return 0;
      if (key === 'confidence')
        return parseFloat(b.dataset.confidence || 0) - parseFloat(a.dataset.confidence || 0);
      if (key === 'views') {
        const d = (views[b.dataset.hash] || 0) - (views[a.dataset.hash] || 0);
        if (d) return d;
      }
      return (b.dataset.published || '').localeCompare(a.dataset.published || '');
    });
    for (const bl of blocks) dl.appendChild(bl);
  }
}

// ── URL 상태 ──────────────────────────────────────────────────────
function filterParams() {
  const p = new URLSearchParams();
  for (const g of URL_GROUPS) for (const v of checkedVals(g)) if (v !== 'all') p.append(g, v);
  if (sortSel && sortSel.value !== 'latest') p.set('sort', sortSel.value);
  const q = (searchInput?.value || '').trim();
  if (q) p.set('q', q);
  return p;
}
function restoreFromQuery() {
  const p = new URLSearchParams(location.search);
  if (![...p.keys()].length) return false;
  const want = {};
  for (const g of URL_GROUPS) want[g] = p.getAll(g);
  boxesOf('outlet').concat(boxesOf('journalist'), boxesOf('stage'), boxesOf('bucket'))
    .forEach(c => { c.checked = want[c.dataset.group].includes(c.dataset.value); });
  box('tier').forEach(c => {
    if (c.dataset.value === 'all') c.checked = want.tier.length === 0;
    else c.checked = want.tier.includes(c.dataset.value);
  });
  if (sortSel) sortSel.value = ['confidence', 'views'].includes(p.get('sort')) ? p.get('sort') : 'latest';
  if (searchInput) searchInput.value = p.get('q') || '';
  return true;
}

// ── 배선 ──────────────────────────────────────────────────────────
function resetAll() {
  boxesOf('outlet').concat(boxesOf('journalist'), boxesOf('stage'), boxesOf('bucket'))
    .forEach(c => { c.checked = false; c.closest('.opt').classList.remove('auto'); });
  box('tier').forEach(c => { c.checked = c.dataset.value === 'all'; });
  box('team').forEach(c => { c.checked = c.dataset.value === 'arsenal'; });
  userTouchedSrc = false;
  if (searchInput) searchInput.value = '';
}

if (side) setupAllMore();

if (items.length) {                                       // 인덱스
  side.addEventListener('change', (e) => {
    const t = e.target;
    if (t.dataset?.group === 'tier') { syncTierAll(t); syncTierLinkage(t); }
    if (t.dataset?.group === 'outlet' || t.dataset?.group === 'journalist') {
      t.closest('.opt').classList.remove('auto');
      userTouchedSrc = true;
    }
    applyBtn?.classList.add('dirty');
  });
  if (applyBtn) applyBtn.onclick = applyFilters;
  if (resetBtn) resetBtn.onclick = () => { resetAll(); applyFilters(); };
  if (sortSel) sortSel.onchange = () => { sortBlocks(); const qs = filterParams().toString();
    history.replaceState(null, '', qs ? `?${qs}` : location.pathname); };
  if (searchInput) searchInput.addEventListener('input', applyFilters);
  if (restoreFromQuery()) applyFilters();
  else { sortBlocks(); hideEmpty(); }
} else if (side) {                                         // 상세 — 필터는 인덱스로 이동
  const indexHref = document.querySelector('.logo')?.getAttribute('href') || 'index.html';
  side.addEventListener('change', (e) => {
    const t = e.target;
    if (t.dataset?.group === 'tier') { syncTierAll(t); syncTierLinkage(t); }
    applyBtn?.classList.add('dirty');
  });
  if (applyBtn) applyBtn.onclick = () => {
    const qs = filterParams().toString();
    location.href = qs ? `${indexHref}?${qs}` : indexHref;
  };
  if (resetBtn) resetBtn.onclick = resetAll;
}
