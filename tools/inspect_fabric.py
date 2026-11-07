with open('editor-actas.html', 'r', encoding='utf-8') as f:
    html = f.read()

import re
pos = html.find('fabric')
while pos != -1:
    print("MATCH:", html[pos-50:pos+150])
    pos = html.find('fabric', pos+150)

