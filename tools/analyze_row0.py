import os, sys, re

v2_path = os.path.abspath('../EDITOR DE ACTAS V2')
sys.path.insert(0, os.path.join(v2_path, 'src'))
import svg_glyphs

raw = open(os.path.join(v2_path, 'assets', 'Letra Jessica.svg'), encoding='utf-8').read()
subs = svg_glyphs.sheet_subpaths(raw)
vb = re.search(r'viewBox="([^"]+)"', raw)
vw, vh = [float(x) for x in vb.group(1).split()][2:4]
subs_rot = svg_glyphs.rotate_subpaths(subs, 'cw', vw, vh)
shapes = svg_glyphs.merge_marks(svg_glyphs.group_shapes(subs_rot))
rows = svg_glyphs.rows_tracked(shapes, 5)

row0 = svg_glyphs.reconcile(rows[0], 10)
seq0 = "0123456789"

print("Row 0 glyphs analysis:")
for ch, sh in zip(seq0, row0):
    b = sh["box"]
    cx = (b[0] + b[2]) / 2.0
    cy = (b[1] + b[3]) / 2.0
    print(f"ch '{ch}': x=[{b[0]:.1f}..{b[2]:.1f}] cx={cx:.1f}, y=[{b[1]:.1f}..{b[3]:.1f}] bottom_y={b[3]:.1f}, height={b[3]-b[1]:.1f}")

# Linear regression on Row 0 bottom points
pts = [((sh["box"][0] + sh["box"][2]) / 2.0, sh["box"][3]) for sh in row0]
n = len(pts)
sx = sum(q[0] for q in pts)
sy = sum(q[1] for q in pts)
sxx = sum(q[0] * q[0] for q in pts)
sxy = sum(q[0] * q[1] for q in pts)
den = n * sxx - sx * sx
m = (n * sxy - sx * sy) / den
b_val = (sy - m * sx) / n

heights = sorted(sh["box"][3] - sh["box"][1] for sh in row0)
hmed = heights[len(heights) // 2]
width = max(q[0] for q in pts) - min(q[0] for q in pts)
drift = abs(m) * width

print(f"\nLinear fit for Row 0: m={m:.5f}, b={b_val:.2f}")
print(f"hmed={hmed:.2f}, width={width:.2f}, drift={drift:.2f} (hmed * BASELINE_DRIFT = {hmed * svg_glyphs.BASELINE_DRIFT:.2f})")
print(f"Is drift >= threshold? {drift >= hmed * svg_glyphs.BASELINE_DRIFT}")

# Compare fitted baseline vs median baseline for each character in Row 0
med_y = sorted(q[1] for q in pts)[len(pts)//2]
print(f"Median y = {med_y:.2f}")
for ch, (cx, bot_y) in zip(seq0, pts):
    fit_y = m * cx + b_val
    print(f"ch '{ch}' cx={cx:6.1f} bot_y={bot_y:5.1f} | med_diff={bot_y - med_y:5.2f} | fit_diff={bot_y - fit_y:5.2f}")
