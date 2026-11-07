"""Inject glyphs.json into editor-actas.html so the app stays a single self-contained file.

Re-run after adding new handwriting sheets:
    python tools/extract.py && python tools/embed.py
"""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "editor-actas.html")
JSON = os.path.join(ROOT, "glyphs.json")

OPEN = '<script id="glyphbank" type="application/json">'
CLOSE = "</script>"
PATTERN = re.compile(re.escape(OPEN) + r".*?" + re.escape(CLOSE), re.S)

bank = open(JSON, encoding="utf-8").read()
html = open(HTML, encoding="utf-8").read()
block = OPEN + bank + CLOSE

if PATTERN.search(html):
    html = PATTERN.sub(lambda _: block, html, count=1)
elif "<!--GLYPHBANK-->" in html:
    html = html.replace("<!--GLYPHBANK-->", block, 1)
else:
    sys.exit("No <!--GLYPHBANK--> placeholder and no existing bank block in the HTML.")

open(HTML, "w", encoding="utf-8").write(html)

data = json.loads(bank)
n = sum(len(v) for v in data["glyphs"].values())
print(f"embedded {n} glyphs / {len(data['glyphs'])} chars "
      f"({len(bank)/1024:.1f} KB) -> editor-actas.html "
      f"({os.path.getsize(HTML)/1024:.1f} KB total)")
