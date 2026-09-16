"""Rebuildable, source-ordered public event projection. Never acknowledges events."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import heapq
import re

from .storage import atomic, digest, encode, now, read_json, write_json

PRIVATE = {'analysis', 'justify', 'confidence', 'summary', 'reasoning', 'system', 'developer'}
KINDS = {'message', 'tool_call', 'tool_result', 'run_intent', 'run_started', 'run_finished', 'source', 'decision', 'lifecycle'}
CONTROL = re.compile(r'^(?:请)?(?:继续|继续执行|继续推进|开始执行|检查错误并修正|检查并修正|执行)[。！!\s]*$')
ENVIRONMENT = re.compile(r'^\s*<environment_context>[\s\S]*</environment_context>\s*$')
HOST_BLOCKS = re.compile(r'(?:\s*<recommended_plugins>[\s\S]*?</recommended_plugins>|\s*# AGENTS\.md instructions\s*<INSTRUCTIONS>[\s\S]*?</INSTRUCTIONS>|\s*<environment_context>[\s\S]*?</environment_context>)+\s*')


def classify(event, text):
    """Conservative display classification, independent of the model-facing role."""
    if event.get('kind') != 'message':
        return 'technical'
    payload = event.get('payload') or {}
    if ENVIRONMENT.fullmatch(text):
        return 'environment'
    if text.lstrip().startswith(('<recommended_plugins>', '# AGENTS.md instructions')) and HOST_BLOCKS.fullmatch(text):
        return 'environment'
    if payload.get('origin') in ('environment', 'host_environment') and not text.strip():
        return 'environment'
    return 'technical' if CONTROL.fullmatch(text.strip()) else 'research'


def stamp(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (TypeError, ValueError, AttributeError, OverflowError):
        return float('inf')


def public_body(event):
    """Only the already-public payload is projected; private channels stay excluded."""
    payload = event.get('payload') or {}
    if event.get('kind') not in KINDS or event.get('author') in PRIVATE or payload.get('channel') in PRIVATE:
        return None
    attachments = []
    if event['kind'] == 'message':
        parts = []
        for part in payload.get('content', []):
            if part.get('type') in {'input_text', 'output_text', 'text'}:
                parts.append(part.get('text', ''))
            elif part.get('type') in {'input_image', 'input_file', 'image', 'audio'}:
                attachments.append({k: part[k] for k in ('type', 'reference', 'attachment_hash', 'availability') if k in part})
        text = '\n'.join(parts) or payload.get('text') or payload.get('observation') or ''
        # Explicit public research observations keep their conditions and alternatives.
        extra = {k: payload[k] for k in ('conditions', 'alternatives', 'verification_plan', 'references') if payload.get(k)}
        return {'text': str(text), 'attachments': attachments, 'context': extra}
    import json
    return {'text': json.dumps(payload, ensure_ascii=False, indent=2), 'attachments': [], 'context': {}}


def source_order(rows):
    """Merge source streams by their next event, preserving each stream's sequence."""
    streams = defaultdict(list)
    for row in rows:
        streams[(row['source_key'], isinstance(row.get('source_sequence'), (int, float)))].append(row)
    queues = []
    for key in sorted(streams):
        stream = streams[key]
        stream.sort(key=lambda r: ((r['source_sequence'] if key[1] else stamp(r['occurred_at'])), r['id']))
        queues.append(stream)
    heap = []
    for i, stream in enumerate(queues):
        heapq.heappush(heap, (stamp(stream[0]['occurred_at']), stream[0]['id'], i, 0))
    result = []
    while heap:
        _, _, i, j = heapq.heappop(heap)
        result.append(queues[i][j])
        if j + 1 < len(queues[i]):
            row = queues[i][j + 1]
            heapq.heappush(heap, (stamp(row['occurred_at']), row['id'], i, j + 1))
    return result


