import html.parser, json, sys

path = r"C:\Users\AllanPerezRobles\OneDrive - INRED\Documentos\EDITOR DE ACTAS\editor-actas.html"

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Check glyphbank tag
gb_start = content.find('<script id="glyphbank" type="application/json">')
if gb_start == -1:
    print("ERROR: <script id=\"glyphbank\"> not found")
    sys.exit(1)

gb_end = content.find('</script>', gb_start)
json_str = content[gb_start + len('<script id="glyphbank" type="application/json">'):gb_end].strip()

try:
    bank = json.loads(json_str)
    print(f"Glyphbank JSON valid. Contains {len(bank['glyphs'])} characters.")
except Exception as e:
    print(f"ERROR: Invalid JSON in glyphbank: {e}")
    sys.exit(1)

# Check script tag with JS code
js_start = content.find('<script>', gb_end)
js_end = content.find('</script>', js_start)
js_str = content[js_start + len('<script>'):js_end].strip()

print(f"JS Core code size: {len(js_str)/1024:.1f} KB.")
print("HTML verification passed!")
