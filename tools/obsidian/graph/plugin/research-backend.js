"use strict";
// Fixed executable + argv + JSON stdin. No shell or source-text interpolation.
const {spawn}=require('node:child_process');
function invoke(settings,operation,request={}){
  if(!settings?.python||!settings?.root) return Promise.reject(Error('尚未连接本地 Research Memory 后端，请运行 attach-obsidian。'));
  return new Promise((resolve,reject)=>{
    const child=spawn(settings.python,['-m','research_memory.cli','--root',settings.root,'research',operation,'--file','-'],
      {shell:false,windowsHide:true,env:{...process.env,PYTHONUTF8:'1',PYTHONIOENCODING:'utf-8'},stdio:['pipe','pipe','pipe']});
    let out='',err='',done=false;
    const timer=setTimeout(()=>{if(!done){child.kill();reject(Error('操作未返回。请保留请求 ID 并核对记录，不要重新创建请求。'));}},60000);
    child.stdout.on('data',b=>{out+=b.toString('utf8');});child.stderr.on('data',b=>{err+=b.toString('utf8');});
    child.on('error',e=>{done=true;clearTimeout(timer);reject(e);});
    child.on('close',code=>{done=true;clearTimeout(timer);try{if(code!==0){const message=JSON.parse(err);const e=Error(message.message);e.rejected=message.mutation_state==='rejected';reject(e);return;}resolve(JSON.parse(out));}catch(e){reject(Error(e.message||err||'后端返回无效'));}});
    child.stdin.on('error',()=>{});child.stdin.end(JSON.stringify(request));
  });
}
module.exports={invoke};
