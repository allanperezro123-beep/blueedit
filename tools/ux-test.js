/* UX regression test. Serves ./public on a free port, drives it in headless
   Chrome at desktop and phone sizes, and asserts the ergonomics that were
   reported broken. Self-contained: no server or browser to start by hand.

     node tools/ux-test.js

   Set CHROME to override the browser path. */
const path = require('path');
const fs = require('fs');
const http = require('http');
const puppeteer = require('puppeteer-core');

const ROOT = path.resolve(__dirname, '..');
const PUB = path.join(ROOT, 'public');
const CHROME = process.env.CHROME || [
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  '/usr/bin/google-chrome'
].find(p => fs.existsSync(p));
const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript',
  '.svg': 'image/svg+xml', '.jpg': 'image/jpeg', '.png': 'image/png'
};

const results = [];
const ok = (name, pass, info) => results.push({ name, pass: !!pass, info: info === undefined ? '' : String(info) });
const sleep = ms => new Promise(r => setTimeout(r, ms));

const server = http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split('?')[0]);
  if (p === '/') p = '/index.html';
  const f = path.join(PUB, p);
  if (!f.startsWith(PUB) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) {
    res.writeHead(404); return res.end('not found');
  }
  res.writeHead(200, { 'Content-Type': MIME[path.extname(f)] || 'application/octet-stream' });
  fs.createReadStream(f).pipe(res);
});

/* Helpers injected into the page. */
const HELPERS = () => {
  window.UT = {
    rect(sel) {
      const el = typeof sel === 'string' ? document.querySelector(sel) : sel;
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: r.left, y: r.top, w: r.width, h: r.height, r: r.right, b: r.bottom };
    },
    /* Visible AND inside the viewport: an element pushed off-screen is not usable. */
    onScreen(sel) {
      const el = typeof sel === 'string' ? document.querySelector(sel) : sel;
      if (!el) return false;
      const r = el.getBoundingClientRect(), s = getComputedStyle(el);
      return r.width > 4 && r.height > 4 && s.display !== 'none' && s.visibility !== 'hidden' &&
        r.left >= -1 && r.top >= -1 && r.right <= innerWidth + 1 && r.bottom <= innerHeight + 1;
    },
    wait: ms => new Promise(r => setTimeout(r, ms))
  };
};

async function open(browser, url, w, h, mobile) {
  const page = await browser.newPage();
  await page.setViewport({ width: w, height: h, isMobile: !!mobile, hasTouch: !!mobile });
  const errors = [];
  page.on('console', m => { if (m.type() === 'error' && !/favicon/i.test(m.text())) errors.push(m.text()); });
  page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message));
  await page.evaluateOnNewDocument(() => { try { localStorage.clear(); } catch (e) {} });
  await page.goto(url, { waitUntil: 'networkidle2', timeout: 60000 });
  await sleep(1500);
  await page.evaluate(HELPERS);
  return { page, errors };
}

