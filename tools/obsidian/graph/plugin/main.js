/* Research Memory graph adapter. GPL-3.0. Reuses Juggl's public createJuggl API. */
"use strict";
const {Plugin, ItemView, Notice, TFile} = require("obsidian");
const {createHash} = require("node:crypto");
const {ResearchGraphModel} = require("./model");
const Dialogue = require("./dialogue");
const Dynamic = require("./dynamic");
const Timeline = require("./timeline");
const VIEW = "research-graph-view", DATA = "系统视图/research-graph.json", LEGACY_DATA = "System/research-graph.json";
const TYPES = {question:"问题", idea:"候选想法", evidence:"证据", experiment:"实验", task:"验证任务", decision:"决策"};
const RELS = {derived_from:"来源", extends:"延伸", depends_on:"依赖", supports:"支持", contradicts:"反驳", refines:"细化", replaces:"替代", related_to:"相关", tests:"验证", adopts:"采用", rejects:"否决"};
const REVIEWS = {unreviewed:"未审阅", accepted:"人工认可", rejected:"未认可", needs_revision:"待修订"};
const EVIDENCE = {unassessed:"证据待评估", unsupported:"尚无支持", supported:"有证据支持", mixed:"证据不一致", contradicted:"存在反证"};
const AUTHORS={user:'用户提出',assistant:'AI 提出',shared:'共同提出',unknown:'归属待核对'};
const AUTHOR_COLORS={user:'#3a7eb8',assistant:'#9a6eb6',shared:'#399b88',unknown:'#8994a3'};
const authorGroup=n=>Dialogue.group({...n,type:'idea'});
const COLORS = {question:"#3266ad", idea:"#8364ab", evidence:"#367d69", experiment:"#be8235", task:"#667b8c", decision:"#bd6666"};
const sha = text => createHash("sha256").update(text, "utf8").digest("hex");
function el(parent, tag, cls, text) { const x=parent.createEl(tag,{cls}); if(text!==undefined) x.textContent=String(text); return x; }
function button(parent, label, callback) { const b=el(parent,"button","rg-button",label); b.type="button"; b.addEventListener("click",()=>Promise.resolve(callback()).catch(e=>new Notice(e.message))); return b; }
function select(parent, label, values, value, callback) {
  const wrap=el(parent,"label","rg-select"), caption=el(wrap,"span","",label), input=el(wrap,"select","");
  input.setAttribute("aria-label",label);
  for(const [key,title] of Object.entries(values)) { const o=el(input,"option","",title); o.value=key; }
  input.value=value||""; input.addEventListener("change",()=>callback(input.value)); return input;
}

