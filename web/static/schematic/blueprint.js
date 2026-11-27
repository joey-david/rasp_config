// Drawing-sheet furniture: zone rulers, cursor readout, plotter pass, title block, keyboard.
(() => {
  const frame = document.getElementById('frame');
  const wrap = document.querySelector('.board-wrap');
  const board = document.getElementById('board');
  const detail = document.getElementById('detail');
  const hud = document.getElementById('hud');
  const readout = document.getElementById('readout');
  const xh = wrap.querySelector('.xh');
  const xv = wrap.querySelector('.xv');
  const MM_PER_PX = 0.25;
  const COLS = 8;
  const sheetOrder = ['assembly', 'wiring', 'software'];
  let rows = 6;

  // Zone rulers: numbers across, letters down, like a real drawing frame.
  function buildRulers() {
    rows = Math.max(3, Math.round(frame.offsetHeight / 340));
    const nums = Array.from({ length: COLS }, (_, i) => `<span data-c="${i}">${i + 1}</span>`).join('');
    const lets = Array.from({ length: rows }, (_, i) => `<span data-r="${i}">${String.fromCharCode(65 + i)}</span>`).join('');
    frame.querySelectorAll('.ruler-top, .ruler-bottom').forEach((r) => (r.innerHTML = nums));
    frame.querySelectorAll('.ruler-left, .ruler-right').forEach((r) => (r.innerHTML = lets));
  }
  new ResizeObserver(buildRulers).observe(frame);

  const fmt = (v) => (v * MM_PER_PX).toFixed(1).padStart(6, '0');
  let lastZone = '';

  frame.addEventListener('pointermove', (e) => {
    if (e.pointerType === 'touch') return;
    const r = frame.getBoundingClientRect();
    const x = e.clientX - r.left;
    const y = e.clientY - r.top;
    const c = Math.min(COLS - 1, Math.max(0, Math.floor((x / r.width) * COLS)));
    const row = Math.min(rows - 1, Math.max(0, Math.floor((y / r.height) * rows)));
    const zone = String.fromCharCode(65 + row) + (c + 1);
    if (zone !== lastZone) {
      lastZone = zone;
      frame.querySelectorAll('.ruler span.on').forEach((s) => s.classList.remove('on'));
      frame.querySelectorAll(`[data-c="${c}"], [data-r="${row}"]`).forEach((s) => s.classList.add('on'));
    }
    hud.innerHTML = `<b>ZONE ${zone}</b><span>X ${fmt(x)}</span><span>Y ${fmt(y)}</span><span>MM</span>`;
    hud.classList.add('on');
  });
  frame.addEventListener('pointerleave', () => {
    hud.classList.remove('on');
    frame.querySelectorAll('.ruler span.on').forEach((s) => s.classList.remove('on'));
    lastZone = '';
  });

  // Crosshair + coordinate readout over the drawing board.
  wrap.addEventListener('pointermove', (e) => {
    if (e.pointerType === 'touch') return;
    const r = wrap.getBoundingClientRect();
    const x = e.clientX - r.left;
    const y = e.clientY - r.top;
    xh.style.top = y + 'px';
    xv.style.left = x + 'px';
    wrap.classList.add('tracking');
    readout.textContent = `X ${fmt(x + board.scrollLeft)} · Y ${fmt(y + board.scrollTop)} MM`;
  });
  wrap.addEventListener('pointerleave', () => {
    wrap.classList.remove('tracking');
    readout.textContent = 'X —— · Y ——';
  });

  // Plotter pass whenever a different sheet (or software sub-sheet) is drawn.
  let lastView = null;
  function plot() {
    wrap.classList.remove('plotting');
    void wrap.offsetWidth;
    wrap.classList.add('plotting');
  }
  wrap.addEventListener('animationend', (e) => {
    if (e.animationName === 'plot') wrap.classList.remove('plotting');
  });

  function viewKey() {
    const [page, id] = location.hash.slice(1).split('/');
    const sheet = sheetOrder.includes(page) ? page : 'assembly';
    return sheet === 'software' && (id === 'tracking' || id === 'diagnosis') ? sheet + '/' + id : sheet;
  }

  // Title block follows the open sheet and the inspected part.
  function syncTitle() {
    const sheet = viewKey().split('/')[0];
    const n = sheetOrder.indexOf(sheet) + 1;
    document.getElementById('tb-title').textContent = document.getElementById('title').textContent || '—';
    document.getElementById('tb-sheet').textContent = `${n} of ${sheetOrder.length}`;
    document.getElementById('tb-dwg').textContent = `MB-001-0${n}`;
    document.title = `${document.getElementById('title').textContent} · Mischief Bot DWG MB-001-0${n}`;
    const key = viewKey();
    if (key !== lastView) {
      if (lastView !== null) plot();
      lastView = key;
    }
  }

  const bubble = document.getElementById('detail-ref');
  let lastSel = '';
  function syncSel() {
    const name = detail.querySelector('h2')?.textContent || '—';
    document.getElementById('tb-sel').textContent = name;
    if (name === lastSel) return;
    lastSel = name;
    const num = board.querySelector('.part.active .part-num')?.textContent;
    bubble.textContent = num || name.replace(/[^A-Za-z0-9 ]/g, ' ').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase();
    bubble.classList.remove('pop');
    void bubble.offsetWidth;
    bubble.classList.add('pop');
  }
  new MutationObserver(syncSel).observe(detail, { childList: true });
  syncSel();

  window.addEventListener('hashchange', syncTitle);
  syncTitle();
  plot();

  // Keyboard: 1–3 switch sheets, [ and ] step through the parts on the current sheet.
  document.addEventListener('keydown', (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey || e.target.closest('input, textarea, select, #orbit')) return;
    const i = ['1', '2', '3'].indexOf(e.key);
    if (i >= 0) {
      location.hash = sheetOrder[i];
      return;
    }
    if (e.key !== '[' && e.key !== ']') return;
    const items = Array.from(board.querySelectorAll('a[data-part], a[data-sw-mod]'));
    if (!items.length) return;
    const cur = items.findIndex((el) => el.classList.contains('active'));
    const next = items[(cur + (e.key === ']' ? 1 : -1) + items.length) % items.length];
    location.hash = next.getAttribute('href');
    next.focus({ preventScroll: true });
    e.preventDefault();
  });

  // Rubber stamp re-approves on click; the scan's pencil note fades once touched.
  const stamp = document.getElementById('stamp');
  stamp.addEventListener('click', () => {
    stamp.classList.remove('thunk');
    void stamp.offsetWidth;
    stamp.classList.add('thunk');
  });
  stamp.classList.add('thunk');
  document.getElementById('orbit').addEventListener('pointerdown', (e) => {
    e.currentTarget.dataset.touched = '';
  }, { once: true });
})();
