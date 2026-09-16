const test=require('node:test'),assert=require('node:assert/strict');
const M=require('./plugin/timeline-model');
const s={key:'s',project:'p',branch:'b',rows:[{id:'u1',folded:false},{id:'u2',folded:false},{id:'t1',folded:true},{id:'t2',folded:true},{id:'a1',folded:false}]};
test('consecutive speakers preserve source ordering and process groups remain reversible',()=>{
 const items=M.itemsFor([s]);assert.deepEqual(items.map(i=>i.id),['session:s','u1','u2','process:t1','a1']);
 assert.equal(M.findItem(items,'t2'),3);assert.equal(M.itemsFor([s],{t2:{classification:'substantive'}}).length,6);
});
test('scope prevents unrelated project or branch leakage',()=>{
 assert.equal(M.scopedSessions({sessions:[s,{...s,branch:'other'},{...s,project:'other'}]},'p','b').length,1);
});
test('invalid source paths and duplicate identities are rejected',()=>{
 assert.equal(M.safeBodyPath('System/timeline/messages/'+'a'.repeat(64)+'.json'),true);
 for(const p of ['../data/events/a.json','https://example.com','System/timeline/messages/../../../x.json'])assert.equal(M.safeBodyPath(p),false);
 assert.throws(()=>M.validate({schema_version:1,project_id:'p',sessions:[s,s]},{project_id:'p'}));
 assert.throws(()=>M.validate({schema_version:1,project_id:'p',sessions:[]},{project_id:'q'}));
});
test('message and process bodies use distinct storage interfaces',()=>{
 assert.deepEqual(M.bodyAt({u1:{text:'original'}},{id:'u1',kind:'message'}),{text:'original'});
 assert.deepEqual(M.bodyAt({text:'log'},{id:'t1',kind:'tool_result'}),{text:'log'});
});
