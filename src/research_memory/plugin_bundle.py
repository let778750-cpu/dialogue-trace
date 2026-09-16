"""Bundle local CommonJS modules for Obsidian's single-entry plugin loader."""
import json
import re
from pathlib import Path


def bundle_main(source):
    source=Path(source)
    modules={p.stem:p.read_text(encoding='utf-8-sig') for p in source.glob('*.js')}
    if 'main' not in modules:raise ValueError('Plugin main.js missing')
    for name,code in modules.items():
        for dependency in re.findall(r'require\([\'"](\.[^\'"]+)[\'"]\)',code):
            key=dependency.removeprefix('./').removesuffix('.js')
            if key not in modules:raise ValueError('Plugin external file dependency: '+name+' -> '+dependency)
    definitions=',\n'.join(json.dumps(name)+': function(module,exports,require){\n'+code+'\n}' for name,code in sorted(modules.items()))
    return ('/* Research Memory Obsidian bundle. GPL-3.0; see LICENSE and NOTICE.txt. */\n'
        '(function(externalRequire){\nconst modules={'+definitions+'};\nconst cache={};\n'
        'function localRequire(name){if(!name.startsWith("./"))return externalRequire(name);'
        'const key=name.slice(2).replace(/\\.js$/,"");if(!modules[key])throw Error("Missing local module: "+name);'
        'if(!cache[key]){const entry={exports:{}};cache[key]=entry;modules[key](entry,entry.exports,localRequire);}return cache[key].exports;}\n'
        'module.exports=localRequire("./main");\n})(require);\n').encode('utf-8')
