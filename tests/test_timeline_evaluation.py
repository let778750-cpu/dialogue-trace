import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('timeline_evaluation', Path(__file__).parents[1] / 'tools/obsidian/graph/timeline_evaluation.py')
study = importlib.util.module_from_spec(spec); spec.loader.exec_module(study)


def sample():
    sources = {task[2]: '真实原话' for task in study.TASKS}
    data = {'participant_kind': 'human', 'participant_id': 'test-fixture', 'reviewer_id': 'fixture-only', 'plugin_hashes': {},
            'trials': [dict(task_id=task[0], mode=mode, seconds=80 if mode == 'timeline' else 100 if mode == 'old_graph' else 120,
                            navigations=2, source_event_id=task[2], source_quote='真实原话', answer_correct=True)
                       for task in study.TASKS for mode in study.MODES]}
    return data, sources


def test_human_study_requires_complete_measured_inputs():
    data, sources = sample()
    data['trials'][0]['seconds'] = None
    with pytest.raises(ValueError): study.score(data, {}, sources)
    data, sources = sample(); data['participant_kind'] = 'agent'
    with pytest.raises(ValueError): study.score(data, {}, sources)


def test_faster_cannot_pass_with_worse_source_accuracy():
    data, sources = sample()
    assert study.score(data, {}, sources)['state'] == 'passed'
    data['trials'][0]['source_quote'] = '错误原话'
    assert study.score(data, {}, sources)['state'] == 'not_met'


def test_threshold_uses_fastest_baseline_and_build_identity():
    data, sources = sample()
    for row in data['trials']:
        if row['mode'] == 'original_chat': row['seconds'] = 90
    result = study.score(data, {}, sources)
    assert result['best_baseline'] == 'original_chat' and result['state'] == 'not_met'
    with pytest.raises(ValueError): study.score(data, {'changed': 'build'}, sources)
