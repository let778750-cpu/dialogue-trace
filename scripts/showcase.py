"""Create the public, synthetic thermal-drift case used in README screenshots.

No private transcript is read. Tool outputs below are labeled illustrative data,
not measurements. Use a new instance directory; existing instances are preserved.
"""
import argparse
import os
from pathlib import Path
from research_memory.installation import setup, attach_obsidian
from research_memory.storage import Config, Store
from research_memory.continuity import Continuity
from research_memory.research import ResearchService
from research_memory.knowledge import Knowledge
from research_memory.timeline import publish_projection


def create(root, with_obsidian=False):
    # Resources belong to this skill, even if Python imports an installed wheel.
    previous_package = os.environ.get('RESEARCH_MEMORY_PACKAGE_ROOT')
    os.environ['RESEARCH_MEMORY_PACKAGE_ROOT'] = str(Path(__file__).resolve().parents[1])
    try:
        return _create(root, with_obsidian)
    finally:
        if previous_package is None:
            os.environ.pop('RESEARCH_MEMORY_PACKAGE_ROOT', None)
        else:
            os.environ['RESEARCH_MEMORY_PACKAGE_ROOT'] = previous_package


def _create(root, with_obsidian=False):
    root = Path(root).resolve()
    if (root/'config.json').exists():
        raise ValueError('Choose a new directory; existing research data is preserved.')
    workspace = root/'demo-workspace'
    workspace.mkdir(parents=True, exist_ok=True)
    setup(root, workspace, '温漂研究 · 合成案例 / Thermal drift demo')
    store = Store(Config(root))
    continuity = Continuity(store)
    for session in ('demo-task-a', 'demo-task-b'):
        continuity.bind(workspace, session, 'main')
    service = ResearchService(store)

    def change(op, **args):
        return service.mutate(op, dict(args, expected_version=service.state()['version']))

    change('workstream.update', request_id='showcase-name', id='main', branch_version=0,
           name='温升与漂移 / Temperature and drift', goal='Synthetic example; no scientific evidence')
    change('workstream.create', request_id='showcase-measurement', id='measurement',
           project=store.config.project_id, name='测量方案 / Measurement design', goal='Separate research question')
    sequence = {'demo-task-a': 0, 'demo-task-b': 0}

    def event(session, author, text, minute, kind='message', **extra):
        sequence[session] += 1
        payload = dict(text=text, **extra)
        return store.capture(dict(source='synthetic-showcase', source_id=f'{session}-{sequence[session]}',
            source_sequence=sequence[session], session_id=session, workstream_id='main',
            kind=kind, author=author, payload=payload, occurred_at=f'2026-01-01T09:{minute:02d}:00Z'))

    event('demo-task-a', 'user', '<environment_context>synthetic workspace; powershell</environment_context>', 0)
    event('demo-task-a', 'user', '温升是否导致传感器漂移？先保存假设，再讨论怎样验证。\n\nCould rising temperature explain sensor drift?', 1)
    event('demo-task-a', 'assistant', '先把相关性和因果解释分开。\n\n- 假设：温度变化与输出漂移有关。\n- 控制：供电、采样间隔、安装条件。\n- 下一步：记录温度与输出，并设置恒温对照。\n\nSeparate correlation from causation; keep a constant-temperature control.', 2)
    event('demo-task-a', 'user', '补充约束：预热时间还没有统一。这可能影响比较。\n\nWarm-up duration is not controlled yet.', 3)
    event('demo-task-a', 'assistant', '修正方案：先确定热稳定条件，再比较漂移。当前不能把差异全部归因于温度。\n\nRevision: establish a thermal-stability criterion before comparing drift.', 4)
    call = event('demo-task-a', 'assistant', 'Illustrative tool invocation — no experiment executed.', 5,
                 kind='tool_call', call_id='demo-check', name='analyze_stability',
                 arguments={'input': 'synthetic-readings.csv', 'window': 60},
                 tool_schema={'description': 'Illustrative stability check', 'parameters': {'window': 'seconds'}})
    result = event('demo-task-a', 'tool', 'Synthetic fixture: criterion not met; extend warm-up. No real measurement.', 6,
                   kind='tool_result', call_id='demo-check', output={'stable': False, 'sample_kind': 'synthetic'},
                   duration_ms=12, status='completed', exit_code=0)
    event('demo-task-b', 'user', '在另一个任务继续：我补充了恒温对照，但还缺少重复试验。\n\nContinue in a second task: the control is planned; repeated trials are still missing.', 10)
    last = event('demo-task-b', 'assistant', '保留前面的修正，暂不下因果结论。\n\n| 已知 / Known | 待补充 / Missing |\n|---|---|\n| 需要统一预热条件 | 热稳定判据 |\n| 需要恒温对照 | 重复试验与误差范围 |\n\n下一步：制定测量方案，并引用同一条研究线的依据。', 11)
    change('progress.publish', request_id='showcase-checkpoint', id='thermal-next-step',
           kind='research_checkpoint', workstream_id='main', title='研究断点：先验证热稳定 / Next: thermal stability',
           summary='合成案例：新增约束改变了实验顺序；没有真实实验结论。',
           known=['预热条件尚未统一 / Warm-up is uncontrolled'],
           unknown=['热稳定判据、重复性 / Stability criterion and repeatability'],
           next_steps=['先定义稳定判据，再完成恒温对照 / Define stability, then run the control'],
           event_ids=[last], source_hashes={last: store.get(last)['content_hash']})
    report = publish_projection(Knowledge(store))
    if with_obsidian:
        attach_obsidian(store.config)
    return dict(report, synthetic_only=True, tool_call=call, tool_result=result, checkpoint_source=last)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--with-obsidian', action='store_true')
    args = parser.parse_args()
    print(create(args.root, args.with_obsidian))
