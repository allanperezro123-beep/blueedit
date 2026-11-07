"""Render proof sheets from glyphs-vector.json using the exact layout maths the
JS engine will use, so what looks right here looks right in the app."""
import json, os, random, re
from PIL import Image, ImageDraw, ImageChops

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANK = json.load(open(os.path.join(ROOT, "glyphs-vector.json"), encoding="utf-8"))
G = BANK["glyphs"]
EM = BANK["units"]["em"]
BASE = BANK["units"]["base"]

SUB = re.compile(r"M([^MZ]+)Z")


def points(path):
    for m in SUB.finditer(path):
        yield [tuple(float(v) for v in pair.split())
               for pair in m.group(1).split("L") if pair.strip()]


class Bag:
    def __init__(self, seed=7):
        self.q, self.last, self.rnd = {}, {}, random.Random(seed)

    def pick(self, ch):
        n = len(G[ch])
        if n == 1: return 0
        q = self.q.get(ch)
        if not q:
            q = list(range(n)); self.rnd.shuffle(q)
            if q[-1] == self.last.get(ch) and n > 1:
                q[0], q[-1] = q[-1], q[0]
            self.q[ch] = q
        i = q.pop()
        self.last[ch] = i
        return i


def draw_line(canvas, text, x, baseline, size, bag, bearing, wordgap,
              rgb=(20, 20, 24), jitter=0.0, rnd=None):
    s = size / EM
    pen = float(x)
    W, H = canvas.size
    for ch in text:
        if ch == " ":
            pen += wordgap * s
            continue
        if ch not in G:
            pen += 20 * s
            continue
        v = G[ch][bag.pick(ch)]
        dy = (rnd.uniform(-1, 1) * jitter * s) if (rnd and jitter) else 0.0
        mask = Image.new("1", (W, H), 0)
        for poly in points(v["p"]):
            if len(poly) < 3: continue
            layer = Image.new("1", (W, H), 0)
            ImageDraw.Draw(layer).polygon(
                [(pen + px * s, baseline + (py - BASE) * s + dy) for px, py in poly], fill=1)
            mask = ImageChops.logical_xor(mask, layer)      # even-odd -> real holes
        canvas.paste(Image.new("RGB", (W, H), rgb), (0, 0), mask)
        pen += (v["w"] + bearing) * s
    return pen


def sheet(path, lines, size=54, variants=((2.0, 26), (4.0, 30), (6.0, 34))):
    W = 1900
    H = 60 + len(variants) * (len(lines) * 92 + 60)
    cv = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(cv)
    y = 70
    for bearing, wordgap in variants:
        d.text((14, y - 44), f"bearing={bearing}  wordgap={wordgap}", fill=(200, 60, 60))
        bag, rnd = Bag(11), random.Random(5)
        for ln in lines:
            d.line([(40, y), (W - 40, y)], fill=(228, 236, 246))
            draw_line(cv, ln, 44, y, size, bag, bearing, wordgap, jitter=1.1, rnd=rnd)
            y += 92
        y += 60
    cv.save(path)


if __name__ == "__main__":
    lines = [
        "Hola a todos, Hola a todos, Hola a todos",
        "Acta No 123 - reunion ordinaria",
        "El coordinador presento el informe tecnico",
    ]
    sheet(os.path.join(ROOT, "tools", "proof_vec_spacing.png"), lines)
    miss = [c for c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789áéíóúÁÉÍÓÚ"
            if c not in G]
    print("chars:", len(G), "variants:", sum(len(v) for v in G.values()))
    print("missing:", miss or "none")
    print("wrote proof_vec_spacing.png")