def build_projection(envelopes, graph, annotations=None, processed=(), gaps=()):
    annotations = annotations or {}
    links = defaultdict(list)
    quotes = defaultdict(list)
    for node in graph.get('nodes', []):
        for source in node.get('sources', []):
            event_id = source.get('event_id')
            if event_id:
                links[event_id].append(node['id'])
                if source.get('quote'):
                    quotes[event_id].append(source['quote'])
    sessions = defaultdict(list)
    bodies, seen, issues = {}, set(), []
    last_capture = None
    for envelope in envelopes:
        event = envelope['event']
        body = public_body(event)
        if body is None:
            continue
        event_id = event['event_id']
        if event_id in seen:
            continue
        seen.add(event_id)
        last_capture = max(last_capture or '', envelope.get('captured_at') or '')
        annotation = annotations.get(event_id, {})
        if annotation.get('source_hash') != envelope['content_hash']:
            annotation = {}
        excerpt = annotation.get('excerpt', '')
        if excerpt and excerpt not in body['text']:
            issues.append({'event_id': event_id, 'reason': 'annotation_excerpt_mismatch'})
            excerpt = ''
        if not excerpt:
            excerpt = next((q for q in quotes[event_id] if q in body['text']), '')
        kind = event['kind']
        classification = classify(event, body['text'])
        folded = classification != 'research'
        if annotation.get('classification') in {'substantive', 'process'}:
            folded = annotation['classification'] == 'process'
        payload = event.get('payload', {})
        status = payload.get('status') or payload.get('scientific_outcome')
        failed = status in {'failed', 'error', 'cancelled', 'interrupted'} or (isinstance(payload.get('exit_code'), int) and payload['exit_code'] != 0)
        author = str(event.get('author') or 'unknown')
        role = ('user' if author == 'user' else 'assistant' if author.startswith('assistant') else 'process') if kind == 'message' else 'process'
        if classification == 'environment':
            role = 'environment'
        preview = excerpt or body['text'][:1600]
        if kind != 'message':
            preview = payload.get('name') or payload.get('purpose') or {'tool_call': '工具调用', 'tool_result': '工具结果', 'run_intent': '实验运行', 'run_finished': '运行结果'}.get(kind, '公开过程记录')
        source_key = str(event.get('source', 'unknown')) + ':' + str(event.get('origin', {}).get('path', ''))
        row = {'id': event_id, 'source_hash': envelope['content_hash'], 'kind': kind, 'role': role, 'author': author,
               'project': event.get('research_project_id') or event.get('project_id'), 'branch': event['workstream_id'] or '__unassigned__',
               'session': event['session_id'], 'source': event.get('source'), 'source_key': source_key,
               'occurred_at': event.get('occurred_at'), 'captured_at': envelope.get('captured_at'),
               'source_sequence': event.get('source_sequence'), 'origin': event.get('origin'),
               'preview': preview, 'excerpt': bool(excerpt), 'folded': folded, 'failed': bool(failed), 'classification': classification,
               'knowledge': sorted(set(links[event_id])), 'organized': event_id in processed,
               'call_id': payload.get('call_id'), 'phase': payload.get('phase') or payload.get('channel'),
               'order_uncertain': event.get('source_sequence') is None or stamp(event.get('occurred_at')) == float('inf'),
               'attachment_count': len(body['attachments']), 'milestone': annotation.get('milestone')}
        bodies[event_id] = dict(body, source_hash=envelope['content_hash'])
        sessions[(row['project'], row['branch'], row['session'])].append(row)
    grouped = []
    for (project, branch, session_id), rows in sessions.items():
        rows = source_order(rows)
        known_times = [r['occurred_at'] for r in rows if stamp(r['occurred_at']) != float('inf')]
        calls = defaultdict(list)
        for row in rows:
            if row['call_id']:
                calls[row['call_id']].append(row['id'])
        for row in rows:
            row['paired_ids'] = [i for i in calls.get(row['call_id'], []) if i != row['id']]
        grouped.append({'id': session_id, 'key': digest(encode([project, branch, session_id]))[:24],
                        'project': project, 'branch': branch, 'start': min(known_times, key=stamp) if known_times else None,
                        'end': max(known_times, key=stamp) if known_times else None, 'overlaps': [], 'rows': rows})
    grouped.sort(key=lambda s: (stamp(s['start']), s['key']))
    for i, session in enumerate(grouped):
        for other in grouped[:i]:
            if (session['project'], session['branch']) == (other['project'], other['branch']) and session['start'] and other['end'] and stamp(session['start']) <= stamp(other['end']):
                session['overlaps'].append(other['id'])
                other['overlaps'].append(session['id'])
    projection = {'schema_version': 1, 'reading_mode': 'research', 'project_id': graph['project_id'], 'default_project_id': graph.get('default_project_id', graph['project_id']),
                  'projects': graph.get('projects', []), 'branches': graph.get('branches', []), 'sessions': grouped,
                  'knowledge': graph.get('nodes', []), 'relations': graph.get('edges', []), 'issues': issues,
                  'coverage': {'events': len(seen), 'organized': len(seen.intersection(processed)),
                               'pending': len(seen.difference(processed)), 'last_captured_at': last_capture,
                               'gaps': list(gaps), 'host_live_coverage': 'not_verified'}}
    return projection, bodies