class GraphView extends ItemView {
  constructor(leaf, plugin) { super(leaf); this.plugin=plugin; this.history=[]; this.closed=false; this.saveTimer=null; this.renderToken=0; }
  getViewType() { return VIEW; }
  getDisplayText() { return "科研图谱"; }
  getIcon() { return "network"; }
  async onOpen() {
    this.closed=false; this.containerEl.children[1].empty(); this.containerEl.children[1].addClass("research-graph-content"); this.root=el(this.containerEl.children[1],"div","rg-root");
    try {
      this.graph=await this.plugin.readGraph();
      const project=this.graph.default_project_id||this.graph.project_id;
      const saved={...(this.plugin.saved.views?.[project] || {}),project};
      if(!saved.dynamicIntroduced){if(!saved.layoutMode||saved.layoutMode==='dialogue')saved.layoutMode='dynamic';saved.dynamicIntroduced=true;}
      this.model=new ResearchGraphModel(this.graph,saved);
      this.history=(saved.history||[]).slice(-30);
      this.drawShell(); await this.makeGraph();
    } catch(e) { this.showError(e); }
  }
  showError(e) { if(this.root) { this.root.empty(); el(this.root,"h3","","图谱暂不可用"); el(this.root,"p","",e.message); el(this.root,"p","rg-muted","研究笔记与原始记录仍保存在知识库中。"); } }
  drawShell() {
    const head=el(this.root,"div","rg-head");
    el(head,"strong","","科研图谱");
    this.count=el(head,"span","rg-muted","");
    button(head,"适应视图",()=>this.fitView());
    this.arrangeButton=button(head,"整理布局",()=>{this.remember(); this.arrange();});
    this.motionButton=button(head,"动态开启",()=>{this.model.state.motionPaused=!this.model.state.motionPaused;if(this.model.state.motionPaused){this.stopDynamic();this.routeDynamic();}else this.startDynamic();this.updateMotion();this.scheduleSave();});
    button(head,"刷新",()=>this.reload());
    this.detailsToggle=button(head,"收起详情",()=>this.toggleDetails());
    const orientation=el(this.root,'div','rg-orientation');
    const entryRow=el(orientation,'div','rg-location-row');this.entryLabel=el(entryRow,'strong','rg-entry-label');
    this.homeButton=button(entryRow,'回到入口',()=>{this.remember();this.model.returnToEntry();this.render(false);this.fitView();});
    button(entryRow,'其他问题',()=>this.overview());
    const currentRow=el(orientation,'div','rg-location-row');this.currentLabel=el(currentRow,'span','rg-current-label');
    this.backButton=button(currentRow,'返回上一步',()=>this.back());
    const more=el(currentRow,'details','rg-more');el(more,'summary','','更多');const menu=el(more,'div','rg-more-menu');
    for(const [label,action] of [['项目概览',()=>this.overview()],['浏览足迹',()=>this.showTrail()],['来源与演变',()=>this.showLineage()],['来源时间线',()=>this.showTimeline()]])
      button(menu,label,()=>{more.open=false;action();});
    this.layoutSelect=select(menu,'布局',{dynamic:'动态知识图谱',dialogue:'双方分区（固定）',entry:'按入口分层',network:'局部网络'},this.model.state.layoutMode,value=>{more.open=false;this.changeLayout(value);});
    const controls=el(this.root,"div","rg-controls");
    if(this.graph.projects){
      this.projectSelect=select(controls,'研究项目',Object.fromEntries(this.graph.projects.map(p=>[p.id,p.name+(p.kind==='example'?'（示例）':'')])),this.model.state.project,v=>this.switchProject(v));
      button(head,'项目首页',()=>this.plugin.openExisting(this.graph.projects.find(p=>p.id===this.model.state.project).path+'/项目首页.md'));
    }
    this.search=el(controls,"input","rg-search"); this.search.placeholder="查找问题或想法…"; this.search.setAttribute("aria-label","查找问题或想法");
    this.search.addEventListener("input",()=>this.searchResults());
    this.search.addEventListener("keydown",e=>{if(e.key==="Escape"){this.search.value="";this.results.empty();}});
    const branches=this.branchOptions();
    this.branchSelect=select(controls,"研究分支",branches,this.model.state.workstream,value=>this.switchBranch(value).catch(e=>new Notice(e.message)));
    this.labelSelect=select(controls,"关系文字",{auto:"自动",all:"全部",adjacent:"所选实体周围",selected:"所选连线"},this.model.state.labelMode||"auto",value=>{this.model.state.labelMode=value;this.updateLabels();this.scheduleSave();});
    this.results=el(this.root,"div","rg-results");
    const filters=el(this.root,"details","rg-filters"); el(filters,"summary","","筛选实体与关系"); const fields=el(filters,"div","rg-filter-fields");
    const change=(key,val)=>{this.remember();this.model.state.filters[key]=val;this.render(false);};
    select(fields,"实体",{"":"全部类型",...TYPES},this.model.state.filters.type,v=>change("type",v));
    select(fields,"人工审阅",{"":"全部审阅状态",...REVIEWS},this.model.state.filters.review,v=>change("review",v));
    select(fields,"证据",{"":"全部证据状态",...EVIDENCE},this.model.state.filters.evidence,v=>change("evidence",v));
    select(fields,"关系",{"":"全部关系",...RELS},this.model.state.filters.relation,v=>change("relation",v));
    const cross=el(fields,"label","rg-check"), checkbox=el(cross,"input",""); checkbox.type="checkbox";checkbox.checked=!!this.model.state.filters.crossBranch;
    el(cross,"span","","显示跨分支关联"); checkbox.addEventListener("change",()=>change("crossBranch",checkbox.checked));
    if(this.graph.projects){
      const label=el(fields,'label','rg-cross-project'),check=el(label,'input','');check.type='checkbox';check.checked=!!this.model.state.filters.crossProject;
      el(label,'span','','显示跨项目关联（包含示例）');check.addEventListener('change',()=>change('crossProject',check.checked));
    }
    this.notice=el(this.root,"div","rg-notice");
    const body=el(this.root,"div","rg-body"),stage=el(body,'div','rg-stage'); this.canvas=el(stage,"div","rg-canvas"); this.canvas.setAttribute("aria-label","局部研究实体图");
    this.zones=el(stage,'div','rg-zones');
    this.motionStatus=el(stage,'div','rg-motion-status');this.motionStatus.setAttribute('role','status');
    this.overviewPane=el(stage,'div','rg-overview');this.overviewPane.hidden=true;
    this.details=el(body,"aside","rg-details"); this.details.setAttribute("aria-label","实体和关系详情");
    const legend=this.legend=el(this.root,"div","rg-legend");
    for(const [kind,label] of Object.entries(TYPES)) {const item=el(legend,"span","",label);item.style.setProperty("--rg-color",COLORS[kind]);}
    el(legend,"span","rg-tip","单击查看详情 · 展开按钮增加关联 · 拖动固定位置");
  }
  toggleDetails(){this.model.state.detailsCollapsed=!this.model.state.detailsCollapsed;this.updateDetailsVisibility();this.scheduleSave();}
  updateDetailsVisibility(){this.root.classList.toggle('rg-details-hidden',!!this.model.state.detailsCollapsed);this.detailsToggle.textContent=this.model.state.detailsCollapsed?'展开详情':'收起详情';}
  branchOptions(){return Object.fromEntries([...new Set(this.graph.nodes.filter(n=>this.model.inProject(n)).map(n=>n.workstream_id))].map(b=>[b,this.graph.branches?.find(x=>x.id===b)?.name||b]));}
  async switchProject(project){
    await this.persist();clearTimeout(this.saveTimer);
    const saved={...(this.plugin.saved.views[project]||{}),project};
    this.history=(saved.history||[]).slice(-30);if(!saved.dynamicIntroduced){if(!saved.layoutMode||saved.layoutMode==='dialogue')saved.layoutMode='dynamic';saved.dynamicIntroduced=true;}
      this.model=new ResearchGraphModel(this.graph,saved);
    this.search.value='';this.results.empty();this.render(!this.model.state.viewport);
    if(this.model.state.viewport){this.cy.zoom(this.model.state.viewport.zoom);this.cy.pan(this.model.state.viewport.pan);}
  }
  async switchBranch(workstream){
    await this.persist();clearTimeout(this.saveTimer);
    const project=this.model.state.project,saved={...(this.plugin.saved.branchViews?.[project]?.[workstream]||{}),project,workstream};
    this.history=(saved.history||[]).slice(-30);if(!saved.dynamicIntroduced){if(!saved.layoutMode||saved.layoutMode==='dialogue')saved.layoutMode='dynamic';saved.dynamicIntroduced=true;}
      this.model=new ResearchGraphModel(this.graph,saved);
    this.search.value='';this.results.empty();this.render(!this.model.state.viewport);
    if(this.model.state.viewport){this.cy.zoom(this.model.state.viewport.zoom);this.cy.pan(this.model.state.viewport.pan);}
  }
  updateLocation(){
    const state=this.model.state,entry=this.model.nodes.get(state.entry),selected=this.model.nodes.get(state.selected);
    this.entryLabel.textContent='研究入口：'+(entry?.title || (this.model.entryMissing?'原入口已失效，请选择问题':'尚未选择问题'));
    this.currentLabel.textContent='当前查看：'+(state.mode==='overview'?'项目概览':selected?.title||'尚无知识记录');
    this.entryLabel.title=this.entryLabel.textContent;this.currentLabel.title=this.currentLabel.textContent;
    this.homeButton.disabled=!entry;this.backButton.disabled=!this.history.length;this.layoutSelect.value=state.layoutMode;
  }
  overview(){this.remember();this.model.overview();this.render(false);}
  enterQuestion(id){this.remember();this.model.chooseEntry(id);this.render(false);this.fitView();}
  pagedList(parent,items,render,size=30){
    const list=el(parent,'div','rg-paged-list');let end=0;
    const next=button(parent,'显示更多',()=>load());
    const load=()=>{for(const item of items.slice(end,end+size))render(list,item);end+=size;next.hidden=end>=items.length;next.textContent=`还有 ${Math.max(0,items.length-end)} 项 · 继续显示`;};load();
  }
  showOverview(){
    const pane=this.overviewPane;pane.empty();const project=this.graph.projects?.find(p=>p.id===this.model.state.project);
    el(pane,'h2','',project?.name||'研究概览');el(pane,'p','rg-muted',project?.goal||'从问题进入局部图；所有记录均可查找。');
    const groups=this.model.overviewGroups(),registered=new Set(this.model.registeredEntries().map(n=>n.id));
    el(pane,'h3','',`入口问题 · ${groups.questions.length}`);
    this.pagedList(pane,groups.questions,(list,n)=>{
      const item=el(list,'div','rg-overview-item');button(item,n.title,()=>this.enterQuestion(n.id));
      el(item,'small','rg-muted',(registered.has(n.id)?'已登记入口 · ':'可从此问题进入 · ')+(n.display?.branch||n.workstream_id));
    });
    if(!groups.questions.length)el(pane,'p','','尚无问题记录，可先查看项目首页或下方现有记录。');
    const details=el(pane,'details','rg-section');el(details,'summary','',`未与问题建立联系的记录 · ${groups.detached.length}`);
    if(!groups.questions.length)details.open=true;
    this.pagedList(details,groups.detached,(list,n)=>button(list,`${TYPES[n.type]} · ${n.title}`,()=>this.focus(n.id)));
    const all=el(pane,'details','rg-section');el(all,'summary','',`全部记录 · ${this.model.projectNodes().length}`);
    this.pagedList(all,this.model.projectNodes(),(list,n)=>button(list,`${TYPES[n.type]} · ${n.title}`,()=>n.type==='question'?this.enterQuestion(n.id):this.focus(n.id)));
  }
  auxiliary(title){
    ++this.renderToken;this.details.empty();el(this.details,'h2','',title);
    if(this.model.state.selected)button(this.details,'返回实体详情',()=>this.showNode(this.model.nodes.get(this.model.state.selected)));
  }
  showTrail(){
    this.auxiliary('浏览足迹');el(this.details,'p','rg-muted','最近 100 次实体访问；这是浏览记录，不表示研究的发生顺序。');
    this.pagedList(this.details,[...this.model.state.trail].reverse(),(list,row)=>{
      const n=this.model.nodes.get(row.id);if(!n)return;const item=el(list,'div','rg-overview-item');
      button(item,n.title,()=>this.focus(n.id));el(item,'small','rg-muted',new Date(row.at).toLocaleString());
    });
  }
  showLineage(){
    this.auxiliary('来源与演变');const result=this.model.lineage(this.model.state.selected);
    el(this.details,'p','rg-muted','仅回溯已记录的来源、延伸和细化关系；关系存在不代表已核证。');
    if(!result.edges.length)el(this.details,'p','','尚未记录可回溯的派生关系。');
    if(result.cycle)el(this.details,'p','rg-note-warning','存在循环关联，不构成唯一的先后推导链。');
    if(result.truncated)el(this.details,'p','rg-note-warning','本次回溯范围已达上限；请进入上游实体继续查看。');
    this.pagedList(this.details,result.edges,(list,e)=>button(list,`${this.model.nodes.get(e.source).title} —${RELS[e.type]}→ ${this.model.nodes.get(e.target).title}`,()=>this.showEdge(e.id)));
  }
  showTimeline(){
    this.auxiliary('来源时间线');
    el(this.details,'p','rg-muted','当前实体及已记录上游的引用来源，按发生时间展示；跨会话的时间先后不代表因果。未整理的原始记录仍在采集队列中。');
    const rows=this.model.timeline(this.model.state.selected);if(!rows.length)el(this.details,'p','','尚无可用的引用来源。');
    if(this.model.lineage(this.model.state.selected).truncated)el(this.details,'p','rg-note-warning','已达到本次回溯上限；请进入上游实体继续查看来源。');
    const date=t=>Number.isFinite(Date.parse(t))?new Date(t).toLocaleString():'未记录';
    this.pagedList(this.details,rows,(list,s)=>{
      const item=el(list,'div','rg-timeline-item');el(item,'strong','','发生：'+date(s.occurred_at));
      el(item,'div','rg-muted','入库：'+date(s.captured_at)+' · '+({user:'用户',assistant:'AI',tool:'工具'}[s.author]||s.author||'作者未记录'));
      button(item,s.title||'打开原始来源',()=>this.plugin.openExisting(s.path));
      if(s.quote)el(item,'p','rg-prose',s.quote);
      const provenance=el(item,'details');el(provenance,'summary','','来源顺序与前驱');
      el(provenance,'p','rg-muted',`来源序号：${s.source_sequence??'未记录'}；已记录前驱：${(s.predecessors||[]).length}。`);
      for(const id of s.predecessors||[]){const prior=rows.find(r=>r.event_id===id);if(prior)button(provenance,prior.title||'前驱来源',()=>this.plugin.openExisting(prior.path));else el(provenance,'p','rg-muted','有前驱记录未包含在当前引用范围内。');}
    });
  }
  searchResults() {
    this.results.empty(); if(!this.search.value.trim())return;
    const matches=this.model.search(this.search.value);
    if(!matches.length)el(this.results,"span","rg-muted","当前分支未找到，可启用跨分支查找。");
    for(const n of matches)button(this.results,`${TYPES[n.type]||n.type} · ${n.title}`,()=>{this.search.value="";this.results.empty();this.focus(n.id);});
    if(matches.length===50)el(this.results,"small","rg-muted","已显示前 50 条，请缩小查找范围。");
  }
  async makeGraph() {
    const juggl=this.plugin.app.plugins.getPlugin("juggl");
    if(!juggl || typeof juggl.createJuggl!=="function")throw Error("请先启用固定版本 Juggl 1.5.0，再重新打开科研图谱。");
    if(juggl.manifest.version!=="1.5.0")throw Error("Juggl 版本尚未验收，请使用本项目固定的 1.5.0。");
    const store={storeId:()=>"research", get:async id=>({data:{id:id.toId(),name:id.id,title:"载入中"}}), getNeighbourhood:async()=>[], connectNodes:async()=>[]};
    const settings={...juggl.settings.embedSettings,mode:"workspace",layout:"circle",expandInitial:false,toolbar:false,navigator:false,
      animateLayout:false,autoAddNodes:false,autoExpand:false,autoZoom:false,hoverEdges:false,openWithShift:true,readContent:false,filter:"",width:"100%",height:"100%"};
    // Without initialNodes Juggl does not schedule its automatic initial layout.
    // Replace its temporary elements only after vizReady, so restored positions stay authoritative.
    this.juggl=juggl.createJuggl(this.canvas,settings,{dataStores:[store],coreStore:store});
    await new Promise((resolve,reject)=>{
      const timeout=setTimeout(()=>reject(Error("Juggl 图引擎加载超时")),15000);
      this.juggl.on("vizReady",()=>queueMicrotask(()=>{
        try {
          clearTimeout(timeout); if(this.closed){resolve();return;}
          this.cy=this.juggl.viz;
          // Own navigation in this view; Juggl's standard file graph remains available separately.
          this.juggl.removeChild(this.juggl.mode);
          this.juggl.activeLayout?.stop();
          this.cy.off("tap dblclick taphold mouseover mouseout cxttap grab dragfree");
          this.cy.minZoom(.2);this.cy.maxZoom(3);
          this.cy.on("tap","node",e=>this.selectNode(e.target.id()));
          this.cy.on("tap","edge",e=>this.showEdge(e.target.id()));
          this.cy.on("mouseover","node",e=>e.target.addClass("rg-hover"));
          this.cy.on("mouseout","node",e=>e.target.removeClass("rg-hover"));
          this.cy.on("mouseover","edge",e=>{e.target.addClass("rg-hover");this.updateLabels();});
          this.cy.on("mouseout","edge",e=>{e.target.removeClass("rg-hover");this.updateLabels();});
          this.cy.on("grab","node",()=>{if(this.isDynamic())this.stopDynamic();});
          this.cy.on("drag","node",e=>{if(this.isDynamic()){const n=e.target;n.position(Dynamic.constrain({...n.position()},this.dynamicGroups[n.id()]));this.queueLabels();}});
          this.cy.on("dragfree","node",e=>{const n=e.target;if(this.isDynamic())this.pinDynamic(n.id(),n.position());else{this.model.state.positions[n.id()]={...n.position()};this.model.state.pins[n.id()]={...n.position()};this.scheduleSave();}});
          this.cy.on("pan zoom",()=>{this.scheduleSave();this.queueLabels();});
          this.render(!this.model.state.viewport);
          if(this.model.state.viewport){const v=this.model.state.viewport;if(['dialogue','dynamic'].includes(this.model.state.layoutMode)&&(v.width!==this.cy.width()||v.height!==this.cy.height()))this.fitView();else{this.cy.zoom(v.zoom);this.cy.pan(v.pan);}}
          this.canvasSize={width:this.cy.width(),height:this.cy.height()};
          this.resizeObserver=new ResizeObserver(()=>{if(!this.closed){this.cy.resize();const size={width:this.cy.width(),height:this.cy.height()};if(['dialogue','dynamic'].includes(this.model.state.layoutMode)&&(size.width!==this.canvasSize.width||size.height!==this.canvasSize.height))this.fitView();this.canvasSize=size;this.queueLabels();}});this.resizeObserver.observe(this.canvas);
          resolve();
        }catch(e){reject(e);}
      }));
      this.addChild(this.juggl);
    });
  }
  remember() { this.captureViewport();this.history.push(this.model.snapshot()); if(this.history.length>30)this.history.shift();if(this.backButton)this.backButton.disabled=false; }
  back() { if(!this.history.length)return;this.model=new ResearchGraphModel(this.graph,this.history.pop());this.render(false); if(this.model.state.viewport){this.cy.zoom(this.model.state.viewport.zoom);this.cy.pan(this.model.state.viewport.pan);} }
  focus(id) {this.remember();this.model.focus(id);this.render(false);this.fitView();}
  changeLayout(value){
    this.remember();this.model.state.layoutMode=value;
    this.stopDynamic();
    if(!['dialogue','dynamic'].includes(value))this.cy.nodes().forEach(n=>{if(this.model.state.positions[n.id()])n.position({...this.model.state.positions[n.id()]});});
    this.render(false);this.fitView();
  }
  render(fit=false) {
    if(!this.cy)return;
    this.stopDynamic();
    const dynamic=this.isDynamic(),dialogue=dynamic||this.model.state.layoutMode==='dialogue';
    const visible=dialogue?Dialogue.visible(this.model):this.model.visible(), ids=new Set(visible.nodes.map(n=>n.id)), edgeIds=new Set(visible.edges.map(e=>e.id));
    if(!ids.has(this.model.state.selected))this.model.state.selected=this.model.state.focus;
    this.cy.startBatch();
    this.cy.edges().filter(e=>!edgeIds.has(e.id())).remove();this.cy.nodes().filter(n=>!ids.has(n.id())).remove();
    visible.nodes.forEach((n,i)=>{
      const limit=dialogue?(n.id===this.model.state.entry?38:24):16;
      const short=n.title.length>limit?n.title.slice(0,limit-1)+"…":n.title;
      const caption=n.id===this.model.state.entry?'研究入口':Dialogue.GROUPS[Dialogue.group(n)];
      const data={id:n.id,name:n.id,title:dialogue?(dynamic&&n.id!==this.model.state.entry?short:caption+'\n'+short):(n.id===this.model.state.entry?'入口 · ':'')+short,kind:n.type,color:dynamic?AUTHOR_COLORS[authorGroup(n)]:(COLORS[n.type]||"#667b8c")};
      const node=this.cy.$id(n.id);
      if(node.length)node.data(data);
      else {const p=this.model.state.positions[n.id]||{x:Math.cos(i*2.39996)*200,y:Math.sin(i*2.39996)*200};this.cy.add({data,position:{...p}});}
    });
    for(const e of visible.edges){
      const peers=visible.edges.filter(x=>x.source===e.source&&x.target===e.target&&x.type===e.type);
      const qualifier=String(e.conditions?.[0]||e.basis||"").match(/^条件[^\s：:，,；;]{1,8}/)?.[0];
      const label=(RELS[e.type]||e.type)+(peers.length>1?" · "+(qualifier||String(peers.indexOf(e)+1)):"");
      const data={id:e.id,source:e.source,target:e.target,type:e.type,label};
      if(this.cy.$id(e.id).length)this.cy.$id(e.id).data(data);else this.cy.add({data});
    }
    const css=getComputedStyle(this.root),background=css.getPropertyValue('--background-primary').trim()||"#ffffff",foreground=css.getPropertyValue('--text-normal').trim()||"#344054";
    this.cy.style([
      {selector:"node",style:{label:"data(title)","background-color":"data(color)",width:24,height:24,"border-width":2,"border-color":"#ffffff","font-family":"Microsoft YaHei, sans-serif","font-size":13,"min-zoomed-font-size":10,"text-wrap":"wrap","text-max-width":130,"text-valign":"bottom","text-margin-y":8,color:"#344054","text-background-color":"#ffffff","text-background-opacity":.88,"text-background-padding":3}},
      {selector:"edge",style:{width:1.4,"curve-style":"bezier","control-point-step-size":62,"line-color":"#9da8b5","target-arrow-color":"#8593a3","target-arrow-shape":"triangle","arrow-scale":.75,label:"","font-size":12,"text-rotation":"none",color:foreground,"text-background-color":background,"text-background-opacity":.94,"text-background-padding":3,"text-events":"yes"}},
      {selector:'edge[type="related_to"]',style:{"target-arrow-shape":"none","source-arrow-shape":"none"}},
      {selector:'edge[type="contradicts"]',style:{"line-style":"dashed","line-color":"#b46a65","target-arrow-color":"#b46a65"}},
      {selector:"edge.rg-adjacent",style:{width:1.8,opacity:1}},
      {selector:"node.rg-selected, node.rg-hover",style:{"border-width":3,"border-color":"#243b53",width:30,height:30,"font-weight":"bold","min-zoomed-font-size":0}},
      {selector:"edge.rg-selected",style:{width:3,"line-color":"#3266ad","target-arrow-color":"#3266ad",color:foreground,'z-index':20,'z-index-compare':'manual'}},
      {selector:"node.rg-pinned",style:{"border-style":"double","border-width":4}}
      ,{selector:"node.rg-entry",style:{shape:'round-rectangle',width:42,height:32,'border-width':3,'border-color':'#3266ad','font-weight':'bold','min-zoomed-font-size':0}}
    ]).update();
    this.cy.nodes().style({color:foreground,"text-background-color":background});
    this.cy.elements().removeStyle();
    this.cy.nodes().style({color:foreground,'text-background-color':background});
    this.cy.nodes().unlock();
    if(dialogue){
      this.cy.nodes().ungrabify();this.cy.nodes().style({shape:'ellipse',width:44,height:44,'text-valign':'bottom','text-margin-y':8,'text-max-width':172,'text-overflow-wrap':'anywhere','font-size':14,'border-width':2,'min-zoomed-font-size':0,'text-background-opacity':0});
      this.cy.nodes().forEach(n=>n.style('background-color',n.data('color')));
      this.cy.nodes().forEach(n=>n.style('border-color',n.data('color')));
      this.cy.$id(this.model.state.entry).style({shape:'round-rectangle',width:240,height:112,'text-max-width':216,'font-size':18,'text-valign':'center','text-margin-y':0,'border-width':3,'background-color':background});
    if(dynamic){
        this.cy.nodes().grabify();this.cy.$id(this.model.state.entry).ungrabify();
        this.cy.nodes().style({'background-opacity':.9,'border-width':5,'border-opacity':.14,'underlay-color':'data(color)','underlay-opacity':0,'underlay-padding':9,'underlay-shape':'ellipse','text-background-opacity':.88,'text-background-padding':3});
        this.cy.$id(this.model.state.entry).style({'background-opacity':1,'background-color':background,'border-width':2,'border-opacity':.9,'underlay-opacity':0,'underlay-padding':12});
        this.cy.edges().style({'width':1.5,'opacity':.72,'arrow-scale':.65});
      }
    }else this.cy.nodes().grabify();
    this.cy.nodes().removeClass("rg-pinned");for(const id of Object.keys(dynamic?this.model.state.dynamicPins:this.model.state.pins))this.cy.$id(id).addClass("rg-pinned");
    this.cy.nodes().removeClass('rg-entry');if(this.model.state.entry)this.cy.$id(this.model.state.entry).addClass('rg-entry');
    this.cy.endBatch();
    this.count.textContent=`${visible.nodes.length} 个实体 · ${visible.edges.length} 条关系`;
    this.branchSelect.empty();for(const [branch,name] of Object.entries(this.branchOptions())){const o=el(this.branchSelect,'option','',name);o.value=branch;}
    this.branchSelect.value=this.model.state.workstream;
    if(this.projectSelect)this.projectSelect.value=this.model.state.project;
    const labels={"实体":"type","人工审阅":"review","证据":"evidence","关系":"relation"};
    for(const [label,key] of Object.entries(labels))this.root.querySelector(`select[aria-label="${label}"]`).value=this.model.state.filters[key]||"";
    this.root.querySelector('.rg-check input').checked=!!this.model.state.filters.crossBranch;
    const crossProject=this.root.querySelector('.rg-cross-project input');if(crossProject)crossProject.checked=!!this.model.state.filters.crossProject;
    this.labelSelect.value=this.model.state.labelMode||"auto";
    this.notice.textContent=this.graph.issues.length?`有 ${this.graph.issues.length} 条关系的端点待核对。`:"";
    const overview=this.model.state.mode==='overview';this.overviewPane.hidden=!overview;this.canvas.style.visibility=overview?'hidden':'visible';
    if(overview)this.showOverview();this.updateLocation();
    this.updateDetailsVisibility();this.root.classList.toggle('rg-dynamic',dynamic);this.zones.hidden=true;
    this.legend.querySelectorAll('span:not(.rg-tip)').forEach(n=>n.remove());
    for(const [kind,label] of Object.entries(dynamic?AUTHORS:TYPES)){const item=el(this.legend,'span','',label);item.style.setProperty('--rg-color',(dynamic?AUTHOR_COLORS:COLORS)[kind]);this.legend.insertBefore(item,this.legend.querySelector('.rg-tip'));}
    this.motionStatus.hidden=!dynamic||overview;this.motionButton.hidden=!dynamic;this.arrangeButton.textContent=dynamic?'重新舒展':'整理布局';
    if(dynamic&&!overview)this.prepareDynamic(visible);else if(dialogue&&!overview)this.arrangeDialogue(visible);
    this.root.querySelector('.rg-tip').textContent=dynamic?'拖动圆点固定 · 滚轮缩放 · 点击连线查看依据':dialogue?'按提出者排列 · 滚轮缩放 · 拖动画布 · 点击查看详情':'拖动固定位置 · 点击查看详情';
    if(fit){if(dynamic)this.fitView();else this.arrange();}
    if(overview){
      ++this.renderToken;this.details.empty();el(this.details,'h2','','从问题继续研究');
      el(this.details,'p','rg-prose','选择一个问题开始浏览，或查看尚未与问题建立联系的记录。');
      el(this.details,'p','rg-muted','入口问题与原始来源分别保留；共享证据仍是同一条记录。');
      this.count.textContent=`${this.model.projectNodes().length} 条研究记录 · 项目概览`;
    }
    else if(this.model.state.selected)this.selectNode(this.model.state.selected);
    else {this.details.empty();el(this.details,'h2','','尚无知识记录');el(this.details,'p','rg-muted','此项目尚未整理研究实体。可从项目首页开始，或切换其他项目。');}
    this.scheduleSave();
  }
  arrange() {
    if(!this.cy.nodes().length)return;
    if(this.isDynamic()){if(this.model.state.motionPaused){this.routeDynamic();return;}const seeds=Dynamic.seed(this.dynamicVisible.nodes,this.model.state.entry,this.dynamicVisible.edges,this.model.state.dynamicPins);this.cy.nodes().positions(n=>seeds[n.id()]);this.startDynamic();this.fitView();return;}
    if(this.model.state.layoutMode==='dialogue'){this.arrangeDialogue(Dialogue.visible(this.model));this.fitView();this.scheduleSave();return;}
    const pins=Object.keys(this.model.state.pins);for(const id of pins)this.cy.$id(id).lock();
    if(this.model.state.layoutMode==='entry' && this.model.state.entry){
      const levels=this.model.entryLevels(),groups=new Map(),positions={};
      for(const node of this.cy.nodes()){const depth=levels.get(node.id())??-1;if(!groups.has(depth))groups.set(depth,[]);groups.get(depth).push(node.id());}
      const lastDepth=Math.max(0,...[...groups.keys()].filter(d=>d>=0));
      for(const [depth,ids] of groups){ids.sort((a,b)=>this.model.nodes.get(a).title.localeCompare(this.model.nodes.get(b).title,'zh'));
        const radius=ids.length===1?0:Math.max(110,ids.length*24);
        ids.forEach((id,i)=>{const angle=2*Math.PI*i/ids.length-Math.PI/2;
          positions[id]=depth<0?{x:(lastDepth+1)*240+radius+radius*Math.cos(angle),y:radius*Math.sin(angle)}:
            {x:depth*240,y:(i-(ids.length-1)/2)*115};});}
      this.cy.layout({name:'preset',positions:n=>positions[n.id()],animate:false,fit:true,padding:60}).run();
      this.notice.textContent='按已记录的派生关系分层；其他关联放在旁侧。空间位置不表示时间或证据强度。';
    }else this.cy.layout({name:"concentric",animate:false,fit:true,padding:45,minNodeSpacing:55,nodeDimensionsIncludeLabels:true,
      concentric:n=>n.id()===this.model.state.focus?2:1,levelWidth:()=>1,avoidOverlap:true}).run();
    for(const id of pins)this.cy.$id(id).unlock();this.fitView();this.scheduleSave();
  }
  isDynamic(){return this.model?.state.layoutMode==='dynamic';}
  updateMotion(){
    if(!this.motionButton)return;
    this.motionButton.textContent=this.model.state.motionPaused?'动态暂停':'动态开启';
    this.motionButton.setAttribute('aria-pressed',String(!this.model.state.motionPaused));
    this.motionStatus.textContent=this.dynamicGeometry?.budget?'展开范围较大 · 动态暂缓':this.dynamicLayout?'正在舒展…':this.model.state.motionPaused?'布局已暂停':'布局已稳定';
    this.motionStatus.classList.toggle('is-running',!!this.dynamicLayout);
  }
  stopDynamic(){
    this.dynamicGeneration=(this.dynamicGeneration||0)+1;
    const layout=this.dynamicLayout;this.dynamicLayout=null;layout?.stop();
    this.cy?.nodes().unlock();
    if(this.model)this.updateMotion();
  }
  prepareDynamic(visible){
    this.dynamicGroups=Object.fromEntries(visible.nodes.map(n=>[n.id,n.id===this.model.state.entry?'entry':'node']));
    this.dynamicVisible=visible;
    const saved=this.model.state.dynamicPositions,positions=Dynamic.seed(visible.nodes,this.model.state.entry,visible.edges,saved);
    this.cy.nodes().positions(n=>positions[n.id()]);
    this.routeDynamic();this.updateMotion();
    if(visible.nodes.some(n=>!Dynamic.finite(saved[n.id])))this.startDynamic();
  }
  routeDynamic(){
    if(!this.isDynamic()||!this.cy||this.closed)return;
    const nodes=this.cy.nodes().map(n=>({id:n.id(),...n.position()}));
    this.dynamicGeometry=Dynamic.route(nodes,this.dynamicVisible.edges,this.model.state.entry,this.dynamicGroups,this.dynamicGeometry?.paths);
    this.cy.batch(()=>{for(const e of this.cy.edges()){
      const path=this.dynamicGeometry.paths[e.id()];if(path)e.style(path.style);
    }});
    const overlaps=Dynamic.overlaps(nodes,this.dynamicGroups);
    this.dynamicGeometry.nodeOverlaps=overlaps;
    this.notice.textContent=overlaps.length?'部分固定位置相互拥挤，请取消固定或收起关联。':
      this.dynamicGeometry.budget?'当前展开范围较大，请聚焦一个实体查看局部关系。':
      this.dynamicGeometry.issues.length||this.dynamicGeometry.overlaps?'部分关系仍较拥挤，可聚焦所选实体查看；全部依据保留在详情中。':'';
    this.queueLabels();
  }
  startDynamic(){
    if(!this.isDynamic()||this.model.state.mode==='overview'||!this.cy?.nodes().length||this.closed)return;
    this.stopDynamic();
    const state=this.model.state,entry=state.entry,groups=this.dynamicGroups,generation=this.dynamicGeneration;
    const nodes=this.dynamicVisible.nodes,pins=state.dynamicPins;
    const current=this.cy.nodes().map(n=>({id:n.id(),...n.position()}));
    Dynamic.resolve(current,entry,groups,pins,16);
    const positions=Object.fromEntries(current.map(n=>[n.id,n]));
    this.cy.nodes().positions(n=>({x:positions[n.id()].x,y:positions[n.id()].y}));
    if(state.motionPaused||nodes.length>100||this.dynamicVisible.edges.length>180){this.routeDynamic();this.captureViewport();this.scheduleSave();this.updateMotion();return;}
    for(const n of this.cy.nodes()){
      n.removeScratch('d3-force');
      if(n.id()===entry||Dynamic.finite(pins[n.id()]))n.lock();
    }
    const active=()=>!this.closed&&this.isDynamic()&&this.dynamicGeneration===generation;
    const finish=()=>{
      if(!active())return;
      this.dynamicLayout=null;
      const final=this.cy.nodes().map(n=>({id:n.id(),...n.position()}));Dynamic.resolve(final,entry,groups,pins,24);
      const map=Object.fromEntries(final.map(n=>[n.id,n]));
      this.cy.nodes().unlock();this.cy.nodes().positions(n=>({x:map[n.id()].x,y:map[n.id()].y}));
      this.routeDynamic();this.captureViewport();this.updateMotion();this.scheduleSave();
    };
    const layout=this.cy.elements().layout({name:'d3-force',animate:true,fit:false,randomize:false,infinite:false,
      maxSimulationTime:1400,alpha:.65,alphaDecay:.055,alphaMin:.005,velocityDecay:.62,
      ungrabifyWhileSimulating:false,fixedAfterDragging:false,linkId:n=>n.id,
      linkDistance:e=>e.source.id===entry||e.target.id===entry?290:220,linkStrength:.13,
      manyBodyStrength:-650,collideRadius:n=>n.id===entry?130:94,collideStrength:.9,collideIterations:2,
      xX:()=>0,xStrength:.035,yY:()=>0,yStrength:.035,
      tick:()=>{if(active()){Dynamic.resolve(layout.simulation.nodes(),entry,groups,pins,3);this.queueLabels();}},stop:finish});
    this.dynamicLayout=layout;this.updateMotion();
    try{
      layout.run();
      // Juggl pins cytoscape-d3-force 1.1.4. Its stock viewport centering force conflicts
      // with the research anchor. Remove it; fixed root and topology forces own space.
      layout.simulation.force('center',null);
      if(window.matchMedia('(prefers-reduced-motion: reduce)').matches){
        for(let i=0;i<100;i++){layout.simulation.tick();Dynamic.resolve(layout.simulation.nodes(),entry,groups,pins,3);}
        layout.refreshPositions(layout.state.nodes,layout.state,false);layout.stop();finish();
      }
    }catch(error){this.stopDynamic();this.routeDynamic();this.notice.textContent='动态布局暂不可用：'+error.message;}
  }
  pinDynamic(id,point){
    if(!this.isDynamic()||id===this.model.state.entry)return;
    const p=Dynamic.constrain({...point},this.dynamicGroups[id]);
    const fixed=[{id:this.model.state.entry,x:0,y:0},...Object.entries(this.model.state.dynamicPins).filter(([key])=>key!==id).map(([key,v])=>({id:key,...v}))];
    if(fixed.some(n=>Dynamic.intersects(Dynamic.box(p,this.dynamicGroups[id]),Dynamic.box(n,this.dynamicGroups[n.id]),0))){
      new Notice('此位置与已固定的实体或标题重叠，请换一个位置。');this.startDynamic();return;
    }
    this.model.state.dynamicPins[id]={...p};this.model.state.dynamicPositions[id]={...p};this.cy.$id(id).position({...p}).addClass('rg-pinned');
    this.startDynamic();this.selectNode(id);this.scheduleSave();
  }
  arrangeDialogue(visible){
    const boxes=Dialogue.layout(visible.nodes,this.model.state.entry),result=Dialogue.route(boxes,visible.edges);this.dialogueGeometry={boxes,...result};
    this.cy.nodes().positions(n=>({x:boxes[n.id()].x,y:boxes[n.id()].y}));
    for(const e of visible.edges){const points=result.paths[e.id],edge=this.cy.$id(e.id);if(points)edge.style(Dialogue.cyStyle(points,boxes[e.source],boxes[e.target]));else edge.style({'line-color':'#b46a65','line-style':'dashed'});}
    this.notice.textContent='左：用户提出 · 中：研究入口 · 右：AI 提出；共同整理在下方，资料与验证及归属待核对在上方。'+
      (visible.hidden?.length?` ${visible.hidden.length} 条纯操作记录仅在原记录中保留。`:'')+
      (result.issues.length?' 部分连线未通过绕线核对，请收起分支后查看关系详情。':result.crossings||result.overlaps?' 部分连线交叉或共用路径；点击关系可突出完整路径。':' 连线已绕开其他节点。');
    this.updateLabels();
  }
  fitView() {
    if(this.isDynamic()&&this.cy.$id(this.model.state.entry).length){
      const boxes=this.cy.elements().map(n=>n.boundingBox({includeLabels:true,includeOverlays:false}));
      const w=Math.max(...boxes.map(b=>Math.max(Math.abs(b.x1),Math.abs(b.x2))))+40,h=Math.max(...boxes.map(b=>Math.max(Math.abs(b.y1),Math.abs(b.y2))))+40;
      this.cy.zoom(Math.min(1.2,this.cy.width()/(2*w),this.cy.height()/(2*h)));this.cy.pan({x:this.cy.width()/2,y:this.cy.height()/2});return;
    }
    if(this.model.state.layoutMode==='dialogue'&&this.dialogueGeometry?.boxes[this.model.state.entry]){
      const boxes=Object.values(this.dialogueGeometry.boxes).map(b=>b.obstacle||b),w=Math.max(...boxes.map(b=>Math.abs(b.x)+b.w/2))+45,h=Math.max(...boxes.map(b=>Math.abs(b.y)+b.h/2))+45;
      this.cy.zoom(Math.min(1.2,this.cy.width()/(w*2),this.cy.height()/(h*2)));this.cy.pan({x:this.cy.width()/2,y:this.cy.height()/2});return;
    }
    this.cy.fit(undefined,45);if(this.cy.zoom()>1.2)this.cy.zoom({level:1.2,renderedPosition:{x:this.cy.width()/2,y:this.cy.height()/2}});
  }
  queueLabels(){if(this.labelFrame)return;this.labelFrame=requestAnimationFrame(()=>{this.labelFrame=null;this.updateLabels();});}
  updateLabels(){
    if(!this.cy||this.closed)return;
    if(this.model.state.mode==='overview'){this.count.textContent=`${this.model.projectNodes().length} 条研究记录 · 项目概览`;return;}
    const mode=this.model.state.labelMode||"auto",zoom=this.cy.zoom(),edges=[...this.cy.edges()],font=12/zoom;
    // Keep entity names readable when an old saved layout is fitted to a smaller window.
    if(!['dialogue','dynamic'].includes(this.model.state.layoutMode))this.cy.nodes().style({'font-size':13/zoom,'text-max-width':150/zoom,'text-margin-y':8/zoom});
    this.measureContext ||= document.createElement('canvas').getContext('2d');this.measureContext.font='12px Microsoft YaHei, sans-serif';
    const intersects=(a,b)=>a.x1<b.x2+4&&a.x2>b.x1-4&&a.y1<b.y2+4&&a.y2>b.y1-4;
    const nodeBoxes=this.cy.nodes().map(n=>n.renderedBoundingBox());
    const box=(edge,dy=0)=>{const p=edge.renderedMidpoint(),w=this.measureContext.measureText(edge.data('label')).width+8;return {x1:p.x-w/2,x2:p.x+w/2,y1:p.y-9+dy,y2:p.y+9+dy};};
    const boxes=edges.map(e=>box(e));
    const crowded=zoom<.65||boxes.some((b,i)=>nodeBoxes.some(n=>intersects(b,n))||boxes.slice(0,i).some(a=>intersects(a,b)));
    const effective=mode==='auto'?(crowded?'adjacent':'all'):mode;
    const ordered=edges.sort((a,b)=>Number(b.hasClass('rg-selected'))-Number(a.hasClass('rg-selected'))||Number(b.hasClass('rg-hover'))-Number(a.hasClass('rg-hover')));
    const occupied=[...nodeBoxes];let shown=0;
    for(const edge of ordered){
      const important=edge.hasClass('rg-selected')||edge.hasClass('rg-hover');
      let show=important||effective==='all'||(effective==='adjacent'&&(edge.data('source')===this.model.state.selected||edge.data('target')===this.model.state.selected));
      let dy=0,position=box(edge);
      if(show){
        let found=false;
        for(const offset of [0,-18,18,-36,36]){const candidate=box(edge,offset);if(!occupied.some(b=>intersects(candidate,b))){dy=offset;position=candidate;found=true;break;}}
        if(!found&&(!important&&mode==='auto'||['dialogue','dynamic'].includes(this.model.state.layoutMode)))show=false;
      }
      edge.style({label:show?edge.data('label'):'','font-size':font,'text-margin-y':dy/zoom,'text-margin-x':0});
      if(show){shown++;occupied.push(position);}
    }
    this.count.textContent=`${this.cy.nodes().length} 个实体 · ${edges.length} 条关系`+(shown<edges.length?` · ${shown} 条文字可见`:'');
  }
  selectNode(id) {
    const n=this.model.nodes.get(id);if(!n)return;if(this.model.state.selected!==id)this.remember();this.model.select(id);this.selectedEdge=null;
    this.cy.elements().removeClass("rg-selected rg-adjacent");this.cy.$id(id).addClass("rg-selected").connectedEdges().addClass("rg-adjacent");
    if(['dialogue','dynamic'].includes(this.model.state.layoutMode)){this.cy.nodes().forEach(n=>n.style('border-color',n.data('color')));this.cy.$id(id).style('border-color','#243b53');}
    if(this.isDynamic()){this.cy.nodes().style('underlay-opacity',0);this.cy.$id(id).style('underlay-opacity',id===this.model.state.entry?0:.1);this.cy.edges().style('opacity',.58);this.cy.$id(id).connectedEdges().style('opacity',.9);}
    this.updateLabels();
    this.updateLocation();this.showNode(n);this.scheduleSave();
  }
  async showNode(n) {
    const token=++this.renderToken;this.details.empty();
    el(this.details,"div","rg-eyebrow",TYPES[n.type]||n.type);el(this.details,"h2","",n.title);
    if(n.id===this.model.state.entry)el(this.details,'span','rg-entry-badge','研究入口');
    const state=el(this.details,"div","rg-status");
    if(n.display){el(state,'span','',n.display.status);el(this.details,'p','rg-muted',`${n.display.project} · ${n.display.branch} · 提出者：${n.display.authors.join('、')}`);}
    else {el(state,"span","",REVIEWS[n.human_review]||n.human_review);el(state,"span","",EVIDENCE[n.evidence_status]||n.evidence_status);}
    const actions=el(this.details,"div","rg-actions");
    button(actions,`展开关联（余 ${this.model.remaining(n.id)}）`,()=>{this.remember();this.model.expand(n.id);this.render(false);});
    button(actions,"收起关联",()=>{this.remember();this.model.collapse(n.id);this.render(false);});
    if(this.isDynamic()&&n.id!==this.model.state.entry)button(actions,this.model.state.dynamicPins[n.id]?'取消固定':'固定位置',()=>{if(this.model.state.dynamicPins[n.id]){delete this.model.state.dynamicPins[n.id];this.cy.$id(n.id).removeClass('rg-pinned');this.startDynamic();this.showNode(n);}else this.pinDynamic(n.id,this.cy.$id(n.id).position());});
    if(!['dialogue','dynamic'].includes(this.model.state.layoutMode))button(actions,this.model.state.pins[n.id]?"取消固定":"固定",()=>{this.remember();this.model.togglePin(n.id,this.cy.$id(n.id).position());this.render(false);});
    button(actions,['dialogue','dynamic'].includes(this.model.state.layoutMode)?"查看相关想法":"以此为中心",()=>this.focus(n.id));
    if(n.id===this.model.state.entry&&n.sources?.length)button(actions,'入口原话',()=>this.plugin.openExisting(n.sources[0].path));
    const byType=el(this.details,"div","rg-relation-expansion");
    for(const kind of new Set((this.model.adjacency.get(n.id)||[]).map(e=>e.type))) {
      const remaining=this.model.remaining(n.id,kind);
      if(remaining)button(byType,`${RELS[kind]||kind} +${remaining}`,()=>{this.remember();this.model.expand(n.id,kind);this.render(false);});
    }
    const warning=el(this.details,"div","rg-note-warning");
    el(this.details,"p","rg-prose",n.body);
    if(n.conditions?.length){el(this.details,"h3","","适用条件");const list=el(this.details,"ul","");for(const condition of n.conditions)el(list,"li","",condition);}
    this.sources(this.details,n.sources);
    const relationships=el(this.details,"details","rg-section");el(relationships,"summary","",`关系与依据（${this.model.adjacency.get(n.id).length}）`);
    if(!this.model.adjacency.get(n.id).length)el(relationships,'p','rg-muted','尚未建立关系。');
    for(const e of this.model.adjacency.get(n.id)) {
      const other=this.model.nodes.get(e.source===n.id?e.target:e.source);
      button(relationships,`${e.type==='related_to'?"—":e.source===n.id?"→":"←"} ${RELS[e.type]||e.type} · ${other.title}`,()=>this.showEdge(e.id));
    }
    if(n.evidence){const d=el(this.details,"details","rg-section");el(d,"summary","","证据记录");const labels={url:'来源',locator:'位置',excerpt:'片段',access_level:'访问范围',verification:'来源核对'};const values={verified:'已核对',unverified:'待核对',abstract_only:'仅摘要',metadata_only:'仅题录',local_artifact:'本地产物',full_text:'全文'};for(const [key,label] of Object.entries(labels))if(n.evidence[key])el(d,"p","rg-prose",`${label}：${values[n.evidence[key]]||n.evidence[key]}`);}
    button(this.details,"打开完整笔记",()=>this.plugin.openExisting(n.path));
    const meta=el(this.details,"details","rg-section");el(meta,"summary","","来源身份与修订");
    el(meta,"p","rg-muted",`${n.authors?.join("、")||""} · 修订 ${n.version} · ${n.updated_at||""}`);el(meta,"code","",n.id);
    try{
      const file=this.plugin.file(n.path);const text=await this.app.vault.cachedRead(file);
      if(token!==this.renderToken)return;
      if(n.needs_reconciliation || sha(text)!==n.published_hash)warning.textContent="笔记已有变更，图中结构待核对。请打开完整笔记查看当前内容。";
    }catch(e){if(token===this.renderToken)warning.textContent=`笔记状态待核对：${e.message}`;}
  }
  sources(parent,sources=[]) {
    const d=el(parent,"details","rg-section");el(d,"summary","",`原话与来源（${sources.length}）`);
    for(const s of sources){if(s.quote)el(d,"blockquote","",s.quote);button(d,s.title||`查看原始记录${s.author?" · "+s.author:""}`,()=>this.plugin.openExisting(s.path));}
  }
  async showEdge(id) {
    const e=this.model.edges.get(id);if(!e)return;const token=++this.renderToken;this.selectedEdge=id;this.details.empty();
    this.cy.elements().removeClass("rg-selected rg-adjacent");this.cy.$id(id).addClass("rg-selected");
    if(this.isDynamic()){this.cy.edges().style('opacity',.35);this.cy.$id(id).style('opacity',1);}
    this.updateLabels();
    el(this.details,"div","rg-eyebrow","关系详情");el(this.details,"h2","",RELS[e.type]||e.type);
    el(this.details,"p","rg-prose",`${this.model.nodes.get(e.source).title} — ${RELS[e.type]||e.type} ${e.type==='related_to'?'—':'→'} ${this.model.nodes.get(e.target).title}`);
    if(e.type==='tests')el(this.details,"p","rg-muted","此关系表示验证对象，不代表已经证实。");
    if(['adopts','rejects'].includes(e.type))el(this.details,"p","rg-muted","此关系记录方案选择；人工采用或否决不改变证据状态。");
    el(this.details,"h3","","判断依据");el(this.details,"p","rg-prose",e.basis||"尚未记录关系依据。");
    if(e.conditions?.length){el(this.details,"h3","","关系适用条件");for(const x of e.conditions)el(this.details,"p","rg-prose",x);}
    const warning=el(this.details,"p","rg-note-warning",e.needs_reconciliation?"来源笔记已变更，关系待核对。":"");
    el(this.details,"p","rg-muted",e.provenance_scope==="relation"?"以下来源直接关联此关系。":"以下为提出该关系的笔记来源，不表示该关系已被核证。");
    this.sources(this.details,e.sources);
    button(this.details,"打开关系原文",()=>this.plugin.openExisting(e.note_path));
    button(this.details,"连线起点",()=>this.selectNode(e.source));button(this.details,"连线终点",()=>this.selectNode(e.target));
    try{
      for(const id of [e.source,e.target]){const node=this.model.nodes.get(id);const text=await this.app.vault.cachedRead(this.plugin.file(node.path));if(token!==this.renderToken)return;if(node.needs_reconciliation||sha(text)!==node.published_hash)warning.textContent="相关笔记已有变更，此关系待核对；请读取当前原文。";}
    }catch(error){if(token===this.renderToken)warning.textContent=`关系来源待核对：${error.message}`;}
  }
  captureViewport() {
    if(!this.cy || this.closed)return;
    this.model.state.viewport={zoom:this.cy.zoom(),pan:{...this.cy.pan()},width:this.cy.width(),height:this.cy.height()};
    if(this.isDynamic())this.cy.nodes().forEach(n=>{this.model.state.dynamicPositions[n.id()]={...n.position()};});
    if(!['dialogue','dynamic'].includes(this.model.state.layoutMode))this.cy.nodes().forEach(n=>{this.model.state.positions[n.id()]={...n.position()};});
  }
  scheduleSave() { if(this.closed)return;clearTimeout(this.saveTimer);this.saveTimer=setTimeout(()=>this.persist().catch(e=>new Notice(`图谱位置未保存：${e.message}`)),250); }
  async persist(){if(!this.model)return;this.captureViewport();await this.plugin.saveView(this.model.state.project||this.graph.project_id,{...this.model.snapshot(),history:structuredClone(this.history)});}
  async reload() {
    const data=await this.plugin.readGraph();this.captureViewport();this.model=new ResearchGraphModel(data,this.model.snapshot());this.graph=data;this.render(false);
    if(!['dialogue','dynamic'].includes(this.model.state.layoutMode))this.notice.textContent="已刷新研究记录；图谱位置已保留。";
  }
  async onClose() {this.stopDynamic();clearTimeout(this.saveTimer);cancelAnimationFrame(this.labelFrame);await this.persist();this.closed=true;this.resizeObserver?.disconnect();this.cy?.destroy();}
}

