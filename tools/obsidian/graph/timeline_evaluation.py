"""Human retrieval study; never fills in human timings from automated tests."""
import argparse
import math
from pathlib import Path
from statistics import median
from research_memory.storage import read_json, write_json, file_hash

ROOT = Path(__file__).resolve().parents[3]
MODES = ('timeline', 'old_graph', 'original_chat')
TASKS = [('initial_question', 'Synthetic fixture initial_question', 'synthetic_initial_question'), ('user_condition', 'Synthetic fixture user_condition', 'synthetic_user_condition'), ('ai_revision', 'Synthetic fixture ai_revision', 'synthetic_ai_revision'), ('rejection_reason', 'Synthetic fixture rejection_reason', 'synthetic_rejection_reason'), ('experiment_basis', 'Synthetic fixture experiment_basis', 'synthetic_experiment_basis'), ('resume_next_step', 'Synthetic fixture resume_next_step', 'synthetic_resume_next_step')]

def score(record, hashes, sources):
    if record.get('participant_kind') != 'human' or not record.get('participant_id') or not record.get('reviewer_id'):
        raise ValueError('Actual human participant and source/answer reviewer required')
    if record.get('plugin_hashes') != hashes:
        raise ValueError('Study does not match the candidate build')
    trials = record.get('trials', [])
    expected = {(mode, task[0]) for mode in MODES for task in TASKS}
    if len(trials) != len(expected) or {(r.get('mode'), r.get('task_id')) for r in trials} != expected:
        raise ValueError('Exactly six tasks in each of three modes are required')
    results = {}
    for mode in MODES:
        rows = [r for r in trials if r['mode'] == mode]
        for row in rows:
            seconds = row.get('seconds')
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
                raise ValueError('Every trial needs a measured positive duration (include failed trials)')
            if not isinstance(row.get('navigations'), int) or isinstance(row['navigations'], bool) or row['navigations'] < 0:
                raise ValueError('Every trial needs a navigation count')
            if type(row.get('answer_correct')) is not bool:
                raise ValueError('Answers must be explicitly reviewed')
            key = next(task[2] for task in TASKS if task[0] == row['task_id'])
            source = sources[key]
            quote = row.get('source_quote') or ''
            row['source_correct'] = row.get('source_event_id') == key and bool(quote.strip()) and quote in source
            row['correct'] = row['source_correct'] and row['answer_correct']
        results[mode] = {'median_seconds': median(r['seconds'] for r in rows), 'correct': sum(r['correct'] for r in rows),
                         'median_navigations': median(r['navigations'] for r in rows), 'tasks': len(rows)}
    best = min(MODES[1:], key=lambda mode: results[mode]['median_seconds'])
    improvement = 1 - results['timeline']['median_seconds'] / results[best]['median_seconds']
    no_accuracy_loss = results['timeline']['correct'] >= max(results[m]['correct'] for m in MODES[1:])
    passed = improvement >= .2 - 1e-12 and no_accuracy_loss
    return {'state': 'passed' if passed else 'not_met', 'participant_kind': 'human', 'participant_id': record['participant_id'],
            'reviewer_id': record['reviewer_id'], 'plugin_hashes': hashes, 'best_baseline': best, 'results': results,
            'median_improvement': improvement, 'no_accuracy_loss': no_accuracy_loss,
            'limitations': 'Single-person, repeated-task pilot; prior familiarity and learning order can bias timing.'}


# Public 11-task study launcher: scripts/retrieval_study.py
