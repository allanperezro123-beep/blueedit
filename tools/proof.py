"""Render proof sheets from glyphs.json — validates cropping, alpha, baseline and upp.

Mirrors exactly what the JS engine will do, so whatever looks right here looks right
in the app.
"""
import base64, io, json, os, random
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANK = json.load(open(os.path.join(ROOT, "glyphs.json"), encoding="utf-8"))
G = BANK["glyphs"]
EM = BANK["units"]["em"]          # 90
BEARING = 6.0                     # units of side bearing between glyphs


def img_of(v):
    return Image.open(io.BytesIO(base64.b64decode(v["d"]))).convert("RGBA")


def tint(im, rgb):
    r, g, b = rgb
    px = im.split()[3]
    solid = Image.new("RGBA", im.size, (r, g, b, 0))
    solid.putalpha(px)
    return solid


class Bag:
    """Shuffle bag: never repeats a variant back to back for the same character."""
    def __init__(self, seed=7):
        self.q, self.last, self.rnd = {}, {}, random.Random(seed)

    def pick(self, ch):
        n = len(G[ch])
        if n == 1:
            return 0
        q = self.q.get(ch)
        if not q:
            q = list(range(n))
            self.rnd.shuffle(q)
            if ch in self.last and q[-1] == self.last[ch] and n > 1:
                q[0], q[-1] = q[-1], q[0]
            while q and q[-1] == self.last.get(ch) and n > 1:
                self.rnd.shuffle(q)
            self.q[ch] = q
        i = q.pop()
        self.last[ch] = i
        return i


def draw_text(canvas, text, x, y, size, bag, rgb=(20, 20, 24), jitter=True,
              spacing=0.0, rnd=None):
    """y is the BASELINE. Returns the pen x after the last glyph."""
    rnd = rnd or random.Random(1)
    s = size / EM
    pen = float(x)
    for ch in text:
        if ch == " ":
            pen += 26 * s
            continue
        if ch not in G:
            pen += 20 * s
            continue
        v = G[ch][bag.pick(ch)]
        uw, uh = v["w"] * v["upp"], v["h"] * v["upp"]
        im = tint(img_of(v), rgb)
        w_px, h_px = max(1, round(uw * s)), max(1, round(uh * s))
        im = im.resize((w_px, h_px), Image.LANCZOS)
        dy = rnd.uniform(-1.2, 1.2) * s * 6 if jitter else 0
        if jitter:
            im = im.rotate(rnd.uniform(-2.2, 2.2), resample=Image.BICUBIC, expand=True)
            a = im.split()[3].point(lambda p: int(p * rnd.uniform(0.90, 1.0)))
            im.putalpha(a)
        bottom = y + v["desc"] * s + dy
        canvas.alpha_composite(im, (round(pen), round(bottom - im.size[1])))
        pen += (uw + BEARING + spacing) * s
    return pen


def sheet_alignment(path):
    """Every character, every variant, sitting on a drawn baseline."""
    rows = ["ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz",
            "0123456789", "áéíóúÁÉÍÓÚ,-_"]
    size, lead, pad = 62, 108, 40
    W, H = 2100, pad * 2 + lead * sum(len(G.get(c, [])) and 1 or 1 for r in rows for c in "x") * 0
    H = pad * 2 + lead * (len(rows) * 3)
    cv = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    d = ImageDraw.Draw(cv)
    y = pad + 60
    for row in rows:
        for var in range(3):
            d.line([(pad, y), (W - pad, y)], fill=(255, 90, 90, 255), width=1)
            d.text((8, y - 14), f"v{var}", fill=(200, 60, 60, 255))
            pen = pad
            s = size / EM
            for ch in row:
                if ch not in G:
                    continue
                vs = G[ch]
                v = vs[var % len(vs)]
                uw, uh = v["w"] * v["upp"], v["h"] * v["upp"]
                im = tint(img_of(v), (20, 20, 24)).resize(
                    (max(1, round(uw * s)), max(1, round(uh * s))), Image.LANCZOS)
                bottom = y + v["desc"] * s
                cv.alpha_composite(im, (round(pen), round(bottom - im.size[1])))
                pen += (uw + BEARING) * s
            y += lead
    cv.convert("RGB").save(path)


def sheet_words(path):
    """Real sentences — proves variant rotation and overall texture."""
    lines = [
        "Hola a todos, Hola a todos, Hola a todos",
        "Acta No 123 - ano 2026",
        "El coordinador presento el informe tecnico",
        "abcdefghijklmnopqrstuvwxyz",
        "Bogota, 14 de agosto - reunion ordinaria",
    ]
    W, H, pad, size, lead = 1900, 120 + 96 * len(lines), 50, 52, 96
    cv = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    d = ImageDraw.Draw(cv)
    bag = Bag(11)
    rnd = random.Random(5)
    y = pad + 56
    for i, ln in enumerate(lines):
        d.line([(pad, y), (W - pad, y)], fill=(225, 235, 245, 255), width=1)
        col = (26, 58, 143) if i == 1 else (22, 22, 26)
        draw_text(cv, ln, pad, y, size, bag, col, jitter=True, rnd=rnd)
        y += lead
    cv.convert("RGB").save(path)


if __name__ == "__main__":
    out = os.path.join(ROOT, "tools")
    sheet_alignment(os.path.join(out, "proof_align.png"))
    sheet_words(os.path.join(out, "proof_words.png"))
    miss = [c for c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789áéíóúÁÉÍÓÚ,-_"
            if c not in G]
    print("chars:", len(G), " variants:", sum(len(v) for v in G.values()))
    print("missing:", miss or "none")
    print("wrote proof_align.png, proof_words.png")
