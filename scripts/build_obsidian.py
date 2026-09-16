"""Build an optional Obsidian component without private instance data."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from research_memory.plugin_bundle import bundle_main
p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
root=Path(__file__).resolve().parents[1];source=root/'tools/obsidian/graph/plugin';target=Path(a.output).resolve()
if target.exists():raise SystemExit('Choose a new build directory; existing plugin state is preserved')
target.mkdir(parents=True)
for name in ['manifest.json','styles.css','LICENSE','NOTICE.txt']:(target/name).write_bytes((source/name).read_bytes())
(target/'main.js').write_bytes(bundle_main(source))
print(target)
