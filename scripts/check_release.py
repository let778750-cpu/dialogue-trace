"""Verify source distribution hashes and relative Markdown links using stdlib only."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
TOP = {'AGENTS.md', 'SKILL.md', 'README.md', 'README.zh-CN.md', 'VALIDATION.md',
       'VALIDATION.zh-CN.md', 'LICENSE', 'THIRD_PARTY.md', 'CONTRIBUTING.md',
       'pyproject.toml', 'config.example.json', '.gitignore', '.gitattributes'}
FOLDERS = ['src', 'tests', 'scripts', 'references', 'agents', 'docs', 'assets',
           'integrations', 'tools/obsidian/graph', '.github']
SUFFIXES = {'.py', '.md', '.json', '.yaml', '.yml', '.js', '.cjs', '.css', '.ps1', '.txt', '.jpg', '.png'}


def selected_files():
    files = {name for name in TOP if (ROOT/name).is_file()}
    for folder in FOLDERS:
        for path in (ROOT/folder).rglob('*'):
            generated = any(part == '__pycache__' or part.endswith('.egg-info') for part in path.parts)
            if path.is_file() and not generated and (path.suffix in SUFFIXES or path.name == 'LICENSE'):
                files.add(path.relative_to(ROOT).as_posix())
    return sorted(files)


def hashes():
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in selected_files()}


def check_links(names):
    issues = []
    for name in names:
        if not name.endswith('.md'):
            continue
        text = (ROOT/name).read_text(encoding='utf-8-sig')
        text = re.sub(r'```[\s\S]*?```', '', text)
        for target in re.findall(r'!?\[[^\]]*\]\(([^\n)]+)\)', text):
            target = target.strip('<>').split('#')[0]
            if not target or re.match(r'[A-Za-z][A-Za-z+.-]*:', target):
                continue
            path = ((ROOT/name).parent/unquote(target)).resolve()
            if not path.is_relative_to(ROOT) or not path.exists():
                issues.append(f'{name}: broken or external local link: {target}')
    return issues


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--write', action='store_true'); args = parser.parse_args()
    path = ROOT/'release-manifest.json'
    current = hashes()
    issues = check_links(current)
    if issues:
        raise SystemExit('\n'.join(issues))
    if args.write:
        manifest = dict(release='0.8.0-preview.2', skill='research-memory', python='0.8.0a1',
                        obsidian='0.8.0', private_data_included=False,
                        source_license='AGPL-3.0-only; see per-component exceptions', files=current)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    else:
        recorded = json.loads(path.read_text(encoding='utf-8'))['files']
        mismatched = [name for name in set(current)|set(recorded) if current.get(name)!=recorded.get(name)]
        if mismatched:
            raise SystemExit('Release manifest mismatch: '+', '.join(sorted(mismatched)))
    print(f'PASS: {len(current)} files; hashes and relative documentation links verified.')


if __name__ == '__main__':
    main()
