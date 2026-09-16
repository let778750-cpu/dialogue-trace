"use strict";
const {ItemView, Modal, MarkdownRenderer, Notice, Component}=require('obsidian');
const TM=require('./timeline-model');
const TYPE='research-timeline-view';
const date=x=>Number.isFinite(Date.parse(x))?new Date(x).toLocaleString('zh-CN'):'时间未记录';
const roles={user:'用户',assistant:'AI',process:'技术记录',environment:'来源环境'};
const relations={derived_from:'来源',extends:'延伸',depends_on:'依赖',supports:'支持',contradicts:'反驳',refines:'细化',replaces:'替代',related_to:'相关',tests:'验证',adopts:'采用',rejects:'否决'};
function el(parent,tag,cls,text){const n=parent.createEl(tag,{cls});if(text!==undefined)n.textContent=String(text);return n;}
function button(parent,text,fn){const b=el(parent,'button','rt-button',text);b.type='button';b.addEventListener('click',()=>Promise.resolve(fn()).catch(e=>new Notice(e.message)));return b;}
function select(parent,label,values,value,fn){const s=el(parent,'select','rt-select');s.setAttribute('aria-label',label);for(const [id,title] of values){const o=el(s,'option','',title);o.value=id;}s.value=value;s.addEventListener('change',()=>fn(s.value));return s;}
class Reader extends Modal{
  constructor(view,row,body){super(view.app);this.view=view;this.row=row;this.body=body;this.renderer=new Component();}
  async onOpen(){this.renderer.load();this.modalEl.addClass('rt-reader');const c=this.contentEl;
    button(c,'返回时间线',()=>this.close());el(c,'h2','',roles[this.row.role]+(this.row.role==='environment'?' · 环境信息':' · 原始公开记录'));
    el(c,'p','rt-muted',date(this.row.occurred_at)+' · '+this.row.session);
    const body=el(c,'div','rt-full');await this.view.renderBody(body,this.row,this.body,this.renderer);
    const audit=el(c,'details','rt-provenance');el(audit,'summary','','来源定位与校验');
    el(audit,'pre','',JSON.stringify({event_id:this.row.id,source_hash:this.row.source_hash,source:this.row.source,sequence:this.row.source_sequence,origin:this.row.origin,captured_at:this.row.captured_at},null,2));
    if(this.row.paired_ids?.length)el(audit,'p','','有明确标识的工具关联：'+this.row.paired_ids.join('、'));
  }
  onClose(){this.renderer.unload();this.contentEl.empty();}
}
class TimelineView extends ItemView{
  constructor(leaf,plugin){super(leaf);this.plugin=plugin;this.cache=new Map();this.searchGeneration=0;this.renderGeneration=0;this.overrides=plugin.saved.timelineOverrides||={};this.closed=false;this.selected=new Set();this.includeTechnical=false;this.searchScope='branch';}
  getViewType(){return TYPE;}
  getDisplayText(){return '研究时间线';}
  getIcon(){return 'list';}
  async onOpen(){
    this.root=this.contentEl;this.root.addClass('research-timeline');
    try{await this.load();this.chooseScope();this.shell();await this.render();}
    catch(e){this.root.empty();el(this.root,'h2','','时间线暂不可用');el(this.root,'p','',e.message);button(this.root,'查看现有知识图谱',()=>this.plugin.openGraph());}
  }
  async load(){
    const adapter=this.app.vault.adapter;
    this.base=await adapter.exists('系统视图/research-timeline.json')?'系统视图':'System';
    const identity=JSON.parse(await adapter.read(this.base+'/research-memory-identity.json'));
    try{this.data=TM.validate(JSON.parse(await adapter.read(this.base+'/research-timeline.json')),identity);this.stale=false;}
    catch(error){if(this.data){this.stale=true;return;}this.data=TM.validate(JSON.parse(await adapter.read(this.base+'/research-timeline.previous.json')),identity);this.stale=true;}
  }
  chooseScope(project,branch){
    const saved=this.plugin.saved.timeline||={};
    const projects=this.data.projects.filter(p=>p.kind!=='example');
    this.project=project||saved.project||this.data.default_project_id;
    if(!this.data.projects.some(p=>p.id===this.project))this.project=projects[0]?.id||this.data.sessions[0]?.project;
    const branches=this.branchIds();
    this.branch=branch||saved.branch;if(!branches.includes(this.branch))this.branch=branches[0]||'';
    this.scope=this.project+'|'+this.branch;this.state=saved.scopes?.[this.scope]||{anchor:null,expanded:{}};this.state.expanded||={};
    this.resumeAnchor=this.state.anchor;this.sessions=TM.scopedSessions(this.data,this.project,this.branch);this.rebuildItems();
    const found=TM.findItem(this.items,this.state.anchor?.id);this.start=found<0?0:Math.max(0,found-5);this.end=this.start+50;
  }
  branchIds(){return [...new Set([...(this.data.workstreams||[]).filter(b=>b.project===this.project).map(b=>b.id),...this.data.sessions.filter(s=>s.project===this.project).map(s=>s.branch)])];}
  branchName(id){return id==='__unassigned__'?'待归线':(this.data.workstreams||[]).find(b=>b.id===id)?.name||this.data.branches.find(b=>b.id===id)?.name||id;}
  rebuildItems(){this.items=TM.itemsFor(this.sessions,this.overrides,{research:this.data.reading_mode==='research',progress:this.data.progress||[]});}
  shell(){
    this.root.empty();const head=el(this.root,'header','rt-head');
    const title=el(head,'div','rt-title');el(title,'strong','','研究时间线');el(title,'span','rt-muted','沿讨论顺序，找回研究思路');
    const nav=el(head,'div','rt-nav');
    select(nav,'研究项目',this.data.projects.map(p=>[p.id,p.name+(p.kind==='example'?'（示例）':'')]),this.project,p=>this.switchScope(p));
    const branches=this.branchIds();
    select(nav,'研究分支',branches.map(b=>[b,this.branchName(b)]),this.branch,b=>this.switchScope(this.project,b));
    button(nav,'管理研究线',()=>this.manage());button(nav,'归线所选消息',()=>this.routeSelection());
    button(nav,'回到开头',()=>this.jump(this.items[0]?.id));button(nav,'最近阅读',()=>this.jump(this.resumeAnchor?.id||this.items[0]?.id));
    button(nav,'刷新',()=>this.reload(true));
    const tools=el(head,'div','rt-nav');this.search=el(tools,'input','rt-search');this.search.placeholder='搜索研究原话与关键进展…';this.search.setAttribute('aria-label','搜索研究原话与关键进展');
    select(tools,'搜索范围',[['branch','当前研究线'],['project','当前项目'],['unassigned','待归线']],this.searchScope,value=>{this.searchScope=value;this.runSearch(this.search.value);});
    const technicalLabel=el(tools,'label','rt-muted','包含技术记录 ');const technical=el(technicalLabel,'input','');technical.type='checkbox';technical.checked=this.includeTechnical;technical.addEventListener('change',()=>{this.includeTechnical=technical.checked;this.runSearch(this.search.value);});
    this.search.addEventListener('input',()=>{clearTimeout(this.searchTimer);++this.searchGeneration;this.searchTimer=setTimeout(()=>this.runSearch(this.search.value),300);});
    this.search.addEventListener('keydown',e=>{if(e.key==='Escape'){this.search.value='';++this.searchGeneration;this.results.empty();}});
    const more=el(tools,'details','rt-more');el(more,'summary','','知识与显示');
    button(more,'查看已有局部图',()=>this.plugin.openGraph());button(more,'只看重点',()=>this.showBookmarks());
    button(more,'技术记录与来源环境',()=>this.showTechnical());button(more,'全部运行结果',()=>this.showRuns());
    this.status=el(head,'div','rt-status');this.updateStatus();
    this.results=el(this.root,'div','rt-results');
    const milestones=el(this.root,'details','rt-milestones');el(milestones,'summary','','关键研究节点');this.milestones(milestones);
    this.scroller=el(this.root,'div','rt-scroll');this.scroller.setAttribute('aria-label','研究对话时间线');
    this.scroller.addEventListener('scroll',()=>{if(this.rendering||this.closed)return;clearTimeout(this.saveTimer);this.saveTimer=setTimeout(()=>this.persist(),250);});
    this.root.classList.toggle('rt-wide',this.scroller.clientWidth>=960);
    this.resizeObserver?.disconnect();this.resizeObserver=new ResizeObserver(entries=>{const wide=entries[0].contentRect.width>=960;if(wide===this.root.classList.contains('rt-wide'))return;const a=this.rendering?null:this.captureAnchor();this.root.classList.toggle('rt-wide',wide);if(a)this.restoreAnchor(a);});this.resizeObserver.observe(this.scroller);
  }
  updateStatus(){const c=this.data.coverage;this.status.textContent=(this.stale?'正在显示上次可用版本 · ':'')+`${this.sessions.reduce((n,s)=>n+s.rows.length,0)} 条分支记录 · 最近采集 ${date(c.last_captured_at)} · 全库待整理 ${c.pending} 条`;
    this.status.title='这里只反映已采集记录；新任务自动采集覆盖尚未验证。';
    if(c.gaps?.some(g=>g.state!=='resolved'))this.status.textContent+=' · 存在采集缺口';
  }
  milestones(parent){
    const ids=new Set(this.sessions.flatMap(s=>s.rows.map(r=>r.id)));
    const labels={question:'问题',revision:'方案修正',decision:'决定',result:'实验结果'};
    for(const row of this.sessions.flatMap(s=>s.rows))if(labels[row.milestone]){const d=el(parent,'div','rt-milestone');button(d,`${labels[row.milestone]} · ${row.preview.slice(0,90)}`,()=>this.jump(row.id));}
    const types={question:'问题',idea:'候选想法',decision:'决定',experiment:'实验结果'};
    for(const n of this.data.knowledge){if(n.research_project_id!==this.project||n.workstream_id!==this.branch||!types[n.type])continue;
      const refs=[...new Set((n.sources||[]).map(s=>s.event_id).filter(id=>ids.has(id)))];if(!refs.length)continue;
      const d=el(parent,'details','rt-milestone');el(d,'summary','',`${types[n.type]} · ${n.title}`);
      for(const id of refs){const row=this.sessions.flatMap(s=>s.rows).find(r=>r.id===id);button(d,`${roles[row.role]} · ${date(row.occurred_at)}`,()=>this.jump(id));}
    }
    if(parent.children.length===1)el(parent,'p','rt-muted','尚无已整理的关键节点；原话仍完整可查。');
  }
  captureAnchor(){if(!this.scroller)return this.state?.anchor;const top=this.scroller.getBoundingClientRect().top;
    const row=[...this.scroller.querySelectorAll('[data-item-id]')].find(n=>n.getBoundingClientRect().bottom>top+4);
    return row?{id:row.dataset.itemId,offset:row.getBoundingClientRect().top-top}:this.state.anchor;
  }
  async persist(){if(!this.state||!this.scope)return;this.state.anchor=this.captureAnchor();
    const saved=this.plugin.saved.timeline||={};saved.scopes||={};saved.scopes[this.scope]=structuredClone(this.state);saved.project=this.project;saved.branch=this.branch;
    this.plugin.saved.timelineOverrides=this.overrides;await this.plugin.persistData();
  }
  async switchScope(project,branch){await this.persist();++this.searchGeneration;this.chooseScope(project,branch);this.shell();await this.render();}
  async render(anchor=this.state.anchor){
    this.rendering=true;clearTimeout(this.saveTimer);const generation=++this.renderGeneration;this.pageRenderer?.unload();this.pageRenderer=new Component();this.pageRenderer.load();
    this.scroller.empty();this.processGroups=new Map();
    if(this.start>0)button(this.scroller,`显示前面的记录（${this.start} 项）`,()=>{const a=this.captureAnchor();this.start=Math.max(0,this.start-50);return this.render(a);});
    const line=el(this.scroller,'div','rt-line');
    for(const item of this.items.slice(this.start,this.end)){
      if(item.type==='session'){const s=el(line,'section','rt-session');s.dataset.itemId=item.id;el(s,'strong','',`会话 · ${date(item.session.start)}`);el(s,'small','rt-muted',item.session.id);if(item.session.overlaps.length)el(s,'span','rt-overlap','与其他会话时间重叠，各会话内按原始顺序阅读');continue;}
      if(item.type==='process'){this.process(line,item);continue;}
      if(item.type==='progress'){this.progressCard(line,item);continue;}
      if(item.type==='failure'){const p=el(line,'section','rt-progress rt-failure');p.dataset.itemId=item.id;el(p,'span','','运行出现失败或中断；结果尚待核对。');button(p,'查看来源',()=>this.openSource(item.row.id));continue;}
      await this.card(line,item.row,generation);
      if(this.closed||generation!==this.renderGeneration)return;
    }
    if(!this.items.length)el(line,'p','rt-empty','此分支尚无已采集记录。');
    if(this.end<this.items.length)button(this.scroller,`继续显示（剩余 ${this.items.length-this.end} 项）`,()=>{const a=this.captureAnchor();this.end+=50;return this.render(a);});
    for(const group of this.processGroups.values())if(group.d.open){await group.load();const at=group.rows.findIndex(r=>r.id===anchor?.id);while(at>=group.shown)await group.load();}
    await new Promise(resolve=>requestAnimationFrame(resolve));if(generation!==this.renderGeneration||this.closed)return;
    this.root.classList.toggle('rt-wide',this.scroller.clientWidth>=960);if(anchor)this.restoreAnchor(anchor);this.rendering=false;
  }
  restoreAnchor(anchor){const n=[...this.scroller.querySelectorAll('[data-item-id]')].find(n=>n.dataset.itemId===anchor.id);if(n)this.scroller.scrollTop+=n.getBoundingClientRect().top-this.scroller.getBoundingClientRect().top-(anchor.offset||0);}
  process(parent,item){
    const wrap=el(parent,'section','rt-process');wrap.dataset.itemId=item.id;
    const d=el(wrap,'details','');el(d,'summary','',`${item.rows.length} 条过程 / 操作记录${item.rows.some(r=>r.failed)?' · 含失败或中断':''}`);
    const body=el(d,'div','rt-process-list');let shown=0,loading=null;const generation=this.renderGeneration;
    const load=()=>{if(loading)return loading;loading=(async()=>{next.remove();const batch=item.rows.slice(shown,shown+50);for(const row of batch){if(generation!==this.renderGeneration||this.closed)return;await this.card(body,row,generation);}shown+=batch.length;if(shown<item.rows.length)body.append(next);})().finally(()=>{loading=null;});return loading;};
    const next=button(body,'继续显示过程',load);next.remove();d.addEventListener('toggle',()=>{if(d.open&&!shown)load().catch(e=>new Notice(e.message));});
    d.open=!!this.state.expanded[item.id];d.addEventListener('toggle',()=>{this.state.expanded[item.id]=d.open;if(!this.rendering)this.persist();});
    this.processGroups||=new Map();this.processGroups.set(item.id,{d,load,get shown(){return shown;},rows:item.rows});
  }
  async card(parent,row,generation){
    const wrap=el(parent,'article','rt-row rt-'+row.role);wrap.dataset.itemId=row.id;const card=el(wrap,'div','rt-card');
    const meta=el(card,'div','rt-card-meta');el(meta,'strong','',roles[row.role]||row.author);el(meta,'time','',date(row.occurred_at));
    if(row.reference){el(card,'small','rt-muted','引用自研究线：'+this.branchName(row.primary_branch));el(card,'p','',row.preview.slice(0,180));button(card,'前往原消息',()=>this.openSource(row.source_event_id));return;}
    if(row.kind==='message'&&row.classification!=='environment'){const checkbox=el(meta,'input','');checkbox.type='checkbox';checkbox.setAttribute('aria-label','选择消息以调整研究线');checkbox.checked=this.selected.has(row.id);checkbox.addEventListener('change',()=>checkbox.checked?this.selected.add(row.id):this.selected.delete(row.id));}
    if(row.failed)el(meta,'span','rt-failure','失败 / 中断');if(this.overrides[row.id]?.bookmark)el(meta,'span','rt-bookmark','重点');
    const text=el(card,'div','rt-preview',row.preview||'附件或公开过程记录');
    if(row.kind==='message'&&row.role!=='environment')el(card,'small','rt-muted',row.excerpt?'原话节选 · 已省略其他内容，全文可查':'原话预览 · 超出六行的内容已折叠');
    if(row.order_uncertain)el(card,'small','rt-muted','部分顺序或时间信息未记录');
    if(row.attachment_count)el(card,'small','rt-muted',`${row.attachment_count} 个来源附件`);
    const actions=el(card,'div','rt-actions');
    const toggle=async(save=true)=>{
      if(text.dataset.expanded){text.empty();text.textContent=row.preview;text.className='rt-preview';delete text.dataset.expanded;inline.textContent='展开全文';this.state.expanded[row.id]=false;}
      else{const content=await this.readBody(row);if(this.closed||generation!==this.renderGeneration)return;text.empty();text.className='rt-full';text.dataset.expanded='1';await this.renderBody(text,row,content,this.pageRenderer);inline.textContent='收起全文';this.state.expanded[row.id]=true;}
      if(save)await this.persist();
    };
    const inline=button(actions,'展开全文',()=>toggle());
    if(this.state.expanded[row.id])await toggle(false);
    button(actions,row.role==='environment'?'环境信息 · 宽幅阅读':'原话 · 宽幅阅读',async()=>new Reader(this,row,await this.readBody(row)).open());
    button(actions,'类型与来源详情',()=>this.inspectSource(row.id));
    if(row.knowledge.length)button(actions,`相关知识 ${row.knowledge.length}`,()=>this.showKnowledge(row));
    const m=el(actions,'details','rt-card-more');el(m,'summary','','标记');
    button(m,this.overrides[row.id]?.bookmark?'取消重点':'标为重点',async()=>{this.overrides[row.id]={...this.overrides[row.id],bookmark:!this.overrides[row.id]?.bookmark};const a=this.captureAnchor();await this.persist();await this.render(a);});
    button(m,'作为研究内容显示',()=>this.classify(row,'substantive'));button(m,'作为过程折叠',()=>this.classify(row,'process'));button(m,'恢复默认分类',()=>this.classify(row,null));
  }
  async classify(row,classification){const a={id:row.id,offset:0};this.overrides[row.id]={...this.overrides[row.id],classification};await this.persist();this.rebuildItems();if(TM.findItem(this.items,a.id)>=0)await this.jump(a.id);else await this.render();}
  async readBody(row){if(!TM.safeBodyPath(row.body_path))throw Error('来源内容路径无效');
    let chunk=this.cache.get(row.body_path);if(!chunk){chunk=await this.readChunk(row.body_path);this.cache.set(row.body_path,chunk);if(this.cache.size>20)this.cache.delete(this.cache.keys().next().value);}
    const body=TM.bodyAt(chunk,row);if(!body||body.source_hash!==row.source_hash)throw Error('原话缺失或来源哈希不匹配，未生成替代内容');return body;
  }
  async readChunk(path){if(!TM.safeBodyPath(path))throw Error('来源内容路径无效');const raw=await this.app.vault.adapter.read(path);const expected=path.split('/').at(-1).slice(0,-5);if(require('crypto').createHash('sha256').update(raw).digest('hex')!==expected)throw Error('来源文件内容校验失败');return JSON.parse(raw);}
  async renderBody(parent,row,body,component){
    if(row.kind==='message')await MarkdownRenderer.render(this.app,body.text,parent,'',component);else el(parent,'pre','rt-log',body.text);
    for(const a of body.attachments||[]){const p=el(parent,'div','rt-attachment','来源附件 · '+a.type);el(p,'p','rt-muted','本地附件未提供；请在原会话核对。');el(p,'code','',typeof a.reference==='string'?a.reference:JSON.stringify(a.reference||{attachment_hash:a.attachment_hash,availability:a.availability||'host_reference'}));}
    if(Object.keys(body.context||{}).length){const d=el(parent,'details','');el(d,'summary','','公开记录中的条件与补充');el(d,'pre','',JSON.stringify(body.context,null,2));}
  }
  async jump(id){if(!id)return;const index=TM.findItem(this.items,id);if(index<0){new Notice('这条记录不在当前研究分支');return;}
    this.start=Math.max(0,index-5);this.end=this.start+50;this.processGroups=new Map();await this.render(null);
    const item=this.items[index];if(item.type==='process'&&id!==item.id){const group=this.processGroups.get(item.id);group.d.open=true;const target=group.rows.findIndex(r=>r.id===id);while(group.shown<=target)await group.load();}
    const node=[...this.scroller.querySelectorAll('[data-item-id]')].find(n=>n.dataset.itemId===id)||[...this.scroller.querySelectorAll('[data-item-id]')].find(n=>n.dataset.itemId===item.id);
    if(node){this.scroller.scrollTop+=node.getBoundingClientRect().top-this.scroller.getBoundingClientRect().top;node.addClass('rt-located');setTimeout(()=>node.removeClass('rt-located'),1600);}await this.persist();
  }
  async runSearch(query){
    const generation=++this.searchGeneration;this.results.empty();query=query.trim().toLocaleLowerCase();if(!query)return;
    const progress=el(this.results,'small','rt-muted','正在搜索研究记录…');let found=0,read=0,missing=0;
    const sessions=this.searchScope==='branch'?this.sessions:this.data.sessions.filter(s=>s.project===this.project&&(this.searchScope!=='unassigned'||s.branch==='__unassigned__'));
    const rows=sessions.flatMap(s=>s.rows).filter(r=>!r.reference&&(this.includeTechnical||((this.overrides[r.id]?.classification==='substantive'||!r.folded)&&r.classification!=='environment')));
    for(const row of rows){if(this.closed||generation!==this.searchGeneration)return;
      let text;try{
        if(row.search_path){if(!TM.safeBodyPath(row.search_path))throw Error('搜索来源路径无效');
          if(this.searchChunkPath!==row.search_path){this.searchChunk=await this.readChunk(row.search_path);this.searchChunkPath=row.search_path;}
          text=this.searchChunk[row.id];if(typeof text!=='string')throw Error('搜索来源缺失');
        }else text=(await this.readBody(row)).text;
      }catch(e){missing++;continue;}
      if(generation!==this.searchGeneration)return;
      const at=text.toLocaleLowerCase().indexOf(query);
      if(at>=0){const snippet=text.slice(Math.max(0,at-25),at+100).replace(/\s+/g,' ');button(this.results,`${roles[row.role]} · ${date(row.occurred_at)} · ${snippet}`,()=>this.openSource(row.id));if(++found===100)break;}
      if(++read%50===0){progress.textContent=`正在查找 ${read}/${rows.length}`;await new Promise(resolve=>setTimeout(resolve,0));}
    }
    for(const p of this.data.progress||[]){if(p.project!==this.project||(this.searchScope==='branch'&&p.workstream_id!==this.branch)||this.searchScope==='unassigned')continue;if((p.title+' '+(p.summary||'')).toLocaleLowerCase().includes(query)){button(this.results,'关键进展 · '+p.title,()=>this.progressDetail(p));found++;}}
    progress.textContent=(found>=100?'显示前 100 个匹配，请缩小关键词':`找到 ${found} 条记录`)+(this.includeTechnical?' · 包含技术记录':'')+(missing?` · ${missing} 条来源无法读取，结果不完整`:'');
  }
  async backend(operation,spec={}){
    const call=require('./research-backend').invoke;
    return call(this.plugin.saved.backend,operation,spec);
  }
  async change(operation,spec){
    if(this.plugin.saved.pendingResearchRequest)throw Error('请先在研究线管理中核对上一次操作结果。');
    // Retain the exact request in plugin state before dispatch, including uncertain attempts.
    const request={...spec,request_id:require('crypto').randomUUID(),expected_version:this.data.research_version||0};
    this.plugin.saved.pendingResearchRequest={operation,request};await this.plugin.persistData();
    let result;try{result=await this.backend(operation,request);}catch(error){if(error.rejected){delete this.plugin.saved.pendingResearchRequest;await this.plugin.persistData();}throw error;}delete this.plugin.saved.pendingResearchRequest;await this.plugin.persistData();
    this.selected.clear();await this.reload(true);return result;
  }
  dialog(title){const m=new Modal(this.app);m.modalEl.addClass('rt-reader');el(m.contentEl,'h2','',title);button(m.contentEl,'关闭',()=>m.close());m.open();return m;}
  async openSource(id){
    const row=this.data.sessions.flatMap(s=>s.rows).find(r=>r.id===id);
    if(!row){new Notice('来源未进入当前投影，请核对原始事件。');return;}
    if(row.project!==this.project||row.branch!==this.branch)await this.switchScope(row.project,row.branch);
    if(TM.findItem(this.items,id)>=0){await this.jump(id);return;}
    new Reader(this,row,await this.readBody(row)).open();
  }
  inspectSource(id){const row=this.data.sessions.flatMap(s=>s.rows).find(r=>r.id===id);if(!row)throw Error('来源未进入当前投影');new (require('./event-inspector').EventInspector)(this,row).open();}
  showTechnical(){
    const m=this.dialog('技术记录与来源环境');el(m.contentEl,'p','rt-muted','按需读取；这些记录不代表用户研究提示，也不代表实验已成功。');
    const rows=this.sessions.flatMap(s=>s.rows).filter(r=>r.folded||r.classification==='environment');let offset=0;
    const list=el(m.contentEl,'div','');const more=button(m.contentEl,'继续显示',()=>load());
    const load=()=>{for(const row of rows.slice(offset,offset+50))button(list,`${roles[row.role]} · ${date(row.occurred_at)} · ${row.preview.slice(0,75)}`,()=>this.inspectSource(row.id));offset+=50;more.hidden=offset>=rows.length;};load();
  }
  showRuns(){const m=this.dialog('运行结果');for(const run of this.data.runs||[]){if(run.project!==this.project||run.branch!==this.branch)continue;const d=el(m.contentEl,'details','rt-progress');el(d,'summary','',run.purpose+' · '+(run.status==='completed'?'运行完成，结果待解读':run.status));el(d,'pre','rt-log',JSON.stringify(run,null,2));}if(m.contentEl.children.length===2)el(m.contentEl,'p','','尚无结构化运行。');}
  progressCard(parent,item){const p=el(parent,'section','rt-progress');p.dataset.itemId=item.id;
    el(p,item.compact?'span':'strong','',item.progress.title);el(p,'small','rt-muted','AI 归纳 · '+date(item.progress.updated_at));
    if(!item.compact)el(p,'p','',item.progress.summary||'');if(item.progress.needs_review)el(p,'span','rt-failure','来源或归属待复核');
    button(p,'结果与依据',()=>this.progressDetail(item.progress));
  }
  progressDetail(progress){const m=this.dialog(progress.title);el(m.contentEl,'p','rt-muted','AI 归纳');el(m.contentEl,'p','',progress.summary||'');
    for(const [key,label] of [['known','已知'],['unknown','未知'],['next_steps','下一步'],['conditions','条件'],['limitations','限制'],['restore_conditions','恢复条件']])if(progress[key]){el(m.contentEl,'h3','',label);el(m.contentEl,'p','',Array.isArray(progress[key])?progress[key].join('；'):progress[key]);}
    if(Object.keys(progress.facts||{}).length){el(m.contentEl,'h3','','运行事实');el(m.contentEl,'pre','rt-log',JSON.stringify(progress.facts,null,2));}
    if(progress.needs_review)el(m.contentEl,'p','rt-failure','来源或归属发生变化，请复核后修订。');
    for(const id of progress.event_ids)button(m.contentEl,'来源 · '+id.slice(0,15),async()=>{m.close();await this.openSource(id);});
  }
  async manage(){const m=this.dialog('研究线管理');el(m.contentEl,'p','rt-muted','这里调整研究线；浏览选择不会改变 Codex 当前任务的绑定。');
    const pending=this.plugin.saved.pendingResearchRequest;
    if(pending){el(m.contentEl,'p','rt-failure','有一次尚未确认结果的操作。核对并重试同一请求后，再提交新修改。');button(m.contentEl,'核对／重试原请求',async()=>{try{await this.backend(pending.operation,pending.request);}catch(error){if(!error.rejected)throw error;new Notice(error.message);}delete this.plugin.saved.pendingResearchRequest;await this.plugin.persistData();await this.reload(true);m.close();});return;}
    const field=(parent,label,value='')=>{const l=el(parent,'label','rt-field',label);const input=el(l,'input','');input.value=value;return input;};
    const name=field(m.contentEl,'新研究线名称');const goal=field(m.contentEl,'研究目标');
    button(m.contentEl,'创建研究线',async()=>{await this.change('workstream.create',{id:'line_'+require('crypto').randomUUID().replaceAll('-',''),name:name.value,goal:goal.value,project:this.project});m.close();});
    for(const line of (this.data.workstreams||[]).filter(b=>b.project===this.project)){
      const d=el(m.contentEl,'details','rt-progress');el(d,'summary','',line.name+' · '+({active:'进行中',paused:'已暂停',finished:'已结束'}[line.status]||line.status));
      const n=field(d,'名称',line.name),g=field(d,'目标',line.goal);let status=line.status;
      select(d,'状态',[['active','进行中'],['paused','暂停'],['finished','结束']],status,v=>status=v);
      button(d,'保存',async()=>{await this.change('workstream.update',{id:line.id,name:n.value,goal:g.value,status,branch_version:line.version});m.close();});
    }
    el(m.contentEl,'h3','','待确认归线建议');
    for(const suggestion of this.data.proposals||[]){if(suggestion.status!=='pending')continue;const d=el(m.contentEl,'div','rt-progress');el(d,'p','',`${suggestion.spec.event_ids.length} 条消息 → ${this.branchName(suggestion.spec.workstream_id)}`);
      for(const id of suggestion.spec.event_ids)button(d,'查看来源',()=>this.openSource(id));
      button(d,'采用归线',async()=>{await this.change('route.apply',suggestion.spec);m.close();});button(d,'不采用',async()=>{await this.change('route.reject',{proposal_id:suggestion.id});m.close();});
    }
    const latest=[...(this.data.history||[])].reverse().find(h=>h.operation==='route.apply');
    if(latest)button(m.contentEl,'撤销最近归线修改',async()=>{await this.change('route.undo',{undo_request_id:latest.request_id});m.close();});
  }
  routeSelection(){const rows=this.data.sessions.flatMap(s=>s.rows).filter(r=>this.selected.has(r.id)&&!r.reference);
    if(!rows.length){new Notice('请先选择同一会话中连续的完整消息。');return;}
    const m=this.dialog(`调整 ${rows.length} 条消息的研究线`);let target=this.branch==='__unassigned__'?null:this.branch;
    select(m.contentEl,'主研究线',[['','待归线'],...(this.data.workstreams||[]).filter(b=>b.project===this.project).map(b=>[b.id,b.name])],target||'',v=>target=v||null);
    const refs=new Set();el(m.contentEl,'p','','同时引用到其他研究线：');for(const b of (this.data.workstreams||[]).filter(b=>b.project===this.project)){const label=el(m.contentEl,'label','rt-field',b.name);const input=el(label,'input','');input.type='checkbox';input.addEventListener('change',()=>input.checked?refs.add(b.id):refs.delete(b.id));}
    el(m.contentEl,'p','rt-muted','原消息和科学结论保持不变；相关工具记录随区间归属，已有进展将标为待复核。');
    button(m.contentEl,'应用归属',async()=>{await this.change('route.apply',{event_ids:rows.map(r=>r.id),source_hashes:Object.fromEntries(rows.map(r=>[r.id,r.source_hash])),workstream_id:target,references:[...refs]});m.close();});
  }
  showBookmarks(){this.results.empty();const rows=this.sessions.flatMap(s=>s.rows).filter(r=>this.overrides[r.id]?.bookmark);for(const r of rows)button(this.results,`${roles[r.role]} · ${r.preview.slice(0,90)}`,()=>this.openSource(r.id));if(!rows.length)el(this.results,'p','rt-muted','尚未标记重点。');}
  showKnowledge(row){
    const modal=new Modal(this.app);modal.modalEl.addClass('rt-reader');const p=modal.contentEl;button(p,'返回时间线',()=>modal.close());el(p,'h2','','相关知识与依据');
    for(const id of row.knowledge){const n=this.data.knowledge.find(n=>n.id===id);if(!n)continue;el(p,'h3','',n.title);el(p,'p','',n.body);el(p,'small','rt-muted','提出者：'+(n.authors||[]).join('、'));
      if(n.needs_reconciliation)el(p,'p','rt-failure','知识笔记有待核对的人工修改，请打开完整笔记核查。');
      button(p,'完整知识笔记',()=>this.plugin.openExisting(n.path));button(p,'局部关系图',async()=>{modal.close();await this.plugin.openGraph(id);});
      const edges=this.data.relations.filter(e=>e.source===id||e.target===id);for(const e of edges){const a=this.data.knowledge.find(n=>n.id===e.source),b=this.data.knowledge.find(n=>n.id===e.target);el(p,'p','',`${a?.title||e.source} — ${relations[e.type]||e.type} ${e.type==='related_to'?'—':'→'} ${b?.title||e.target}`);el(p,'blockquote','',e.basis||'尚未记录关系依据');if(e.conditions?.length)el(p,'p','',e.conditions.join('；'));}
    }modal.open();
  }
  async reload(manual=false){
    const anchor=this.captureAnchor(),revision=this.data.revision;await this.load();if(this.data.revision===revision){this.updateStatus();return;}
    ++this.searchGeneration;this.cache.clear();this.chooseScope(this.project,this.branch);this.state.anchor=anchor;this.shell();const i=TM.findItem(this.items,anchor?.id);this.start=i<0?0:Math.max(0,i-5);this.end=this.start+50;await this.render(anchor);this.status.textContent+=' · 记录已更新，阅读位置已保留';
  }
  async onClose(){await this.persist();this.closed=true;++this.searchGeneration;++this.renderGeneration;clearTimeout(this.searchTimer);clearTimeout(this.saveTimer);this.resizeObserver?.disconnect();this.pageRenderer?.unload();this.cache.clear();}
}
module.exports={TimelineView,TYPE};
