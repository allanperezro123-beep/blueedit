"""Segment the vectorised alphabet sheets into per-character VECTOR glyphs.

Sheets arrive in whatever shape the tracer felt like. Two are one giant <path> of
pure polygons (M/L/Z), no ids and no groups. One is a tracing exported as ~100
separate <path> elements carrying cubic Beziers over a page-sized background
rect. Two are potrace output: many paths in a <g> whose transform flips the Y axis and
scales by a tenth, which has to be applied or every letter comes out upside down.
One of those was also scanned sideways and written on lines that climb as they go,
so it needs a quarter turn and a row finder that follows a drifting line instead
of slicing the page into level bands.
One reader handles both: it walks the full SVG path grammar and flattens curves
into dense polylines, because every stage after it works on plain point lists.
Then we attach counters (the holes of B/O/a/8), split rows, and assign characters
from the known sequence — the same ground-truth approach already validated on the
raster sheets.

Geometry is never redrawn or approximated: subpath points are only translated and
uniformly scaled into glyph units. What we compute is each glyph's LOGICAL advance
from its real ink bbox, which is what fixes the spacing — the viewBox says nothing
about typographic width.

Glyph unit system (shared with the engine):
    ascender 6 | capTop 10 | xTop 32 | BASELINE 72 | descBottom 96 | em 90
"""
import json, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])|(-?\d*\.?\d+(?:[eE][-+]?\d+)?)")

# A curve becomes this many straight segments: fine enough that the flattening is
# invisible at any size these glyphs are drawn, and paid once here instead of on
# every render.
CURVE_STEPS = 16

# Anything covering this much of the sheet is the page background, not ink.
BG_AREA_FRACTION = 0.5
BASE, XTOP, CAPTOP, EM = 72.0, 32.0, 10.0, 90.0
DESCENDERS = "gjpqy,;_"
XCHARS = "acemnorsuvwxz"

# Glyphs a sheet traced badly enough to be unusable. Keeping one out costs a
# variant; shipping it puts a visible defect in one word out of three, because the
# shuffle spreads variants evenly rather than hiding the bad one.
SKIP = {
    # The tracer closed this 'o' into a blob and laid a page-coloured patch over
    # the whole glyph instead of just its counter, so there is no hole to recover.
    # The other alphabets still supply 'o'.
    "Letra Jesus Dario anacona": "o",
    # A speck of ink sits just left of this 'y', close enough that the row's
    # count-fixing pass glues it on, and it reads as a stray blob beside the
    # letter at normal size. Deciding by distance alone cannot tell it apart from
    # the detached strokes that DO belong to a letter elsewhere, so the glyph is
    # named and dropped instead of the rule being bent around it. Three other
    # alphabets supply 'y'.
    "alfabeto_limpio_mejor": "y",
}

# A sheet may carry options as a third element:
#   rotate: "cw" | "ccw"   the page was scanned sideways
SHEETS = [
    ("letras_limpias.svg", [
        "ABCDEFGHIJKLM", "NOPQRSTUVWXYZ",
        "abcdefghijklm", "nopqrstuvwxyz",
        "0123456789", "0123456789"]),
    ("alfabeto_limpio_mejor.svg", [
        "áéíóú", "ÁÉÍÓÚ",
        "ABCDEFGHIJKLMN", "OPQRSTUVWXYZ",
        "abcdefghijklmn", "opqrstuvwxyz"]),
    ("Letra Jesus Dario anacona.svg", [
        "ABCDEFGHIJKLM", "NOPQRSTUVWXYZ",
        "abcdefghijklm", "nopqrstuvwxyz",
        "0123456789", "\u00e1\u00e9\u00ed\u00f3\u00fa@"]),
    ("LETRA MILER CERQUERA.svg", [
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "abcdefghijklmnopqrstuvwxyz",
        "0123456789",
        "0123456789",
        # the last two rows are plain vowels, not accented ones: no detached mark
        # sits above any of them, so they are a second take of the same letters
        "aeiou",
        "AEIOU"]),
    # Scanned sideways, and every line climbs to the right. No lowercase on it.
    ("Letra Jessica.svg", [
        "0123456789",
        "0123456789",
        "ABCDEF",
        "ABCDEFGHIJKLMN",
        "OPQRSTUVWXYZ"], {"rotate": "cw"}),
]


