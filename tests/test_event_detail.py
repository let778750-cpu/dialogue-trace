import json
import pytest
from research_memory.capture import Transcript, public_item
from research_memory.event_detail import inspect_event
from research_memory.timeline import classify
from research_memory.research import ResearchService
from research_memory.continuity import Continuity


def test_typed_tool_details_keep_exact_payload_and_unknown_metrics(store,event):
    call=store.capture(dict(event, source_id='call',kind='tool_call',payload={'call_id':'c','name':'measure','arguments':'{ "sample": 1 }'}))
    result=store.capture(dict(event,source_id='result',kind='tool_result',payload={'call_id':'c','output':'negative result','status':'failed'}))
    d=inspect_event(store,call)
    assert d['kind']=='tool' and d['inputs'][0]['value']=='{ "sample": 1 }'
    assert d['outputs'][0]['event_id']==result
    assert d['timing']=={} and d['usage']=={} and d['schemas']==[]
    assert d['status']=='not_recorded'
    store.capture(dict(event,source_id='second-call',kind='tool_call',payload={'call_id':'c','name':'other'}))
    assert inspect_event(store,call)['ambiguous_call']
    assert inspect_event(store,call)['outputs']==[]


def test_environment_envelopes_preserve_mixed_user_requests(store,event):
    text='<recommended_plugins>x</recommended_plugins># AGENTS.md instructions\n<INSTRUCTIONS>x</INSTRUCTIONS><environment_context>shell</environment_context>'
    assert classify(event,text)=='environment'
    assert classify(event,text+'\n请分析漂移参数')=='research'
    id=store.capture(dict(event,payload={'text':text}))
    assert inspect_event(store,id)['kind']=='context'


def test_compaction_boundary_never_copies_private_summary(store,event,tmp_path):
    Continuity(store).bind(store.config.root,'test-session','system-development',create=True)
    path=tmp_path/'transcript.jsonl'
    path.write_text(json.dumps({'type':'compacted','payload':{'summary':'private summary','replacement_history':[]},'timestamp':'2026-01-01T00:00:00Z'})+'\n')
    Transcript(store).ingest(path,'test-session','system-development')
    records=ResearchService(store).events()
    assert len(records)==1
    assert records[0]['event']['kind']=='lifecycle'
    assert 'private summary' not in json.dumps(records)
    assert public_item({'type':'reasoning','text':'private reasoning'}) is None


def test_read_receipt_cannot_consume_later_arrivals(store,event):
    Continuity(store).bind(store.config.root,'test-session','system-development',create=True)
    store.capture(event);s=ResearchService(store)
    first=s.delta('reader','system-development')
    later=store.capture(dict(event,source_id='later',payload={'text':'later finding'}))
    s.delta('reader','system-development',since=first['revision'],acknowledge=True)
    second=s.delta('reader','system-development')
    assert second['new_messages']==1
    with pytest.raises(ValueError,match='revision'):
        s.delta('reader','system-development',acknowledge=True)


def test_invalid_workstream_does_not_leave_catalog_entry(store,event):
    Continuity(store).bind(store.config.root,'test-session','system-development',create=True)
    s=ResearchService(store)
    with pytest.raises(ValueError):
        s.mutate('workstream.create',dict(request_id='bad',expected_version=0,id='invalid',name=' ',project=store.config.project_id))
    assert s.branch('invalid') is None
