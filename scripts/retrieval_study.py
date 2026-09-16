"""Build-bound human retrieval study; synthetic/automatic timings cannot pass."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import median

GROUPS={
 'original_six':['initial_question','added_condition','ai_revision','rejection_reason','experiment_basis','resume_next_step'],
 'new_five':['cross_session_resume','mixed_topic_routing','ownership_correction','result_provenance','checkpoint_resume']}
MODES=['candidate_08','timeline_07','original_chat']


def template(build):
    return dict(build_sha256=build,participant_kind='human',participant_id='',reviewer_id='',
        trials=[dict(group=g,task=task,mode=m,seconds=None,navigations=None,event_id='',quote='',answer='',answer_correct=None)
                for g,tasks in GROUPS.items() for i,task in enumerate(tasks) for m in MODES[i%3:]+MODES[:i%3]])


def score(record,build,sources):
    if record.get('build_sha256')!=build or record.get('participant_kind')!='human' or not record.get('participant_id') or not record.get('reviewer_id'):
        raise ValueError('Exact build, actual human participant and reviewer are required')
    rows=record.get('trials',[])
    expected={(g,t,m) for g,tasks in GROUPS.items() for t in tasks for m in MODES}
    if len(rows)!=len(expected) or {(r['group'],r['task'],r['mode']) for r in rows}!=expected:
        raise ValueError('All eleven tasks need the same three comparison modes')
    for r in rows:
        if type(r['seconds']) not in (int,float) or not math.isfinite(r['seconds']) or r['seconds']<=0 or type(r['navigations']) is not int or r['navigations']<0 or type(r['answer_correct']) is not bool:
            raise ValueError('Measured timings, navigation counts and reviewed answers required, including failed tasks')
        source=sources[r['task']]
        if not source.get('sha256') or source['sha256']!=hashlib.sha256(source['text'].encode()).hexdigest():
            raise ValueError('Answer key source content needs its verified hash')
        r['correct']=r['answer_correct'] and r['event_id']==source['event_id'] and bool(r['quote'].strip()) and r['quote'] in source['text']
    results={}
    for group in GROUPS:
        modes={m:dict(median_seconds=median(r['seconds'] for r in rows if r['group']==group and r['mode']==m),
                      correct=sum(r['correct'] for r in rows if r['group']==group and r['mode']==m)) for m in MODES}
        best=min(MODES[1:],key=lambda m:modes[m]['median_seconds'])
        gain=1-modes['candidate_08']['median_seconds']/modes[best]['median_seconds']
        accuracy=modes['candidate_08']['correct']>=max(modes[m]['correct'] for m in MODES[1:])
        results[group]=dict(modes=modes,best_baseline=best,median_improvement=gain,no_accuracy_loss=accuracy,passed=gain>=.2-1e-12 and accuracy)
    return dict(groups=results,passed=all(g['passed'] for g in results.values()),build_sha256=build,
                limitation='Single-person pilot; counterbalance order. Automated tests do not fill human trial fields.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['init','score']);p.add_argument('--file',required=True);p.add_argument('--manifest',required=True);p.add_argument('--sources');a=p.parse_args()
    build=hashlib.sha256(Path(a.manifest).read_bytes()).hexdigest();file=Path(a.file)
    if a.action=='init':
        with file.open('x',encoding='utf-8') as f:json.dump(template(build),f,ensure_ascii=False,indent=2)
    else:
        result=score(json.loads(file.read_text(encoding='utf-8')),build,json.loads(Path(a.sources).read_text(encoding='utf-8')))
        print(json.dumps(result,ensure_ascii=False,indent=2))
