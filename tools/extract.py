"""Extract handwritten glyphs from scanned grid sheets into an alpha-mask glyph bank."""
import base64, io, json, os, sys
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.dirname(os.path.abspath(__file__))

def resolve_src(name):
    for p in [os.path.join(ROOT, "assets", "scans", name), os.path.join(ROOT, name)]:
        if os.path.exists(p):
            return p
    return os.path.join(ROOT, name)



# ---------------------------------------------------------------- background
def estimate_paper(gray, block=28):
    """Per-block high percentile, bilinearly upscaled -> paper brightness field."""
    h, w = gray.shape
    bh, bw = max(1, h // block), max(1, w // block)
    ys = np.linspace(0, h, bh + 1).astype(int)
    xs = np.linspace(0, w, bw + 1).astype(int)
    coarse = np.zeros((bh, bw), np.float32)
    for i in range(bh):
        for j in range(bw):
            tile = gray[ys[i]:ys[i + 1], xs[j]:xs[j + 1]]
            coarse[i, j] = np.percentile(tile, 88) if tile.size else 255
    img = Image.fromarray(coarse.astype(np.uint8)).resize((w, h), Image.BILINEAR)
    return np.asarray(img, np.float32)


def _erode_dir(m, L, axis):
    out = m.copy()
    for _ in range(L - 1):
        sh = np.zeros_like(out)
        if axis == 1: sh[:, :-1] = out[:, 1:]
        else:         sh[:-1, :] = out[1:, :]
        out &= sh
    return out


def _dilate_dir(m, L, axis):
    out = m.copy()
    for _ in range(L - 1):
        sh = np.zeros_like(out)
        if axis == 1: sh[:, 1:] = out[:, :-1]
        else:         sh[1:, :] = out[:-1, :]
        out |= sh
    return out


def strip_rules(ink, cut, L=26):
    """Erase graph-paper rules from the whole sheet before anything else looks at it.

    Directional opening keeps only runs of ink that stay straight for L pixels — that
    is a ruled line, never a handwritten stroke. Pen strokes are protected by a core
    mask (a 1px erosion survives ink, not 2px rules), so thick glyph parts that happen
    to be straight and long, like `_` or the stem of `l`, are never cut.
    """
    m = ink > 0.12
    lines = (_dilate_dir(_erode_dir(m, L, 1), L, 1) |
             _dilate_dir(_erode_dir(m, L, 0), L, 0))
    core = erode(ink > cut, 1)
    for _ in range(2):                       # keep a halo around real strokes
        d = core.copy()
        d[1:, :] |= core[:-1, :]; d[:-1, :] |= core[1:, :]
        d[:, 1:] |= core[:, :-1]; d[:, :-1] |= core[:, 1:]
        core = d
    ink[lines & ~core] = 0.0
    return ink


def ink_field(path, gain=1.0):
    """Return (rgb, ink) where ink is 0..1 ink strength with paper/grid removed."""
    im = Image.open(path).convert("RGB")
    rgb = np.asarray(im, np.float32)
    gray = rgb.min(axis=2)                       # min channel: blue ink stays dark
    paper = estimate_paper(gray)
    diff = np.clip(paper - gray, 0, 255)
    lo, hi = 42.0 / gain, 96.0 / gain            # grid+watermark sit under `lo`
    ink = np.clip((diff - lo) / (hi - lo), 0, 1)
    return im.size, ink


# ------------------------------------------------------------ blob labeling
def components(mask):
    """Iterative 8-connected labeling. mask: bool HxW -> list of boxes."""
    h, w = mask.shape
    flat = mask.ravel()
    lab = np.zeros(h * w, np.int32)
    stack = np.empty(h * w, np.int32)
    boxes = []
    idxs = np.flatnonzero(flat)
    cur = 0
    for seed in idxs:
        if lab[seed]:
            continue
        cur += 1
        sp = 0
        stack[sp] = seed; sp += 1
        lab[seed] = cur
        x0 = x1 = seed % w; y0 = y1 = seed // w; n = 0
        while sp:
            sp -= 1
            p = stack[sp]
            px = p % w; py = p // w; n += 1
            if px < x0: x0 = px
            if px > x1: x1 = px
            if py < y0: y0 = py
            if py > y1: y1 = py
            for dy in (-1, 0, 1):
                ny = py + dy
                if ny < 0 or ny >= h: continue
                base = ny * w
                for dx in (-1, 0, 1):
                    nx = px + dx
                    if nx < 0 or nx >= w: continue
                    q = base + nx
                    if flat[q] and not lab[q]:
                        lab[q] = cur
                        stack[sp] = q; sp += 1
        boxes.append({"x0": int(x0), "y0": int(y0), "x1": int(x1), "y1": int(y1), "n": int(n)})
    return boxes


def merge_marks(boxes):
    """Glue small marks (i/j dots, accents, tildes) onto the body right below them.

    Strict on purpose: only a clearly smaller blob may be absorbed, and only when it
    overlaps the body horizontally and sits close to it. Anything looser starts
    swallowing neighbouring letters or letters from the row above.
    """
    boxes = sorted(boxes, key=lambda b: -(b["x1"] - b["x0"]) * (b["y1"] - b["y0"]))
    used = [False] * len(boxes)
    for i, big in enumerate(boxes):
        if used[i]:
            continue
        bw = big["x1"] - big["x0"] + 1
        bh = big["y1"] - big["y0"] + 1
        for j, sm in enumerate(boxes):
            if j == i or used[j]:
                continue
            sw = sm["x1"] - sm["x0"] + 1
            sh = sm["y1"] - sm["y0"] + 1
            if sw * sh > bw * bh * 0.62 or sh > bh * 0.80:
                continue                            # not a mark, another letter
            # A mark sits ABOVE (or below) the body, never beside it. Without this
            # test, adjacent letters of unequal size merge into one blob.
            vov = min(big["y1"], sm["y1"]) - max(big["y0"], sm["y0"]) + 1
            if vov > sh * 0.30:
                continue
            ov = min(big["x1"], sm["x1"]) - max(big["x0"], sm["x0"]) + 1
            scx = (sm["x0"] + sm["x1"]) / 2
            margin = max(bw * 0.25, 4)
            if (ov < 1 and ov < sw * 0.35) or not (big["x0"] - margin <= scx <= big["x1"] + margin):
                continue
            gap = max(0, max(big["y0"], sm["y0"]) - min(big["y1"], sm["y1"]))
            if gap > bh * 0.75:
                continue
            big["x0"] = min(big["x0"], sm["x0"]); big["y0"] = min(big["y0"], sm["y0"])
            big["x1"] = max(big["x1"], sm["x1"]); big["y1"] = max(big["y1"], sm["y1"])
            big["n"] += sm["n"]
            used[j] = True
            bw = big["x1"] - big["x0"] + 1; bh = big["y1"] - big["y0"] + 1
    return [b for k, b in enumerate(boxes) if not used[k]]


def _cut(prof, thr, minh):
    on = prof > thr
    out, s = [], None
    for y, v in enumerate(on):
        if v and s is None:
            s = y
        elif not v and s is not None:
            if y - s >= minh:
                out.append((s, y))
            s = None
    if s is not None and len(on) - s >= minh:
        out.append((s, len(on)))
    return out


def bbox_of(mask, ox, oy):
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    return {"x0": int(xs.min()) + ox, "y0": int(ys.min()) + oy,
            "x1": int(xs.max()) + ox, "y1": int(ys.max()) + oy, "n": int(len(xs))}


def vsplit(box, ink, cut):
    """Split a blob at the deepest valley of its vertical ink projection."""
    sub = ink[box["y0"]:box["y1"] + 1, box["x0"]:box["x1"] + 1] > cut
    col = sub.sum(axis=0).astype(float)
    w = len(col)
    if w < 14:
        return None
    m = max(4, int(w * 0.22))
    inner = col[m:w - m]
    if not len(inner):
        return None
    j = int(np.argmin(inner)) + m
    if col[j] > col.max() * 0.42:            # no real gap: it is one letter
        return None
    a = bbox_of(sub[:, :j], box["x0"], box["y0"])
    b = bbox_of(sub[:, j:], box["x0"] + j, box["y0"])
    return (a, b) if a and b else None


def reconcile(boxes, want, ink, cut):
    """Force a row to exactly `want` glyphs.

    The sequence for each row is known, so the count is ground truth. Too many
    blobs -> merge the best vertical pair (accent onto its body) or drop specks.
    Too few -> split the widest blob at its ink valley (two letters touching).
    """
    boxes = [dict(b) for b in boxes]

    while len(boxes) > want:
        best, bestcost = None, 1e18
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                ov = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]) + 1
                mw = min(a["x1"] - a["x0"], b["x1"] - b["x0"]) + 1
                if ov < mw * 0.45:
                    continue
                gap = max(0, max(a["y0"], b["y0"]) - min(a["y1"], b["y1"]))
                dc = abs((a["x0"] + a["x1"]) - (b["x0"] + b["x1"])) / 2
                cost = gap * 2 + dc
                if cost < bestcost:
                    best, bestcost = (i, j), cost
        if best is None:
            k = min(range(len(boxes)), key=lambda i: boxes[i]["n"])
            boxes.pop(k)
            continue
        i, j = best
        a, b = boxes[i], boxes[j]
        a["x0"] = min(a["x0"], b["x0"]); a["y0"] = min(a["y0"], b["y0"])
        a["x1"] = max(a["x1"], b["x1"]); a["y1"] = max(a["y1"], b["y1"])
        a["n"] += b["n"]
        boxes.pop(j)

    while len(boxes) < want:
        order = sorted(range(len(boxes)), key=lambda i: -(boxes[i]["x1"] - boxes[i]["x0"]))
        done = False
        for i in order:
            got = vsplit(boxes[i], ink, cut)
            if got:
                boxes.pop(i); boxes.extend(got); done = True
                break
        if not done:
            break

    boxes.sort(key=lambda b: b["x0"])
    return boxes