def publish_projection(knowledge, target_vault=None):
    """Publish content-addressed payloads first, then atomically switch the index."""
    from .research_projects import ResearchProjects, SYSTEM
    store = knowledge.store
    projects = ResearchProjects(store.config)
    from .research import ResearchService
    service = ResearchService(store)
    service.sync_catalog()
    vault = target_vault or knowledge.vault
    system = SYSTEM if projects.active else 'System'
    with store.lock('timeline-projection'):
        graph = read_json(knowledge.vault / system / 'research-graph.json')
        if not graph:
            raise ValueError('Build the research graph projection before the timeline')
        with store.db() as db:
            rows = db.execute('SELECT event_id,workstream FROM events ORDER BY position').fetchall()
            processed = {r['event_id'] for r in db.execute('SELECT event_id FROM processed')}
        envelopes = []
        for row in rows:
            envelope = store.get(row['event_id'])
            # Ownership corrections are projections, never edits of immutable archive fields.
            event = dict(envelope['event'], research_project_id=projects.event_project(envelope['event']),
                         workstream_id=row['workstream'] or None)
            envelopes.append(dict(envelope, event=event))
        annotations = read_json(store.data / 'timeline-annotations.json', {}).get('events', {})
        gaps = [{'state': d.get('state'), 'checked_at': d.get('checked_at'), 'remaining_bytes': d.get('remaining_bytes', 0)}
                for p in (store.data / 'gaps').glob('*.json') if (d := read_json(p, {}))]
        projection, bodies = build_projection(envelopes, graph, annotations, processed, gaps)
        state = service.state()
        projection['research_version'] = state['version']
        projection['progress'] = service.progress()
        projection['workstreams'] = service.branches()
        projection['proposals'] = list(state['proposals'].values())
        projection['history'] = state['history'][-30:]
        projection['runs'] = []
        from .runs import Runs
        for run in Runs(store).reconcile():
            intent = read_json(Runs(store).path(run['run_id']) / 'intent.json')
            projection['runs'].append(dict(run, project=projects.run_project(intent), branch=projects.run_workstream(intent),
                                           purpose=intent['spec']['purpose']))
        for session in list(projection['sessions']):
            for row in list(session['rows']):
                assignment = state['assignments'].get(row['id'], {})
                for branch in assignment.get('references', []):
                    if branch == row['branch']:
                        continue
                    key = digest(encode([row['project'], branch, row['session']]))[:24]
                    target = next((s for s in projection['sessions'] if s['key'] == key), None)
                    if target is None:
                        target = dict(session, key=key, branch=branch, rows=[], chunks=[])
                        projection['sessions'].append(target)
                    ref = dict(row, id='ref_'+digest(encode([row['id'], branch]))[:40], source_event_id=row['id'], branch=branch,
                               primary_branch=row['branch'], reference=True)
                    target['rows'].append(ref)
                    bodies[ref['id']] = bodies[row['id']]
        for session in projection['sessions']:
            session['rows'] = source_order(session['rows'])
        def put(value, folder):
            content = encode(value)
            path = system + '/timeline/' + folder + '/' + digest(content) + '.json'
            if not (vault / path).is_file():
                atomic(vault / path, content)
            return path
        for session in projection['sessions']:
            session['chunks'] = []
            for offset in range(0, len(session['rows']), 100):
                batch = session['rows'][offset:offset + 100]
                chunk = {}
                for row in batch:
                    body = bodies[row['id']]
                    if row['kind'] != 'message':
                        row['body_path'] = put(body, 'process')
                    else:
                        chunk[row['id']] = body
                path = put(chunk, 'messages')
                search_path = put({row['id']: bodies[row['id']]['text'] for row in batch}, 'search')
                session['chunks'].append(path)
                for row in batch:
                    row['search_path'] = search_path
                    if row['kind'] == 'message':
                        row['body_path'] = path
            session['count'] = len(session['rows'])
        projection['revision'] = digest(encode(projection))
        projection['generated_at'] = now()
        index_path = vault / system / 'research-timeline.json'
        current = read_json(index_path, {})
        if current.get('revision') != projection['revision']:
            if current:
                write_json(vault / system / 'research-timeline.previous.json', current)
            write_json(index_path, projection)
        return {'path': str(index_path), 'revision': projection['revision'], 'events': projection['coverage']['events'],
                'sessions': len(projection['sessions']), 'issues': projection['issues']}


