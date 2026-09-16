"use strict";

// Pure view state. No model calls, file writes, or inference of scientific relationships.
class ResearchGraphModel {
  constructor(graph, saved = {}) {
    if (![1,2].includes(graph.schema_version) || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) throw Error("不支持的图谱数据格式");
    this.graph = graph;
    this.nodes = new Map(graph.nodes.map(n => [n.id, n]));
    if (this.nodes.size !== graph.nodes.length) throw Error("实体标识重复");
    this.edges = new Map();
    this.adjacency = new Map(graph.nodes.map(n => [n.id, []]));
    for (const e of graph.edges) {
      if (this.edges.has(e.id) || !this.nodes.has(e.source) || !this.nodes.has(e.target)) throw Error("关系标识或端点无效");
      this.edges.set(e.id, e);
      this.adjacency.get(e.source).push(e);
      if (e.source !== e.target) this.adjacency.get(e.target).push(e);
    }
    const {history, ...view} = structuredClone(saved);
    this.state = {project: graph.default_project_id || graph.project_id, entry: null, focus: null, selected: null, workstream: "", expanded: {}, pins: {}, positions: {}, dynamicPositions: {}, dynamicPins: {}, motionPaused: false, filters: {}, viewport: null, labelMode: "auto", layoutMode: "entry", mode: "local", trail: [], ...view};
    if(!['auto','all','adjacent','selected'].includes(this.state.labelMode))this.state.labelMode='auto';
    for (const k of ["expanded", "pins", "positions", "dynamicPositions", "dynamicPins", "filters"]) this.state[k] ||= {};
    this.state.trail = (Array.isArray(this.state.trail) ? this.state.trail : []).filter(x=>this.nodes.has(x.id)).slice(-100);
    if(!['entry','network','dialogue','dynamic'].includes(this.state.layoutMode))this.state.layoutMode='entry';
    const members=graph.nodes.filter(n=>this.inProject(n));
    const prior=this.nodes.get(this.state.focus);
    if (graph.navigation) {
      const priorEntry=this.nodes.get(this.state.entry);
      this.entryMissing=!!this.state.entry && (!priorEntry || !this.inProject(priorEntry) || priorEntry.type!=='question');
      if(this.entryMissing) {this.state.entry=null;this.state.mode='overview';}
      if(!this.state.entry && !this.entryMissing)this.state.entry=this.registeredEntries(this.state.workstream)[0]?.id || null;
      if(!this.state.workstream)this.state.workstream=this.nodes.get(this.state.entry)?.workstream_id || (prior&&this.inProject(prior)?prior.workstream_id:'');
      if(prior && this.inProject(prior) && (!this.state.workstream || prior.workstream_id===this.state.workstream)) {
        if(!this.nodes.has(this.state.selected) || !this.inProject(this.nodes.get(this.state.selected)))this.state.selected=prior.id;
      } else if(this.state.entry && this.state.mode!=='overview')this.focus(this.state.entry);
      else {this.state.focus=null;this.state.selected=null;this.state.mode='overview';}
      return;
    }
    const initial = (prior && this.inProject(prior)?prior:null) || members.find(n => n.type === "question") || members[0];
    if (!initial) {this.state.focus=null;this.state.selected=null;this.state.workstream='';return;}
    if (!prior || !this.inProject(prior)) this.focus(initial.id);
    this.state.selected = this.nodes.has(this.state.selected) ? this.state.selected : this.state.focus;
  }
  inProject(n) { return this.graph.schema_version===1 || n.research_project_id===this.state.project; }
  focus(id) {
    const n = this.nodes.get(id);
    if (!n) throw Error("实体不存在");
    this.state.focus = id;
    this.state.selected = id;
    this.state.workstream = n.workstream_id;
    this.state.mode = 'local';
    this.state.expanded = {[id]: {"*": 20}};
    this.state.viewport = null;
    this.visit(id);
  }
  registeredEntries(branch='') {
    const config=this.graph.navigation?.projects?.[this.state.project] || {};
    const ids=(branch && Object.hasOwn(config.branches||{},branch))?config.branches[branch]:(config.entry_ids||[]);
    return ids.map(id=>this.nodes.get(id)).filter(n=>n&&this.inProject(n)&&n.type==='question'&&(!branch||n.workstream_id===branch));
  }
  chooseEntry(id) {
    const n=this.nodes.get(id);
    if(!n || !this.inProject(n) || n.type!=='question')throw Error('请选择本项目的现有问题');
    this.state.entry=id;this.entryMissing=false;this.state.filters={};this.focus(id);
  }
  returnToEntry() {
    if(!this.state.entry || !this.nodes.has(this.state.entry)){this.overview();return;}
    this.focus(this.state.entry);
  }
  overview() {this.state.mode='overview';}
  visit(id) {
    if(this.state.trail.at(-1)?.id!==id)this.state.trail.push({id,at:new Date().toISOString()});
    this.state.trail=this.state.trail.slice(-100);
  }
  projectNodes() {return this.graph.nodes.filter(n=>this.inProject(n));}
  overviewGroups() {
    const questions=this.projectNodes().filter(n=>n.type==='question');
    const connected=new Set(questions.map(n=>n.id)), queue=[...connected];
    for(let i=0;i<queue.length;i++)for(const e of this.adjacency.get(queue[i])||[]) {
      const id=e.source===queue[i]?e.target:e.source;
      if(this.inProject(this.nodes.get(id))&&!connected.has(id)){connected.add(id);queue.push(id);}
    }
    return {questions, detached:this.projectNodes().filter(n=>!connected.has(n.id))};
  }
  lineageEdges() {
    return this.graph.edges.filter(e=>['derived_from','extends','refines'].includes(e.type) &&
      (e.basis || e.sources?.length) && this.inProject(this.nodes.get(e.source)) && this.inProject(this.nodes.get(e.target)));
  }
  lineage(id,limit=100) {
    const adjacency=new Map();for(const e of this.lineageEdges()){if(!adjacency.has(e.source))adjacency.set(e.source,[]);adjacency.get(e.source).push(e);}
    const edges=new Map(),done=new Set(),active=new Set(),entered=new Set(),stack=[{id,exit:false}];let cycle=false,truncated=false;
    while(stack.length){
      const item=stack.pop();
      if(item.exit){active.delete(item.id);done.add(item.id);continue;}
      if(active.has(item.id)){cycle=true;continue;}
      if(done.has(item.id))continue;
      if(entered.size>=limit){truncated=true;continue;}entered.add(item.id);
      active.add(item.id);stack.push({id:item.id,exit:true});
      for(const e of adjacency.get(item.id)||[]){edges.set(e.id,e);stack.push({id:e.target,exit:false});}
    }
    return {edges:[...edges.values()],cycle,truncated};
  }
  entryLevels() {
    const levels=new Map(),children=new Map();
    for(const e of this.lineageEdges()){if(!children.has(e.target))children.set(e.target,[]);children.get(e.target).push(e.source);}
    if(!this.nodes.has(this.state.entry))return levels;
    const queue=[this.state.entry];levels.set(queue[0],0);
    for(let i=0;i<queue.length;i++)for(const child of children.get(queue[i])||[])
      if(!levels.has(child)){levels.set(child,levels.get(queue[i])+1);queue.push(child);}
    return levels;
  }
  timeline(id) {
    const node=this.nodes.get(id);if(!node)return [];
    const sourceNodes=new Set([id]);for(const e of this.lineage(id).edges){sourceNodes.add(e.source);sourceNodes.add(e.target);}
    const events=new Map();
    const add=(s,owner)=>{const key=s.event_id||s.path;if(!key)return;if(!events.has(key))events.set(key,{...s,nodes:[]});const row=events.get(key);if(!row.nodes.includes(owner))row.nodes.push(owner);};
    for(const key of sourceNodes)for(const s of this.nodes.get(key)?.sources||[])add(s,key);
    for(const e of this.lineage(id).edges)for(const s of e.sources||[])add(s,e.source);
    const time=s=>Number.isFinite(Date.parse(s.occurred_at))?Date.parse(s.occurred_at):Infinity;
    return [...events.values()].sort((a,b)=>time(a)-time(b)||String(a.event_id||a.path).localeCompare(String(b.event_id||b.path)));
  }
  allowed(id) {
    const n = this.nodes.get(id), f = this.state.filters;
    return !!n && (this.inProject(n) || f.crossProject) && (f.crossBranch || (f.crossProject&&!this.inProject(n)) || n.workstream_id === this.state.workstream) &&
      (!f.type || n.type === f.type) && (!f.review || n.human_review === f.review) &&
      (!f.evidence || n.evidence_status === f.evidence);
  }
  neighbours(id, type = "*") {
    const found = new Set();
    for (const e of this.adjacency.get(id) || []) {
      if ((type === "*" || e.type === type) && (!this.state.filters.relation || e.type === this.state.filters.relation)) {
        const other = e.source === id ? e.target : e.source;
        if (this.allowed(other)) found.add(other);
      }
    }
    return [...found].sort((a, b) => this.nodes.get(a).title.localeCompare(this.nodes.get(b).title, "zh") || a.localeCompare(b));
  }
  visible() {
    if(this.state.mode==='overview')return {nodes:[],edges:[]};
    const seen = new Set([this.state.focus]);
    for (const id of Object.keys(this.state.pins)) if (this.nodes.has(id) && this.allowed(id)) seen.add(id);
    const queue = [...seen];
    for (let i = 0; i < queue.length; i++) {
      const id = queue[i];
      for (const [type, count] of Object.entries(this.state.expanded[id] || {})) {
        for (const other of this.neighbours(id, type).slice(0, Math.max(0, count))) {
          if (!seen.has(other)) { seen.add(other); queue.push(other); }
        }
      }
    }
    const edges = this.graph.edges.filter(e => seen.has(e.source) && seen.has(e.target) &&
      (!this.state.filters.relation || e.type === this.state.filters.relation));
    return {nodes: [...seen].map(id => this.nodes.get(id)).filter(Boolean), edges};
  }
  expand(id, type = "*", count = 20) {
    if (!this.nodes.has(id)) throw Error("实体不存在");
    this.state.expanded[id] ||= {};
    this.state.expanded[id][type] = Math.min(this.nodes.size, (this.state.expanded[id][type] || 0) + count);
  }
  collapse(id) { delete this.state.expanded[id]; }
  remaining(id, type = "*") {
    const visible = new Set(this.visible().nodes.map(n => n.id));
    return this.neighbours(id, type).filter(n => !visible.has(n)).length;
  }
  select(id) { if (this.nodes.has(id)) {this.state.selected = id;this.visit(id);} }
  togglePin(id, position) {
    if (this.state.pins[id]) delete this.state.pins[id];
    else if (this.nodes.has(id)) this.state.pins[id] = {...position};
  }
  search(text) {
    const q = text.trim().toLocaleLowerCase();
    return this.graph.nodes.filter(n => (!q || `${n.title} ${n.id} ${n.body}`.toLocaleLowerCase().includes(q)) &&
      this.allowed(n.id)).slice(0, 50);
  }
  snapshot() { return structuredClone(this.state); }
}

module.exports = {ResearchGraphModel};
