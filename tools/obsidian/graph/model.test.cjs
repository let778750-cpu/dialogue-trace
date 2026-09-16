const test = require('node:test');
const assert = require('node:assert/strict');
const {ResearchGraphModel} = require('./plugin/model');
const node = (id, extra={}) => ({id,title:id,type:'idea',body:'中文研究',workstream_id:'a',human_review:'unreviewed',evidence_status:'unassessed',...extra});
const edge = (source,target,type='related_to',id=`${source}-${target}-${type}`) => ({id,source,target,type});
const graph = (nodes,edges) => ({schema_version:1,nodes,edges});

test('clicking a node changes selection without expanding it',()=>{
  const m=new ResearchGraphModel(graph([node('q',{type:'question'}),node('a'),node('b')],[edge('q','a'),edge('a','b')]));
  assert.deepEqual(m.visible().nodes.map(n=>n.id),['q','a']);
  m.select('a');assert.equal(m.state.selected,'a');assert.equal(m.visible().nodes.length,2);
  m.expand('a');assert.equal(m.visible().nodes.length,3);
});
test('collapse preserves neighbours shared by another expanded branch',()=>{
  const m=new ResearchGraphModel(graph(['q','a','b','s','leaf'].map(id=>node(id)),[edge('q','a'),edge('q','b'),edge('a','s'),edge('b','s'),edge('s','leaf')]));
  m.expand('a');m.expand('b');m.expand('s');m.collapse('a');
  assert.ok(m.visible().nodes.some(n=>n.id==='s'));
  m.collapse('b');assert.ok(!m.visible().nodes.some(n=>n.id==='s'));assert.ok(!m.visible().nodes.some(n=>n.id==='leaf'));
});
test('pinned branch survives collapse and full state can be reopened',()=>{
  const g=graph(['q','a','b'].map(id=>node(id)),[edge('q','a'),edge('a','b')]);const m=new ResearchGraphModel(g);
  m.expand('a');m.togglePin('b',{x:21,y:42});m.state.viewport={zoom:1.2,pan:{x:10,y:20}};m.collapse('q');
  const reopened=new ResearchGraphModel(g,JSON.parse(JSON.stringify(m.snapshot())));
  assert.ok(reopened.visible().nodes.some(n=>n.id==='b'));assert.deepEqual(reopened.state.pins.b,{x:21,y:42});assert.equal(reopened.state.viewport.zoom,1.2);
});
test('opposing and repeated types between the same endpoints are not merged',()=>{
  const m=new ResearchGraphModel(graph([node('a'),node('b')],[edge('a','b','supports','r1'),edge('a','b','contradicts','r2'),edge('a','b','supports','r3')]));
  assert.equal(m.visible().edges.length,3);m.state.filters.relation='contradicts';assert.equal(m.visible().edges.length,1);
});
test('large neighbourhood is bounded, remaining count is accurate, no record discarded',()=>{
  const nodes=[node('q'),...Array.from({length:999},(_,i)=>node(`n${i}`))], edges=nodes.slice(1).map(n=>edge('q',n.id));
  const m=new ResearchGraphModel(graph(nodes,edges));assert.equal(m.visible().nodes.length,21);assert.equal(m.remaining('q'),979);
  m.expand('q');assert.equal(m.visible().nodes.length,41);assert.equal(m.remaining('q'),959);assert.equal(m.graph.nodes.length,1000);
});
test('branch and review filters preserve scientific states independently',()=>{
  const m=new ResearchGraphModel(graph([node('q'),node('b',{workstream_id:'b'}),node('c',{human_review:'accepted'})],[edge('q','b'),edge('q','c')]));
  assert.equal(m.visible().nodes.length,2);m.state.filters.crossBranch=true;assert.equal(m.visible().nodes.length,3);
  m.state.filters.evidence='supported';assert.equal(m.visible().nodes.length,1);assert.equal(m.nodes.get('c').evidence_status,'unassessed');
});
test('removing an entity restores an existing focus and does not manufacture a note',()=>{
  const m=new ResearchGraphModel(graph([node('new')],[]),{focus:'deleted',selected:'deleted',expanded:{deleted:{'*':20}}});
  assert.equal(m.state.focus,'new');assert.equal(m.visible().nodes.length,1);
});

