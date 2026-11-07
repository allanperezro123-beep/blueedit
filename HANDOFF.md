# HANDOFF — Editor de Actas

Continuation brief for the next agent. Read this fully before touching code.

---

## 1. Goal

Single self-contained HTML file (`editor-actas.html`) — a dark, Figma-style editor that:

- loads PDFs (rasterized via pdf.js) and images, edits them as a canvas document, and
  exports back to PDF (exact original mm/pt) or HD PNG;
- supports pasted images, free drawing, layers, undo/redo, zoom/pan;
- **core feature — "escritura manual":** the user types text and the app renders it using
  *real handwritten glyphs* extracted from three scanned alphabet sheets, picking a
  different variant of each letter every time so the same word never looks identical twice.

Libraries: fabric.js 5.3.0, pdf.js 3.11.174, jsPDF 2.5.1 — all via CDN (already in the file).

**UI copy is in Spanish** (the project and its users are Spanish-speaking). Code identifiers
and comments stay in English.

---

## 2. Current state

| File | State |
|---|---|
| `editor-actas.html` | **~35%.** `<head>`, full CSS, full HTML markup, CDN tags, all element IDs — DONE. The trailing `<script>` contains only the placeholder `/*JS_CORE*/`. **All JavaScript is missing.** |
| `tools/extract.py` | **~85%.** Detects and isolates glyphs from the three sheets. Cropping/metrics/export stage not written yet. |
| `tools/check_LETRAS*.png` | Annotated contact sheets from the last run — visual proof of what the detector found. Regenerate after every change and **look at them**. |
| `LETRAS 1/2/3.jpeg` | Source scans. Do not modify. |

Nothing has been run in a browser yet.

---

## 3. Phase A — finish the glyph extractor (`tools/extract.py`)

Run with: `python tools/extract.py` (PIL 12.3 + numpy 2.4 confirmed installed).

### What the sheets contain

| Sheet | Rows (top → bottom) | Ink |
|---|---|---|
| LETRAS 1 | `ABCDEFGHIJKLM` / `NOPQRSTUVWXYZ` / `abcdefghijklm` / `nopqrstuvwxyz` / `0123456789` / `0123456789` | thin black |
| LETRAS 2 | `ABCDEFGHIJKLM` / `NOPQRSTUVWXYZ` / `abcdefghijklm` / `nopqrstuvwxyz` | thick blue |
| LETRAS 3 | `áéíóú,` / `ÁÉÍÓÚ-_` / `ABCDEFGHIJKLMN` / `OPQRSTUVWXYZ` / `abcdefghijklmn` / `opqrstuvwxyz` | black round |

Result: **3 variants** per letter A–Z/a–z, **2** per digit, **1** per accent/symbol.

### Pipeline (already working — do not redesign)

1. `ink_field()` — per-block 88th-percentile paper estimation, bilinearly upscaled, then
   `paper - min(R,G,B)`. **This is the piece that erases the graph paper, the "TIC donde
   necesitas" / "22 años" watermarks and the scan shading. It works perfectly. Leave it alone.**
   Uses the min channel so blue ink stays dark.
2. `crop` — fractional `(top, right, bottom, left)` trim per sheet, kills page frames and
   the CamScanner footer.
3. `bands()` — horizontal ink projection → text rows. Ascenders/descenders of adjacent rows
   touch, so a fixed threshold fails; it **sweeps** the threshold across 120 levels and keeps
   the widest plateau that yields the sheet's expected row count.
4. `components()` — iterative 8-connected labeling, per band.
5. `merge_marks()` — glues i/j dots, accents and tildes onto their body. Critical guard:
   a mark sits **above** the body, never beside it (`vov > sh*0.30` rejects neighbours).
   Without that test, adjacent letters merge (this was a real bug — B+C, G+H+I+J).
6. `reconcile()` — **just added, NOT yet wired in.** Forces each row to exactly the expected
   glyph count: too many → merge best vertical pair, else drop the smallest speck; too few →
   `vsplit()` the widest blob at its ink valley.

### Detection status at last run (14 of 16 rows exact)

