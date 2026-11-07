import base64, os

html_path = r"C:\Users\AllanPerezRobles\OneDrive - INRED\Documentos\EDITOR DE ACTAS\editor-actas.html"
ttf_path = r"C:\Users\AllanPerezRobles\OneDrive - INRED\Documentos\EDITOR DE ACTAS\Jennifer-Regular.ttf"

with open(html_path, "r", encoding="utf-8") as f:
    html = f.read()

with open(ttf_path, "rb") as f:
    ttf_b64 = base64.b64encode(f.read()).decode("ascii")

font_face_css = f"""
@font-face {{
  font-family: 'Jennifer';
  src: url('data:font/ttf;charset=utf-8;base64,{ttf_b64}') format('truetype');
  font-weight: normal;
  font-style: normal;
}}
"""

if "@font-face {" in html and "font-family: 'Jennifer';" in html:
    print("Jennifer font-face already present.")
else:
    # Insert right after <style>
    html = html.replace("<style>", "<style>\n" + font_face_css)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Injected @font-face 'Jennifer' into {html_path}")
