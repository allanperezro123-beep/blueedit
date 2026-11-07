import json, os

REPLACEMENTS = {
    "LETRA MILER CERQUERA": "Trazo Rápido (Bolígrafo)",
    "Letra Jessica": "Mayúsculas Redondeadas",
    "Letra Jesus Dario anacona": "Cursiva Fluida",
    "letras_limpias": "Caligráfica Fina",
    "alfabeto_limpio_mejor": "Imprenta Limpia"
}

files = ['glyphs-vector.json', os.path.join('assets', 'data', 'glyphs-vector.json')]

for fpath in files:
    if not os.path.exists(fpath):
        continue
    print(f"Processing {fpath}...")
    with open(fpath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    count = 0
    sources_before = set()
    sources_after = set()
    for char, variants in data.get('glyphs', {}).items():
        for v in variants:
            old_src = v.get('src')
            if old_src:
                sources_before.add(old_src)
                if old_src in REPLACEMENTS:
                    v['src'] = REPLACEMENTS[old_src]
                    count += 1
                sources_after.add(v['src'])
                
    with open(fpath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
        
    print(f"Updated {count} glyph source tags in {fpath}.")
    print(f"  Before: {sources_before}")
    print(f"  After:  {sources_after}")