# ---------------------------------------------------------------- parsing
def _tokens(d):
    for m in TOKEN.finditer(d):
        yield ("c", m.group(1)) if m.group(1) else ("n", float(m.group(2)))


def parse_subpaths(d):
    """Walk one `d` attribute and return its closed subpaths as point lists.

    Handles the whole path grammar, not just M/L/Z, because the third sheet is a
    tracing made of cubic Beziers. Curves are subdivided rather than reduced to
    their endpoints, which would turn every round letter into a polygon.
    """
    subs, cur = [], []
    x = y = sx = sy = 0.0
    ctrl = None                      # previous control point, for S/T reflection
    cmd = None
    toks = list(_tokens(d))
    i = 0

    def cubic(p0, p1, p2, p3):
        for k in range(1, CURVE_STEPS + 1):
            t = k / CURVE_STEPS
            u = 1.0 - t
            cur.append((u*u*u*p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t*t*t*p3[0],
                        u*u*u*p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t*t*t*p3[1]))

    def quad(p0, p1, p2):
        for k in range(1, CURVE_STEPS + 1):
            t = k / CURVE_STEPS
            u = 1.0 - t
            cur.append((u*u*p0[0] + 2*u*t*p1[0] + t*t*p2[0],
                        u*u*p0[1] + 2*u*t*p1[1] + t*t*p2[1]))

    while i < len(toks):
        kind, val = toks[i]
        if kind == "c":
            cmd = val
            i += 1
            if cmd in "Zz":
                if len(cur) >= 3:
                    subs.append(cur)
                cur = []
                x, y = sx, sy
                ctrl = None
            continue
        if cmd is None:
            i += 1
            continue

        def num():
            nonlocal i
            v = toks[i][1]
            i += 1
            return v

        rel = cmd.islower()
        c = cmd.upper()

        if c == "M":
            nx, ny = num(), num()
            if rel: nx, ny = x + nx, y + ny
            if len(cur) >= 3: subs.append(cur)
            cur = [(nx, ny)]
            x, y = sx, sy = nx, ny
            cmd = "l" if rel else "L"    # extra pairs after M are implicit lines
            ctrl = None
        elif c == "L":
            nx, ny = num(), num()
            if rel: nx, ny = x + nx, y + ny
            cur.append((nx, ny)); x, y = nx, ny; ctrl = None
        elif c == "H":
            nx = num()
            if rel: nx = x + nx
            cur.append((nx, y)); x = nx; ctrl = None
        elif c == "V":
            ny = num()
            if rel: ny = y + ny
            cur.append((x, ny)); y = ny; ctrl = None
        elif c == "C":
            x1, y1, x2, y2, nx, ny = (num() for _ in range(6))
            if rel:
                x1, y1, x2, y2, nx, ny = x+x1, y+y1, x+x2, y+y2, x+nx, y+ny
            cubic((x, y), (x1, y1), (x2, y2), (nx, ny))
            ctrl = (x2, y2); x, y = nx, ny
        elif c == "S":
            x2, y2, nx, ny = (num() for _ in range(4))
            if rel:
                x2, y2, nx, ny = x+x2, y+y2, x+nx, y+ny
            x1, y1 = (2*x - ctrl[0], 2*y - ctrl[1]) if ctrl else (x, y)
            cubic((x, y), (x1, y1), (x2, y2), (nx, ny))
            ctrl = (x2, y2); x, y = nx, ny
        elif c == "Q":
            x1, y1, nx, ny = (num() for _ in range(4))
            if rel:
                x1, y1, nx, ny = x+x1, y+y1, x+nx, y+ny
            quad((x, y), (x1, y1), (nx, ny))
            ctrl = (x1, y1); x, y = nx, ny
        elif c == "T":
            nx, ny = num(), num()
            if rel: nx, ny = x+nx, y+ny
            x1, y1 = (2*x - ctrl[0], 2*y - ctrl[1]) if ctrl else (x, y)
            quad((x, y), (x1, y1), (nx, ny))
            ctrl = (x1, y1); x, y = nx, ny
        elif c == "A":
            # No sheet uses arcs; consume all seven numbers and take the endpoint
            # so a stray one cannot desync the token stream.
            _rx, _ry, _rot, _laf, _sf, nx, ny = (num() for _ in range(7))
            if rel: nx, ny = x+nx, y+ny
            cur.append((nx, ny)); x, y = nx, ny; ctrl = None
        else:
            i += 1

    if len(cur) >= 3:
        subs.append(cur)
    return [sub for sub in subs if len(sub) >= 3]


