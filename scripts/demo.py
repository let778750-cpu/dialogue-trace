"""Create a clearly synthetic, independent research example."""
import argparse
from pathlib import Path
from research_memory.installation import setup
from research_memory.storage import Config,Store
from research_memory.continuity import Continuity
from research_memory.research import ResearchService
from research_memory.timeline import publish_projection
from research_memory.knowledge import Knowledge

p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args()
root=Path(a.root).resolve()
if (root/'config.json').exists():raise SystemExit('Use a new directory; existing research instances are never reset')
workspace=root/'demo-workspace';workspace.mkdir(parents=True,exist_ok=True)
setup(root,workspace,'合成温漂研究演示')
s=Store(Config(root));c=Continuity(s)
c.bind(workspace,'demo-a','main');c.bind(workspace,'demo-b','main')
service=ResearchService(s)
service.mutate('workstream.create',dict(request_id='demo-secondary',expected_version=0,id='measurement',project=s.config.project_id,name='测量方案',goal='合成示例，不构成科研证据'))
ids=[]
messages=[('demo-a','user','温升是否可能导致漂移？'),('demo-a','assistant','需要控制温度之外的变量，并设计对照。'),
          ('demo-b','user','补充条件：传感器尚未热稳定。'),('demo-b','assistant','此前直接比较漂移的方案需要修正。先验证热稳定，再比较结果。')]
for i,(session,author,text) in enumerate(messages):
 ids.append(s.capture(dict(source='synthetic-demo',source_id=str(i),source_sequence=i,session_id=session,workstream_id='main',kind='message',author=author,payload={'text':text},occurred_at=f'2026-01-01T00:0{i}:00Z')))
service.mutate('progress.publish',dict(request_id='demo-progress',expected_version=service.state()['version'],id='thermal-revision',kind='revision',
 workstream_id='main',title='先验证热稳定条件',summary='合成案例：新增条件改变了下一步实验安排。',event_ids=ids[-2:],source_hashes={id:s.get(id)['content_hash'] for id in ids[-2:]}))
print(publish_projection(Knowledge(s)))
print('Synthetic only. No experiment has actually been run.')
