from copy import deepcopy
import pytest
from research_memory.storage import Conflict, read_json, write_json
from research_memory.continuity import Continuity
from research_memory.research import ResearchService, dispatch
from research_memory.research_projects import ResearchProjects
from research_memory.timeline import classify, public_body, publish_projection


def arrange(store, event):
    c = Continuity(store)
    c.bind(store.config.root,'test-session','system-development',create=True)
    c.bind(store.config.root,'second','alternative',create=True)
    ids=[]
    for i,text in enumerate(['最初的问题','继续，并检查温升是否导致漂移','我们需要改变方法']):
        ids.append(store.capture(dict(event,source_id=str(i),source_sequence=i,payload={'text':text})))
    return ids


def spec(store, ids, request='move', **kw):
    return dict(request_id=request,expected_version=ResearchService(store).state()['version'],event_ids=ids,
                source_hashes={id:store.get(id)['content_hash'] for id in ids},workstream_id='alternative',**kw)


def test_route_rebuild_idempotent_undo_and_raw_unchanged(store,event):
    ids=arrange(store,event); before=[store.get(id) for id in ids]
    service=ResearchService(store)
    request=spec(store,ids[1:])
    result=service.mutate('route.apply',request)
    assert service.mutate('route.apply',request)['reused']
    assert [e['event']['event_id'] for e in store.pending('alternative')]==ids[1:]
    assert [store.get(id) for id in ids]==before
    store.repair()
    assert len(store.pending('alternative'))==2
    service.mutate('route.undo',dict(request_id='undo',expected_version=result['version'],undo_request_id='move'))
    assert len(store.pending('system-development'))==3


def test_noncontiguous_and_stale_rejected(store,event):
    ids=arrange(store,event); service=ResearchService(store)
    with pytest.raises(ValueError,match='contiguous'):
        service.mutate('route.apply',spec(store,[ids[0],ids[2]]))
    first=spec(store,ids[:1]); stale=spec(store,ids[1:],'stale')
    service.mutate('route.apply',first)
    with pytest.raises(Conflict,match='version'):
        service.mutate('route.apply',stale)
    with pytest.raises(Conflict,match='Request ID'):
        service.mutate('route.apply',dict(first,workstream_id='system-development'))


def test_declined_suggestion_does_not_reappear(store,event):
    ids=arrange(store,event); service=ResearchService(store)
    result=service.mutate('route.propose',spec(store,ids[:1]))
    service.mutate('route.reject',dict(request_id='reject',expected_version=result['version'],proposal_id=result['proposal']['id']))
    duplicate=service.mutate('route.propose',spec(store,ids[:1],'again'))
    assert duplicate['proposal']['status']=='rejected'


def test_boundary_backfill_and_late_result(store,event):
    ids=arrange(store,event); service=ResearchService(store)
    call=store.capture(dict(event,source_id='call',source_sequence=1.1,kind='tool_call',author='assistant',payload={'call_id':'c','name':'measure'}))
    service.mutate('route.apply',spec(store,[ids[1]]))
    late=store.capture(dict(event,source_id='late',source_sequence=9,kind='tool_result',author='tool',payload={'call_id':'c','output':'3'}))
    service.sync_catalog()
    assert ResearchProjects(store.config).event_workstream(store.get(late)['event'])=='alternative'
    with pytest.raises(ValueError,match='after-event'):
        Continuity(store).bind(store.config.root,'test-session','alternative')
    Continuity(store).bind(store.config.root,'test-session','alternative',after_event=ids[2])
    future=store.capture(dict(event,source_id='future',source_sequence=10,payload={'text':'新讨论'}))
    assert ResearchProjects(store.config).event_workstream(store.get(future)['event'])=='alternative'
    # The importer may now pass the current binding, but the old source remains identical.
    original=store.get(ids[0])['event']; supplied={k:v for k,v in original.items() if k not in {'event_id','project_id'}}
    supplied['workstream_id']='alternative'
    assert store.capture(supplied)==ids[0]
    assert ResearchProjects(store.config).event_workstream(store.get(ids[0])['event'])=='system-development'
    backfill=store.capture(dict(event,source_id='missing-old',source_sequence=0.5,workstream_id='alternative',payload={'text':'补录早先条件'}))
    missing_sequence=store.capture(dict(event,source_id='missing-sequence',source_sequence=None,workstream_id='alternative',payload={'text':'位置未知'}))
    assert ResearchProjects(store.config).event_workstream(store.get(backfill)['event'])=='system-development'
    assert ResearchProjects(store.config).event_workstream(store.get(missing_sequence)['event']) is None


def test_environment_not_user_research_mixed_kept(store,event):
    assert classify(event,'<environment_context>powershell</environment_context>')=='environment'
    assert classify(event,'<environment_context>x</environment_context>\n温度漂移为什么变化？')=='research'
    assert classify(event,'继续')=='technical'
    assert classify(event,'可以')=='research'
    assert classify(event,'继续，并检查温升是否导致漂移')=='research'
    assert classify(event,'运行 python script.py 检验这个假设')=='research'