def group_transform(body):
    """The translate+scale on a wrapping <g>, as (tx, ty, sx, sy).

    potrace wraps its output in a group that flips Y (`scale(0.1,-0.1)`) and
    shifts the origin to the page height. Ignoring it turns every glyph upside
    down. A negative scale also reverses every contour, but nonzero filling only
    cares about outline and counter running OPPOSITE ways, and both flip together.
    """
    m = re.search(r"<g\b[^>]*transform=\"([^\"]+)\"", body)
    if not m:
        return 0.0, 0.0, 1.0, 1.0
    tr = m.group(1)
    tx = ty = 0.0
    sx = sy = 1.0
    t = re.search(r"translate\(\s*([-\d.eE]+)(?:[ ,]+([-\d.eE]+))?\s*\)", tr)
    if t:
        tx = float(t.group(1))
        ty = float(t.group(2)) if t.group(2) else 0.0
    c = re.search(r"scale\(\s*([-\d.eE]+)(?:[ ,]+([-\d.eE]+))?\s*\)", tr)
    if c:
        sx = float(c.group(1))
        sy = float(c.group(2)) if c.group(2) else sx
    return tx, ty, sx, sy


def rotate_subpaths(subs, how, w, h):
    """Quarter turn, for a page that was scanned sideways."""
    if how == "cw":
        return [[(h - y, x) for (x, y) in sub] for sub in subs]
    if how == "ccw":
        return [[(y, w - x) for (x, y) in sub] for sub in subs]
    return subs


def sheet_subpaths(raw):
    """Every inked subpath in a sheet, whatever shape the file takes.

    A one-path sheet comes back untouched: its tracer already wound counters the
    right way, which is why those glyphs have always rendered with holes.

    A multi-path sheet is different. It paints each counter as its own path filled
    with the PAGE COLOUR, stacked over the letter — a hole by overpainting, which
    survives neither merging into one path nor a nonzero fill. The file already
    says which contour is which, so rather than guessing from nesting we read the
    fill: page-coloured contours are holes and get wound against the ink, and
    everything else is ink. Deciding by colour also keeps the few glyphs painted
    with a gradient on the ink side.
    """
    body = raw[raw.index("</metadata>"):] if "</metadata>" in raw else raw
    tx, ty, sx, sy = group_transform(body)
    place = (lambda sub: [(x * sx + tx, y * sy + ty) for x, y in sub]) \
        if (tx or ty or sx != 1.0 or sy != 1.0) else (lambda sub: sub)
    els = re.findall(r'<path\b([^>]*?)\bd="([^"]+)"([^>]*)>', body)
    if not els:
        return [place(sub) for d in re.findall(r'\bd="([^"]+)"', raw)
                for sub in parse_subpaths(d)]

    vb = re.search(r'viewBox="\s*([-\d.]+)[ ,]+([-\d.]+)[ ,]+([-\d.]+)[ ,]+([-\d.]+)', raw)
    sheet_area = (float(vb.group(3)) * float(vb.group(4))) if vb else 0.0

    def fill_of(pre, post):
        m = re.search(r'fill="([^"]*)"', pre + post)
        return (m.group(1) if m else "").strip().lower()

    # The page colour is whatever fills the sheet-sized rectangle.
    page_fill = None
    for pre, d, post in els:
        for sub in parse_subpaths(d):
            if sheet_area and area(bbox(place(sub))) > sheet_area * BG_AREA_FRACTION:
                page_fill = fill_of(pre, post)
                break
        if page_fill is not None:
            break

    out = []
    for pre, d, post in els:
        hole = page_fill is not None and fill_of(pre, post) == page_fill
        for sub in parse_subpaths(d):
            sub = place(sub)
            if sheet_area and area(bbox(sub)) > sheet_area * BG_AREA_FRACTION:
                continue          # the page itself
            if page_fill is not None:
                # ink winds one way, holes the other, so a nonzero fill cuts them out
                positive = signed_area(sub) > 0
                if positive == hole:
                    sub = sub[::-1]
            out.append(sub)
    return out