test('project selection excludes samples even with cross-branch search; layouts remain independent',()=>{
  const g={schema_version:2,project_id:'archive',default_project_id:'real',nodes:[node('sample',{research_project_id:'demo',type:'question'}),node('real',{research_project_id:'real',type:'question'}),node('r2',{research_project_id:'real'})],edges:[edge('real','sample'),edge('real','r2')]};
  const m=new ResearchGraphModel(g);assert.equal(m.state.focus,'real');m.state.filters.crossBranch=true;
  assert.deepEqual(m.visible().nodes.map(n=>n.id),['real','r2']);assert.equal(m.search('').length,2);
  m.state.positions.real={x:34,y:52};const saved=m.snapshot();
  const sample=new ResearchGraphModel(g,{project:'demo'});assert.equal(sample.state.focus,'sample');assert.equal(sample.visible().nodes.length,1);
  const reopened=new ResearchGraphModel(g,saved);assert.deepEqual(reopened.state.positions.real,{x:34,y:52});
  reopened.state.filters.crossProject=true;assert.equal(reopened.visible().nodes.length,3);
});
test('an empty registered project can be selected without displaying another project',()=>{
  const g={schema_version:2,project_id:'archive',default_project_id:'real',nodes:[node('r',{research_project_id:'real'})],edges:[]};
  const empty=new ResearchGraphModel(g,{project:'new',focus:'r'});assert.equal(empty.state.focus,null);assert.deepEqual(empty.visible().nodes,[]);assert.deepEqual(empty.search(''),[]);
});

const navigationGraph=()=>({schema_version:2,project_id:'archive',default_project_id:'p',
  navigation:{schema_version:1,projects:{p:{entry_ids:['q','q2'],branches:{a:['q'],b:['q2']}}}},
  nodes:[node('q2',{type:'question',research_project_id:'p',workstream_id:'b'}),node('q',{type:'question',research_project_id:'p'}),node('a',{research_project_id:'p'}),node('b',{research_project_id:'p'}),node('e',{type:'evidence',research_project_id:'p'}),node('detached',{research_project_id:'p'})],
  edges:[{...edge('a','q','derived_from'),basis:'原问题'}, {...edge('b','a','refines'),basis:'条件细化'},edge('e','a','supports'),edge('e','q2','supports')]});

