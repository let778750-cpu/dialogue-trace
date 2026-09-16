from pathlib import Path
import subprocess
from research_memory.plugin_bundle import bundle_main


def test_single_entry_loads_without_development_files_or_juggl(tmp_path):
    source=Path(__file__).resolve().parents[1]/'tools/obsidian/graph/plugin'
    main=tmp_path/'main.js';main.write_bytes(bundle_main(source))
    script='''const vm=require('node:vm'),fs=require('node:fs');const module={exports:{}};
    const requests=[];const obsidian={Plugin:class{},ItemView:class{},Modal:class{},Component:class{},TFile:class{}};
    const load=name=>{requests.push(name);if(name==='obsidian')return obsidian;if(name.startsWith('.'))throw Error('Unbundled dependency '+name);return require(name);};
    vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),{module,require:load});
    if(typeof module.exports!=='function')throw Error('Plugin entry missing');
    if(requests.some(n=>n.includes('juggl')))throw Error('Graph engine loaded at startup');'''
    result=subprocess.run(['node','-e',script,str(main)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
