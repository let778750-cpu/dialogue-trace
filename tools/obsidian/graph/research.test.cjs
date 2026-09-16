const test=require('node:test'),assert=require('node:assert/strict');
const M=require('./plugin/timeline-model');
test('research reading removes technical placeholders while preserving unknown/mixed messages',()=>{
 const s={key:'s',branch:'line',rows:[{id:'env',folded:true,classification:'environment'},
 {id:'u',folded:false,classification:'research'}, {id:'t',folded:true,classification:'technical'},
 {id:'mixed',folded:false,classification:'research'}, {id:'a',folded:false}]};
 const items=M.itemsFor([s],{},{research:true});
 assert.deepEqual(items.map(x=>x.id),['session:s','u','mixed','a']);
 assert(!items.some(x=>x.type==='process'));
 assert(M.itemsFor([s],{t:{classification:'substantive'}},{research:true}).some(x=>x.id==='t'));
 assert(!M.itemsFor([s],{env:{classification:'substantive'}},{research:true}).some(x=>x.id==='env'));
});
test('progress survives a hidden source and does not manufacture user/assistant pairs',()=>{
 const s={key:'s',branch:'b',rows:[{id:'u1',folded:false},{id:'u2',folded:false},{id:'result',folded:true}]};
 const items=M.itemsFor([s],{},{research:true,progress:[{id:'p',workstream_id:'b',anchor_event_id:'result'}]});
 assert.deepEqual(items.map(x=>x.id),['session:s','u1','u2','progress:p']);
});
test('necessary errors are concise entries rather than full command logs',()=>{
 const s={key:'s',rows:[{id:'failure',folded:true,failed:true,classification:'technical'}]};
 assert.equal(M.itemsFor([s],{},{research:true})[1].type,'failure');
});