def bands(ink, x0, x1, minh=18, expect=None):
    """Horizontal ink projection -> text row bands.

    Ascenders and descenders of adjacent rows touch, so a single fixed threshold
    either merges rows or shreds them. Sweep the threshold and keep the level that
    yields the expected row count, preferring the widest stable plateau.
    """
    prof = ink[:, x0:x1].sum(axis=1)
    k = 9
    pad = np.pad(prof, k // 2, mode="edge")
    prof = np.convolve(pad, np.ones(k) / k, mode="valid")[: len(prof)]
    peak = prof.max()
    if expect is None:
        return _cut(prof, peak * 0.055, minh)

    levels = np.linspace(0.02, 0.60, 120)
    runs, cur = [], None
    for f in levels:
        ok = len(_cut(prof, peak * f, minh)) == expect
        if ok and cur is None:
            cur = [f, f]
        elif ok:
            cur[1] = f
        elif cur is not None:
            runs.append(cur); cur = None
    if cur is not None:
        runs.append(cur)
    if not runs:
        raise SystemExit(f"band sweep failed: expected {expect} rows, none of the "
                         f"thresholds produced it")
    best = max(runs, key=lambda r: r[1] - r[0])
    return _cut(prof, peak * (best[0] + best[1]) / 2, minh)


# ------------------------------------------------------------------ driver
def clean_boxes(boxes, W, H, minpx, maxfrac=0.35):
    out = []
    for x in boxes:
        bw, bh = x["x1"] - x["x0"] + 1, x["y1"] - x["y0"] + 1
        if x["n"] < minpx: continue
        if bw > W * maxfrac or bh > H * maxfrac: continue      # frames
        if bh < 5 or bw < 3: continue
        if bw > bh * 4.5 and bh < 14: continue                 # horizontal grid rules
        if bh > bw * 3.8 and bw < 8: continue                  # vertical grid rules
        if x["n"] < bw * bh * 0.055: continue                  # hollow / speckle
        out.append(x)
    return out



def analyze(path, gain=1.0, minpx=60, crop=(0, 0, 0, 0), expect=None, minband=18, cut=0.34, seq=None, has_accents=False):
    (W, H), ink = ink_field(path, gain)
    t, r, b, l = crop
    ink[:int(H * t), :] = 0
    ink[H - int(H * b):, :] = 0
    ink[:, :int(W * l)] = 0
    ink[:, W - int(W * r):] = 0

    ink = strip_rules(ink, cut)

    x0, x1 = int(W * l), W - int(W * r)
    rows = []
    for ri, (by0, by1) in enumerate(bands(ink, x0, x1, minband, expect)):
        # 1. Main letter bodies in row band
        strip = np.zeros_like(ink)
        strip[by0:by1, :] = ink[by0:by1, :]
        body_boxes = clean_boxes(components(strip > cut), W, H, minpx)

        # 2. Floating accents above row band (only if row has accents or has_accents flag is set)
        row_has_acc = has_accents or (seq and ri < len(seq) and any(c in "áéíóúÁÉÍÓÚ" for c in seq[ri]))
        if row_has_acc:
            mark_y0 = max(0, by0 - 32)
            mark_strip = np.zeros_like(ink)
            mark_strip[mark_y0:by0, :] = ink[mark_y0:by0, :]
            mark_boxes = components(mark_strip > cut)
            all_boxes = body_boxes + mark_boxes
        else:
            all_boxes = body_boxes

        boxes = merge_marks(all_boxes)
        boxes = [b for b in boxes if b["n"] >= minpx]
        if seq and ri < len(seq):
            boxes = reconcile(boxes, len(seq[ri]), ink, cut)
        boxes.sort(key=lambda b: b["x0"])
        if boxes:
            rows.append({"y0": by0, "y1": by1, "items": boxes})
    flat = [b for r in rows for b in r["items"]]
    return ink, flat, rows, (W, H)






def contact_sheet(ink, rows, path):
    """Annotated overview so the extraction can be eyeballed."""
    h, w = ink.shape
    base = (255 - (ink * 255)).astype(np.uint8)
    img = Image.fromarray(base).convert("RGB")
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    for ri, row in enumerate(rows):
        col = [(220, 20, 60), (0, 120, 220), (0, 160, 60), (200, 120, 0), (140, 0, 200), (0, 150, 150)][ri % 6]
        for ci, b in enumerate(row["items"]):
            d.rectangle([b["x0"] - 2, b["y0"] - 2, b["x1"] + 2, b["y1"] + 2], outline=col, width=2)
            d.text((b["x0"], max(0, b["y0"] - 13)), f"{ri}.{ci}", fill=col)
    img.save(path)


# sheet -> (extraction params, expected character sequence per row)
# crop is (top, right, bottom, left) as a fraction, trimming page frames and the
# CamScanner footer so they never register as blobs.
SHEETS = [
    ("LETRAS 1.jpeg", dict(
        gain=1.00, minpx=50, cut=0.42, crop=(0.015, 0.020, 0.075, 0.060), expect=6,
        seq=["ABCDEFGHIJKLM", "NOPQRSTUVWXYZ",
             "abcdefghijklm", "nopqrstuvwxyz",
             "0123456789", "0123456789"])),
    ("LETRAS 2.jpeg", dict(
        gain=1.15, minpx=90, crop=(0.075, 0.030, 0.095, 0.045), expect=4,
        seq=["ABCDEFGHIJKLM", "NOPQRSTUVWXYZ",
             "abcdefghijklm", "nopqrstuvwxyz"])),
    ("LETRAS 3.jpeg", dict(
        gain=1.00, minpx=70, crop=(0.015, 0.030, 0.075, 0.065), expect=6,
        seq=["áéíóú,", "ÁÉÍÓÚ-_",
             "ABCDEFGHIJKLMN", "OPQRSTUVWXYZ",
             "abcdefghijklmn", "opqrstuvwxyz"])),
]


DESCENDERS = set("gjpqy,;_")
XHEIGHT_CHARS = set("acemnorsuvwxz")


def erode(m, k=1):
    """4-neighbour binary erosion; k iterations remove structures thinner than 2k+1."""
    for _ in range(k):
        e = m.copy()
        e[1:, :] &= m[:-1, :]
        e[:-1, :] &= m[1:, :]
        e[:, 1:] &= m[:, :-1]
        e[:, :-1] &= m[:, 1:]
        m = e
    return m


def _grow(seed, weak, k):
    """Dilate seed inside weak, at most k steps.

    An unbounded flood fill would rebuild the whole grid cell, because the rules pass
    behind the letters and are therefore connected to them. Bounding the growth to k
    steps restores the stroke (seed was eroded by k-2) while a rule can only bleed a
    few pixels out from where it touches.
    """
    m = seed & weak
    for _ in range(k):
        d = m.copy()
        d[1:, :] |= m[:-1, :]
        d[:-1, :] |= m[1:, :]
        d[:, 1:] |= m[:, :-1]
        d[:, :-1] |= m[:, 1:]
        m = d & weak
    return m


def clean_crop_mask(crop_ink, cut=0.45, low=None, min_area=7):
    """Hysteresis threshold: keep faint ink only where it touches a solid core.

    Filling each component's bounding box (the previous approach) copied every grid
    line crossing that box, which is why glyphs came out framed in little squares.
    Graph paper and watermarks never reach `cut`, so seeding from the strong mask and
    growing through the weak one removes them completely, while antialiased stroke
    edges survive because they are connected to the stroke core.
    """
    if low is None:
        low = max(0.20, cut * 0.45)
    hi = crop_ink > cut
    weak = crop_ink > low
    if not hi.any():
        return np.zeros_like(crop_ink)

    # Grid rules survive plain thresholding — they are as dark as thin pen strokes.
    # What separates them is THICKNESS: rules are 1-3px, pen strokes 5-12px. Eroding
    # the seed deletes the rules outright, then the real strokes are rebuilt from
    # their surviving cores. Back off if a thin-penned glyph would be lost.
    full = float(hi.sum())
    keep = None
    for k in (3, 2, 1, 0):
        seed = erode(hi, k)
        if not seed.any():
            continue
        got = _grow(seed, weak, k + 2)
        if got.sum() >= full * 0.80 or k == 0:
            keep = got
            break
    if keep is None:
        keep = weak

    cleaned = np.where(keep, crop_ink, 0.0)
    # Stretch so strokes go fully opaque instead of staying washed out.
    return np.clip((cleaned - 0.10) / 0.62, 0, 1)


def export_bank():
    all_glyphs = {}
    total_count = 0

    for name, kw in SHEETS:
        seq = kw["seq"]
        ink, flat, rows, size = analyze(resolve_src(name), **kw)
        H, W = ink.shape

        for ri, r in enumerate(rows):
            if ri >= len(seq):
                continue
            row_seq = seq[ri]
            boxes = r["items"]
            if len(boxes) != len(row_seq):
                print(f"Skipping row {ri} of {name}: count mismatch {len(boxes)} vs {len(row_seq)}")
                continue

            # Phase 1 -- clean every blob and re-measure its box. Boxes inflated by
            # grid lines would otherwise skew the baseline and x-height of the row.
            cleaned = []
            for char, b in zip(row_seq, boxes):
                y0_c, y1_c = max(0, b["y0"] - 3), min(H, b["y1"] + 4)
                x0_c, x1_c = max(0, b["x0"] - 3), min(W, b["x1"] + 4)
                a = clean_crop_mask(ink[y0_c:y1_c, x0_c:x1_c], cut=kw.get("cut", 0.34))
                ys, xs = np.nonzero(a > 0.02)
                if not len(xs):
                    print(f"  ! {name} row {ri}: '{char}' vanished after cleaning")
                    continue
                cleaned.append({
                    "c": char,
                    "a": a[ys.min():ys.max() + 1, xs.min():xs.max() + 1],
                    "y0": y0_c + int(ys.min()), "y1": y0_c + int(ys.max()),
                })
            if not cleaned:
                continue

            # Phase 2 -- row metrics from the cleaned boxes
            nd = [g["y1"] for g in cleaned if g["c"] not in DESCENDERS]
            baseline_px = float(np.median(nd or [g["y1"] for g in cleaned]))
            xb = [g for g in cleaned if g["c"] in XHEIGHT_CHARS]
            cb = [g for g in cleaned if g["c"].isupper() or g["c"].isdigit() or g["c"] in "ÁÉÍÓÚ"]
            if len(xb) >= 2:
                upp = 40.0 / max(1.0, float(np.median([baseline_px - g["y0"] for g in xb])))
            elif cb:
                upp = 62.0 / max(1.0, float(np.median([baseline_px - g["y0"] for g in cb])))
            else:
                upp = 50.0 / max(1.0, float(np.median([baseline_px - g["y0"] for g in cleaned])))

            # Phase 3 -- emit alpha-mask PNGs
            for g in cleaned:
                h_c, w_c = g["a"].shape
                rgba = np.zeros((h_c, w_c, 4), np.uint8)
                rgba[:, :, 3] = np.clip(g["a"] * 255, 0, 255).astype(np.uint8)
                buf = io.BytesIO()
                Image.fromarray(rgba, "RGBA").save(buf, format="PNG", optimize=True)
                all_glyphs.setdefault(g["c"], []).append({
                    "d": base64.b64encode(buf.getvalue()).decode("ascii"),
                    "w": w_c, "h": h_c,
                    "upp": round(float(upp), 4),
                    "desc": round(float((g["y1"] - baseline_px) * upp), 2),
                })
                total_count += 1

    bank = {
        "units": {"base": 72, "xtop": 32, "cap": 10, "desc": 96, "em": 90},
        "glyphs": all_glyphs
    }

    out_json_path = os.path.join(ROOT, "glyphs.json")
    with open(out_json_path, "w", encoding="utf-8") as f:
        json.dump(bank, f, ensure_ascii=False)

    size_kb = os.path.getsize(out_json_path) / 1024.0
    print(f"\nExported {total_count} glyphs for {len(all_glyphs)} characters to glyphs.json ({size_kb:.1f} KB)")
    return bank


if __name__ == "__main__":
    for name, kw in SHEETS:
        ink, boxes, rows, size = analyze(resolve_src(name), **kw)
        seq = kw.get("seq", [])
        print(f"\n=== {name}  {size}  blobs={len(boxes)}  rows={len(rows)}")
        for i, r in enumerate(rows):
            want = len(seq[i]) if i < len(seq) else 0
            got = len(r["items"])
            flag = "OK " if got == want else ">> "
            print(f"  {flag}row {i}: got {got:3d} / want {want:3d}   y {r['y0']}..{r['y1']}   {seq[i] if i < len(seq) else ''}")
        contact_sheet(ink, rows, os.path.join(OUT, f"check_{name.split('.')[0].replace(' ', '')}.png"))

    export_bank()

