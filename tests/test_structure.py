from copy import deepcopy
import pytest
import yaml

from research_memory.storage import atomic, Conflict, file_hash, read_json, write_json
from research_memory.knowledge import Knowledge
from research_memory.continuity import Continuity
from research_memory.research_projects import ResearchProjects
from research_memory.structure_migration import StructureMigration
from research_memory.graph_view import build_projection
from research_memory.readability import ViewPaths
from research_memory.obsidian import Obsidian
from research_memory.projects import enabled, resolve
from test_readability_migration import setup_pair
from test_knowledge import note


def test_independent_view_publishers_keep_both_maps_and_detect_collision(store, event):
    k, eid, _, _ = migrate(store, event)
    first, second = ViewPaths(store), ViewPaths(store)
    first.value['runs'] = {'run-one': '研究项目/科研记忆系统/知识记录/实验/运行一.md'}
    first.save()
    second.value['aliases']['old.md'] = ViewPaths(store).note('idea-a')
    second.save()
    assert ViewPaths(store).value['runs'] == first.value['runs']
    assert 'old.md' in ViewPaths(store).value['aliases']
    a, b = ViewPaths(store), ViewPaths(store)
    a.value['runs']['run-two'] = '研究项目/科研记忆系统/知识记录/实验/同名.md'
    b.value['runs']['run-three'] = a.value['runs']['run-two']
    a.save()
    with pytest.raises(Conflict): b.save()
    assert 'run-two' in ViewPaths(store).value['runs']
    with pytest.raises(ValueError): ResearchProjects(store.config).register(store.config.project_id, '科研记忆系统', enabled=False)


def test_obsidian_base_normalization_is_equivalent_but_user_filters_are_protected(store, event):
    k, eid, _, _ = migrate(store, event)
    path=k.vault/'研究项目/科研记忆系统/研究记录表.base'
    value=yaml.safe_load(path.read_text(encoding='utf-8'))
    for view in value['views']: view['order']=[p.removeprefix('note.') for p in view['order']]
    normalized=yaml.safe_dump(value,allow_unicode=True,sort_keys=True).encode()
    atomic(path,normalized)
    k.views()
    assert path.read_bytes()==normalized
    value['filters']['and'].append('type == "idea"')
    edited=yaml.safe_dump(value,allow_unicode=True).encode();atomic(path,edited)
    with pytest.raises(Conflict): k.views()
    assert path.read_bytes()==edited
    assert list((store.data/'conflicts').glob('navigation-*.json'))


def migrate(store, event):
    k, eid = setup_pair(store, event)
    migration = StructureMigration(k)
    plan = migration.prepare()
    migration.apply(plan['plan'])
    return k, eid, migration, plan


def test_structure_preserves_science_raw_source_and_manual_canvas_and_rollback(store, event):
    k, eid = setup_pair(store, event)
    canvas = {'nodes': [{'id': 'manual', 'type': 'file', 'file': 'Notes/idea-a.md', 'x': 123, 'y': -532, 'width': 720, 'height': 460}], 'edges': []}
    write_json(k.vault / 'Graphs/我的布局.canvas', canvas)
    baseline = {p.relative_to(store.config.root).as_posix(): p.read_bytes() for p in k.vault.rglob('*') if p.is_file()}
    original = {n['id']: deepcopy(n) for n in k.records()}
    raw = file_hash(store.events / (eid + '.json'))
    m = StructureMigration(k); plan = m.prepare()
    assert not ResearchProjects(store.config).active
    m.apply(plan['plan'])
    for n in k.records():
        for key in ('id', 'version', 'body', 'authors', 'sources', 'relations', 'conditions', 'human_review', 'evidence_status'):
            assert n.get(key) == original[n['id']].get(key)
        assert n['path'].startswith('研究项目/科研记忆系统/知识记录/')
    assert file_hash(store.events / (eid + '.json')) == raw
    updated = read_json(k.vault / '研究项目/科研记忆系统/图谱/我的布局.canvas')
    assert updated['nodes'][0]['x'] == 123
    assert updated['nodes'][0]['file'] == ViewPaths(store).note('idea-a')
    assert Obsidian(store.config).path('Notes/idea-a.md') == ViewPaths(store).note('idea-a')
    assert not (k.vault / 'Research.md').exists()
    assert (k.vault / '科研工作台.md').exists()
    m.apply(plan['plan'], rollback=True)
    assert not ResearchProjects(store.config).active
    assert all((store.config.root / p).read_bytes() == data for p, data in baseline.items())
    assert {n['id']: n for n in k.records()} == original


def test_prepare_and_rollback_guard_human_changes(store, event):
    k, eid = setup_pair(store, event); m = StructureMigration(k); plan = m.prepare()
    path = k.vault / 'Notes/idea-a.md'; original = path.read_bytes()
    atomic(path, original + b'\nHuman review\n')
    with pytest.raises(Conflict): m.apply(plan['plan'])
    assert not ResearchProjects(store.config).active
    atomic(path, original);m.apply(plan['plan'])
    migrated = k.vault / ViewPaths(store).note('idea-a')
    atomic(migrated, migrated.read_bytes() + b'\nLater review\n')
    with pytest.raises(Conflict): m.apply(plan['plan'], rollback=True)
    assert migrated.read_text(encoding='utf-8').endswith('Later review\n')


