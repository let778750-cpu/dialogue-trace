"use strict";
function scopedSessions(data, project, branch) {
  return data.sessions.filter(s=>s.project===project && s.branch===branch);
}
function itemsFor(sessions, overrides={}, options={}) {
  const items=[];
  for(const session of sessions){
    items.push({id:'session:'+session.key,type:'session',session});
    let group=null;
    for(const row of session.rows){
      const folded=overrides[row.id]?.classification==='process' || (overrides[row.id]?.classification!=='substantive' && row.folded);
      if(options.research){
        if(!folded && row.classification!=='environment')items.push({id:row.id,type:'message',row,session});
        else if(row.failed && row.classification!=='environment')items.push({id:'failure:'+row.id,type:'failure',row,session});
        for(const progress of options.progress||[])if(progress.anchor_event_id===(row.source_event_id||row.id)&&progress.workstream_id===session.branch)
          items.push({id:'progress:'+progress.id,type:'progress',progress,row,session,compact:!folded&&row.role==='assistant'});
        group=null;continue;
      }
      if(folded){
        if(!group){group={id:'process:'+row.id,type:'process',session,rows:[]};items.push(group);}
        group.rows.push(row);
      }else{group=null;items.push({id:row.id,type:'message',row,session});}
    }
  }
  return items;
}
function findItem(items,id){return items.findIndex(i=>i.id===id||i.row?.id===id||i.rows?.some(r=>r.id===id));}
function bodyAt(chunk,row){return row.kind==='message'?chunk[row.id]:chunk;}
function validate(data,identity){
  if(data?.schema_version!==1||data.project_id!==identity.project_id||!Array.isArray(data.sessions))throw Error('时间线版本或仓库身份不匹配');
  const seen=new Set();
  for(const s of data.sessions){if(!Array.isArray(s.rows))throw Error('时间线会话记录损坏');for(const r of s.rows){if(!r.id||seen.has(r.id))throw Error('时间线事件身份重复');seen.add(r.id);}}
  return data;
}
function safeBodyPath(path){return typeof path==='string'&&/^(系统视图|System)\/timeline\/(messages|process|search)\/[a-f0-9]{64}\.json$/.test(path);}
module.exports={scopedSessions,itemsFor,findItem,bodyAt,validate,safeBodyPath};