async function desktop(browser, url) {
  const { page, errors } = await open(browser, url, 1440, 900);

  /* ---- zoom field must not be stretched by the generic input rule ---- */
  const zw = await page.evaluate(() => UT.rect('#zoomPct').w);
  ok('Escritorio: el campo de zoom mide lo que debe', zw <= 70, Math.round(zw) + ' px');

  /* ---- rail tooltips describe what each tool really does ---- */
  const tips = await page.evaluate(() => ({
    select: document.querySelector('[data-tool="select"]').title,
    pan: document.querySelector('[data-tool="pan"]').title
  }));
  ok('Escritorio: el rótulo de la 1.ª herramienta dice que mueve objetos', /objeto/i.test(tips.select) && /área/i.test(tips.select), tips.select);
  ok('Escritorio: el rótulo de la 2.ª herramienta dice que mueve la vista', /vista/i.test(tips.pan) && !/capa|objeto/i.test(tips.pan), tips.pan);

  /* ---- ...and the labels are TRUE: checked with the real pointer ---- */
  const dragWith = async (tool) => {
    const a = await page.evaluate(async (tool) => {
      const E = window.EditorActas, c = E.canvas;
      if (!c.getObjects().some(o => !o.isPage)) {
        document.querySelector('[data-tool="shape"]').click(); await UT.wait(80);
        document.getElementById('shFillColor').click(); await UT.wait(80);
        document.getElementById('shInsertBtn').click(); await UT.wait(250);
      }
      c.discardActiveObject();
      document.querySelector('[data-tool="' + tool + '"]').click(); await UT.wait(150);
      const o = c.getObjects().filter(x => !x.isPage)[0];
      const p = fabric.util.transformPoint(o.getCenterPoint(), c.viewportTransform);
      const r = UT.rect('canvas.upper-canvas');
      return { x: r.x + p.x, y: r.y + p.y, left: o.left, vx: c.viewportTransform[4], title: document.getElementById('panelTitle').textContent };
    }, tool);
    await page.mouse.move(a.x, a.y); await page.mouse.down();
    for (let i = 1; i <= 8; i++) await page.mouse.move(a.x + i * 6, a.y + i * 3);
    await page.mouse.up(); await sleep(250);
    const z = await page.evaluate(() => {
      const c = window.EditorActas.canvas, o = c.getObjects().filter(x => !x.isPage)[0];
      return { left: o.left, vx: c.viewportTransform[4] };
    });
    return { objMoved: Math.abs(z.left - a.left) > 5, viewMoved: Math.abs(z.vx - a.vx) > 5, title: a.title };
  };
  const dPan = await dragWith('pan');
  ok('Escritorio: la Mano mueve la vista y no el objeto', dPan.viewMoved && !dPan.objMoved);
  ok('Escritorio: el panel de la Mano habla de la vista', /vista/i.test(dPan.title), dPan.title);
  const dSel = await dragWith('select');
  ok('Escritorio: Seleccionar mueve el objeto y no la vista', dSel.objMoved && !dSel.viewMoved);
  await page.evaluate(async () => {
    const E = window.EditorActas, c = E.canvas;
    c.getObjects().filter(o => !o.isPage).forEach(o => c.remove(o)); c.discardActiveObject();
    E.zoomToFit(); c.requestRenderAll();
    await UT.wait(100);
  });

  /* ---- Escape closes a dialog even with the caret inside one of its fields ---- */
  await page.click('#btnAuth');
  await sleep(500);
  await page.focus('#snUser');
  await page.keyboard.press('Escape');
  await sleep(250);
  const authOpen = await page.evaluate(() => document.getElementById('authModal').classList.contains('on'));
  ok('Escritorio: Esc cierra el diálogo de sesión desde un campo', !authOpen);

  await page.click('#liveBtn');
  await sleep(400);
  const liveInput = await page.$('#liveModal input');
  if (liveInput) await liveInput.focus();
  await page.keyboard.press('Escape');
  await sleep(250);
  const liveOpen = await page.evaluate(() => document.getElementById('liveModal').classList.contains('on'));
  ok('Escritorio: Esc cierra "Sala en vivo" desde un campo', !liveOpen);

  /* ---- clicking the backdrop closes a dialog ---- */
  await page.click('#btnHelp');
  await sleep(350);
  await page.mouse.click(12, 450);
  await sleep(250);
  const helpOpen = await page.evaluate(() => document.getElementById('helpModal').classList.contains('on'));
  ok('Escritorio: clic fuera cierra el diálogo', !helpOpen);

  /* ---- "Hoja A4" adds a sheet; it used to wipe the whole document ---- */
  const blank = await page.evaluate(async () => {
    const E = window.EditorActas;
    document.querySelector('[data-tool="shape"]').click(); await UT.wait(80);
    document.getElementById('shInsertBtn').click(); await UT.wait(200);
    const before = { pages: E.Doc.pages.length, objs: E.canvas.getObjects().filter(o => !o.isPage).length };
    document.getElementById('btnBlank').click(); await UT.wait(500);
    const pages = E.Doc.pages.length;
    document.querySelector('#pagebar .pg').click(); await UT.wait(500);
    return { before, pages, objsBack: E.canvas.getObjects().filter(o => !o.isPage).length };
  });
  ok('Escritorio: "Hoja A4" agrega una hoja', blank.pages === blank.before.pages + 1,
     blank.before.pages + ' -> ' + blank.pages + ' hojas');
  ok('Escritorio: "Hoja A4" no borra el trabajo hecho', blank.before.objs === 1 && blank.objsBack === 1,
     blank.objsBack + ' objeto(s) en la hoja 1');

  /* ---- a burst of notices must not bury the layers panel ---- */
  const toasts = await page.evaluate(async () => {
    for (let i = 0; i < 6; i++) { window.toast('Aviso de prueba ' + i, 'ok'); await UT.wait(40); }
    window.toast('Aviso repetido', 'ok'); window.toast('Aviso repetido', 'ok');
    await UT.wait(150);
    const list = [...document.querySelectorAll('#toasts .toast')].filter(t => !t.querySelector('button'));
    const panel = UT.rect('.panel.right');
    const overlap = list.some(t => { const r = t.getBoundingClientRect(); return r.right > panel.x + 1 && r.left < panel.r - 1; });
    const dups = list.filter((t, i) => i > 0 && t.textContent === list[i - 1].textContent).length;
    return { n: list.length, overlap, dups };
  });
  ok('Escritorio: 3 avisos a la vez, sin repetidos pegados', toasts.n === 3 && toasts.dups === 0, toasts.n + ' avisos, ' + toasts.dups + ' repetidos');
  ok('Escritorio: los avisos no tapan el panel de Capas', !toasts.overlap);

  /* ---- both side panels collapse, and the canvas takes the room ---- */
  const collapse = await page.evaluate(async () => {
    const stageW = () => UT.rect('#stage').w;
    const cvW = () => UT.rect('canvas.upper-canvas').w;
    const out = { hasLeft: !!document.getElementById('uxToggleLeft'), hasRight: !!document.getElementById('uxToggleRight') };
    if (!out.hasLeft || !out.hasRight) return out;
    /* how far the sheet's centre is from the stage's centre, in px */
    const pageOff = () => { const c = window.EditorActas.canvas, p = window.EditorActas.Doc.page(), v = c.viewportTransform;
      return (v[4] + p.pxW * v[0] / 2) - stageW() / 2; };
    out.s0 = stageW(); out.c0 = cvW(); out.off0 = pageOff();
    document.getElementById('uxToggleLeft').click(); await UT.wait(450);
    out.s1 = stageW(); out.c1 = cvW(); out.leftW = UT.rect('.panel.left').w; out.off1 = pageOff();
    document.getElementById('uxToggleRight').click(); await UT.wait(450);
    out.s2 = stageW(); out.c2 = cvW(); out.rightW = UT.rect('.panel.right').w;
    /* choosing a tool brings its panel back: otherwise the click looks dead */
    document.querySelector('[data-tool="shape"]').click(); await UT.wait(450);
    out.leftBack = UT.rect('.panel.left').w;
    document.getElementById('uxToggleRight').click(); await UT.wait(450);
    out.s3 = stageW();
    return out;
  });
  ok('Escritorio: hay botones para plegar los paneles', collapse.hasLeft && collapse.hasRight);
  ok('Escritorio: plegar el panel izquierdo agranda el lienzo',
     collapse.leftW < 2 && collapse.s1 > collapse.s0 + 200 && collapse.c1 > collapse.c0 + 200,
     `escenario ${Math.round(collapse.s0)} -> ${Math.round(collapse.s1)}, canvas ${Math.round(collapse.c0)} -> ${Math.round(collapse.c1)}`);
  ok('Escritorio: al plegar, la hoja sigue centrada', Math.abs(collapse.off1 - collapse.off0) < 2,
     Math.round(collapse.off0) + ' -> ' + Math.round(collapse.off1) + ' px del centro');
  ok('Escritorio: plegar el panel derecho agranda el lienzo',
     collapse.rightW < 2 && collapse.s2 > collapse.s1 + 150 && collapse.c2 > collapse.c1 + 150,
     `escenario ${Math.round(collapse.s1)} -> ${Math.round(collapse.s2)}`);
  ok('Escritorio: elegir una herramienta reabre su panel', collapse.leftBack > 200, Math.round(collapse.leftBack) + ' px');
  ok('Escritorio: los paneles vuelven a su sitio', Math.abs(collapse.s3 - collapse.s0) < 2,
     Math.round(collapse.s0) + ' -> ' + Math.round(collapse.s3));

  /* ---- the collapsed state survives a reload ---- */
  await page.evaluate(() => document.getElementById('uxToggleRight').click());
  await sleep(300);
  await page.evaluateOnNewDocument(() => {});
  const kept = await (async () => {
    const p2 = await browser.newPage();
    await p2.setViewport({ width: 1440, height: 900 });
    await p2.goto(url, { waitUntil: 'networkidle2' });
    await sleep(1200);
    const w = await p2.evaluate(() => document.querySelector('.panel.right').getBoundingClientRect().width);
    await p2.evaluate(() => { try { localStorage.clear(); } catch (e) {} });
    await p2.close();
    return w;
  })();
  ok('Escritorio: el panel plegado se recuerda al recargar', kept < 2, Math.round(kept) + ' px');

  ok('Escritorio: consola sin errores', errors.length === 0, errors.slice(0, 3).join(' | '));
  await page.screenshot({ path: path.join(__dirname, 'shot_ux_desktop.png') });
  await page.close();
}

