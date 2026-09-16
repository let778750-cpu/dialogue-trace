"""Versioned research ownership and progress. Public source envelopes never change."""
from copy import deepcopy
from pathlib import Path

from .storage import Conflict, digest, encode, file_hash, now, read_json, safe_id, write_json


def initial_state():
    return dict(schema_version=1, version=0, assignments={}, boundaries={}, proposals={},
                progress={}, requests={}, history=[])


def read_state(config):
    return read_json(config.directory('data') / 'research-state.json', initial_state())


def source_key(event):
    return str(event.get('source', '')) + ':' + str(event.get('origin', {}).get('path', ''))


def effective_branch(event, fallback, state):
    assignment = state['assignments'].get(event.get('event_id'))
    if assignment is not None:
        return assignment['workstream_id']
    seq = event.get('source_sequence')
    boundaries = [b for b in state['boundaries'].get(event.get('session_id'), []) if b['source_key'] == source_key(event)]
    if boundaries and not isinstance(seq, (int, float)):
        return None
    candidates = [b for b in boundaries if seq > b['after_sequence']]
    if candidates:
        return max(candidates, key=lambda b: b['after_sequence'])['workstream_id']
    if boundaries:
        return min(boundaries, key=lambda b: b['after_sequence']).get('previous_workstream', fallback)
    return fallback


