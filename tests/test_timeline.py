from copy import deepcopy
import json
import pytest
from research_memory.storage import digest, encode, read_json, write_json, file_hash, Conflict
from research_memory.timeline import build_projection, public_body, publish_projection, annotate, refresh_if_present
from research_memory.knowledge import Knowledge


GRAPH = {'project_id': 'archive', 'nodes': [], 'edges': []}


def event(i, text='研究内容', **fields):
    e = dict(event_id=f'e{i}', project_id='archive', research_project_id='p', workstream_id='b', session_id='s',
             kind='message', author='user', payload={'text': text}, source='test', source_sequence=i,
             occurred_at=f'2026-09-01T00:{i % 60:02}:00Z')
    e.update(fields)
    return {'event': e, 'content_hash': digest(encode(e)), 'captured_at': '2026-09-16T00:00:00Z'}


def rows(events, graph=None, **kwargs):
    p, b = build_projection(events, graph or GRAPH, **kwargs)
    return [r for s in p['sessions'] for r in s['rows']], p, b


def test_unorganized_messages_and_consecutive_roles_are_preserved():
    r, p, _ = rows([event(3, author='assistant'), event(2), event(1)])
    assert [x['id'] for x in r] == ['e1', 'e2', 'e3']
    assert p['coverage']['pending'] == 3
    assert not any(x['organized'] for x in r)


@pytest.mark.parametrize('text,folded', [('继续', True), ('检查错误并修正', True), ('继续，并检查温度升高是否导致漂移', False), ('好的，但条件A尚未成立', False)])
def test_only_whole_control_messages_fold(text, folded):
    assert rows([event(1, text)])[0][0]['folded'] == folded


def test_unreviewed_commentary_is_visible_and_private_channels_are_excluded():
    public = event(1, payload={'content': [{'type': 'output_text', 'text': '失败可能说明温度条件不成立'}], 'channel': 'commentary'})
    hidden = event(2, payload={'text': 'private', 'channel': 'analysis'})
    r, _, _ = rows([public, hidden])
    assert len(r) == 1 and not r[0]['folded']


def test_source_sequence_overrides_clock_regression_and_equal_timestamps():
    a, b = event(1), event(2, occurred_at='2020-01-01T00:00:00Z')
    r, _, _ = rows([b, a, deepcopy(a)])
    assert [x['id'] for x in r] == ['e1', 'e2']


def test_missing_time_not_replaced_by_import_time_and_sessions_overlap():
    r, p, _ = rows([event(1), event(3), event(2, session_id='parallel'), event(4, session_id='unknown', occurred_at=None, source_sequence=None)])
    assert p['sessions'][0]['overlaps'] == ['parallel']
    assert p['sessions'][-1]['start'] is None
    assert r[-1]['order_uncertain'] and r[-1]['occurred_at'] is None


def test_calls_pair_only_by_explicit_identifier():
    a = event(1, kind='tool_call', payload={'call_id': 'c', 'name': 'test'})
    b = event(2, kind='tool_result', payload={'call_id': 'c', 'exit_code': 1})
    c = event(3, kind='tool_result', payload={'text': 'unpaired'})
    r, _, _ = rows([a, b, c])
    assert r[0]['paired_ids'] == ['e2'] and r[1]['failed']
    assert r[0]['role'] == 'process'
    assert not r[2]['paired_ids']


def test_excerpt_must_be_exact_and_does_not_establish_authorship():
    e = event(1, '条件A才支持该假设。', author='assistant')
    graph = dict(GRAPH, nodes=[{'id': 'idea', 'authors': ['user', 'assistant'], 'sources': [{'event_id': 'e1', 'quote': '条件A才支持该假设。'}]}])
    annotations = {'e1': {'source_hash': e['content_hash'], 'excerpt': '支持该假设。'}}
    r, _, _ = rows([e], graph, annotations=annotations)
    assert r[0]['preview'] == '支持该假设。' and r[0]['role'] == 'assistant' and r[0]['knowledge'] == ['idea']
    annotations['e1']['excerpt'] = 'invented'
    assert rows([e], graph, annotations=annotations)[1]['issues']


def test_attachments_and_public_conditions_survive():
    b = public_body(event(1, payload={'content': [{'type': 'input_image', 'reference': 'host-id', 'availability': 'host_reference'}], 'conditions': ['A']})['event'])
    assert b['attachments'][0]['reference'] == 'host-id' and b['context']['conditions'] == ['A']


def test_hash_guarded_annotations_do_not_acknowledge_pending(store, event):
    event_id = store.capture(event)
    envelope = store.get(event_id)
    batch = {'processor': 'test', 'expected_version': 0, 'events': [{'event_id': event_id, 'source_hash': envelope['content_hash'], 'excerpt': event['payload']['text'], 'classification': 'substantive'}]}
    annotate(store, batch)
    assert len(store.pending()) == 1
    with pytest.raises(Conflict):
        annotate(store, batch)
    batch['expected_version'] = 1; batch['events'][0]['source_hash'] = 'wrong'
    with pytest.raises(ValueError):
        annotate(store, batch)


def test_chunks_are_bounded_tool_payloads_deferred_and_originals_unchanged(store, event):
    k = Knowledge(store)
    write_json(k.vault / 'System/research-graph.json', dict(GRAPH, project_id=store.config.project_id))
    for i in range(205):
        store.capture(dict(event, source_id=str(i), source_sequence=i))
    tool = dict(event, source_id='tool', kind='tool_result', payload={'output': 'huge-' * 10000})
    id = store.capture(tool)
    before = file_hash(store.events / (id + '.json'))
    first = publish_projection(k); index = read_json(first['path'])
    assert len(index['sessions'][0]['chunks']) == 3
    for path in index['sessions'][0]['chunks']:
        assert len(read_json(k.vault / path)) <= 100
    assert 'huge-' not in json.dumps(index)
    assert file_hash(store.events / (id + '.json')) == before
    assert publish_projection(k)['revision'] == first['revision']
    original = (k.vault / 'System/research-timeline.json').read_bytes()
    (store.events / (id + '.json')).write_text('{}')
    refresh_if_present(store)
    assert (k.vault / 'System/research-timeline.json').read_bytes() == original
    assert read_json(store.data / 'health/timeline.json')['state'] == 'stale'


def test_ten_thousand_records_have_stable_identity_and_no_omissions():
    items = [event(i, author='assistant' if i % 2 else 'user') for i in range(10000)]
    r, _, _ = rows(items)
    assert len(r) == len({x['id'] for x in r}) == 10000
    assert r[-1]['source_sequence'] == 9999


def test_curated_revision_navigation_is_bound_to_the_source():
    e=event(1, '修正：必须保留原始记录')
    annotations={'e1':{'source_hash':e['content_hash'],'milestone':'revision'}}
    assert rows([e],annotations=annotations)[0][0]['milestone']=='revision'
    annotations['e1']['source_hash']='stale'
    assert rows([e],annotations=annotations)[0][0]['milestone'] is None
