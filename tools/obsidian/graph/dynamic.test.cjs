const test=require('node:test'),assert=require('node:assert/strict');
const D=require('./plugin/dynamic'),Dialogue=require('./plugin/dialogue');
test('color attribution does not restrict positions or alias saved layouts',()=>{
  const nodes=[{id:'root',authors:['user']},{id:'u',authors:['user']},{id:'a',authors:['assistant']}],saved={u:{x:450,y:60},a:{x:400,y:20}};
  const p=D.seed(nodes,'root',[],saved);assert.deepEqual(p.root,{x:0,y:0});assert.equal(p.u.x,450);assert.equal(p.a.x,400);p.a.x=600;assert.equal(saved.a.x,400);
});
test('settling separates visible titles, respects fixed root and pinned idea',()=>{
  const groups={root:'entry',u:'node',u2:'node',u3:'node',a:'node',s:'node',e:'node'};
  const nodes=Object.keys(groups).map(id=>({id,x:0,y:0})),pins={u:{x:-300,y:0}};
  D.resolve(nodes,'root',groups,pins,32);assert.deepEqual(D.overlaps(nodes,groups),[]);assert.equal(nodes.find(n=>n.id==='u').x,-300);assert.equal(nodes[0].x,0);
});
test('smooth curves avoid central topic and retain reciprocal and parallel relations',()=>{
  const nodes=[{id:'u',x:-370,y:0},{id:'a',x:370,y:0},{id:'root',x:0,y:0}];
  const edges=[{id:'one',source:'u',target:'a'},{id:'two',source:'u',target:'a'},{id:'three',source:'a',target:'u'}];
  const result=D.route(nodes,edges,'root',{root:'entry',u:'user',a:'assistant'});assert.equal(Object.keys(result.paths).length,3);assert.deepEqual(result.issues,[]);
  assert.equal(new Set(edges.map(e=>result.paths[e.id].distance*(e.source==='u'?-1:1))).size,3);
  for(const e of edges){assert.equal(result.paths[e.id].style['curve-style'],'unbundled-bezier');assert.equal(Math.round(Math.hypot(result.paths[e.id].start.x-nodes.find(n=>n.id===e.source).x,result.paths[e.id].start.y)),23);}
});
test('a disconnected anchor adds no inferred relationship',()=>{
  const result=D.route([{id:'root',x:0,y:0},{id:'a',x:400,y:0}],[],'root',{root:'entry',a:'assistant'});assert.deepEqual(result.paths,{});
});
