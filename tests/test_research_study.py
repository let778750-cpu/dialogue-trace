import hashlib
import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('research_study',Path(__file__).parents[1]/'scripts/retrieval_study.py')
study=importlib.util.module_from_spec(spec);spec.loader.exec_module(study)


def fixture():
    record=study.template('build');record.update(participant_id='synthetic-participant',reviewer_id='synthetic-reviewer')
    sources={t:dict(event_id='synthetic-'+t,text='synthetic quote',sha256=hashlib.sha256(b'synthetic quote').hexdigest()) for ts in study.GROUPS.values() for t in ts}
    for r in record['trials']:
        r.update(seconds=70 if r['mode']=='candidate_08' else 100,navigations=2,quote='synthetic quote',event_id='synthetic-'+r['task'],answer_correct=True)
    return record,sources


def test_group_regression_cannot_hide_in_overall_gain():
    r,s=fixture()
    assert study.score(r,'build',s)['passed']
    for row in r['trials']:
        if row['group']=='new_five' and row['mode']=='candidate_08':row['seconds']=101
    result=study.score(r,'build',s)
    assert result['groups']['original_six']['passed'] and not result['passed']


def test_unknown_human_results_and_modified_source_rejected():
    r,s=fixture();r['trials'][0]['seconds']=None
    with pytest.raises(ValueError):study.score(r,'build',s)
    r,s=fixture();next(iter(s.values()))['text']='changed source'
    with pytest.raises(ValueError):study.score(r,'build',s)
