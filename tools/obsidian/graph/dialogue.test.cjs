const test=require('node:test'),assert=require('node:assert/strict');
const D=require('./plugin/dialogue');
const {ResearchGraphModel}=require('./plugin/model');
const n=(id,authors=['user'],type='idea')=>({id,authors,type,title:id,body:'观察温度变化可能影响漂移，需要核对。',workstream_id:'w',research_project_id:'p'});
const e=(id,source,target,type='derived_from')=>({id,source,target,type,basis:'明确记录的关系'});
const g=(nodes,edges)=>({schema_version:2,project_id:'p',default_project_id:'p',navigation:{projects:{p:{entry_ids:['root']}}},nodes,edges});
test('authorship uses explicit contributors and never borrowed citation speakers',()=>{
  assert.equal(D.group({...n('a',['user']),sources:[{author:'assistant'}]}),'user');
  assert.equal(D.group(n('b',['assistant'])),'assistant');
  assert.equal(D.group(n('c',['user','assistant interpretation'])),'shared');
  assert.equal(D.group(n('d',['assistant observation'],'evidence')),'material');
  assert.equal(D.group(n('e',['paper author'])),'unknown');assert.equal(D.group(n('f',[])),'unknown');
});
test('pure commands are omitted only from dialogue, mixed research statements remain',()=>{
  assert.equal(D.controlOnly({...n('c'),title:'继续',body:'继续'}),true);
  assert.equal(D.controlOnly({...n('c'),title:'检查错误并修正',body:'检查错误并修正！'}),true);
  assert.equal(D.controlOnly({...n('c'),title:'继续',body:'继续，并检查温度升高是否导致漂移。'}),false);
  assert.equal(D.controlOnly({...n('c'),title:'继续',body:'继续',conditions:['对照组温度不变']}),false);
});
test('center, left and right represent entry and authors, shared and evidence stay distinct',()=>{
  const nodes=[n('root',['user'],'question'),n('u'),n('a',['assistant']),n('s',['user','assistant']),n('e',['assistant'],'evidence')],boxes=D.layout(nodes,'root');
  assert.equal(boxes.root.x,0);assert.equal(boxes.root.y,0);assert.ok(boxes.root.w>boxes.u.w);
  assert.ok(boxes.u.x<0&&boxes.a.x>0);assert.equal(boxes.s.group,'shared');assert.equal(boxes.e.group,'material');
  for(const a0 of Object.values(boxes))for(const b0 of Object.values(boxes))if(a0!==b0){const a=a0.obstacle||a0,b=b0.obstacle||b0;assert.ok(Math.abs(a.x-b.x)>=(a.w+b.w)/2||Math.abs(a.y-b.y)>=(a.h+b.h)/2);}
});
test('off-subgraph entry is shown without adding a fake connection, original edges retained',()=>{
  const graph=g([n('root',['user'],'question'),n('u'),n('a',['assistant']),{...n('control'),title:'继续',body:'继续'}],[e('one','a','u'),e('two','control','u')]);
  const before=JSON.stringify(graph),m=new ResearchGraphModel(graph);m.focus('a');const v=D.visible(m);
  assert.ok(v.nodes.some(n=>n.id==='root'));assert.deepEqual(v.edges.map(e=>e.id),['one']);assert.equal(JSON.stringify(graph),before);
});
function audit(nodes,edges){
  const boxes=D.layout(nodes,'root'),r=D.route(boxes,edges);assert.equal(Object.keys(r.paths).length,edges.length,JSON.stringify(r.issues));
  for(const edge of edges){const points=r.paths[edge.id];assert.ok(points.length>=2);
    for(const [end,id] of [[points[0],edge.source],[points.at(-1),edge.target]]){const b=boxes[id];if(b.shape==='circle')assert.ok(Math.abs(Math.hypot(end.x-b.x,end.y-b.y)-b.w/2)<.01);else assert.ok(Math.abs(Math.abs(end.x-b.x)-b.w/2)<.01||Math.abs(Math.abs(end.y-b.y)-b.h/2)<.01);}
    for(let i=1;i<points.length;i++)for(const box of Object.values(boxes))if(box.id!==edge.source&&box.id!==edge.target)assert.equal(D.segmentHits(points[i-1],points[i],box),false,edge.id+' crosses '+box.id);
  }
  return {boxes,r};
}
test('cross-side path goes around central question, inverse and parallel relations stay independent',()=>{
  const nodes=[n('root',['user'],'question'),n('u'),n('a',['assistant'])],edges=[e('one','u','a'),e('two','a','u'),e('three','a','u','contradicts')];
  const {r}=audit(nodes,edges);assert.notDeepEqual(r.paths.two,r.paths.three);
});
test('mixed lanes, shared evidence and a cyclic relation remain connected and obstacle-free',()=>{
  const nodes=[n('root',['user'],'question'),n('u'),n('a',['assistant']),n('s',['user','assistant']),n('p',['paper author']),n('e',['assistant'],'evidence')];
  audit(nodes,[e('1','u','root'),e('2','a','root'),e('3','s','u'),e('4','a','s'),e('5','e','a','supports'),e('6','e','u','contradicts'),e('7','p','e','related_to')]);
});
test('nonplanar three-by-three network reports crossings instead of claiming a crossing-free layout',()=>{
  const nodes=[n('root',['user'],'question'),...Array.from({length:3},(_,i)=>n('u'+i)),...Array.from({length:3},(_,i)=>n('a'+i,['assistant']))];
  const edges=Array.from({length:9},(_,i)=>e('e'+i,'u'+Math.floor(i/3),'a'+i%3));const {r}=audit(nodes,edges);
  assert.ok(r.crossings+r.overlaps>0);assert.equal(Object.keys(r.paths).length,9);
});
test('large canvas stops within an explicit budget rather than allocating unbounded grids',()=>{
  const boxes={a:{id:'a',x:-1e8,y:0,w:192,h:88},b:{id:'b',x:1e8,y:0,w:192,h:88}};
  assert.ok(D.route(boxes,[e('one','a','b')]).issues.length);
});
test('circle ports follow the circumference and routes also avoid every external title',()=>{
  const nodes=[n('root',['user'],'question'),...Array.from({length:5},(_,i)=>n('u'+i)),n('a',['assistant']),n('s',['user','assistant']),n('e',['assistant'],'evidence')];
  const edges=[...Array.from({length:5},(_,i)=>e('r'+i,'u'+i,'root')),e('x','u0','a'),e('y','a','s'),e('z','s','e'),e('v','e','u1')];
  const {boxes,r}=audit(nodes,edges);
  for(const points of Object.values(r.paths))for(const b of Object.values(boxes).filter(b=>b.shape==='circle')){
    const label={x:b.x,y:b.y+58,w:180,h:58};
    for(let i=1;i<points.length;i++)assert.equal(D.segmentHits(points[i-1],points[i],label),false,'route crossed label '+b.id);
  }
});
