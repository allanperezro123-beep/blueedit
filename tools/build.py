"""Assemble editor-actas.html from the CSS/markup, the vector glyph bank and app.js.

Run after changing the glyph sheets or the app source:
    python tools/svg_glyphs.py && python tools/build.py

Output is a single self-contained file: no local assets, only CDN scripts, so it
can be dropped straight into Firebase Hosting.
"""
import json, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "editor-actas.html")
OUT = os.path.join(ROOT, "editor-actas.html")

html = open(SRC, encoding="utf-8").read()

# --- CSS: keep the existing design, drop the now-unused embedded font ---
css = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
css = re.sub(r"@font-face\s*\{.*?\}\s*", "", css, flags=re.S)

# --- markup: from <div id="app"> through the hidden file inputs ---
start = html.index('<div id="app">')
end = html.index('<script id="glyphbank"') if '<script id="glyphbank"' in html \
    else html.index("<!--GLYPHBANK-->")
markup = html[start:end].strip()

bank_path = os.path.join(ROOT, "assets", "data", "glyphs-vector.json") if os.path.exists(os.path.join(ROOT, "assets", "data", "glyphs-vector.json")) else os.path.join(ROOT, "glyphs-vector.json")
bank = open(bank_path, encoding="utf-8").read()
app = open(os.path.join(ROOT, "tools", "app.js"), encoding="utf-8").read()

doc = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BlueEdit — Suite Creativa & Caligrafía Digital por BlueCode</title>
<meta name="description" content="BlueEdit: Suite avanzada de edición de documentos, caligrafía manuscrita vectorial y renderizado de alta fidelidad desarrollada por BlueCode.">
<meta name="theme-color" content="#0A0A0C">
<meta property="og:type" content="website">
<meta property="og:title" content="BlueEdit — Suite Creativa por BlueCode">
<meta property="og:description" content="Edición de documentos, firmas y caligrafía vectorial con el motor y estética de BlueCode.">
<meta property="og:url" content="https://blueedit.web.app/">
<link rel="icon" type="image/svg+xml" href="logo_BC.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Space+Mono:ital,wght@0,400;0,700;1,400&display=swap" rel="stylesheet">
<!-- Libraries are loaded by the boot loader below: ./vendor first, CDN as fallback. -->
<style>{css}</style>
</head>
<body>
{markup}

<script id="glyphbank" type="application/json">{bank}</script>

<script>
{app}
</script>
</body>
</html>
"""

open(OUT, "w", encoding="utf-8").write(doc)
pub_out = os.path.join(ROOT, "public", "index.html")
open(pub_out, "w", encoding="utf-8").write(doc)

data = json.loads(bank)
n = sum(len(v) for v in data["glyphs"].values())
print(f"built editor-actas.html  ({os.path.getsize(OUT)/1024:.1f} KB)")
print(f"  glyphs {n} / {len(data['glyphs'])} chars   app {len(app)/1024:.1f} KB")