test('explicit entry wins over node order; focus and repeated selection do not replace it',()=>{
  const m=new ResearchGraphModel(navigationGraph());assert.equal(m.state.entry,'q');assert.equal(m.state.focus,'q');
  m.state.positions.q={x:32,y:18};m.state.pins.q={x:32,y:18};
  for(const id of ['a','b','e','a','b'])m.focus(id);
  assert.equal(m.state.entry,'q');m.returnToEntry();assert.equal(m.state.selected,'q');assert.deepEqual(m.state.pins.q,{x:32,y:18});
});
test('unconfigured, no-question and removed-entry projects open an honest overview',()=>{
  const g=navigationGraph();g.navigation.projects.p.entry_ids=[];g.navigation.projects.p.branches={};
  const m=new ResearchGraphModel(g);assert.equal(m.state.mode,'overview');assert.equal(m.state.focus,null);
  m.chooseEntry('q');assert.equal(m.state.entry,'q');assert.equal(m.state.mode,'local');
  const saved=m.snapshot();g.nodes=g.nodes.filter(n=>n.id!=='q');g.edges=g.edges.filter(e=>e.target!=='q');
  const reopened=new ResearchGraphModel(g,saved);assert.equal(reopened.state.mode,'overview');assert.equal(reopened.state.entry,null);assert.equal(reopened.entryMissing,true);
  const noQuestions={...g,nodes:g.nodes.filter(n=>n.type!=='question'),edges:[]};
  assert.equal(new ResearchGraphModel(noQuestions).state.focus,null);
});
test('entry, trail and layout survive reload without reordering scientific edges',()=>{
  const g=navigationGraph(),original=structuredClone(g),m=new ResearchGraphModel(g);
  m.focus('b');m.select('a');m.state.viewport={zoom:.7,pan:{x:10,y:20}};
  const reopened=new ResearchGraphModel(g,JSON.parse(JSON.stringify({...m.snapshot(),history:[m.snapshot()]})));
  assert.equal(reopened.state.entry,'q');assert.equal(reopened.state.selected,'a');assert.deepEqual(reopened.state.viewport,m.state.viewport);
  assert.deepEqual(reopened.state.trail,m.state.trail);assert.equal(reopened.state.history,undefined);assert.deepEqual(g,original);
});
test('branch-specific entry and selected overview question remain distinct from scientific ownership',()=>{
  const g=navigationGraph(),m=new ResearchGraphModel(g,{workstream:'b'});assert.equal(m.state.entry,'q2');
  m.chooseEntry('q');assert.equal(m.state.workstream,'a');assert.equal(g.nodes.find(n=>n.id==='q').workstream_id,'a');
  assert.throws(()=>m.chooseEntry('e'));
});
test('overview exposes disconnected records while shared evidence has one stable entity',()=>{
  const m=new ResearchGraphModel(navigationGraph()),groups=m.overviewGroups();
  assert.equal(groups.questions.length,2);assert.deepEqual(groups.detached.map(n=>n.id),['detached']);
  assert.equal(m.projectNodes().filter(n=>n.id==='e').length,1);
});
test('lineage and entry layers use declared derivation only, preserve multi-source and cycles',()=>{
  const g=navigationGraph();g.edges.push({...edge('b','q2','derived_from'),basis:'另一来源'}, {...edge('a','b','refines'),basis:'循环修订'});
  const original=JSON.stringify(g.edges),m=new ResearchGraphModel(g),path=m.lineage('b');
  assert.equal(path.cycle,true);assert.ok(path.edges.some(e=>e.target==='q2'));assert.ok(!path.edges.some(e=>e.type==='supports'));
  assert.equal(m.entryLevels().get('q'),0);assert.equal(m.entryLevels().get('a'),1);assert.equal(m.entryLevels().get('b'),2);assert.equal(m.entryLevels().has('e'),false);
  assert.equal(JSON.stringify(g.edges),original);assert.deepEqual(m.lineage('detached').edges,[]);
});
test('source timeline deduplicates shared events and sorts occurrence rather than import or edit time',()=>{
  const g=navigationGraph();const events=[
    {event_id:'old',occurred_at:'2026-01-01T12:00:00+08:00',captured_at:'2026-09-12T00:00:00Z',source_sequence:1,predecessors:[]},
    {event_id:'new',occurred_at:'2026-01-02T00:00:00Z',captured_at:'2026-01-02T00:01:00Z',predecessors:['old']},
    {event_id:'unknown',occurred_at:null}];
  g.nodes.find(n=>n.id==='q').sources=[events[0]];g.nodes.find(n=>n.id==='a').sources=events;g.nodes.find(n=>n.id==='a').updated_at='2030-01-01';
  const rows=new ResearchGraphModel(g).timeline('a');assert.deepEqual(rows.map(e=>e.event_id),['old','new','unknown']);assert.equal(rows[0].nodes.length,2);assert.deepEqual(rows[1].predecessors,['old']);
});
test('bounded local exploration scales across 20, 100 and 500 records without discarding unshown branches',()=>{
  for(const size of [20,100,500]){
    const g=navigationGraph();g.nodes=[g.nodes.find(n=>n.id==='q'),...Array.from({length:size-1},(_,i)=>node('n'+i,{research_project_id:'p'}))];g.edges=g.nodes.slice(1).map(n=>({...edge(n.id,'q','derived_from'),basis:'示例来源'}));
    const m=new ResearchGraphModel(g);assert.equal(m.visible().nodes.length,Math.min(size,21));assert.equal(m.entryLevels().size,size);m.focus('n0');m.returnToEntry();assert.equal(m.state.entry,'q');assert.equal(m.projectNodes().length,size);
  }
});
