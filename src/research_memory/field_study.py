"""Human-entered paired evaluation; missing observations never count as success."""
from collections import defaultdict
from datetime import date
from statistics import median


FIELDS = ['date','case_id','project_id','mode','model_condition','source_set_id','seconds','success',
          'citations_checked','citations_correct','recovery_errors','maintenance_minutes','native_memory_observed','notes']
MODES = {'raw','basic_memory','project','native_memory','maintenance'}


def summarize(rows):
    grouped = defaultdict(dict); days = set(); maintenance = []; excluded = []
    for number, source in enumerate(rows, 2):
        row = dict(source)
        if not any(row.values()): continue
        day = date.fromisoformat(row['date']); mode = row['mode']
        if mode not in MODES: raise ValueError(f'Row {number}: unknown mode')
        days.add(day)
        if mode == 'maintenance':
            value = float(row['maintenance_minutes'])
            if value < 0: raise ValueError('Maintenance must not be negative')
            maintenance.append((day, value)); continue
        if mode == 'native_memory' and row['native_memory_observed'] != 'true':
            excluded.append({'row':number,'reason':'native memory participation unverified'}); continue
        for key in ('case_id','project_id','model_condition','source_set_id'):
            if not row[key]: raise ValueError(f'Row {number}: missing {key}')
        row['seconds'] = float(row['seconds'])
        if row['seconds'] <= 0: raise ValueError('Observed task duration must be positive')
        if row['success'] not in ('true','false'): raise ValueError('Success must be true or false')
        for key in ('citations_checked','citations_correct','recovery_errors'): row[key] = int(row[key])
        if min(row[k] for k in ('citations_checked','citations_correct','recovery_errors')) < 0 or row['citations_correct'] > row['citations_checked']:
            raise ValueError('Invalid citation or recovery counts')
        key = tuple(row[k] for k in ('case_id','project_id','model_condition','source_set_id'))
        if mode in grouped[key]: raise ValueError('Duplicate case/mode; use a distinct case ID for another task')
        grouped[key][mode] = row
    comparisons = {}
    for baseline in ('raw','basic_memory','native_memory'):
        pairs = [(g[baseline],g['project']) for g in grouped.values() if baseline in g and 'project' in g]
        if not pairs: continue
        def stats(index):
            r = [p[index] for p in pairs]; checked = sum(x['citations_checked'] for x in r)
            return {'median_seconds':median(x['seconds'] for x in r),'successes':sum(x['success']=='true' for x in r),
                    'citation_precision':sum(x['citations_correct'] for x in r)/checked if checked else None,
                    'recovery_errors':sum(x['recovery_errors'] for x in r)}
        base, project = stats(0), stats(1)
        comparisons[baseline] = {'pairs':len(pairs),'baseline':base,'project':project,
            'median_paired_time_reduction':median(1-p['seconds']/b['seconds'] for b,p in pairs)}
    daily = defaultdict(float)
    for day, minutes in maintenance: daily[day] += minutes
    maintenance_median = median(daily.values()) if daily else None
    enough_days = len(days)>=14 and bool(days) and (max(days)-min(days)).days>=13 and len(daily)>=14
    eligible = {k:v for k,v in comparisons.items() if v['pairs']>=10}
    best = max(eligible, key=lambda k:(eligible[k]['baseline']['successes']/eligible[k]['pairs'],
        eligible[k]['baseline']['citation_precision'] if eligible[k]['baseline']['citation_precision'] is not None else -1,
        -eligible[k]['baseline']['median_seconds'])) if eligible else None
    result = {'state':'insufficient_observations','observed_days':len(days),'maintenance_days':len(daily),
              'maintenance_median_minutes':maintenance_median,'comparisons':comparisons,'best_observed_baseline':best,'excluded':excluded}
    if enough_days and best:
        pair = eligible[best]; b,p=pair['baseline'],pair['project']
        if b['citation_precision'] is not None and p['citation_precision'] is not None:
            gates={'time':pair['median_paired_time_reduction']>=.20,'maintenance':maintenance_median<=5,
                   'source_accuracy':p['citation_precision']>=b['citation_precision'],
                   'task_success':p['successes']>=b['successes'],'recovery':p['recovery_errors']<=b['recovery_errors']}
            result.update(state='targets_met' if all(gates.values()) else 'targets_not_met', gates=gates)
    return result
