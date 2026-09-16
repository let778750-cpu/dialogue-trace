from copy import deepcopy

import pytest

from research_memory.continuity import Continuity
from research_memory.research_projects import ResearchProjects
from research_memory.storage import Conflict, atomic, file_hash, write_json
from test_structure import migrate


def test_new_projects_create_only_used_folders_and_keep_desktop_preferences(store, event):
    knowledge, _, _, _ = migrate(store, event)
    projects = ResearchProjects(store.config)
    project = projects.register('new-study', '新的研究', '检验新的解释')
    root = projects.folder(project['id'])
    assert list(root.iterdir()) == []
    preferences = {}
    for name in ('bookmarks.json', 'workspace.json', 'workspaces.json', 'file-explorer.json'):
        path = knowledge.vault / '.obsidian' / name
        atomic(path, b'{"personal":true}')
        preferences[path] = path.read_bytes()
    knowledge.views()
    first = {p.relative_to(root): p.stat().st_mtime_ns for p in root.rglob('*') if p.is_file()}
    knowledge.views()
    assert {p.relative_to(root): p.stat().st_mtime_ns for p in root.rglob('*') if p.is_file()} == first
    assert not any(p.is_dir() and not any(p.iterdir()) for p in root.rglob('*'))
    assert not (root / '知识记录').exists()
    assert not (root / '图谱').exists()
    assert not (root / '附件').exists()
    assert all(p.read_bytes() == content for p, content in preferences.items())
    assert '新的研究' in (knowledge.vault / '科研工作台.md').read_text(encoding='utf-8')


def test_home_limits_recent_records_but_keeps_every_branch_step_and_full_table(store, event):
    knowledge, _, _, _ = migrate(store, event)
    c = Continuity(store)
    c.bind(store.config.root, 'other-session', 'other-branch', '另一研究分支', True)
    write_json(store.data / 'checkpoints/system-development.json', {'data': {'next_steps': ['核查所有条件']}})
    write_json(store.data / 'checkpoints/other-branch.json', {'data': {'next_steps': ['验证替代解释', '保留负结果']}})
    original = knowledge.records()
    template = next(n for n in original if n['type'] == 'idea')
    for i in range(7):
        item = deepcopy(template)
        item.update(id=f'recent-{i}', title=f'导航排序案例 {i}', updated_at=f'2026-09-{i+1:02d}T00:00:00+00:00')
        item.pop('path', None)
        knowledge.save(dict(item, expected_version=0))
    knowledge.views()
    path = knowledge.vault / '研究项目/科研记忆系统/项目首页.md'
    home = path.read_text(encoding='utf-8')
    assert '![[' not in home
    assert home.count('## 最近更新') == 1
    recent = home.split('## 最近更新', 1)[1]
    assert len([line for line in recent.splitlines() if line.startswith('- ')]) == 5
    expected = sorted(knowledge.records(), key=lambda n: (n['updated_at'], n['id']), reverse=True)[:5]
    assert all(n['title'] in recent for n in expected)
    assert '### 另一研究分支' in home
    assert all(step in home for step in ['核查所有条件', '验证替代解释', '保留负结果'])
    assert '研究记录表.base|全部研究记录' in home
    assert len(knowledge.records()) == len(original) + 7


def test_navigation_refresh_preserves_existing_science_and_manual_home(store, event):
    knowledge, _, _, _ = migrate(store, event)
    original = {n['id']: deepcopy(n) for n in knowledge.records()}
    hashes = {knowledge.vault / n['path']: file_hash(knowledge.vault / n['path']) for n in original.values()}
    knowledge.views()
    assert {n['id']: n for n in knowledge.records()} == original
    assert all(file_hash(p) == value for p, value in hashes.items())
    home = knowledge.vault / '研究项目/科研记忆系统/项目首页.md'
    human = home.read_bytes() + '\n人工下一步，不能覆盖。\n'.encode()
    atomic(home, human)
    with pytest.raises(Conflict):
        knowledge.views()
    assert home.read_bytes() == human


def test_examples_and_disabled_projects_stay_in_collapsed_maintenance(store, event):
    knowledge, _, _, _ = migrate(store, event)
    projects = ResearchProjects(store.config)
    projects.register('archived-study', '暂停的研究', enabled=False)
    knowledge.views()
    home = (knowledge.vault / '科研工作台.md').read_text(encoding='utf-8')
    research, maintenance = home.split('> [!info]- 示例与维护', 1)
    assert '合成噪声实验' not in research and '暂停的研究' not in research
    assert '合成噪声实验' in maintenance and '暂停的研究' in maintenance
    assert '（已停用）' in maintenance and '系统视图/记录状态' in maintenance