async function phone(browser, url) {
  const { page, errors } = await open(browser, url, 390, 844, true);

  const lay = await page.evaluate(() => {
    const stage = UT.rect('#stage');
    const tools = [...document.querySelectorAll('#rail [data-tool]')];
    const rail = document.getElementById('rail');
    return {
      overflowX: document.documentElement.scrollWidth > innerWidth + 1,
      stage,
      railOnScreen: UT.onScreen(rail),
      railScrolls: rail.scrollWidth > rail.clientWidth + 1 ? getComputedStyle(rail).overflowX : 'fits',
      smallTargets: tools.filter(b => { const r = b.getBoundingClientRect(); return r.width < 40 || r.height < 40; }).length,
      exportOn: UT.onScreen('#btnExport'),
      openOn: UT.onScreen('#btnOpen'),
      undoOn: UT.onScreen('#btnUndo'),
      leftOn: UT.onScreen('.panel.left'),
      rightOn: UT.onScreen('.panel.right'),
      zoomOn: UT.onScreen('#btnZoomFit'),
      canvasW: UT.rect('canvas.upper-canvas').w
    };
  });
  ok('Móvil: sin desplazamiento horizontal de la página', !lay.overflowX);
  ok('Móvil: el lienzo ocupa el ancho de la pantalla', lay.stage.w >= 380 && lay.canvasW >= 380,
     `escenario ${Math.round(lay.stage.w)} px, canvas ${Math.round(lay.canvasW)} px`);
  ok('Móvil: el lienzo tiene alto útil', lay.stage.h >= 500, Math.round(lay.stage.h) + ' px');
  ok('Móvil: la barra de herramientas está a la vista', lay.railOnScreen);
  ok('Móvil: todas las herramientas se alcanzan', lay.railScrolls === 'fits' || lay.railScrolls === 'auto' || lay.railScrolls === 'scroll', lay.railScrolls);
  ok('Móvil: botones de herramienta de 40 px o más', lay.smallTargets === 0, lay.smallTargets + ' chicos');
  ok('Móvil: Exportar está a la vista', lay.exportOn);
  ok('Móvil: Abrir y Deshacer están a la vista', lay.openOn && lay.undoOn);
  ok('Móvil: los paneles no tapan el lienzo al entrar', !lay.leftOn && !lay.rightOn);
  ok('Móvil: el ajuste de zoom está a la vista', lay.zoomOn);

  /* ---- a tool opens its options as a sheet; touching the page closes it ---- */
  await page.tap('[data-tool="shape"]');
  await sleep(500);
  const sheet = await page.evaluate(() => ({
    on: UT.onScreen('.panel.left'),
    insert: UT.onScreen('#shInsertBtn') || !!document.getElementById('shInsertBtn'),
    h: UT.rect('.panel.left').h
  }));
  ok('Móvil: tocar una herramienta abre sus opciones', sheet.on && sheet.insert, Math.round(sheet.h) + ' px de alto');
  await page.screenshot({ path: path.join(__dirname, 'shot_ux_phone_sheet.png') });

  const inserted = await page.evaluate(async () => {
    const E = window.EditorActas;
    const n = E.canvas.getObjects().filter(o => !o.isPage).length;
    const b = document.getElementById('shInsertBtn');
    b.scrollIntoView({ block: 'center' });
    b.click(); await UT.wait(300);
    return E.canvas.getObjects().filter(o => !o.isPage).length - n;
  });
  ok('Móvil: insertar una forma desde la hoja de opciones', inserted === 1, '+' + inserted);

  const st = await page.evaluate(() => UT.rect('#stage'));
  await page.touchscreen.tap(st.x + 30, st.y + 24);
  await sleep(500);
  const closed = await page.evaluate(() => !UT.onScreen('.panel.left'));
  ok('Móvil: tocar la hoja cierra las opciones', closed);

  /* ---- layers are one tap away ---- */
  const hasFab = await page.evaluate(() => UT.onScreen('#uxLayersBtn'));
  ok('Móvil: hay un botón de Capas a la vista', hasFab);
  if (hasFab) {
    await page.tap('#uxLayersBtn');
    await sleep(500);
    const layers = await page.evaluate(() => ({
      on: UT.onScreen('.panel.right'),
      rows: document.getElementById('layersList').children.length
    }));
    ok('Móvil: el botón abre las capas', layers.on && layers.rows >= 1, layers.rows + ' capa(s)');
    await page.screenshot({ path: path.join(__dirname, 'shot_ux_phone_layers.png') });
    await page.tap('#uxLayersBtn');
    await sleep(500);
    ok('Móvil: el mismo botón las cierra', await page.evaluate(() => !UT.onScreen('.panel.right')));
  }

  /* ---- dialogs fit the screen ---- */
  await page.tap('#btnExport');
  await sleep(450);
  const dlg = await page.evaluate(() => {
    const r = UT.rect('#exportModal .modal-box');
    return { fits: r.x >= 0 && r.r <= innerWidth + 1 && r.h <= innerHeight, pdf: UT.onScreen('#expPdfAll') };
  });
  ok('Móvil: el diálogo de exportar entra en la pantalla', dlg.fits && dlg.pdf);
  await page.keyboard.press('Escape');

  ok('Móvil: consola sin errores', errors.length === 0, errors.slice(0, 3).join(' | '));
  await sleep(300);
  await page.screenshot({ path: path.join(__dirname, 'shot_ux_phone.png') });
  await page.close();
}

(async () => {
  if (!CHROME) throw new Error('No encontré Chrome ni Edge. Definí la variable CHROME.');
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const url = 'http://127.0.0.1:' + server.address().port + '/';
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new', args: ['--no-first-run', '--disable-gpu']
  });
  try {
    await desktop(browser, url);
    await phone(browser, url);
  } finally {
    await browser.close();
    server.close();
  }

  const pass = results.filter(r => r.pass).length;
  console.log('\n================ RESULTADO ================');
  for (const r of results) console.log(`${r.pass ? ' OK ' : 'FAIL'}  ${r.name}${r.info ? '   (' + r.info + ')' : ''}`);
  console.log('-------------------------------------------');
  console.log(`${pass}/${results.length} pruebas pasan`);
  process.exit(pass === results.length ? 0 : 1);
})().catch(e => { console.error('TEST CRASH:', e); process.exit(2); });
