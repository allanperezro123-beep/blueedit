/* Real-browser smoke test: drives editor-actas.html in Edge and asserts the
   behaviours that were reported broken. Run: node tools/test.js            */
const puppeteer = require('puppeteer-core');
const path = require('path');
const fs = require('fs');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const FILE = 'file:///' + path.resolve(__dirname, '..', 'editor-actas.html').replace(/\\/g, '/');

const results = [];
const ok = (n, c, info) => results.push({ n, pass: !!c, info: info || '' });

(async () => {
  // Edge refuses to be spawned by puppeteer on this machine (corporate policy),
  // but it exposes CDP fine when started separately. tools/run-tests.sh does that.
  const browser = await puppeteer.connect({
    browserURL: 'http://127.0.0.1:9222',
    defaultViewport: null
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000 });

  const errors = [], warns = [];
  const isNoise = t => /runtime\.lastError|Receiving end does not exist|favicon/i.test(t);
  page.on('console', m => {
    if (m.type() === 'error' && !isNoise(m.text())) errors.push(m.text());
    if (m.type() === 'warning') warns.push(m.text());
  });
  page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message));
  page.on('requestfailed', r => {
    const u = r.url();
    if (!u.startsWith('data:') && !/favicon/.test(u))
      errors.push('REQFAIL: ' + u + ' ' + r.failure().errorText);
  });

  await page.goto(FILE, { waitUntil: 'networkidle2', timeout: 60000 });
  await new Promise(r => setTimeout(r, 1500));

  /* ---- boot ---- */
  const boot = await page.evaluate(() => !!(window.EditorActas && window.EditorActas.canvas));
  ok('App arranca y expone el editor', boot);

  const bank = await page.evaluate(() => {
    const B = window.EditorActas.Bank;
    let v = 0;
    for (const c in B.glyphs) v += B.glyphs[c].length;
    return { chars: Object.keys(B.glyphs).length, variants: v, sources: B.sources.length };
  });
  ok('Banco vectorial cargado', bank.chars > 60 && bank.variants > 100,
     `${bank.chars} chars / ${bank.variants} variantes / ${bank.sources} caligrafias`);

  const libs = await page.evaluate(() => {
    const srcs = [...document.querySelectorAll('script[src]')].map(s => s.getAttribute('src'));
    return {
      srcs,
      local: srcs.filter(s => s.indexOf('vendor/') === 0).length,
      cdn: srcs.filter(s => s.indexOf('http') === 0).length,
      fabric: typeof fabric !== 'undefined',
      pdf: typeof pdfjsLib !== 'undefined',
      jspdf: !!(window.jspdf && window.jspdf.jsPDF)
    };
  });
  ok('Librerias cargan desde ./vendor (sin CDN)',
     libs.local === 3 && libs.cdn === 0, `${libs.local} locales / ${libs.cdn} CDN`);
  ok('fabric, pdf.js y jsPDF disponibles', libs.fabric && libs.pdf && libs.jspdf);

  /* ---- handwriting: vector, spacing, baseline ---- */
  const hw = await page.evaluate(() => {
    const E = window.EditorActas;
    E.Hand.text = 'Hola a todos';
    E.Hand.size = 40;
    const g = E.buildHandwriting();
    const kinds = new Set(g._objects.map(o => o.type));
    // gap between consecutive glyph bounding boxes, in px
    const objs = g._objects.slice().sort((a, b) => a.left - b.left);
    const gaps = [];
    for (let i = 1; i < objs.length; i++) {
      const prev = objs[i - 1], cur = objs[i];
      gaps.push((cur.left - cur.getScaledWidth() / 2) -
                (prev.left + prev.getScaledWidth() / 2));
    }
    gaps.sort((a, b) => a - b);
    return {
      count: g._objects.length,
      types: [...kinds],
      w: Math.round(g.width), h: Math.round(g.height),
      medianGap: Math.round(gaps[Math.floor(gaps.length / 2)] * 10) / 10,
      maxGap: Math.round(gaps[gaps.length - 1] * 10) / 10
    };
  });
  ok('Texto se compone como vectores (fabric.Path)',
     hw.types.length === 1 && hw.types[0] === 'path', hw.types.join(','));
  ok('Glifos generados', hw.count === 10, `${hw.count} paths para "Hola a todos" (10 letras)`);
  ok('Espaciado entre letras razonable (< 25% del tamano)',
     hw.medianGap < 10, `gap mediano ${hw.medianGap}px con tamano 40px`);

  /* variant rotation: same word twice must differ */
  const variety = await page.evaluate(() => {
    const E = window.EditorActas;
    E.Hand.source = 'mix';
    E.Bank.bags = {}; E.Bank.last = {};
    const sig = () => {
      const g = E.buildHandwriting();
      return g._objects.map(o => Math.round(o.width * 100)).join('-');
    };
    E.Hand.text = 'Hola';
    const a = sig(), b = sig(), c = sig();
    return { a, b, c, allSame: a === b && b === c };
  });
  ok('La misma palabra no sale identica dos veces', !variety.allSame);

  /* ---- insert into canvas ---- */
  const inserted = await page.evaluate(() => {
    const E = window.EditorActas;
    E.Hand.text = 'Acta 123';
    E.insertHandwriting();
    const objs = E.canvas.getObjects().filter(o => !o.isPage);
    return { n: objs.length, type: objs[0] && objs[0].type };
  });
  ok('Insertar texto crea un grupo unico', inserted.n === 1 && inserted.type === 'group');

  /* ---- zoom anchored on cursor ---- */
  const zoom = await page.evaluate(() => {
    const E = window.EditorActas, c = E.canvas;
    E.zoomToFit();
    const before = c.getZoom();
    const pt = new fabric.Point(400, 300);
    const world0 = fabric.util.transformPoint(pt, fabric.util.invertTransform(c.viewportTransform));
    c.zoomToPoint(pt, before * 2.5);
    const world1 = fabric.util.transformPoint(pt, fabric.util.invertTransform(c.viewportTransform));
    return {
      before, after: c.getZoom(),
      drift: Math.hypot(world1.x - world0.x, world1.y - world0.y)
    };
  });
  ok('Zoom mantiene el punto bajo el cursor', zoom.drift < 0.6,
     `deriva ${zoom.drift.toFixed(3)} px de documento`);

  /* ---- zoom must not alter object geometry ---- */
  const geom = await page.evaluate(() => {
    const E = window.EditorActas, c = E.canvas;
    const o = c.getObjects().filter(x => !x.isPage)[0];
    const snap = () => ({ l: o.left, t: o.top, w: o.getScaledWidth(), h: o.getScaledHeight() });
    const a = snap();
    E.setZoom(0.3); E.setZoom(3); E.zoomToFit();
    const b = snap();
    return {
      moved: Math.abs(a.l - b.l) + Math.abs(a.t - b.t),
      resized: Math.abs(a.w - b.w) + Math.abs(a.h - b.h),
      ratioA: a.w / a.h, ratioB: b.w / b.h
    };
  });
  ok('Zoom no mueve objetos', geom.moved < 1e-6);
  ok('Zoom no deforma objetos', geom.resized < 1e-6 &&
     Math.abs(geom.ratioA - geom.ratioB) < 1e-9);

  /* ---- brush: draw with the real pointer ---- */
  await page.evaluate(() => window.EditorActas && document.querySelector('[data-tool="draw"]').click());
  await new Promise(r => setTimeout(r, 200));
  const box = await page.evaluate(() => {
    const r = document.querySelector('canvas.upper-canvas').getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height };
  });
  await page.mouse.move(box.x + 300, box.y + 300);
  await page.mouse.down();
  for (let i = 0; i <= 12; i++)
    await page.mouse.move(box.x + 300 + i * 12, box.y + 300 + Math.sin(i / 2) * 24);
  await page.mouse.up();
  await new Promise(r => setTimeout(r, 250));

  const brush = await page.evaluate(() => {
    const c = window.EditorActas.canvas;
    const paths = c.getObjects().filter(o => o.type === 'path' && !o.isPage);
    const p = paths[paths.length - 1];
    if (!p) return { n: 0 };
    const inv = fabric.util.invertTransform(c.viewportTransform);
    return { n: paths.length, left: p.left, top: p.top, w: p.width, h: p.height };
  });
  ok('El pincel dibuja de verdad', brush.n >= 1, `${brush.n} trazo(s)`);
  ok('El trazo tiene extension real', brush.n >= 1 && brush.w > 30 && brush.h > 5,
     brush.n ? `${Math.round(brush.w)}x${Math.round(brush.h)} px` : 'sin trazo');

  /* stroke must land under the cursor: compare with the world position of the drag */
  const align = await page.evaluate((b) => {
    const c = window.EditorActas.canvas;
    const paths = c.getObjects().filter(o => o.type === 'path');
    const p = paths[paths.length - 1];
    if (!p) return 999;
    const inv = fabric.util.invertTransform(c.viewportTransform);
    const start = fabric.util.transformPoint(new fabric.Point(300, 300), inv);
    return Math.abs(p.left - start.x);
  }, box);
  ok('El trazo cae bajo el cursor', align < 12, `desfase ${Math.round(align)} px`);

  /* ---- undo / redo ---- */
  const hist = await page.evaluate(async () => {
    const E = window.EditorActas, c = E.canvas;
    const count = () => c.getObjects().filter(o => !o.isPage).length;
    const before = count();
    E.History.undo();
    await new Promise(r => setTimeout(r, 120));
    const afterUndo = count();
    E.History.redo();
    await new Promise(r => setTimeout(r, 120));
    const afterRedo = count();
    return { before, afterUndo, afterRedo, depth: E.History.stack.length };
  });
  ok('Ctrl+Z deshace', hist.afterUndo === hist.before - 1,
     `${hist.before} -> ${hist.afterUndo}`);
  ok('Ctrl+Y rehace', hist.afterRedo === hist.before,
     `${hist.afterUndo} -> ${hist.afterRedo}`);

  /* zoom/pan must not create history entries */
  const histZoom = await page.evaluate(() => {
    const E = window.EditorActas;
    const d0 = E.History.stack.length;
    E.setZoom(0.5); E.setZoom(2); E.zoomToFit();
    return { d0, d1: E.History.stack.length };
  });
  ok('El zoom no entra en el historial', histZoom.d0 === histZoom.d1);

  /* ---- drag = one history entry ---- */
  await page.evaluate(() => document.querySelector('[data-tool="select"]').click());
  const dragHist = await page.evaluate(async () => {
    const E = window.EditorActas, c = E.canvas;
    const o = c.getObjects().filter(x => !x.isPage)[0];
    c.setActiveObject(o);
    const d0 = E.History.stack.length;
    for (let i = 0; i < 25; i++) { o.set({ left: o.left + 1 }); c.fire('object:moving', { target: o }); }
    c.fire('object:modified', { target: o });
    await new Promise(r => setTimeout(r, 60));
    return { d0, d1: E.History.stack.length };
  });
  ok('Un arrastre = una sola operacion', dragHist.d1 - dragHist.d0 === 1,
     `+${dragHist.d1 - dragHist.d0} estados`);

  /* ---- export ---- */
  const exp = await page.evaluate(() => {
    const E = window.EditorActas;
    const p = E.Doc.page();
    const c = E.canvas;
    const vpt = c.viewportTransform.slice();
    const url = (function () {
      const w = c.getWidth(), h = c.getHeight();
      c.setViewportTransform([1, 0, 0, 1, 0, 0]);
      c.setDimensions({ width: p.pxW, height: p.pxH });
      const u = c.toDataURL({ format: 'png', multiplier: 0.25, enableRetinaScaling: false });
      c.setDimensions({ width: w, height: h });
      c.setViewportTransform(vpt);
      return u;
    })();
    return { len: url.length, head: url.slice(0, 22), ratio: p.pxW / p.pxH, ptRatio: p.ptW / p.ptH };
  });
  ok('Exporta imagen del documento', exp.head.startsWith('data:image/png') && exp.len > 5000,
     Math.round(exp.len / 1024) + ' KB');
  ok('Proporcion px coincide con la fisica', Math.abs(exp.ratio - exp.ptRatio) < 0.01);

  /* ---- tool isolation ---- */
  const tools = await page.evaluate(() => {
    const E = window.EditorActas, c = E.canvas;
    const out = {};
    document.querySelector('[data-tool="pan"]').click();
    out.panNoSelect = c.selection === false && c.isDrawingMode === false;
    document.querySelector('[data-tool="draw"]').click();
    out.drawMode = c.isDrawingMode === true && c.selection === false;
    document.querySelector('[data-tool="select"]').click();
    out.selectMode = c.selection === true && c.isDrawingMode === false;
    return out;
  });
  ok('Herramienta mano no selecciona ni dibuja', tools.panNoSelect);
  ok('Pincel no selecciona', tools.drawMode);
  ok('Seleccion vuelve a estado normal', tools.selectMode);

  /* ---- panels render without throwing ---- */
  const panels = await page.evaluate(() => {
    const names = ['hand', 'draw', 'media', 'doc', 'bank', 'select'];
    const bad = [];
    for (const n of names) {
      try {
        document.querySelector('[data-tool="' + n + '"]').click();
        if (!document.getElementById('panelBody').innerHTML.trim()) bad.push(n + ':vacio');
      } catch (e) { bad.push(n + ':' + e.message); }
    }
    return bad;
  });
  ok('Todos los paneles abren sin error', panels.length === 0, panels.join(', '));

  /* ---- import a real PDF ---- */
  const pdfPath = path.resolve(__dirname, '..', 'LETRAS.pdf');
  if (fs.existsSync(pdfPath)) {
    const input = await page.$('#fileInput');
    await input.uploadFile(pdfPath);
    await new Promise(r => setTimeout(r, 3500));
    const pdfRes = await page.evaluate(() => {
      const E = window.EditorActas, p = E.Doc.page();
      return { pages: E.Doc.pages.length, ptW: p && Math.round(p.ptW),
               ptH: p && Math.round(p.ptH), hasBg: !!(p && p.bg) };
    });
    ok('Importa PDF real', pdfRes.pages >= 1 && pdfRes.hasBg,
       `${pdfRes.pages} pagina(s), ${pdfRes.ptW}x${pdfRes.ptH} pt`);
    ok('PDF conserva medidas en puntos', pdfRes.ptW > 100 && pdfRes.ptH > 100);
  }

  await page.screenshot({ path: path.join(__dirname, 'shot_editor.png') });

  await page.evaluate(() => {
    document.querySelector('[data-tool="hand"]').click();
    window.EditorActas.Hand.text = 'Hola a todos\nActa No 123 - reunion ordinaria';
    window.EditorActas.Hand.size = 46;
    window.EditorActas.insertHandwriting();
    window.EditorActas.zoomToFit();
  });
  await new Promise(r => setTimeout(r, 400));
  await page.screenshot({ path: path.join(__dirname, 'shot_text.png') });

  ok('Consola sin errores', errors.length === 0, errors.slice(0, 4).join(' | '));

  await page.close();
  browser.disconnect();

  /* ---- report ---- */
  const pass = results.filter(r => r.pass).length;
  console.log('\n================ RESULTADO ================');
  for (const r of results)
    console.log(`${r.pass ? ' OK ' : 'FAIL'}  ${r.n}${r.info ? '   (' + r.info + ')' : ''}`);
  console.log('-------------------------------------------');
  console.log(`${pass}/${results.length} pruebas pasan`);
  if (warns.length) console.log(`avisos de consola: ${warns.length}`);
  process.exit(pass === results.length ? 0 : 1);
})().catch(e => { console.error('TEST CRASH:', e); process.exit(2); });
