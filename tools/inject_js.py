import os

html_path = r"C:\Users\AllanPerezRobles\OneDrive - INRED\Documentos\EDITOR DE ACTAS\editor-actas.html"

with open(html_path, "r", encoding="utf-8") as f:
    html = f.read()

js_code = """
// =========================================================================
// 1. GLYPH BANK & HANDWRITING ENGINE
// =========================================================================
const GlyphBank = {
  units: { base: 72, xtop: 32, cap: 10, desc: 96, em: 90 },
  glyphs: {},
  bitmaps: {},
  tintCache: new Map(),
  bags: {},
  lastUsed: {},

  init() {
    const scriptTag = document.getElementById('glyphbank');
    if (scriptTag && scriptTag.textContent.trim()) {
      try {
        const data = JSON.parse(scriptTag.textContent);
        this.units = data.units || this.units;
        this.glyphs = data.glyphs || {};
        this.preloadBitmaps();
      } catch (e) {
        console.error("Failed to parse embedded glyphbank:", e);
      }
    }
  },

  preloadBitmaps() {
    for (const char in this.glyphs) {
      const variants = this.glyphs[char];
      variants.forEach((v, idx) => {
        const key = char + "_" + idx;
        const img = new Image();
        img.src = "data:image/png;base64," + v.d;
        this.bitmaps[key] = img;
      });
    }
  },

  getVariant(char) {
    const variants = this.glyphs[char];
    if (!variants || variants.length === 0) return null;
    if (variants.length === 1) return { variant: variants[0], index: 0 };

    if (!this.bags[char] || this.bags[char].length === 0) {
      const indices = Array.from({ length: variants.length }, (_, i) => i);
      for (let i = indices.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [indices[i], indices[j]] = [indices[j], indices[i]];
      }
      if (indices.length > 1 && this.lastUsed[char] !== undefined && indices[0] === this.lastUsed[char]) {
        [indices[0], indices[indices.length - 1]] = [indices[indices.length - 1], indices[0]];
      }
      this.bags[char] = indices;
    }
    const idx = this.bags[char].shift();
    this.lastUsed[char] = idx;
    return { variant: variants[idx], index: idx };
  },

  getTintedCanvas(char, vIdx, color) {
    const key = `${char}|${vIdx}|${color}`;
    if (this.tintCache.has(key)) return this.tintCache.get(key);

    const imgKey = char + "_" + vIdx;
    const img = this.bitmaps[imgKey];
    if (!img || !img.complete || img.naturalWidth === 0) return null;

    const cv = document.createElement('canvas');
    cv.width = img.naturalWidth;
    cv.height = img.naturalHeight;
    const ctx = cv.getContext('2d');

    ctx.drawImage(img, 0, 0);
    ctx.globalCompositeOperation = 'source-atop';
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, cv.width, cv.height);

    this.tintCache.set(key, cv);
    return cv;
  }
};

GlyphBank.init();

function renderHandwrittenCanvas(text, params = {}) {
  const fontSize = params.fontSize || 24;
  const color = params.color || '#000000';
  const lineHeight = params.lineHeight || 1.35;
  const letterSpacing = params.letterSpacing || 0;
  const slant = params.slant || 0;
  const drift = params.drift !== undefined ? params.drift : 1.2;
  const rotationJitter = params.rotationJitter !== undefined ? params.rotationJitter : 0.03;
  const alphaJitter = params.alphaJitter !== undefined ? params.alphaJitter : 0.04;
  const maxWidth = params.maxWidth || 0;

  const em = GlyphBank.units.em || 90;
  const s = fontSize / em;
  const lineGap = fontSize * lineHeight;

  const rawLines = text.split('\\n');
  const lines = [];

  // Simple word wrapping if maxWidth > 0
  rawLines.forEach(rawLine => {
    if (!maxWidth || maxWidth <= 0) {
      lines.push(rawLine);
      return;
    }
    const words = rawLine.split(' ');
    let currentLine = '';
    words.forEach(w => {
      const testLine = currentLine ? currentLine + ' ' + w : w;
      let testWidth = 0;
      for (let c of testLine) {
        const vObj = GlyphBank.glyphs[c] ? GlyphBank.glyphs[c][0] : null;
        testWidth += vObj ? (vObj.w * vObj.upp * s + 4 * s + letterSpacing) : (14 * s);
      }
      if (testWidth > maxWidth && currentLine) {
        lines.push(currentLine);
        currentLine = w;
      } else {
        currentLine = testLine;
      }
    });
    if (currentLine) lines.push(currentLine);
  });

  // Calculate layout dimensions
  let maxLineWidth = 0;
  const lineMetrics = lines.map((lineStr, lineIdx) => {
    let lineWidth = 0;
    const chars = [];
    for (let i = 0; i < lineStr.length; i++) {
      const char = lineStr[i];
      if (char === ' ') {
        const adv = 20 * s + letterSpacing;
        chars.push({ char, space: true, adv });
        lineWidth += adv;
      } else {
        const vGot = GlyphBank.getVariant(char);
        if (vGot) {
          const { variant, index } = vGot;
          const adv = variant.w * variant.upp * s + 4 * s + letterSpacing;
          chars.push({ char, variant, vIdx: index, adv });
          lineWidth += adv;
        } else {
          // Fallback font char
          const adv = 15 * s + letterSpacing;
          chars.push({ char, fallback: true, adv });
          lineWidth += adv;
        }
      }
    }
    if (lineWidth > maxLineWidth) maxLineWidth = lineWidth;
    return { lineStr, lineWidth, chars };
  });

  const dpr = 2;
  const pad = 24 * s;
  const totalW = Math.max(80, Math.ceil(maxLineWidth + pad * 2));
  const totalH = Math.max(60, Math.ceil(lines.length * lineGap + pad * 2));

  const cv = document.createElement('canvas');
  cv.width = Math.ceil(totalW * dpr);
  cv.height = Math.ceil(totalH * dpr);
  const ctx = cv.getContext('2d');
  ctx.scale(dpr, dpr);

  let currentY = pad + fontSize;

  lineMetrics.forEach((lMetric, lineIdx) => {
    let penX = pad;
    if (params.align === 'center') {
      penX = (totalW - lMetric.lineWidth) / 2;
    } else if (params.align === 'right') {
      penX = totalW - pad - lMetric.lineWidth;
    }

    lMetric.chars.forEach((cObj, charIdx) => {
      if (cObj.space) {
        penX += cObj.adv;
        return;
      }

      // Deterministic jitter based on character & line index
      const seed = lineIdx * 133 + charIdx * 37;
      const rot = (Math.sin(seed) * rotationJitter);
      const dy = Math.sin(lineIdx * 1.3 + charIdx * 0.11) * drift + (Math.cos(seed) * 0.5);
      const alpha = Math.min(1.0, Math.max(0.85, 1.0 - Math.abs(Math.sin(seed * 0.7)) * alphaJitter));

      if (cObj.fallback) {
        ctx.save();
        ctx.font = `${fontSize}px "Segoe Print", "Comic Sans MS", cursive`;
        ctx.fillStyle = color;
        ctx.globalAlpha = alpha;
        ctx.fillText(cObj.char, penX, currentY + dy);
        ctx.restore();
        penX += cObj.adv;
        return;
      }

      const v = cObj.variant;
      const tCanvas = GlyphBank.getTintedCanvas(cObj.char, cObj.vIdx, color);

      const upp = v.upp;
      const desc = v.desc;
      const sw = v.w * upp * s;
      const sh = v.h * upp * s;
      const glyY = currentY + dy + desc * s - sh;

      ctx.save();
      ctx.translate(penX + sw / 2, currentY + dy);
      ctx.rotate(rot);
      ctx.transform(1, 0, -slant, 1, 0, 0);
      ctx.globalAlpha = alpha;

      if (tCanvas) {
        ctx.drawImage(tCanvas, -sw / 2, desc * s - sh, sw, sh);
      }
      ctx.restore();

      penX += cObj.adv;
    });

    currentY += lineGap;
  });

  return { canvas: cv, width: totalW, height: totalH };
}


// =========================================================================
// 2. STATE & CANVAS MANAGER
// =========================================================================
const state = {
  pages: [],
  currentPage: 0,
  zoom: 1.0,
  tool: 'select',
  undoStack: [],
  redoStack: [],
  isBusy: false,
  selectedObject: null,
  handParams: {
    text: "Escritura manuscrita de prueba\\nLínea dos 0123 áéíóú",
    fontSize: 24,
    color: "#1a3a8f",
    lineHeight: 1.35,
    letterSpacing: 0,
    slant: 0,
    drift: 1.2,
    align: "left"
  }
};

let canvas = null;

function initApp() {
  const cvEl = document.getElementById('cv');
  const stageEl = document.getElementById('stage');

  canvas = new fabric.Canvas('cv', {
    selection: true,
    preserveObjectStacking: true,
    backgroundColor: null
  });

  resizeStage();
  window.addEventListener('resize', resizeStage);

  createBlankDocument();
  setupEvents();
  setupUI();
  selectTool('hand');
}

function resizeStage() {
  const stageEl = document.getElementById('stage');
  if (!stageEl || !canvas) return;
  const w = stageEl.clientWidth;
  const h = stageEl.clientHeight;
  canvas.setWidth(w);
  canvas.setHeight(h);
  updatePageShadow();
}

function createBlankDocument() {
  // A4 size at 150 DPI: 1240 x 1754 px
  state.pages = [{
    bgDataURL: null,
    pxW: 1240,
    pxH: 1754,
    ptW: 595.28,
    ptH: 841.89,
    objects: []
  }];
  state.currentPage = 0;
  loadPage(0);
  fitZoom();
}

function loadPage(pageIdx) {
  if (!state.pages[pageIdx]) return;
  state.currentPage = pageIdx;

  const page = state.pages[pageIdx];

  // Clear objects
  canvas.clear();

  if (page.bgDataURL) {
    fabric.Image.fromURL(page.bgDataURL, (img) => {
      canvas.setBackgroundImage(img, canvas.renderAll.bind(canvas), {
        scaleX: 1,
        scaleY: 1
      });
      document.getElementById('emptyState').classList.add('hide');
    });
  } else {
    canvas.setBackgroundImage(null, canvas.renderAll.bind(canvas));
    document.getElementById('emptyState').classList.add('hide');
  }

  // Load objects if any
  if (page.objects && page.objects.length > 0) {
    fabric.util.enlivenObjects(page.objects, (objs) => {
      objs.forEach(o => canvas.add(o));
      canvas.renderAll();
      updateLayersList();
    });
  } else {
    updateLayersList();
  }

  updateHUD();
  renderPagebar();
}

function saveCurrentPageObjects() {
  if (!state.pages[state.currentPage]) return;
  const objs = canvas.getObjects().map(o => o.toObject(['id', 'name', 'locked', 'hw']));
  state.pages[state.currentPage].objects = objs;
}

function updatePageShadow() {
  const shadow = document.getElementById('pageShadow');
  if (!shadow || !state.pages[state.currentPage]) return;

  const page = state.pages[state.currentPage];
  const vpt = canvas.viewportTransform;
  const zoom = canvas.getZoom();

  const left = vpt[4] + (canvas.width - page.pxW * zoom) / 2;
  const top = vpt[5] + (canvas.height - page.pxH * zoom) / 2;

  shadow.style.display = 'block';
  shadow.style.left = `${left}px`;
  shadow.style.top = `${top}px`;
  shadow.style.width = `${page.pxW * zoom}px`;
  shadow.style.height = `${page.pxH * zoom}px`;
}


// =========================================================================
// 3. HANDWRITING COMPOSER PANEL & FABRIC CREATION
// =========================================================================
function insertOrUpdateHandwriting() {
  const text = document.getElementById('txtHandText')?.value || state.handParams.text;
  state.handParams.text = text;

  const res = renderHandwrittenCanvas(text, state.handParams);
  const dataURL = res.canvas.toDataURL('image/png');

  fabric.Image.fromURL(dataURL, (img) => {
    img.set({
      scaleX: 0.5,
      scaleY: 0.5,
      left: (canvas.width / 2) - (res.width / 4),
      top: (canvas.height / 2) - (res.height / 4),
      hw: { text, params: { ...state.handParams } },
      name: "Texto manuscrito"
    });

    const activeObj = canvas.getActiveObject();
    if (activeObj && activeObj.hw) {
      // Update existing object
      activeObj.setElement(img.getElement());
      activeObj.width = img.width;
      activeObj.height = img.height;
      activeObj.hw = { text, params: { ...state.handParams } };
      canvas.renderAll();
      showToast("Bloque manuscrito actualizado", "ok");
    } else {
      // Insert new object
      canvas.add(img);
      canvas.setActiveObject(img);
      canvas.renderAll();
      showToast("Bloque manuscrito insertado", "ok");
    }
    pushHistory();
    updateLayersList();
  });
}

function loadObjectIntoComposer(obj) {
  if (!obj || !obj.hw) return;
  const hw = obj.hw;
  state.handParams = { ...hw.params, text: hw.text };

  selectTool('hand');

  const txt = document.getElementById('txtHandText');
  if (txt) txt.value = hw.text;

  const rSize = document.getElementById('rHandSize');
  if (rSize) rSize.value = hw.params.fontSize || 24;

  const vSize = document.getElementById('vHandSize');
  if (vSize) vSize.textContent = (hw.params.fontSize || 24) + "px";

  const cColor = document.getElementById('cHandColor');
  if (cColor) cColor.value = hw.params.color || "#1a3a8f";

  showToast("Cargado en el compositor manuscrito", "info");
}


// =========================================================================
// 4. UI PANELS & TOOL SWITCHING
// =========================================================================
function selectTool(toolName) {
  state.tool = toolName;

  document.querySelectorAll('#rail button').forEach(b => {
    b.classList.toggle('on', b.getAttribute('data-tool') === toolName);
  });

  const pTitle = document.getElementById('panelTitle');
  const pBody = document.getElementById('panelBody');

  if (toolName === 'hand') {
    pTitle.textContent = "Escritura manual";
    pBody.innerHTML = `
      <div class="grp">
        <h4>Texto</h4>
        <label class="f">
          <textarea id="txtHandText" placeholder="Escribí tu texto acá...">${state.handParams.text}</textarea>
        </label>
      </div>
      <div class="grp">
        <h4>Estilo de letra</h4>
        <label class="f">
          <span>Tamaño <i id="vHandSize">${state.handParams.fontSize}px</i></span>
          <input type="range" id="rHandSize" min="12" max="60" value="${state.handParams.fontSize}">
        </label>
        <label class="f">
          <span>Tinta</span>
          <div class="row">
            <input type="color" id="cHandColor" value="${state.handParams.color}">
          </div>
        </label>
        <div class="swatches" style="margin-bottom:10px">
          <div class="sw" style="background:#1a3a8f" title="Azul lapicera" data-color="#1a3a8f"></div>
          <div class="sw" style="background:#0b1220" title="Negro tinta" data-color="#0b1220"></div>
          <div class="sw" style="background:#dc2626" title="Rojo corrección" data-color="#dc2626"></div>
          <div class="sw" style="background:#059669" title="Verde" data-color="#059669"></div>
        </div>
        <label class="f">
          <span>Inclinación <i id="vHandSlant">${state.handParams.slant}</i></span>
          <input type="range" id="rHandSlant" min="-0.2" max="0.2" step="0.02" value="${state.handParams.slant}">
        </label>
        <label class="f">
          <span>Variación de renglón <i id="vHandDrift">${state.handParams.drift}</i></span>
          <input type="range" id="rHandDrift" min="0" max="4" step="0.2" value="${state.handParams.drift}">
        </label>
      </div>
      <button class="btn pri wide" id="btnApplyHand">✍ Insertar en el documento</button>
    `;

    document.getElementById('txtHandText')?.addEventListener('input', (e) => {
      state.handParams.text = e.target.value;
    });
    document.getElementById('rHandSize')?.addEventListener('input', (e) => {
      state.handParams.fontSize = parseInt(e.target.value);
      document.getElementById('vHandSize').textContent = e.target.value + "px";
    });
    document.getElementById('cHandColor')?.addEventListener('input', (e) => {
      state.handParams.color = e.target.value;
    });
    document.getElementById('rHandSlant')?.addEventListener('input', (e) => {
      state.handParams.slant = parseFloat(e.target.value);
      document.getElementById('vHandSlant').textContent = e.target.value;
    });
    document.getElementById('rHandDrift')?.addEventListener('input', (e) => {
      state.handParams.drift = parseFloat(e.target.value);
      document.getElementById('vHandDrift').textContent = e.target.value;
    });
    document.querySelectorAll('.swatches .sw').forEach(sw => {
      sw.addEventListener('click', () => {
        const col = sw.getAttribute('data-color');
        state.handParams.color = col;
        document.getElementById('cHandColor').value = col;
      });
    });
    document.getElementById('btnApplyHand')?.addEventListener('click', insertOrUpdateHandwriting);
  } else if (toolName === 'select') {
    pTitle.textContent = "Herramienta Selección";
    pBody.innerHTML = `
      <div class="hint">Hacé clic en cualquier objeto para moverlo, rotarlo o escalarlo.<br><br><b>Doble clic</b> sobre un bloque manuscrito para editar su texto.</div>
    `;
  } else if (toolName === 'draw') {
    pTitle.textContent = "Dibujo a mano alzada";
    pBody.innerHTML = `
      <div class="grp">
        <h4>Pincel</h4>
        <label class="f"><span>Grosor <i id="vBrushW">3px</i></span>
          <input type="range" id="rBrushW" min="1" max="20" value="3"></label>
        <label class="f"><span>Color</span>
          <input type="color" id="cBrushCol" value="#1a3a8f"></label>
      </div>
    `;
    canvas.isDrawingMode = true;
    canvas.freeDrawingBrush.width = 3;
    canvas.freeDrawingBrush.color = "#1a3a8f";

    document.getElementById('rBrushW')?.addEventListener('input', (e) => {
      canvas.freeDrawingBrush.width = parseInt(e.target.value);
      document.getElementById('vBrushW').textContent = e.target.value + "px";
    });
    document.getElementById('cBrushCol')?.addEventListener('input', (e) => {
      canvas.freeDrawingBrush.color = e.target.value;
    });
  } else {
    canvas.isDrawingMode = false;
    pTitle.textContent = toolName.toUpperCase();
    pBody.innerHTML = `<div class="hint">Panel de ${toolName} preparado.</div>`;
  }

  if (toolName !== 'draw') {
    canvas.isDrawingMode = false;
  }
}

function setupUI() {
  document.querySelectorAll('#rail button').forEach(b => {
    b.addEventListener('click', () => {
      const tool = b.getAttribute('data-tool');
      if (tool) selectTool(tool);
    });
  });

  document.getElementById('btnOpen')?.addEventListener('click', triggerFileOpen);
  document.getElementById('btnOpen2')?.addEventListener('click', triggerFileOpen);
  document.getElementById('btnBlank')?.addEventListener('click', createBlankDocument);
  document.getElementById('btnBlank2')?.addEventListener('click', createBlankDocument);
  document.getElementById('fileInput')?.addEventListener('change', handleFileSelect);

  document.getElementById('btnZoomIn')?.addEventListener('click', () => setZoom(state.zoom * 1.15));
  document.getElementById('btnZoomOut')?.addEventListener('click', () => setZoom(state.zoom / 1.15));
  document.getElementById('btnZoomFit')?.addEventListener('click', fitZoom);

  document.getElementById('btnExportPng')?.addEventListener('click', exportPNG);
  document.getElementById('btnExportPdf')?.addEventListener('click', exportPDF);

  document.getElementById('btnUndo')?.addEventListener('click', undo);
  document.getElementById('btnRedo')?.addEventListener('click', redo);

  document.getElementById('btnHelp')?.addEventListener('click', () => {
    document.getElementById('helpModal')?.classList.add('on');
  });
  document.querySelectorAll('[data-close]').forEach(b => {
    b.addEventListener('click', () => {
      document.getElementById('helpModal')?.classList.remove('on');
    });
  });
}

function setupEvents() {
  canvas.on('object:added', pushHistory);
  canvas.on('object:modified', pushHistory);
  canvas.on('object:removed', pushHistory);

  canvas.on('selection:created', onSelect);
  canvas.on('selection:updated', onSelect);
  canvas.on('selection:cleared', onDeselect);

  canvas.on('mouse:dblclick', (e) => {
    if (e.target && e.target.hw) {
      loadObjectIntoComposer(e.target);
    }
  });

  // Drag & drop file support
  const stageEl = document.getElementById('stage');
  const dropzone = document.getElementById('dropzone');

  stageEl.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.classList.add('on');
  });
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('on'));
  dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('on');
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files);
    }
  });

  // Keyboard shortcuts
  window.addEventListener('keydown', (e) => {
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) return;
    if (e.ctrlKey && e.key === 'z') { e.preventDefault(); undo(); }
    if (e.ctrlKey && e.key === 'y') { e.preventDefault(); redo(); }
    if (e.key === 'Delete' || e.key === 'Backspace') {
      const activeObj = canvas.getActiveObject();
      if (activeObj) {
        canvas.remove(activeObj);
        canvas.renderAll();
        updateLayersList();
      }
    }
  });
}


// =========================================================================
// 5. FILE HANDLING (PDF & IMAGES)
// =========================================================================
function triggerFileOpen() {
  document.getElementById('fileInput')?.click();
}

function handleFileSelect(e) {
  if (e.target.files && e.target.files.length > 0) {
    handleFiles(e.target.files);
  }
}

function handleFiles(files) {
  const file = files[0];
  if (!file) return;

  showBusy("Cargando archivo…");

  if (file.type === 'application/pdf' || file.name.endsWith('.pdf')) {
    const reader = new FileReader();
    reader.onload = function(ev) {
      loadPDFBuffer(ev.target.result);
    };
    reader.readAsArrayBuffer(file);
  } else if (file.type.startsWith('image/')) {
    const reader = new FileReader();
    reader.onload = function(ev) {
      const img = new Image();
      img.onload = function() {
        state.pages = [{
          bgDataURL: ev.target.result,
          pxW: img.width,
          pxH: img.height,
          ptW: img.width * 0.75,
          ptH: img.height * 0.75,
          objects: []
        }];
        loadPage(0);
        fitZoom();
        hideBusy();
        showToast("Imagen cargada como documento", "ok");
      };
      img.src = ev.target.result;
    };
    reader.readAsDataURL(file);
  }
}

function loadPDFBuffer(arrayBuffer) {
  if (typeof pdfjsLib === 'undefined') {
    hideBusy();
    showToast("Error: pdf.js no está cargado", "bad");
    return;
  }

  pdfjsLib.getDocument({ data: arrayBuffer }).promise.then((pdf) => {
    const totalPages = pdf.numPages;
    const pagesList = [];

    const renderNextPage = (pageNum) => {
      if (pageNum > totalPages) {
        state.pages = pagesList;
        loadPage(0);
        fitZoom();
        hideBusy();
        showToast(`PDF cargado (${totalPages} página/s)`, "ok");
        return;
      }

      pdf.getPage(pageNum).then((page) => {
        const viewport = page.getViewport({ scale: 2.0 });
        const cv = document.createElement('canvas');
        cv.width = viewport.width;
        cv.height = viewport.height;
        const ctx = cv.getContext('2d');

        const renderCtx = { canvasContext: ctx, viewport: viewport };
        page.render(renderCtx).promise.then(() => {
          const ptViewport = page.getViewport({ scale: 1.0 });
          pagesList.push({
            bgDataURL: cv.toDataURL('image/png'),
            pxW: viewport.width,
            pxH: viewport.height,
            ptW: ptViewport.width,
            ptH: ptViewport.height,
            objects: []
          });
          renderNextPage(pageNum + 1);
        });
      });
    };

    renderNextPage(1);
  }).catch((err) => {
    hideBusy();
    console.error("PDF load error:", err);
    showToast("Error al abrir PDF", "bad");
  });
}


// =========================================================================
// 6. LAYERS, ZOOM & EXPORT
// =========================================================================
function updateLayersList() {
  const container = document.getElementById('layersList');
  const empty = document.getElementById('layersEmpty');
  const countEl = document.getElementById('layerCount');
  if (!container) return;

  const objs = canvas.getObjects();
  if (countEl) countEl.textContent = objs.length;

  if (objs.length === 0) {
    container.innerHTML = '';
    if (empty) empty.style.display = 'block';
    return;
  }
  if (empty) empty.style.display = 'none';

  let html = '';
  objs.slice().reverse().forEach((obj, idx) => {
    const realIdx = objs.length - 1 - idx;
    const name = obj.name || (obj.hw ? "Texto manuscrito" : "Objeto " + (realIdx + 1));
    const active = canvas.getActiveObject() === obj;

    html += `
      <div class="layer ${active ? 'on' : ''}" data-idx="${realIdx}">
        <div class="th">✍</div>
        <div class="nm">${name}</div>
        <div class="act">
          <button onclick="deleteLayer(${realIdx})">🗑</button>
        </div>
      </div>
    `;
  });
  container.innerHTML = html;

  container.querySelectorAll('.layer').forEach(el => {
    el.addEventListener('click', () => {
      const idx = parseInt(el.getAttribute('data-idx'));
      const obj = canvas.getObjects()[idx];
      if (obj) {
        canvas.setActiveObject(obj);
        canvas.renderAll();
        updateLayersList();
      }
    });
  });
}

function deleteLayer(idx) {
  const obj = canvas.getObjects()[idx];
  if (obj) {
    canvas.remove(obj);
    canvas.renderAll();
    updateLayersList();
  }
}

function onSelect(e) {
  updateLayersList();
  const obj = e.selected ? e.selected[0] : null;
  if (obj) {
    document.getElementById('hudSel').textContent = obj.name || "Objeto seleccionado";
  }
}

function onDeselect() {
  updateLayersList();
  document.getElementById('hudSel').textContent = "Sin selección";
}

function setZoom(z) {
  state.zoom = Math.min(3.0, Math.max(0.2, z));
  const center = { x: canvas.width / 2, y: canvas.height / 2 };
  canvas.zoomToPoint(center, state.zoom);
  document.getElementById('hudZoom').textContent = `${Math.round(state.zoom * 100)}%`;
  updatePageShadow();
}

function fitZoom() {
  const page = state.pages[state.currentPage];
  if (!page) return;
  const stageEl = document.getElementById('stage');
  const scaleW = (stageEl.clientWidth - 60) / page.pxW;
  const scaleH = (stageEl.clientHeight - 60) / page.pxH;
  const fitScale = Math.min(scaleW, scaleH, 1.2);

  canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
  setZoom(fitScale);

  const vpt = canvas.viewportTransform;
  vpt[4] = (canvas.width - page.pxW * fitScale) / 2;
  vpt[5] = (canvas.height - page.pxH * fitScale) / 2;
  canvas.requestRenderAll();
  updatePageShadow();
}

function renderPagebar() {
  const pagebar = document.getElementById('pagebar');
  if (!pagebar) return;
  if (state.pages.length <= 1) {
    pagebar.style.display = 'none';
    return;
  }
  pagebar.style.display = 'flex';
  let html = '';
  state.pages.forEach((p, idx) => {
    html += `<button class="pg ${idx === state.currentPage ? 'on' : ''}" onclick="switchPage(${idx})">${idx + 1}</button>`;
  });
  pagebar.innerHTML = html;
}

function switchPage(idx) {
  saveCurrentPageObjects();
  loadPage(idx);
}

function pushHistory() {
  saveCurrentPageObjects();
}

function undo() {
  showToast("Deshacer", "info");
}

function redo() {
  showToast("Rehacer", "info");
}

function exportPNG() {
  saveCurrentPageObjects();
  const page = state.pages[state.currentPage];
  if (!page) return;

  const prevVpt = canvas.viewportTransform;
  canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
  canvas.setDimensions({ width: page.pxW, height: page.pxH });

  const dataURL = canvas.toDataURL({ format: 'png', multiplier: 1 });

  canvas.setDimensions({ width: document.getElementById('stage').clientWidth, height: document.getElementById('stage').clientHeight });
  canvas.setViewportTransform(prevVpt);

  const a = document.createElement('a');
  a.href = dataURL;
  a.download = `acta_pagina_${state.currentPage + 1}.png`;
  a.click();
  showToast("PNG exportado", "ok");
}

function exportPDF() {
  saveCurrentPageObjects();
  if (typeof jspdf === 'undefined' && typeof window.jspdf === 'undefined') {
    showToast("jsPDF no disponible", "bad");
    return;
  }
  const { jsPDF } = window.jspdf;
  showBusy("Generando PDF…");

  setTimeout(() => {
    let doc = null;

    state.pages.forEach((page, idx) => {
      const orientation = page.ptW > page.ptH ? 'l' : 'p';
      if (idx === 0) {
        doc = new jsPDF({ unit: 'pt', format: [page.ptW, page.ptH], orientation });
      } else {
        doc.addPage([page.ptW, page.ptH], orientation);
      }

      // Temporarily set canvas to 1:1 identity transform
      const prevVpt = canvas.viewportTransform;
      canvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
      canvas.setDimensions({ width: page.pxW, height: page.pxH });

      const imgData = canvas.toDataURL({ format: 'jpeg', quality: 0.92, multiplier: 1 });

      canvas.setDimensions({ width: document.getElementById('stage').clientWidth, height: document.getElementById('stage').clientHeight });
      canvas.setViewportTransform(prevVpt);

      doc.addImage(imgData, 'JPEG', 0, 0, page.ptW, page.ptH);
    });

    doc.save('acta_manuscrita.pdf');
    hideBusy();
    showToast("PDF exportado con éxito", "ok");
  }, 100);
}

function updateHUD() {
  const page = state.pages[state.currentPage];
  if (page) {
    document.getElementById('hudDoc').innerHTML = `Pág <b>${state.currentPage + 1}/${state.pages.length}</b> &middot; ${Math.round(page.ptW)}×${Math.round(page.ptH)} pt`;
  }
}

function showToast(msg, type = 'info') {
  const toasts = document.getElementById('toasts');
  if (!toasts) return;
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = msg;
  toasts.appendChild(t);
  setTimeout(() => t.remove(), 2500);
}

function showBusy(txt = "Procesando…") {
  const busy = document.getElementById('busy');
  const bTxt = document.getElementById('busyTxt');
  if (bTxt) bTxt.textContent = txt;
  if (busy) busy.classList.add('on');
}

function hideBusy() {
  const busy = document.getElementById('busy');
  if (busy) busy.classList.remove('on');
}

window.addEventListener('DOMContentLoaded', initApp);
"""

tag_start = '<script>\n/*JS_CORE*/'
tag_end = '</script>'

if tag_start in html:
    html = html.replace(tag_start, '<script>\n' + js_code + '\n')
    print("Replaced /*JS_CORE*/ with full JavaScript code.")
else:
    print("Could not find /*JS_CORE*/ tag pattern, appending script block.")
    html += '\n<script>\n' + js_code + '\n</script>\n'

with open(html_path, "w", encoding="utf-8") as f:
    f.write(html)

print(f"Updated {html_path}. Size: {os.path.getsize(html_path)/1024:.1f} KB")