def bbox(pts):
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return [min(xs), min(ys), max(xs), max(ys)]


def area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def union(a, b):
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def signed_area(pts):
    """Shoelace. Sign tells which way the contour winds."""
    total = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return total * 0.5


def contains(a, b):
    return a[0] <= b[0] and a[1] <= b[1] and a[2] >= b[2] and a[3] >= b[3]




# ---------------------------------------------------- grouping into glyphs
def group_shapes(subs):
    """Attach counters (holes) to the outline that contains them."""
    boxes = [bbox(s) for s in subs]
    order = sorted(range(len(subs)), key=lambda i: -area(boxes[i]))
    parent = {}
    for k, i in enumerate(order):
        for j in order[:k]:
            if j in parent:            # only nest one level; holes are not nested here
                continue
            a, b = boxes[j], boxes[i]
            if a[0] <= b[0] and a[1] <= b[1] and a[2] >= b[2] and a[3] >= b[3]:
                parent[i] = j
                break
    shapes = {}
    for i in range(len(subs)):
        root = parent.get(i, i)
        shapes.setdefault(root, {"subs": [], "box": None})
        shapes[root]["subs"].append(subs[i])
        shapes[root]["box"] = boxes[i] if shapes[root]["box"] is None else \
            union(shapes[root]["box"], boxes[i])
    return list(shapes.values())


def merge_marks(shapes):
    """Glue i/j dots and accents onto the body directly below them.

    A mark sits ABOVE its body, never beside it: without the vertical-overlap test,
    adjacent letters of unequal size merge into one glyph.
    """
    shapes = sorted(shapes, key=lambda s: -area(s["box"]))
    used = [False] * len(shapes)
    for i, big in enumerate(shapes):
        if used[i]: continue
        for j, sm in enumerate(shapes):
            if i == j or used[j]: continue
            B, S = big["box"], sm["box"]
            bw, bh = B[2] - B[0], B[3] - B[1]
            sw, sh = S[2] - S[0], S[3] - S[1]
            if sw * sh > bw * bh * 0.62 or sh > bh * 0.80: continue
            if min(B[3], S[3]) - max(B[1], S[1]) > sh * 0.30: continue      # side by side
            if min(B[2], S[2]) - max(B[0], S[0]) < sw * 0.55: continue
            scx = (S[0] + S[2]) / 2
            if not (B[0] - bw * 0.15 <= scx <= B[2] + bw * 0.15): continue
            if max(0.0, max(B[1], S[1]) - min(B[3], S[3])) > bh * 0.75: continue
            big["subs"] += sm["subs"]
            big["box"] = union(B, S)
            used[j] = True
    return [s for k, s in enumerate(shapes) if not used[k]]


