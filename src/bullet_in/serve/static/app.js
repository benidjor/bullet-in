// Bullet-in 서빙 인터랙션 — 필터 · 정렬 · 공신력 연동 · 테마.
// DOM 계약: a.item[data-hash][data-stage][data-dir][data-tier][data-outlet][data-journalist][data-published][data-confidence][data-text]
//   data-journalist 는 공저 저자 전원을 '|' 로 이은 다중 값이다 (단독 기사면 값 하나).
//           사이드바 옵션 input[data-group][data-value][data-tier]
// URL 계약: ?outlet=&journalist=&tier=&stage=&bucket=other&sort=confidence|views&q=  (다중 선택은 키 반복)
// 결합 규칙 (§8): (소스 OR 기자) AND 공신력 AND 영입 단계 AND 검색어

// ── 계측 (공개 준비 2026-08-23) ─────────────────────────────────────
// 세는 것은 넷이다 — 유입 경로 · 카드 클릭 · 필터 사용 · 원문 이탈.
// 고른 기준은 「이 값이 다르게 나오면 내가 다르게 행동할까」 이고, 그렇지 않은 지표는
// 안 센다. 택소노미 본 설계는 이적시장 마감 뒤로 미루고 이름 규칙만 열어 둔다.
//
// 모든 이벤트에 익명 식별자 (bi_cid) 와 시각 (bi_ts) 을 싣는다.
// 이 둘은 나중에 채울 수 없는 값이라 처음부터 넣는다 — 없이 모으면 공개 주간의
// 행동을 영영 사람 단위로 못 묶는다.
// 세션 경계는 여기서 정하지 않는다. 식별자와 시각만 있으면 세션은 나중에 어떤
// 정의로든 다시 만들 수 있고, 지금 정의를 굳히면 그때 바꾸기 어려워진다.
const CID_KEY = 'bulletin_cid';
const BI_CID = (function clientId() {
  try {
    let v = localStorage.getItem(CID_KEY);
    if (!v) {
      v = (crypto.randomUUID ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`);
      localStorage.setItem(CID_KEY, v);
    }
    return v;
  } catch { return 'nostore'; }   // 저장이 막힌 브라우저 — 이벤트는 그대로 보낸다
})();

function track(name, params) {
  if (typeof gtag !== 'function') return;   // 측정 ID 미설정 · 차단기 — 조용히 넘어간다
  gtag('event', name, Object.assign({}, params,
    { bi_cid: BI_CID, bi_ts: new Date().toISOString() }));
}

// ① 유입 경로 — 어느 커뮤니티 글이 사람을 데려오나 (다음에 어디에 알릴지의 근거)
(function trackEntry() {
  const p = new URLSearchParams(location.search);
  track('bi_entry', {
    entry_path: location.pathname,
    referrer: document.referrer || '(none)',
    utm_source: p.get('utm_source') || '',
    utm_medium: p.get('utm_medium') || '',
    utm_campaign: p.get('utm_campaign') || '',
  });
})();

// ② 카드 클릭 — 이적설인가 오피셜인가 · 무엇을 보러 오나
document.addEventListener('click', (e) => {
  const card = e.target.closest?.('a.item, a.relitem, a.mitem, a.pcard, a.tltitle');
  if (!card) return;
  track('bi_card_click', {
    card_hash: card.dataset.hash || '',
    card_stage: card.dataset.stage || '',
    card_tier: card.dataset.tier || '',
    card_outlet: card.dataset.outlet || '',
    card_surface: card.classList[0] || '',
  });
});

// ④ 원문 이탈 — 탐색 도구로 기능하는가 (색인 정책의 근거 데이터이기도 하다)
document.querySelectorAll('a[data-exit]').forEach(a => {
  a.addEventListener('click', () => track('bi_origin_exit', {
    card_hash: a.dataset.hash || '',
    card_outlet: a.dataset.outlet || '',
    exit_from: a.dataset.exit,          // origin_button · excerpt_note
  }));
});

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
  scope._moreSync = sync;      // 검색칸이 검색을 마칠 때 열려 있던 단계로 되돌린다
}
const setupAllMore = () => document.querySelectorAll('.facetgroup').forEach(setupMore);

// ── facet 검색칸 (기자 목록) ────────────────────────────────────────
// 접힌 단계 안의 이름도 걸려야 하므로 검색 중에는 단계를 전부 펼치고 견출 · 더보기
// 버튼을 감춘다. 그러지 않으면 뒤쪽 단계의 이름이 구조적으로 검색에서 빠진다.
function setupFacetSearch(input) {
  const scope = input.closest('.grpbody')?.querySelector('.facetgroup');
  if (!scope) return;
  const heads = [...scope.querySelectorAll('.tierhead, .unreghead')];
  const stages = [...scope.querySelectorAll('.morestage')];
  const btns = [...scope.querySelectorAll('.morebtn')];
  // 검색 키는 라벨의 텍스트 노드만 — 건수 span 을 넣으면 숫자가 이름에 걸린다
  const opts = [...scope.querySelectorAll('label.opt')].map(o => [o,
    [...o.childNodes].filter(n => n.nodeType === 3)
      .map(n => n.textContent).join(' ').trim().toLowerCase()]);
  const run = () => {
    const q = input.value.trim().toLowerCase();
    heads.forEach(h => { h.hidden = !!q; });
    btns.forEach(b => { if (q) b.hidden = true; });
    opts.forEach(([o, key]) => { o.hidden = !!q && !key.includes(q); });
    if (q) stages.forEach(s => { s.hidden = false; });
    else scope._moreSync?.();
  };
  // 엔터 · 돋보기 버튼에서 걸린다 (기사 검색과 같은 규칙) — 비우면 그 자리에서 되돌린다.
  input.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    run();
  });
  input.addEventListener('input', () => { if (!input.value.trim()) run(); });
  input.addEventListener('search', run);
  document.getElementById('jSearchGo')?.addEventListener('click', run);
}

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
  const day = s => s ? new Date(s.slice(0, 10)) : null;   // 캘린더 날짜 (latest 와 동일 규칙)
  const anchor = day(hidden[0].dataset.published);
  if (anchor) anchor.setDate(anchor.getDate() - 6);
  if (gossipList.classList.contains('weekcut')) {
    gossipList.classList.remove('weekcut');
    gossipCards.forEach(c => { if (c.classList.contains('gwk')) c.classList.add('wcut'); });
  }
  gossipCards.forEach(c => {
    const d = day(c.dataset.published);
    if (!anchor || !d || d >= anchor) c.classList.remove('wcut');
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

// ③ 필터 사용 — 가장 공들인 축 (기자 · 언론사 · 단계) 이 실제로 쓰이나.
// 「적용」 을 누른 순간에만 센다 — 검색어 입력은 글자마다 applyFilters 를 부르므로
// 거기에 붙이면 한 번의 검색이 이벤트 수십 건이 된다.
function trackFilterApply() {
  const q = (searchInput?.value || '').trim();
  const outlets = checkedVals('outlet');
  const journalists = checkedVals('journalist');
  const tiers = checkedVals('tier').filter(v => v !== 'all');
  const stages = checkedVals('stage');
  const other = boxesOf('bucket').some(c => c.checked);
  track('bi_filter_apply', {
    n_outlet: outlets.length, n_journalist: journalists.length,
    n_tier: tiers.length, n_stage: stages.length,
    has_other: other ? 1 : 0, has_query: q ? 1 : 0,
    // 어느 축을 실제로 쓰는지 한 칸에 모아 둔다 — 조합을 세기 쉽게
    axes: [outlets.length && 'outlet', journalists.length && 'journalist',
           tiers.length && 'tier', stages.length && 'stage',
           other && 'other', q && 'query'].filter(Boolean).join('+') || '(none)',
  });
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
      || outlets.includes(d.outlet)
      // data-journalist 는 공저 기사의 저자 전원이라 '|' 로 이어져 있다 — 하나라도
      // 걸리면 참 (render.article_journalists 와 같은 계약).
      || (d.journalist || '').split('|').some(j => journalists.includes(j));
    const okTier = tiers.length === 0 || tiers.includes(d.tier);
    // 링크 선수 배지 (data-ctx) 예외는 2026-08-27 에 배지와 함께 걷어냈다 —
    // 서버 렌더 (_cards.html.j2) 와 같은 규칙을 여기서도 쓴다.
    const isOther = (!d.stage || d.stage === 'other');
    // 단계 필터는 방향 in·out (아스날 주체) 한정 — 타 구단 딜 (none) 은 필터 체크 시
    // 제외되고, 필터가 없을 때의 노출 · 기타 토글 분모는 그대로다 (단계 재정의 스펙 §8).
    // 무산 (collapsed) 은 방향을 보지 않는다 (§8 개정) — 잔류 확정 · 재계약 체결이
    // 방향 none 이라 걸러지면 무산 필터가 제 내용물을 잃는다. render.in_stage_filter 와 같은 규칙.
    const dirOk = d.stage === 'collapsed' || d.dir === 'in' || d.dir === 'out';
    // 언론사 · 기자로 좁히면 기타도 함께 연다 — 사이드바가 적어 둔 건수에는 기타 기사가
    // 들어 있는데 기타 토글 말고는 그것을 열 수단이 없었다 (사이드바 계수 설계 §5.1).
    // 단계를 함께 고른 경우는 그대로 뺀다 — 기타는 어느 단계에도 안 속한다.
    const okStage = isOther ? (showOther || (srcActive && stageEnums.size === 0))
      : (stageEnums.size === 0 || (stageEnums.has(d.stage) && dirOk));
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
    ? `조건 ${conds}개 · ${shown}건${touched}` : `조건 없음 · 전체 ${shown}건`;
  applyBtn?.classList.remove('dirty');
  const qs = filterParams().toString();
  history.replaceState(null, '', qs ? `?${qs}` : location.pathname);
}

// 목록은 2열 격자다 — 보이는 카드가 하나뿐이면 오른쪽 열이 빈 채로 남아 기사가
// 화면 절반으로 찌그러진다. 그 줄만 한 열로 되돌린다 (필터가 걸릴 때 자주 생긴다).
function soloWidth(list) {
  const vis = [...list.children].filter(el => el.style.display !== 'none'
    && !el.hidden && getComputedStyle(el).display !== 'none');
  list.classList.toggle('solo', vis.length === 1);
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
    soloWidth(dl);
  }
  const gl = document.querySelector('.gossiplist');
  if (gl) {
    const vis = [...gl.querySelectorAll('.item')].some(i => i.style.display !== 'none');
    document.querySelectorAll('.gossiphead, .gossipnote').forEach(e => { e.style.display = vis ? '' : 'none'; });
    gl.style.display = vis ? '' : 'none';
    soloWidth(gl);
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
  const js = document.getElementById('jSearch');       // 기자 검색칸도 함께 되돌린다
  if (js && js.value) { js.value = ''; js.dispatchEvent(new Event('input')); }
}

if (side) {
  setupAllMore();
  const jSearch = document.getElementById('jSearch');
  if (jSearch) setupFacetSearch(jSearch);
}

if (items.length && side) {                               // 인덱스
  side.addEventListener('change', (e) => {
    const t = e.target;
    if (t.dataset?.group === 'tier') { syncTierAll(t); syncTierLinkage(t); }
    if (t.dataset?.group === 'outlet' || t.dataset?.group === 'journalist') {
      t.closest('.opt').classList.remove('auto');
      userTouchedSrc = true;
    }
    applyBtn?.classList.add('dirty');
  });
  if (applyBtn) applyBtn.onclick = () => { trackFilterApply(); applyFilters(); };
  if (resetBtn) resetBtn.onclick = () => { resetAll(); applyFilters(); };
  if (sortSel) sortSel.onchange = () => { sortBlocks(); const qs = filterParams().toString();
    history.replaceState(null, '', qs ? `?${qs}` : location.pathname); };
  if (searchInput) {
    // 입력할 때마다 목록이 튀지 않게 — 엔터 · 돋보기 버튼 · 「필터 적용」 에서만 반영한다.
    searchInput.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      applyFilters();
    });
    searchInput.addEventListener('input', () => { applyBtn?.classList.add('dirty'); });
    // 검색칸의 × 로 비우면 그 자리에서 되돌린다 (엔터를 누를 값이 없다)
    searchInput.addEventListener('search', () => { if (!searchInput.value.trim()) applyFilters(); });
    document.getElementById('qGo')?.addEventListener('click', () => {
      trackFilterApply();
      applyFilters();
    });
  }
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
    trackFilterApply();
    const qs = filterParams().toString();
    location.href = qs ? `${indexHref}?${qs}` : indexHref;
  };
  if (resetBtn) resetBtn.onclick = resetAll;
}

// ── 선수 색인 — 무산 그룹 접기 (스펙 §4.1) ─────────────────────────
document.querySelectorAll('.plgrp .plfold').forEach(btn => {
  btn.addEventListener('click', () => {
    const grp = btn.closest('.plgrp');
    const folded = grp.classList.toggle('folded');
    btn.textContent = folded ? '펼치기' : '접기';
  });
});

// ── 선수 페이지 — 기사 10건 단위 더보기 · 접기 (사다리 스펙 §5.2) ────
// 서버가 11번째 블록부터 pl-extra 를 붙여 두고, 여기서는 노출 건수 shown 기준으로
// 매번 다시 계산한다. 선수 페이지엔 사이드바가 없어 applyFilters 가 배선되지
// 않으므로 (items.length && side) 인라인 display 와 부딪히지 않는다.
const plList = document.querySelector('.plist');
const plMore = document.getElementById('plMore');
if (plList && plMore) {
  const plBlocks = [...plList.querySelectorAll('.block')];
  const PL_INIT = 10;
  let plShown = PL_INIT;
  const plSync = () => {
    plBlocks.forEach((b, i) => b.classList.toggle('pl-extra', i >= plShown));
    const left = plBlocks.length - plShown;
    plMore.textContent = left > 0 ? `기사 더보기 · 남은 ${left}건` : '접기';
  };
  plMore.onclick = () => {
    if (plShown < plBlocks.length) { plShown += 10; }
    else {
      plShown = PL_INIT;
      plList.previousElementSibling?.scrollIntoView({ behavior: 'smooth', block: 'start' });  // 구역 머리 (sechead)
    }
    plSync();
  };
}
