"""Back up instance metadata before a code upgrade. Never migrate raw event identities."""
import argparse
from pathlib import Path
import zipfile
from research_memory.storage import Config, read_json, write_json, now

p=argparse.ArgumentParser()
p.add_argument('--root',required=True)
p.add_argument('--package')
p.add_argument('--snapshot',action='store_true')
a=p.parse_args();c=Config(a.root)
if a.snapshot:
    target=c.directory('runtime')/'upgrade-backups'/('before-'+now().replace(':','-')+'.zip')
    target.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED) as z:
        z.write(c.path,'config.json')
        for p in c.directory('data').rglob('*.json'):
            z.write(p,p.relative_to(c.root).as_posix())
        for p in (c.directory('vault')/'.obsidian').rglob('*'):
            if p.is_file():z.write(p,p.relative_to(c.root).as_posix())
    print(target)
elif a.package:
    package=Path(a.package).resolve()
    if not (package/'SKILL.md').is_file():raise ValueError('Invalid skill package')
    c.value['installation_root']=str(package)
    write_json(c.path,c.value)
    print('Updated code location; research files retained')