class ResearchService:
    def __init__(self, store):
        self.store = store
        self.path = store.data / 'research-state.json'

    def state(self):
        return read_state(self.store.config)

    def events(self):
        with self.store.db() as db:
            ids = [r[0] for r in db.execute('SELECT event_id FROM events ORDER BY position')]
        return [self.store.get(i) for i in ids]

    def branches(self, project=None):
        from .continuity import Continuity
        from .research_projects import ResearchProjects
        projects = ResearchProjects(self.store.config)
        return [dict(v, id=k, project=projects.branch_project(k), name=v.get('name') or v.get('goal') or k,
                     status=v.get('status', 'active'), version=v.get('version', 0))
                for k, v in Continuity(self.store).registry()['branches'].items()
                if project is None or projects.branch_project(k) == project]

    def branch(self, id):
        return next((b for b in self.branches() if b['id'] == id), None)

    def _target(self, branch, project):
        if branch is None:
            return
        value = self.branch(branch)
        if not value or value['project'] != project:
            raise ValueError('Unknown workstream or cross-project route')

    def _sources(self, spec):
        ids = spec.get('event_ids', [])
        if not ids or len(ids) != len(set(ids)):
            raise ValueError('Supply distinct source event IDs')
        events = [self.store.get(i) for i in ids]
        hashes = spec.get('source_hashes', {})
        if any(hashes.get(e['event']['event_id']) != e['content_hash'] for e in events):
            raise Conflict('Source hashes changed or not provided')
        return events

    def _interval(self, spec):
        from .research_projects import ResearchProjects
        from .timeline import source_order
        sources = self._sources(spec)
        events = [e['event'] for e in sources]
        if len({e['session_id'] for e in events}) != 1 or any(e['kind'] != 'message' for e in events):
            raise ValueError('Select whole messages in one session')
        all_events = [e['event'] for e in self.events() if e['event']['session_id'] == events[0]['session_id']]
        ordered = source_order([dict(e, id=e['event_id'], source_key=source_key(e), occurred_at=e.get('occurred_at')) for e in all_events])
        messages = [e['event_id'] for e in ordered if e['kind'] == 'message']
        indexes = sorted(messages.index(e['event_id']) for e in events)
        if indexes != list(range(indexes[0], indexes[-1] + 1)):
            raise ValueError('Message selection must be contiguous')
        projects = ResearchProjects(self.store.config)
        owners = {projects.event_project(e) for e in events}
        if len(owners) != 1:
            raise ValueError('Cross-project move is not supported')
        project = owners.pop()
        self._target(spec.get('workstream_id'), project)
        for ref in spec.get('references', []):
            self._target(ref, project)
        # Calls made between selected messages and the next message follow this interval.
        first = next(i for i, e in enumerate(ordered) if e['event_id'] == messages[indexes[0]])
        next_message = messages[indexes[-1] + 1] if indexes[-1] + 1 < len(messages) else None
        end = next((i for i, e in enumerate(ordered) if e['event_id'] == next_message), len(ordered))
        selected = ordered[first:end]
        calls = {e.get('payload', {}).get('call_id') or e.get('payload', {}).get('tool_use_id')
                 for e in selected if e['kind'] == 'tool_call'} - {None}
        from collections import Counter
        call_counts = Counter(e.get('payload', {}).get('call_id') or e.get('payload', {}).get('tool_use_id')
                              for e in all_events if e['kind'] == 'tool_call')
        calls = {call for call in calls if call_counts[call] == 1}
        selected_ids = {e['event_id'] for e in selected}
        selected += [e for e in all_events if e['event_id'] not in selected_ids and e['kind'] == 'tool_result'
                     and (e.get('payload', {}).get('call_id') or e.get('payload', {}).get('tool_use_id')) in calls]
        return selected

    def mutate(self, operation, spec):
        request = safe_id(spec['request_id'])
        fingerprint = digest(encode([operation, spec]))
        with self.store.lock('research-state'):
            state = self.state()
            prior = state['requests'].get(request)
            if prior:
                if prior['fingerprint'] != fingerprint:
                    raise Conflict('Request ID reused with different content')
                result = dict(prior['result'], reused=True)
            else:
                if spec.get('expected_version') != state['version']:
                    error = Conflict(f"Research state version is {state['version']}; reload before editing")
                    error.mutation_state = "rejected"
                    raise error
                try:
                    result = self._apply(state, operation, spec)
                except (ValueError, Conflict) as exc:
                    if not operation.startswith('workstream.'):
                        exc.mutation_state = 'rejected'
                    raise
                state['version'] += 1
                result.update(version=state['version'], request_id=request)
                state['requests'][request] = dict(fingerprint=fingerprint, result=deepcopy(result))
                state['history'].append(dict(version=state['version'], operation=operation, request_id=request, at=now()))
                # Receipt and mutation have one atomic commit point.
                write_json(self.path, state)
        self.sync_catalog()
        from .timeline import refresh_if_present
        refresh_if_present(self.store)
        return result

    def _apply(self, state, operation, spec):
        if operation.startswith('workstream.'):
            from .continuity import Continuity
            from .research_projects import ResearchProjects
            id = safe_id(spec['id'])
            if operation not in {'workstream.create', 'workstream.update'}:
                raise ValueError('Unsupported workstream operation')
            if 'name' in spec and not str(spec['name']).strip():
                raise ValueError('A workstream needs a name')
            if 'status' in spec and spec['status'] not in {'active', 'paused', 'finished'}:
                raise ValueError('Invalid workstream status')
            continuity = Continuity(self.store)
            with self.store.lock('continuity'):
                reg = continuity.registry()
                old = reg['branches'].get(id)
                # Recover a crash after registry publication but before the shared receipt.
                if old and old.get('last_request') == spec['request_id']:
                    if old.get('last_fingerprint') != digest(encode([operation, spec])):
                        raise Conflict('Request ID reused with different content')
                    return {'workstream': dict(old, id=id)}
                if operation == 'workstream.create':
                    if old:
                        raise Conflict('Workstream ID already exists')
                    project = spec.get('project') or ResearchProjects(self.store.config).default
                    ResearchProjects(self.store.config).add_branch(id, project)
                    old = dict(created_at=now(), research_project_id=project, version=0)
                elif not old:
                    raise ValueError('Unknown workstream')
                elif spec.get('branch_version') != old.get('version', 0):
                    raise Conflict('Workstream version changed')
                status = spec.get('status', old.get('status', 'active'))
                if status not in {'active', 'paused', 'finished'}:
                    raise ValueError('Invalid workstream status')
                value = dict(old, name=spec.get('name', old.get('name', id)), goal=spec.get('goal', old.get('goal', '')),
                             status=status, version=old.get('version', 0)+1, updated_at=now(), last_request=spec['request_id'],
                             last_fingerprint=digest(encode([operation, spec])))
                if not str(value['name']).strip():
                    raise ValueError('A workstream needs a name')
                reg['branches'][id] = value
                if operation == 'workstream.create':
                    projects = ResearchProjects(self.store.config)
                    for workspace, branches in reg['workspaces'].items():
                        if any(projects.branch_project(b) == value['research_project_id'] for b in branches) and id not in branches:
                            branches.append(id)
                write_json(continuity.registry_path, reg)
                return {'workstream': dict(value, id=id)}
        if operation in {'route.propose', 'route.apply'}:
            selected = self._interval(spec)
            signature = digest(encode([spec['event_ids'], spec.get('workstream_id'), spec.get('references', [])]))
            if operation == 'route.propose':
                old = state['proposals'].get(signature)
                if old:
                    return {'proposal': old}
                value = dict(id=signature, status='pending', spec={k: v for k, v in spec.items() if k not in {'request_id', 'expected_version'}}, at=now())
                state['proposals'][signature] = value
                return {'proposal': value}
            before, after = {}, {}
            for e in selected:
                id = e['event_id']
                before[id] = deepcopy(state['assignments'].get(id))
                after[id] = dict(workstream_id=spec.get('workstream_id'), references=sorted(set(spec.get('references', [])) - {spec.get('workstream_id')}),
                                 source_hash=self.store.get(id)['content_hash'], request_id=spec['request_id'])
            state['assignments'].update(after)
            if signature in state['proposals']:
                state['proposals'][signature]['status'] = 'applied'
            for progress in state['progress'].values():
                if set(progress['event_ids']) & set(after):
                    progress['needs_review'] = True
            return {'event_ids': list(after), 'before': before, 'after': after}
        if operation == 'route.reject':
            proposal = state['proposals'][spec['proposal_id']]
            if proposal['status'] != 'pending':
                raise Conflict('Proposal already resolved')
            proposal['status'] = 'rejected'
            return {'proposal': proposal}
        if operation == 'route.undo':
            previous = state['requests'][spec['undo_request_id']]['result']
            if 'after' not in previous:
                raise ValueError('Only a route application can be undone')
            for id, value in previous['after'].items():
                if state['assignments'].get(id) != value:
                    raise Conflict('Later ownership changes prevent this undo')
            for id, value in previous['before'].items():
                if value is None:
                    state['assignments'].pop(id, None)
                else:
                    state['assignments'][id] = value
            for progress in state['progress'].values():
                if set(progress['event_ids']) & set(previous['after']):
                    progress['needs_review'] = True
            return {'undone': spec['undo_request_id'], 'event_ids': list(previous['after'])}
        if operation == 'binding.boundary':
            event = self.store.get(spec['after_event'])['event']
            if event['session_id'] != spec['session_id'] or not isinstance(event.get('source_sequence'), (int, float)):
                raise ValueError('Binding needs a source-sequenced event in the same session')
            from .research_projects import ResearchProjects
            from .continuity import Continuity
            self._target(spec['workstream_id'], ResearchProjects(self.store.config).event_project(event))
            boundary = dict(source_key=source_key(event), after_sequence=event['source_sequence'],
                            workstream_id=spec['workstream_id'], after_event=event['event_id'],
                            previous_workstream=Continuity(self.store).registry()['sessions'].get(spec['session_id']))
            rows = state['boundaries'].setdefault(spec['session_id'], [])
            if any(b['source_key'] == boundary['source_key'] and b['after_sequence'] == boundary['after_sequence'] for b in rows):
                raise Conflict('A binding already exists at this boundary')
            rows.append(boundary)
            return {'boundary': boundary}
        if operation == 'progress.publish':
            before = deepcopy(state['progress'].get(spec['id']))
            return {'progress': self._progress(state, spec), 'before_progress': before}
        if operation == 'progress.undo':
            previous = state['requests'][spec['undo_request_id']]['result']
            if 'before_progress' not in previous:
                raise ValueError('Only a recorded progress publication can be undone')
            published = previous['progress']
            current = state['progress'].get(published['id'])
            if current != published:
                raise Conflict('Later changes prevent this progress undo')
            if previous['before_progress'] is None:
                state['progress'].pop(published['id'])
            else:
                restored = deepcopy(previous['before_progress'])
                restored.update(version=published['version']+1, updated_at=now(), needs_review=True)
                state['progress'][published['id']] = restored
            return dict(undone=spec['undo_request_id'], progress_id=published['id'])
        raise ValueError('Unsupported research mutation: ' + operation)

    def _progress(self, state, spec):
        from .research_projects import ResearchProjects
        sources = self._sources(spec)
        projects = ResearchProjects(self.store.config)
        owner = projects.event_project(sources[0]['event'])
        if any(projects.event_project(e['event']) != owner for e in sources):
            raise ValueError('Progress must stay in one project')
        self._target(spec['workstream_id'], owner)
        if any(projects.event_workstream(e['event']) != spec['workstream_id'] for e in sources):
            raise Conflict('Progress sources must belong to the selected workstream')
        kind = spec['kind']
        if kind not in {'result', 'revision', 'decision', 'blocker', 'research_checkpoint', 'compute_checkpoint'}:
            raise ValueError('Invalid progress kind')
        id = safe_id(spec['id'])
        previous = state['progress'].get(id, {})
        if spec.get('progress_version', 0) != previous.get('version', 0):
            raise Conflict('Progress version changed')
        if previous and (previous['workstream_id'] != spec['workstream_id'] or previous.get('run_id') != spec.get('run_id')):
            raise Conflict('Progress identity cannot be reused for another workstream/run')
        anchor = spec.get('anchor_event_id') or spec['event_ids'][-1]
        if anchor not in spec['event_ids']:
            raise ValueError('Progress anchor must be a cited source')
        facts = {}
        if spec.get('run_id'):
            from .runs import Runs
            runs = Runs(self.store)
            run_id = spec['run_id']
            intent = read_json(runs.path(run_id) / 'intent.json', {})
            if not intent or projects.run_project(intent) != owner or projects.run_workstream(intent) != spec['workstream_id']:
                raise ValueError('Run is not in this research line')
            if not any(e['event'].get('payload', {}).get('run_id') == run_id for e in sources):
                raise ValueError('Cite an actual event from this run')
            result = read_json(runs.path(run_id) / 'result.json', {})
            facts = dict(runs.state(run_id), purpose=intent['spec']['purpose'], parameters=intent['spec']['parameters'],
                         artifacts=result.get('artifacts', {}))
            if spec.get('metrics_artifact'):
                artifact = spec['metrics_artifact']
                p = (runs.path(run_id) / artifact).resolve()
                if artifact not in facts['artifacts'] or not p.is_relative_to(runs.path(run_id).resolve()) or not p.is_file() or file_hash(p) != facts['artifacts'][artifact] or p.stat().st_size > 1024*1024:
                    raise ValueError('Metrics require an intact recorded JSON artifact under 1 MB')
                facts['metrics'] = read_json(p)
        if kind == 'research_checkpoint' and not all(k in spec for k in ('known', 'unknown', 'next_steps')):
            raise ValueError('Research checkpoint requires known, unknown and next_steps')
        if kind == 'compute_checkpoint':
            artifact = spec.get('checkpoint_artifact')
            if not facts or artifact not in facts.get('artifacts', {}) or facts.get('artifact_drift') or not spec.get('restore_conditions'):
                raise ValueError('Compute checkpoint needs a verified run artifact and restore conditions')
        value = {k: deepcopy(spec[k]) for k in ('id', 'kind', 'workstream_id', 'title', 'summary', 'event_ids', 'source_hashes', 'run_id',
                    'known', 'unknown', 'next_steps', 'conditions', 'limitations', 'checkpoint_artifact', 'restore_conditions') if k in spec}
        if not str(value.get('title', '')).strip():
            raise ValueError('Progress title is required')
        value.update(project=owner, facts=facts, anchor_event_id=anchor, version=previous.get('version', 0)+1,
                     updated_at=now(), interpretation_label='AI 归纳', needs_review=False)
        state['progress'][id] = value
        return value

    def sync_catalog(self):
        """Repairable derived index; a crash cannot lose an already committed route."""
        from .research_projects import ResearchProjects
        projects = ResearchProjects(self.store.config)
        state = self.state()
        if not state['version']:
            return
        envelopes = self.events()
        projects.call_owners = {}  # Rebuild without recycling a stale/ambiguous derived association.
        call_owners = {}
        call_counts = {}
        owners = {}
        for e in envelopes:
            ev = e['event']
            owners[ev['event_id']] = projects.event_workstream(ev)
            call = ev.get('payload', {}).get('call_id') or ev.get('payload', {}).get('tool_use_id')
            if ev['kind'] == 'tool_call' and call:
                call_owners[(ev['session_id'], call)] = owners[ev['event_id']]
                key = (ev['session_id'], call)
                call_counts[key] = call_counts.get(key, 0) + 1
        call_owners = {key:owner for key,owner in call_owners.items() if call_counts[key] == 1}
        with self.store.db() as db:
            for e in envelopes:
                ev = e['event']; id = ev['event_id']
                call = ev.get('payload', {}).get('call_id') or ev.get('payload', {}).get('tool_use_id')
                branch = owners[id]
                if ev['kind'] == 'tool_result' and id not in state['assignments']:
                    branch = call_owners.get((ev['session_id'], call), branch)
                db.execute('UPDATE events SET workstream=? WHERE event_id=?', (branch or '', id))
        write_json(self.store.data / 'call-ownership.json', {digest(encode(list(k))): v for k, v in call_owners.items()})

    def progress(self, workstream=None, project=None):
        rows = []
        for value in self.state()['progress'].values():
            if (workstream is not None and value['workstream_id'] != workstream) or (project and value['project'] != project):
                continue
            v = deepcopy(value)
            for id, expected in v['source_hashes'].items():
                try:
                    if self.store.get(id)['content_hash'] != expected:
                        v['needs_review'] = True
                except ValueError:
                    v['needs_review'] = True
            if v.get('run_id'):
                from .runs import Runs
                actual = Runs(self.store).state(v['run_id'])
                if actual.get('artifact_drift') or actual.get('status') != v.get('facts', {}).get('status'):
                    v['needs_review'] = True
                v['current_run_state'] = actual
            rows.append(v)
        return rows

    def search(self, query, workstream=None, project=None, technical=False, unassigned=False):
        from .timeline import public_body, classify
        from .research_projects import ResearchProjects
        projects = ResearchProjects(self.store.config)
        matches = []
        for envelope in self.events():
            e = envelope['event']; body = public_body(e)
            branch = projects.event_workstream(e)
            if not body or (project and projects.event_project(e) != project) or (unassigned and branch is not None) or (workstream and branch != workstream):
                continue
            if not technical and classify(e, body['text']) != 'research':
                continue
            at = body['text'].casefold().find(query.casefold())
            if at >= 0:
                matches.append(dict(event_id=e['event_id'], session_id=e['session_id'], workstream_id=branch,
                                    source_hash=envelope['content_hash'], excerpt=body['text'][max(0, at-35):at+160]))
        for p in self.progress(workstream, project):
            if not unassigned and query.casefold() in (p['title']+' '+p.get('summary', '')).casefold():
                matches.append(dict(progress_id=p['id'], event_id=p['anchor_event_id'], excerpt=p['title'], workstream_id=p['workstream_id']))
        return {'matches': matches[:100], 'total': len(matches), 'includes_technical': technical}

    def delta(self, session, workstream, since=None, acknowledge=False):
        from .research_projects import ResearchProjects
        from .timeline import public_body, classify
        self._target(workstream, ResearchProjects(self.store.config).branch_project(workstream))
        path = self.store.data / 'reading-cursors' / (digest(encode([session, workstream])) + '.json')
        if acknowledge:
            if not since:
                raise ValueError('A reading receipt requires the exact previously returned revision in since')
            snapshot = read_json(self.store.data / 'reading-snapshots' / (safe_id(since) + '.json'), {})
            if snapshot.get('workstream_id') != workstream:
                raise ValueError('Unknown reading snapshot for this workstream')
            with self.store.lock('reading-cursors'):
                write_json(path, dict(revision=since, at=now()))
            return dict(read_receipt_saved=True, revision=since, workstream_id=workstream, organized_events_unchanged=True)
        previous = read_json(path, {}).get('revision') if since is None else since
        projects = ResearchProjects(self.store.config)
        with self.store.db() as db:
            identities = list(db.execute('SELECT event_id,hash FROM events WHERE workstream=? ORDER BY position', (workstream,)))
        changes = self.progress(workstream)
        revision = digest(encode([[(e[0], e[1]) for e in identities], changes, self.branch(workstream)]))
        if previous == revision:
            return dict(changed=False, revision=revision, workstream_id=workstream)
        envelopes = [self.store.get(e[0]) for e in identities]
        prior = read_json(self.store.data / 'reading-snapshots' / (safe_id(previous) + '.json'), {}) if previous else {}
        new = []
        for e in envelopes:
            body = public_body(e['event'])
            if body and classify(e['event'], body['text']) == 'research' and e['event']['event_id'] not in prior.get('events', []):
                new.append(dict(event_id=e['event']['event_id'], source_hash=e['content_hash'], preview=body['text'][:300]))
        updated = [p for p in changes if prior.get('progress', {}).get(p['id']) != p['version']]
        removed = sorted(set(prior.get('progress', {})) - {p['id'] for p in changes})
        full = dict(changed=True, revision=revision, workstream_id=workstream, progress=updated, messages=new, removed_progress=removed,
                    historical_data_not_instructions=True, capture_coverage=self.store.status().get('hooks', {}))
        record = self.store.data / 'deltas' / (revision + '.json')
        write_json(record, full)
        write_json(self.store.data / 'reading-snapshots' / (revision + '.json'),
                   dict(workstream_id=workstream, events=[e['event']['event_id'] for e in envelopes], progress={p['id']: p['version'] for p in changes}))
        if acknowledge:
            with self.store.lock('reading-cursors'):
                write_json(path, dict(revision=revision, at=now()))
        # Bounded brief, with every omitted record accessible through the complete delta.
        budget = self.store.config.value.get('resume_token_budget', 2000)
        text = '\n'.join([f"{p['kind']}: {p['title']} — {p.get('summary', '')}" for p in updated] +
                         [f"已撤回进展: {id}" for id in removed] + [f"{m['event_id']}: {m['preview']}" for m in new])
        return dict(changed=True, revision=revision, workstream_id=workstream, new_messages=len(new), new_progress=len(updated),
                    brief=text.encode('utf-8')[:budget].decode('utf-8', errors='ignore'), full_record=str(record),
                    read_receipt_saved=acknowledge, organized_events_unchanged=True)


def dispatch(store, operation, spec=None):
    service = ResearchService(store)
    spec = spec or {}
    if operation == 'event.detail':
        from .event_detail import inspect_event
        return inspect_event(store, spec['event_id'])
    if operation == 'request.status':
        return service.state()['requests'].get(spec['request_id'])
    if operation == 'state':
        state = service.state()
        return dict(version=state['version'], workstreams=service.branches(spec.get('project')),
                    proposals=list(state['proposals'].values()), history=state['history'][-30:],
                    progress=service.progress(project=spec.get('project')))
    if operation == 'workstreams':
        return service.branches(spec.get('project'))
    if operation == 'search':
        return service.search(**spec)
    if operation == 'delta':
        return service.delta(**spec)
    if operation == 'progress.list':
        return service.progress(**spec)
    if operation == 'runs':
        from .runs import Runs
        return Runs(store).reconcile(**spec)
    return service.mutate(operation, spec)