def test_same_title_two_projects_isolates_capture_resume_search_and_views(store, event):
    k, eid, _, _ = migrate(store, event)
    catalog = ResearchProjects(store.config)
    p = catalog.register('second-project', '第二个研究', '独立问题')
    continuity = Continuity(store)
    continuity.bind(store.config.root, 's2', 'second-main', '第二分支', True, 'second-project')
    e2 = dict(event, source_id='m2', session_id='s2', workstream_id='second-main')
    eid2 = store.capture(e2)
    candidate = note(eid2, 'second-idea');candidate.update(title='保留完整公开原文', workstream_id='second-main', research_project_id='second-project')
    saved = k.commit({'event_ids': [eid2], 'processor': 'fixture', 'research_project_id': 'second-project', 'notes': [candidate]})['notes'][0]
    assert saved['path'].startswith(p['path'] + '/知识记录/候选想法/')
    assert ViewPaths(store).note('idea-a') != saved['path']
    assert resolve(store.config, 'second-project')[1] == k.vault / p['path']
    assert 'sample-synthetic-noise' not in enabled(store.config)
    assert 'sample-synthetic-noise' in enabled(store.config, examples=True)
    resumed = continuity.bind(store.config.root, 's3', project='second-project')
    assert resumed['workstream_id'] == 'second-main'
    assert continuity.resume('second-main')['research_project_id'] == 'second-project'
    with pytest.raises(Conflict): store.capture(dict(e2, source_id='bad', research_project_id=catalog.default))
    with pytest.raises(Conflict): k.save(dict(candidate, id='idea-a'))
    assert store.get(eid2)['event']['research_project_id'] == 'second-project'


def test_all_views_share_status_and_incoming_direction_and_bm_predicate(store, event):
    k, eid, _, _ = migrate(store, event)
    graph = build_projection(k)
    question = next(n for n in graph['nodes'] if n['id'] == 'question-a')
    idea = next(n for n in graph['nodes'] if n['id'] == 'idea-a')
    text = (k.vault / question['path']).read_text(encoding='utf-8')
    assert '指向本条' in text and ' — 细化 → 本条' in text
    assert '问题 · 待继续' in text
    metadata = yaml.safe_load(text.split('---', 2)[1])
    assert metadata['display_status'] == question['display']['status']
    assert metadata['display_authors'] == question['display']['authors']
    from basic_memory.markdown.entity_parser import parse
    idea_text = (k.vault / idea['path']).read_text(encoding='utf-8')
    assert '- refines [[' in idea_text and ' (依据：保留完整条件)' in idea_text
    parsed = parse(idea_text)
    assert any(r.type == 'refines' and '保留完整条件' in r.context for r in parsed.relations)
    assert not any(r.type == 'refines' for r in parse(text).relations)
    base = yaml.safe_load((k.vault / '研究项目/科研记忆系统/研究记录表.base').read_text(encoding='utf-8'))
    assert base['properties']['note.display_status']['displayName'] == '当前状态'
    assert len(base['views']) == 7


def test_new_relation_refreshes_incoming_without_overwriting_human_text(store, event):
    k, eid, _, _ = migrate(store, event)
    q = next(n for n in k.records() if n['id'] == 'question-a')
    human = (k.vault / q['path']).read_bytes() + '\n人工补充条件。\n'.encode()
    atomic(k.vault / q['path'], human)
    c = note(eid, 'additional');c['relations'] = [{'type': 'extends', 'target': q['id'], 'basis': '新分支'}]
    k.commit({'event_ids': [eid], 'processor': 'fixture-new', 'notes': [c]})
    assert (k.vault / q['path']).read_bytes() == human
    assert (store.data / 'conflicts/view-question-a.json').exists()
    assert next(n for n in build_projection(k)['nodes'] if n['id']==q['id'])['needs_reconciliation']


def test_interrupted_structure_is_unknown_and_not_replayed(store, event, monkeypatch):
    k, eid = setup_pair(store, event); m = StructureMigration(k); plan = m.prepare()
    import research_memory.structure_migration as module
    original = module.atomic
    count = 0
    def failing(path, data):
        nonlocal count
        count += 1
        if count == 4: raise OSError('power loss')
        return original(path, data)
    monkeypatch.setattr(module, 'atomic', failing)
    with pytest.raises(OSError): m.apply(plan['plan'])
    assert read_json(store.config.root / plan['plan'])['state'] == 'unknown'
    with pytest.raises(Conflict): m.apply(plan['plan'])
    monkeypatch.setattr(module, 'atomic', original)
    m.apply(plan['plan'], rollback=True)
    assert file_hash(k.vault / 'Notes/idea-a.md') == next(n for n in k.records() if n['id']=='idea-a')['published_hash']
