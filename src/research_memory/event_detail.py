"""On-demand typed inspection of archived public events; no model inference."""
from .timeline import classify, public_body


def inspect_event(store, event_id):
    envelope = store.get(event_id)
    event = envelope['event']
    body = public_body(event)
    if body is None:
        raise ValueError('This event has no public inspectable content')
    payload = event.get('payload') or {}
    category = classify(event, body['text'])
    kind = ('context' if category == 'environment' else
            'user' if event['kind'] == 'message' and event['author'] == 'user' else
            'assistant' if event['kind'] == 'message' else
            'tool' if event['kind'] in {'tool_call', 'tool_result'} else 'lifecycle')
    call_id = payload.get('call_id') or payload.get('tool_use_id')
    related = []
    if kind == 'tool' and call_id:
        with store.db() as db:
            ids = [r[0] for r in db.execute('SELECT event_id FROM events WHERE session=? ORDER BY position', (event['session_id'],))]
        for id in ids:
            other = store.get(id)['event']
            p = other.get('payload') or {}
            if other['kind'] in {'tool_call', 'tool_result'} and (p.get('call_id') or p.get('tool_use_id')) == call_id:
                related.append(other)
    calls = [e for e in related if e['kind'] == 'tool_call']
    # An ID is necessary, but duplicate calls are not enough evidence to infer hierarchy.
    ambiguous = len(calls) > 1
    selected = [event] if ambiguous else related or [event]
    inputs, outputs, schemas = [], [], []
    for e in selected:
        p = e.get('payload') or {}
        if e['kind'] == 'tool_call':
            inputs.append(dict(event_id=e['event_id'], name=p.get('name') or p.get('tool_name'),
                               value=next((p[k] for k in ('arguments', 'input', 'action', 'tool_input') if k in p), None)))
        elif e['kind'] == 'tool_result':
            outputs.append(dict(event_id=e['event_id'], value=p.get('output', p.get('tool_response')), error=p.get('error')))
        if 'tool_schema' in p:
            schemas.append(dict(event_id=e['event_id'], value=p['tool_schema']))
    timing = {k: payload[k] for k in ('started_at', 'ended_at', 'duration_ms', 'ttft_ms', 'generation_ms') if k in payload}
    usage = {k: payload[k] for k in ('usage', 'token_count') if k in payload}
    return dict(kind=kind, classification=category, status=payload.get('status', 'not_recorded'),
                phase=payload.get('phase') or payload.get('channel'), preview=body,
                source=dict(event_id=event_id, source=event.get('source'), session=event['session_id'],
                            turn_id=event.get('turn_id'), sequence=event.get('source_sequence'),
                            occurred_at=event.get('occurred_at'), captured_at=envelope.get('captured_at'),
                            origin=event.get('origin'), source_hash=envelope['content_hash']),
                raw_public_event=event, inputs=inputs, outputs=outputs, schemas=schemas,
                timing=timing, usage=usage, timing_basis='explicit_source_fields_only',
                related_ids=[e['event_id'] for e in related], ambiguous_call=ambiguous,
                limitations=['Only archived public fields are shown. Missing values are unknown, not zero.',
                             'Raw is the normalized public event, not a complete model request or hidden reasoning.'])
