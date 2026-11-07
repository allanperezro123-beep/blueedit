import json, os, random, re
from PIL import Image, ImageDraw, ImageChops, ImageFilter

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

def draw_handwriting(canvas, text, x, baseline, size, bag, softness=0.0,
                     rgb=(26, 58, 143), jitter=0.5, rnd=None):
    s = size / EM
    pen = float(x)
    W, H = canvas.size
    bearing = 3.5
    wordgap = 28.0

    # Draw sharp mask
    mask = Image.new("L", (W, H), 0)
    for ch in text:
        if ch == " ":
            pen += wordgap * s
            continue
        if ch not in G:
            pen += 20 * s
            continue
        v = G[ch][bag.pick(ch)]
        dy = (rnd.uniform(-1, 1) * jitter * s * 0.9) if (rnd and jitter) else 0.0
        char_mask = Image.new("1", (W, H), 0)
        for poly in points(v["p"]):
            if len(poly) < 3: continue
            layer = Image.new("1", (W, H), 0)
            ImageDraw.Draw(layer).polygon(
                [(pen + px * s, baseline + (py - BASE) * s + dy) for px, py in poly], fill=1)
            char_mask = ImageChops.logical_xor(char_mask, layer)
        # add to mask
        char_mask_L = char_mask.convert("L")
        mask = ImageChops.lighter(mask, char_mask_L)
        pen += (v["w"] + bearing) * s

    if softness > 0:
        # Simulate the shadow blur around the stroke
        blur_radius = size * softness * 0.35
        blurred = mask.filter(ImageFilter.GaussianBlur(blur_radius))
        # combine core mask + blurred halo
        combined_alpha = ImageChops.lighter(mask, blurred)
        ink_layer = Image.new("RGBA", (W, H), rgb + (255,))
        canvas.paste(ink_layer, (0, 0), combined_alpha)
    else:
        ink_layer = Image.new("RGBA", (W, H), rgb + (255,))
        canvas.paste(ink_layer, (0, 0), mask)

    return pen

def test_sheet():
    W = 1200
    H = 600
    img = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    softness_levels = [0.0, 0.15, 0.30, 0.50, 0.75, 1.0]
    
    y = 60
    d = ImageDraw.Draw(img)
    for soft in softness_levels:
        d.text((40, y - 25), f"Difuminado = {int(soft*100)}%", fill=(100, 100, 100))
        bag, rnd = Bag(42), random.Random(42)
        draw_handwriting(img, "Acta No 123 - El coordinador presentó el informe técnico", 40, y + 25, 34, bag, softness=soft, rnd=rnd)
        y += 85
        
    out_path = os.path.join(ROOT, "tools", "proof_softness.png")
    img.save(out_path)
    print(f"Generated {out_path}")

if __name__ == "__main__":
    test_sheet()