module.exports=class ResearchGraphPlugin extends Plugin {
  async onload() {
    this.saved=(await this.loadData())||{views:{}};this.saved.views||={};this.saved.branchViews||={};this.saveQueue=Promise.resolve();
    this.registerView(VIEW,leaf=>new GraphView(leaf,this));
    this.registerView(Timeline.TYPE,leaf=>new Timeline.TimelineView(leaf,this));
    this.addRibbonIcon("list","打开研究时间线",()=>this.open());
    this.addCommand({id:"open",name:"打开研究时间线",callback:()=>this.open()});
    this.addCommand({id:"open-graph",name:"查看局部知识图谱",callback:()=>this.openGraph()});
    this.addCommand({id:"refresh",name:"刷新研究视图",callback:async()=>{await this.readGraph();await this.repairOpenFiles();await Promise.all([...this.app.workspace.getLeavesOfType(VIEW),...this.app.workspace.getLeavesOfType(Timeline.TYPE)].map(l=>l.view.reload(true)));}});
    this.registerMarkdownPostProcessor((element,context)=>{
      const classes=this.app.metadataCache.getCache(context.sourcePath)?.frontmatter?.cssclasses||[];
      if(!(Array.isArray(classes)?classes:[classes]).includes('research-note'))return;
      for(const item of element.querySelectorAll('li'))for(const child of [...item.childNodes])if(child.nodeType===Node.TEXT_NODE){
        child.textContent=child.textContent.replace(/^(\s*)(derived_from|extends|depends_on|supports|contradicts|refines|replaces|related_to|tests|adopts|rejects)\s+/,(_,space,type)=>space+RELS[type]+' ');
        child.textContent=child.textContent.replace(/^(\s*)\[condition\]\s*/, '$1');
      }
    });
    this.registerEvent(this.app.vault.on("modify",file=>{
      if(file.path==='系统视图/research-timeline.json'||file.path==='System/research-timeline.json')for(const leaf of this.app.workspace.getLeavesOfType(Timeline.TYPE))leaf.view.reload().catch(e=>new Notice(`时间线刷新失败，当前内容保留：${e.message}`));
      for(const leaf of this.app.workspace.getLeavesOfType(VIEW)) {
        if(file.path===DATA||file.path===LEGACY_DATA)leaf.view.reload().catch(e=>new Notice(`图谱刷新失败：${e.message}`));
        else if(file.extension==='md') {const n=leaf.view.model?.nodes.get(leaf.view.model.state.selected);if(n?.path===file.path)leaf.view.showNode(n);}
      }
    }));
  }
  async readGraph(){const path=await this.app.vault.adapter.exists(DATA)?DATA:LEGACY_DATA;const data=JSON.parse(await this.app.vault.adapter.read(path));const identity=JSON.parse(await this.app.vault.adapter.read(path.replace('research-graph.json','research-memory-identity.json')));if(data.project_id!==identity.project_id)throw Error("图谱数据与当前仓库身份不一致");this.pathAliases=data.path_aliases||{};return data;}
  file(path) {
    const valid=p=>typeof p==='string'&&!/[\\:*?"<>|\x00-\x1f]/.test(p)&&p.split('/').every(x=>x&&!x.startsWith('.')&&x.trimEnd()===x)&&/\.(md|canvas|base)$/.test(p)&&(/^(Notes|Sources|研究项目|示例与验收)\//.test(p)||p==='科研工作台.md');
    if(!valid(path))throw Error("不支持的研究笔记路径");
    path=this.pathAliases?.[path]||path;
    if(!valid(path))throw Error("研究笔记路径映射无效");
    const file=this.app.vault.getAbstractFileByPath(path);if(!(file instanceof TFile))throw Error("文件不存在，未创建替代文件");return file;
  }
  async openExisting(path){const file=this.file(path);await this.app.workspace.getLeaf("tab").openFile(file);}
  async repairOpenFiles(){
    const leaves=this.app.workspace.getLeavesOfType('markdown');
    for(const leaf of leaves){const state=leaf.getViewState(),old=state.state?.file,target=this.pathAliases?.[old];if(target){this.file(target);await leaf.setViewState({...state,state:{...state.state,file:target}});}}
  }
  saveView(project,state){this.saved.views[project]=state;if(state.workstream){this.saved.branchViews[project]||={};this.saved.branchViews[project][state.workstream]=structuredClone(state);}const snapshot=structuredClone(this.saved);this.saveQueue=this.saveQueue.catch(()=>{}).then(()=>this.saveData(snapshot));return this.saveQueue;}
  persistData(){const snapshot=structuredClone(this.saved);this.saveQueue=this.saveQueue.catch(()=>{}).then(()=>this.saveData(snapshot));return this.saveQueue;}
  async open(){try{let leaf=this.app.workspace.getLeavesOfType(Timeline.TYPE)[0];if(!leaf){leaf=this.app.workspace.getLeaf('tab');await leaf.setViewState({type:Timeline.TYPE,active:true});}await this.app.workspace.revealLeaf(leaf);return leaf.view;}catch(e){new Notice(e.message);throw e;}}
  async openGraph(id){try{let leaf=this.app.workspace.getLeavesOfType(VIEW)[0];if(!leaf){leaf=this.app.workspace.getLeaf("tab");await leaf.setViewState({type:VIEW,active:true});}await this.app.workspace.revealLeaf(leaf);if(id&&leaf.view.model){const n=leaf.view.model.nodes.get(id);if(n&&n.research_project_id!==leaf.view.model.state.project)await leaf.view.switchProject(n.research_project_id);if(n&&n.workstream_id!==leaf.view.model.state.workstream)await leaf.view.switchBranch(n.workstream_id);leaf.view.focus(id);}return leaf.view;}catch(e){new Notice(e.message);throw e;}}
  onunload(){this.app.workspace.detachLeavesOfType(VIEW);this.app.workspace.detachLeavesOfType(Timeline.TYPE);}
};