```
LETRAS 1   rows 0,1,3,4 OK   row 2: 14/13   row 5: 11/10      (stray specks)
LETRAS 2   rows 1,2,3  OK    row 0: 10/13   (letters touching -> needs vsplit)
LETRAS 3   rows 2,3,4,5 OK   row 0: 7/6 (stray ink dot)  row 1: 8/7 (Á split in two)
```

### Step A1 — wire in `reconcile()`

In `analyze()`, after `merge_marks()`, call
`reconcile(boxes, len(seq[row_index]), ink, cut)`. This means `analyze()` must receive `seq`
(currently `seq` is popped off in `__main__` — stop doing that, pass it through). Then rerun
and **read the three `check_*.png` files** to confirm every box wraps exactly one character.
Expect this single change to fix all four failing rows.

### Step A2 — per-row metrics

Working units (glyph coordinate space, y grows downward):

```
ascender 6 | capTop 10 | xTop 32 | BASELINE 72 | descBottom 96 | EM 90
```

For each row, from the assigned characters:

- `baselinePx` = median of `y1` over glyphs **excluding** descenders `g j p q y , ; _`
- `xHeightPx` = median of `baselinePx - y0` over `a c e m n o r s u v w x z` (if the row has
  them); otherwise `capHeightPx` over uppercase/digits
- `upp` (units per pixel) = `40 / xHeightPx`, or `62 / capHeightPx` for uppercase/digit rows
  (40 = BASELINE−xTop, 62 = BASELINE−capTop)
- per glyph: `desc = (y1 - baselinePx) * upp` — how far below the baseline it hangs.
  This is what makes `g j p q y` and commas drop correctly. **Measured, not hardcoded.**

### Step A3 — export

For each glyph: crop the `ink` field to its box + 1px padding, write a PNG whose **RGB is
pure black and whose alpha is `ink * 255`**.

> Store glyphs as pure alpha masks. Stroke texture and pressure live in the alpha channel;
> keeping the original RGB produces light halos at antialiased edges and makes recolouring
> dirty. Tinting a black mask is exact.

Emit `glyphs.json`:

```json
{ "units": {"base":72,"xtop":32,"cap":10,"desc":96,"em":90},
  "glyphs": { "a": [ {"d":"<base64 png, no data: prefix>","w":41,"h":38,"upp":0.83,"desc":1.4}, ... ] } }
```

Sanity target: ~180 glyphs, roughly 300–700 KB of base64. If it overshoots, downscale each
glyph so x-height ≈ 48 px before encoding.

### Step A4 — embed

Inline the JSON into `editor-actas.html` as `<script id="glyphbank" type="application/json">…`.
Requirement from the user: **glyphs ship embedded, nothing loaded at runtime.**

Also render a proof sheet (e.g. the word "Hola a todos" composed from the bank) as a PNG and
look at it before wiring the UI.

---

## 4. Phase B — handwriting engine (JS, the heart of the app)

### Variant selection — shuffle bag (this is the actual feature request)

Per character keep a shuffled queue of its variant indices; pop one per occurrence; when the
queue empties, reshuffle **ensuring the first item differs from the last one used**. This
guarantees consecutive occurrences of a letter never repeat a variant, and that typing "Hola"
twice yields two visibly different renderings. A plain `random()` does not — it collides.

### Layout

- split on `\n`, then word-wrap by accumulated advance against the block width
- advance per glyph = `w * upp + bearing` (≈6 units) + user letter-spacing + jitter
- scale `s = fontSize / 90`
- baseline drift: `baselineY += sin(lineIdx*1.3 + charIdx*0.11) * drift` — real handwriting
  does not sit on a perfect line, this sells the effect
- per glyph: rotation ±1.5°–3.5°, y-offset jitter, alpha 0.90–1.00 (pen pressure)
- vertical placement: the glyph's **bottom** goes at `baselineY + desc*s`, using the measured
  `desc`. Never bottom-align everything or descenders float.

Draw each glyph with:

```js
ctx.save();
ctx.translate(penX + adv/2, baselineY + dy);
ctx.rotate(rot);
ctx.transform(1, 0, -slant, 1, 0, 0);   // user slant, applied here so bitmap cache stays small
ctx.globalAlpha = alpha;
ctx.drawImage(bmp, ...);
ctx.restore();
```