def test_search_technical_opt_in_and_unassigned(store,event):
    arrange(store,event)
    hidden=store.capture(dict(event,source_id='env',payload={'text':'<environment_context>powershell</environment_context>'}))
    unknown=store.capture(dict(event,source_id='unknown',workstream_id=None,research_project_id=store.config.project_id,payload={'text':'未知归属的问题'}))
    service=ResearchService(store)
    assert service.search('powershell')['total']==0
    assert service.search('powershell',technical=True)['matches'][0]['event_id']==hidden
    assert service.search('未知',unassigned=True)['matches'][0]['event_id']==unknown


def test_progress_version_sources_and_delta_do_not_acknowledge(store,event):
    ids=arrange(store,event); service=ResearchService(store)
    request=spec(store,[ids[0]],'progress')
    request.update(workstream_id='system-development',id='checkpoint-1',kind='research_checkpoint',title='研究断点',
                   summary='先检查温度控制',known=['问题已明确'],unknown=['原因待测'],next_steps=['采集对照数据'])
    service.mutate('progress.publish',request)
    before=store.status()['organized']
    delta=service.delta('second-window','system-development')
    service.delta('second-window','system-development',since=delta['revision'],acknowledge=True)
    assert delta['new_progress']==1
    assert not service.delta('second-window','system-development')['changed']
    assert service.delta('third-window','system-development')['changed']
    assert store.status()['organized']==before
    service.mutate('route.apply',spec(store,[ids[0]],'moved'))
    assert service.progress()[0]['needs_review']


def test_compute_checkpoint_cannot_be_invented(store,event):
    ids=arrange(store,event); service=ResearchService(store)
    request=spec(store,[ids[0]],'fake')
    request.update(workstream_id='system-development',id='fake-checkpoint',kind='compute_checkpoint',title='断点',checkpoint_artifact='checkpoint.bin',restore_conditions='resume')
    with pytest.raises(ValueError,match='verified'):
        service.mutate('progress.publish',request)


def test_progress_undo_preserves_history_and_announces_retraction(store,event):
    ids=arrange(store,event);service=ResearchService(store)
    request=spec(store,[ids[0]],'publish')
    request.update(id='result-one',kind='result',title='未成功的对照',summary='需继续核对',workstream_id='system-development')
    result=service.mutate('progress.publish',request)
    before=service.delta('reader','system-development')
    service.delta('reader','system-development',since=before['revision'],acknowledge=True)
    service.mutate('progress.undo',dict(request_id='undo-progress',expected_version=result['version'],undo_request_id='publish'))
    assert service.progress()==[]
    assert 'publish' in service.state()['requests']
    delta=service.delta('reader','system-development')
    assert '已撤回进展: result-one' in delta['brief']


def test_two_processes_conflict_without_losing_source_or_receipt(store,event):
    import json,os,subprocess,sys
    from concurrent.futures import ThreadPoolExecutor
    ids=arrange(store,event)
    requests=[spec(store,ids[:1],request='concurrent-'+str(i)) for i in range(2)]
    def invoke(request):
        return subprocess.run([sys.executable,'-m','research_memory.cli','--root',str(store.config.root),
                               'research','route.apply','--file','-'],input=json.dumps(request),text=True,
                               capture_output=True,encoding='utf-8',env=dict(os.environ,PYTHONUTF8='1'))
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(invoke,requests))
    assert sorted(r.returncode for r in results)==[0,1]
    assert len(ResearchService(store).state()['requests'])==1
    assert store.get(ids[0])['event']['workstream_id']=='system-development'


def test_duplicate_call_id_does_not_move_a_late_result(store,event):
    ids=arrange(store,event);s=ResearchService(store)
    store.capture(dict(event,source_id='call-a',source_sequence=0.2,kind='tool_call',payload={'call_id':'duplicate'}))
    store.capture(dict(event,source_id='call-b',source_sequence=1.2,kind='tool_call',payload={'call_id':'duplicate'}))
    late=store.capture(dict(event,source_id='late-result',source_sequence=5,kind='tool_result',payload={'call_id':'duplicate','output':'uncertain parent'}))
    s.mutate('route.apply',spec(store,ids[:1],'duplicate-test'))
    assert ResearchProjects(store.config).event_workstream(store.get(late)['event'])=='system-development'


def test_cross_reference_uses_stable_distinct_view_identity(store,event):
    ids=arrange(store,event); service=ResearchService(store)
    req=spec(store,[ids[0]],references=['system-development'])
    service.mutate('route.apply',req)
    from research_memory.knowledge import Knowledge
    Knowledge(store).views()
    result=publish_projection(Knowledge(store))
    data=read_json(result['path']);rows=[r for s in data['sessions'] for r in s['rows']]
    assert len({r['id'] for r in rows})==len(rows)
    assert next(r for r in rows if r.get('reference'))['source_event_id']==ids[0]