def refresh_if_present(store):
    """Capture succeeds even if display rebuilding fails; retain the previous view."""
    from .knowledge import Knowledge
    from .research_projects import ResearchProjects, SYSTEM
    system = SYSTEM if ResearchProjects(store.config).active else 'System'
    if not (store.config.directory('vault') / system / 'research-timeline.json').is_file():
        return
    try:
        result = publish_projection(Knowledge(store))
        write_json(store.data / 'health/timeline.json', {'state': 'ready', 'at': now(), **result})
    except Exception as error:
        write_json(store.data / 'health/timeline.json', {'state': 'stale', 'at': now(), 'error': str(error)})


def annotate(store, batch):
    """Versioned, hash-bound editorial annotations; does not mark events processed."""
    from .storage import Conflict
    path = store.data / 'timeline-annotations.json'
    with store.lock('timeline-annotations'):
        current = read_json(path, {'version': 0, 'events': {}})
        if batch.get('expected_version') != current['version']:
            raise Conflict('Timeline annotation version changed')
        if not batch.get('processor') or len(batch.get('events', [])) > 50:
            raise ValueError('Annotations require a processor and at most 50 inspected events')
        for item in batch.get('events', []):
            envelope = store.get(item['event_id'])
            body = public_body(envelope['event'])
            if not body or envelope['content_hash'] != item.get('source_hash'):
                raise ValueError('Annotation source hash mismatch')
            if item.get('excerpt') and item['excerpt'] not in body['text']:
                raise ValueError('Excerpt must be an exact public source substring')
            if item.get('classification') not in {None, 'process', 'substantive'}:
                raise ValueError('Unknown timeline classification')
            if item.get('milestone') not in {None, 'question', 'revision', 'decision', 'result'}:
                raise ValueError('Unknown timeline milestone')
            current['events'][item['event_id']] = {k: item[k] for k in ('source_hash', 'excerpt', 'classification', 'milestone') if k in item}
        current.update(version=current['version'] + 1, processor=batch['processor'], at=now())
        write_json(store.data / 'timeline-annotation-history' / (str(current['version']) + '.json'), current)
        write_json(path, current)
    refresh_if_present(store)
    return {'version': current['version'], 'annotated': len(batch.get('events', []))}