### Ink colour

Tint each glyph bitmap in an offscreen canvas: draw image → `globalCompositeOperation =
'source-atop'` → `fillStyle = ink` → `fillRect`. Cache by `` `${char}|${variant}|${color}` ``.
Presets: black, pen-blue `#1a3a8f`, red, custom.

### Output object

Compose the whole block into **one** offscreen canvas at 2× the requested size, then insert as
a single `fabric.Image` with `scaleX = scaleY = 0.5`. One object = movable/rotatable/scalable
as a unit (the user asked for this explicitly). Store `{text, params}` on the object so
double-click can reload it into the composer for re-editing.

### Fallback

Characters absent from the bank (`? ! ( ) : ; / % @ …`): render with
`ctx.fillText` in a cursive system font at matching size and ink colour. Graceful, not blank.

---

## 5. Phase C — editor shell

All DOM IDs already exist in the HTML; wire against them.

- **Canvas model:** fabric canvas fills the viewport; the document lives in
  `canvas.backgroundImage` at page pixel size; navigate via `viewportTransform`.
  `#pageShadow` is a plain div positioned under the canvas from the current transform —
  update it on every zoom/pan/resize.
- **Pages:** `state.pages[] = {bgDataURL, pxW, pxH, ptW, ptH, objects[]}`. Switching a page
  saves current objects and loads the target's. `#pagebar` renders the buttons.
- **PDF load:** `page.getViewport({scale:1})` gives **points** — store as `ptW/ptH`; render at
  scale 2.0–3.0 for `pxW/pxH`. This split is what keeps export 1:1.
- **Export:** reset `viewportTransform` to identity and `setDimensions(pxW, pxH)` before
  `toDataURL({multiplier})`, then restore. Fabric's crop options are unreliable under a
  transform — this is the safe path. `multiplier = (ptW/72*DPI) / pxW`.
  jsPDF: `new jsPDF({unit:'pt', format:[ptW,ptH], orientation: ptW>ptH?'l':'p'})`.
- **History:** snapshot `canvas.getObjects().map(o => o.toObject(EXTRA))` — **exclude the
  background image**, it is immutable and would blow up memory. Cap at ~25 states. Extend
  `fabric.Object.prototype.toObject` to carry `['id','name','locked','hw']`.
- **Shortcuts:** Ctrl+Z/Y, Ctrl+D, Del/Backspace, arrows 1px / Shift+arrows 10px, Ctrl+wheel
  zoom to cursor, Space+drag pan, Ctrl+V paste, Ctrl+0 fit, Esc deselect.
  **Guard every handler against `INPUT`/`TEXTAREA`/contenteditable targets.**

---

## 6. Settled decisions — do not relitigate

- Glyphs are **embedded base64 alpha masks**, extracted offline by `tools/extract.py`. No
  vectorization, no runtime font loading.
- The extractor is **guided by known ground truth** (the character sequence of each row).
  That is why `reconcile()` exists and why it is reliable. Do not switch to unsupervised OCR.
- Keep the in-app "Mi letra" panel (`data-tool="bank"`, markup already present) so users can
  add their own sheets later into IndexedDB and export a JSON pack. The embedded bank is the
  default; the imported one extends/overrides it.
- Single-file output. No build step, no local dependencies.

## 7. Known traps

- `merge_marks` without the vertical-overlap guard eats neighbouring letters. Verified bug.
- Band thresholding without the sweep merges rows 2–4 of sheets 1 and 3. Verified bug.
- Fabric `toDataURL` cropping under a viewport transform gives wrong offsets — use the
  identity-transform approach.
- The user's shell is Git Bash on Windows; paths contain spaces (`OneDrive - INRED`). Quote them.

## 8. Suggested order

1. A1 wire `reconcile` → rerun → **look at the three check PNGs**
2. A2 metrics → A3 export `glyphs.json` → render a proof word and look at it
3. A4 embed into the HTML
4. Phase B engine + the "Escritura manual" panel — test it before anything else
5. Phase C: document load/pages → layers/history/shortcuts → export