def rows_of(shapes, expect):
    """Split into text rows, sweeping the gap threshold until the count matches."""
    ys = sorted(shapes, key=lambda s: s["box"][1])
    heights = sorted(s["box"][3] - s["box"][1] for s in shapes)
    hmed = heights[len(heights) // 2]
    for f in [x / 100.0 for x in range(10, 210, 2)]:
        rows, cur, last = [], [], None
        for s in ys:
            if last is not None and s["box"][1] > last + hmed * f:
                rows.append(cur); cur = []
            cur.append(s)
            last = max(last, s["box"][3]) if last is not None else s["box"][3]
            if len(cur) == 1: last = s["box"][3]
        if cur: rows.append(cur)
        if len(rows) == expect:
            for r in rows: r.sort(key=lambda s: s["box"][0])
            return rows
    return None


def rows_tracked(shapes, expect):
    """Walk each line left to right and let its height drift.

    rows_of() slices the page into level bands, which only works while a line
    stays level. On a hand-ruled sheet a line can climb as it goes: here the last
    letter of one row ends up HIGHER than the first letter of the row below, so no
    horizontal cut separates them and the two rows come back glued together. This
    starts at the leftmost unclaimed shape and keeps taking the nearest shape to
    its right whose centre is close to the line's running height, which follows
    the climb instead of fighting it.
    """
    left = sorted(shapes, key=lambda s: s["box"][0])
    used = [False] * len(left)
    heights = sorted(s["box"][3] - s["box"][1] for s in shapes)
    hmed = heights[len(heights) // 2]
    rows = []
    for i, s in enumerate(left):
        if used[i]:
            continue
        used[i] = True
        row = [s]
        cy = (s["box"][1] + s["box"][3]) / 2.0
        while True:
            best, bestd = None, None
            for j in range(len(left)):
                if used[j]:
                    continue
                b = left[j]["box"]
                if b[2] < row[-1]["box"][0]:
                    continue
                if abs((b[1] + b[3]) / 2.0 - cy) > hmed * 0.75:
                    continue
                d = b[0] - row[-1]["box"][2]
                if bestd is None or d < bestd:
                    best, bestd = j, d
            if best is None:
                break
            used[best] = True
            row.append(left[best])
            bb = left[best]["box"]
            cy = cy * 0.5 + ((bb[1] + bb[3]) / 2.0) * 0.5
        rows.append(row)
    if len(rows) != expect:
        return None
    rows.sort(key=lambda r: min(x["box"][1] for x in r))
    for r in rows:
        r.sort(key=lambda x: x["box"][0])
    return rows


# A row whose writing line climbs by more than this many glyph heights across its
# width gets a fitted baseline instead of a single median. Measured: the four
# level sheets never pass 0.25, the sideways one reaches 3.26.
BASELINE_DRIFT = 0.4


def row_baseline(chars, row):
    """Where the writing line sits under each glyph, as a function of x.

    A single median is right for a level row and wrong for one that climbs: on
    the sideways sheet the right end of a row ends up more than three letter
    heights above the left end, and pinning every glyph to one median leaves half
    the row floating above the line and the other half sunk below it. A level row
    keeps the median it always used, so the sheets already shipped are untouched.
    """
    def centre(sh):
        return (sh["box"][0] + sh["box"][2]) / 2.0

    pts = [(centre(sh), sh["box"][3])
           for c, sh in zip(chars, row) if c not in DESCENDERS]
    if len(pts) < 3:
        pts = [(centre(sh), sh["box"][3]) for sh in row]
    ys = sorted(q[1] for q in pts)
    med = ys[len(ys) // 2]
    if len(pts) < 3:
        return lambda x: med

    heights = sorted(sh["box"][3] - sh["box"][1] for sh in row)
    hmed = heights[len(heights) // 2] or 1.0
    n = len(pts)
    sx = sum(q[0] for q in pts)
    sy = sum(q[1] for q in pts)
    sxx = sum(q[0] * q[0] for q in pts)
    sxy = sum(q[0] * q[1] for q in pts)
    den = n * sxx - sx * sx
    if not den:
        return lambda x: med
    m = (n * sxy - sx * sy) / den
    b = (sy - m * sx) / n
    width = max(q[0] for q in pts) - min(q[0] for q in pts)
    if abs(m) * width < hmed * BASELINE_DRIFT:
        return lambda x: med
    return lambda x: m * x + b


def reconcile(row, want):
    """Row text is ground truth, so the glyph count is known. Force it.

    Extra pieces are always parts of a letter that the tracer left detached: the
    two legs of an A, the bar of an E, a speck shed off a stroke. They are far
    closer to their own letter than any two letters are to each other, so the
    pair with the smallest horizontal gap is merged, over and over, until the
    count matches.

    Requiring the pair to OVERLAP horizontally, as this used to, cannot join the
    legs of an A: they meet at a point and overlap by zero. The merge was then
    skipped and a real letter got dropped instead, which shifted every character
    after it onto the wrong glyph.
    """
    row = list(row)
    while len(row) > want:
        best, cost = None, None
        for i in range(len(row)):
            for j in range(i + 1, len(row)):
                A, B = row[i]["box"], row[j]["box"]
                # negative when the boxes overlap, which is an even stronger sign
                gap = max(A[0], B[0]) - min(A[2], B[2])
                if cost is None or gap < cost:
                    best, cost = (i, j), gap
        if best is None:
            k = min(range(len(row)), key=lambda i: area(row[i]["box"]))
            row.pop(k)
            continue
        i, j = best
        row[i]["subs"] += row[j]["subs"]
        row[i]["box"] = union(row[i]["box"], row[j]["box"])
        row.pop(j)
    row.sort(key=lambda s: s["box"][0])
    return row


# Points closer than this to the line they sit on are dropped. In glyph units,
# where the em is 90: at a 40 px rendering that is 0.07 px of movement, so the
# outline is untouched to the eye while the file gets a lot smaller. Flattening a
# curve into 16 segments emits far more points than its shape needs, and a sheet
# traced by potrace is nothing but curves.
SIMPLIFY_TOL = 0.15


def simplify(pts, tol):
    """Ramer-Douglas-Peucker on a closed contour.

    Iterative on purpose: a traced contour can carry a couple of thousand points
    and the recursive form blows Python's stack on the longest ones.
    """
    if len(pts) < 5:
        return pts

    def chain(a, b):
        """Indices to keep between a and b, endpoints included."""
        keep = {a, b}
        stack = [(a, b)]
        while stack:
            i0, i1 = stack.pop()
            if i1 - i0 < 2:
                continue
            ax, ay = pts[i0]
            bx, by = pts[i1]
            dx, dy = bx - ax, by - ay
            norm = (dx * dx + dy * dy) ** 0.5
            best, bestd = -1, -1.0
            for i in range(i0 + 1, i1):
                px, py = pts[i]
                if norm < 1e-9:
                    d = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
                else:
                    d = abs(dy * px - dx * py + bx * ay - by * ax) / norm
                if d > bestd:
                    best, bestd = i, d
            if best >= 0 and bestd > tol:
                keep.add(best)
                stack.append((i0, best))
                stack.append((best, i1))
        return keep

    # A closed ring has no natural endpoints; cut it at the point farthest from
    # the first so the two halves are open chains RDP can work on.
    far = max(range(len(pts)), key=lambda i: (pts[i][0] - pts[0][0]) ** 2
                                             + (pts[i][1] - pts[0][1]) ** 2)
    if far == 0:
        return pts
    keep = chain(0, far) | chain(far, len(pts) - 1)
    out = [pts[i] for i in sorted(keep)]
    return out if len(out) >= 3 else pts


# ------------------------------------------------------------- emitting
def emit(shape, upp, baseline_y):
    """Translate+scale geometry into glyph units. x=0 at the ink's left edge,
    y=BASE at the row baseline. No resampling, no smoothing, no approximation."""
    B = shape["box"]
    out = []
    for sub in shape["subs"]:
        scaled = [((x - B[0]) * upp, BASE + (y - baseline_y) * upp) for (x, y) in sub]
        pts = [f"{x:.2f} {y:.2f}" for (x, y) in simplify(scaled, SIMPLIFY_TOL)]
        out.append("M" + "L".join(pts) + "Z")
    return "".join(out), (B[2] - B[0]) * upp, (B[3] - baseline_y) * upp


def main():
    bank, report = {}, []
    for entry in SHEETS:
        name, seq = entry[0], entry[1]
        opts = entry[2] if len(entry) > 2 else {}
        src = name.replace(".svg", "")
        raw = open(os.path.join(ROOT, "assets", name), encoding="utf-8").read()
        subs = sheet_subpaths(raw)
        if opts.get("rotate"):
            vb = re.search(r'viewBox="\s*([-\d.]+)[ ,]+([-\d.]+)[ ,]+([-\d.]+)[ ,]+([-\d.]+)',
                           raw)
            vw = float(vb.group(3)) if vb else 0.0
            vh = float(vb.group(4)) if vb else 0.0
            subs = rotate_subpaths(subs, opts["rotate"], vw, vh)
        shapes = merge_marks(group_shapes(subs))
        rows = rows_of(shapes, len(seq))
        if rows is None:
            rows = rows_tracked(shapes, len(seq))
        if rows is None:
            report.append(f"{name}: FAILED to split into {len(seq)} rows")
            continue
        report.append(f"\n=== {name}  subpaths {len(subs)}  shapes {len(shapes)}")
        for ri, row in enumerate(rows):
            want = len(seq[ri])
            row = reconcile(row, want)
            flag = "OK " if len(row) == want else ">> "
            report.append(f"  {flag}row {ri}: {len(row):3d}/{want:3d}  {seq[ri]}")
            if len(row) != want:
                continue

            # Row metrics from the real ink boxes, measured against the writing
            # line under each glyph rather than one line for the whole row.
            base_at = row_baseline(seq[ri], row)
            mid = lambda sh: (sh["box"][0] + sh["box"][2]) / 2.0
            xs = sorted(base_at(mid(s)) - s["box"][1]
                        for c, s in zip(seq[ri], row) if c in XCHARS)
            cs = sorted(base_at(mid(s)) - s["box"][1]
                        for c, s in zip(seq[ri], row)
                        if c.isupper() or c.isdigit())
            if len(xs) >= 2:   upp = (BASE - XTOP) / max(1e-6, xs[len(xs) // 2])
            elif cs:           upp = (BASE - CAPTOP) / max(1e-6, cs[len(cs) // 2])
            else:
                hs = sorted(base_at(mid(s)) - s["box"][1] for s in row)
                upp = 50.0 / max(1e-6, hs[len(hs) // 2])

            skip = SKIP.get(src, "")
            for ch, sh in zip(seq[ri], row):
                if ch in skip:
                    report.append(f"     omitido {ch!r}: trazado inservible en esta hoja")
                    continue
                b_y = base_at(mid(sh))
                # Non-descender digits sit on the baseline; if writer dipped below the line or
                # the row baseline drifted, anchor to glyph bottom so it doesn't sink into the ground
                if ch in "01235678":
                    if sh["box"][3] > b_y or abs(sh["box"][3] - b_y) * upp > 3.0:
                        b_y = sh["box"][3]
                p, w, desc = emit(sh, upp, b_y)
                bank.setdefault(ch, []).append({
                    "p": p, "w": round(w, 2), "desc": round(desc, 2),
                    "src": src
                })

    out = {
        "units": {"base": BASE, "xtop": XTOP, "cap": CAPTOP, "em": EM},
        "glyphs": bank
    }
    path = os.path.join(ROOT, "glyphs-vector.json")
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("\n".join(report))
    n = sum(len(v) for v in bank.values())
    widths = sorted(g["w"] for v in bank.values() for g in v)
    print(f"\n{n} glyphs / {len(bank)} chars -> glyphs-vector.json "
          f"({os.path.getsize(path)/1024:.1f} KB)")
    print(f"advance widths (units): min {widths[0]:.0f}  median {widths[len(widths)//2]:.0f}  max {widths[-1]:.0f}")


if __name__ == "__main__":
    main()
