from datetime import date,timedelta
import pytest
from research_memory.field_study import summarize


def observations():
    rows=[]
    for i in range(14):
        day=str(date(2026,9,1)+timedelta(days=i))
        for mode,seconds in [('raw',100),('basic_memory',80),('project',60)]:
            rows.append(dict(date=day,case_id=str(i),project_id='p',mode=mode,model_condition='same',source_set_id='frozen',
                seconds=seconds,success='true',citations_checked=2,citations_correct=2,recovery_errors=0,native_memory_observed='false'))
        rows.append(dict(date=day,mode='maintenance',maintenance_minutes=3))
    return rows


def test_field_study_requires_actual_days_and_paired_comparable_conditions():
    assert summarize([])['state']=='insufficient_observations'
    rows=observations(); report=summarize(rows)
    assert report['best_observed_baseline']=='basic_memory'
    assert report['state']=='targets_met'
    rows[2]['citations_correct']=0
    assert summarize(rows)['gates']['source_accuracy'] is False
    rows[2]['model_condition']='different'
    assert summarize(rows)['comparisons']['basic_memory']['pairs']==13
    with pytest.raises(ValueError): summarize(rows+[rows[0]])


def test_unverified_native_memory_is_not_an_experimental_arm():
    row=observations()[0]; row['mode']='native_memory'
    report=summarize([row])
    assert not report['comparisons'] and report['excluded']
