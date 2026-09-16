"use strict";
const PF = require("./pathfinding");

const GROUPS={user:'用户提出',assistant:'AI 提出',shared:'共同整理',material:'资料与验证',unknown:'归属待核对',entry:'研究入口'};
const CONTROL=/^(?:请)?(?:继续|开始执行|开始|执行|检查错误并修正|检查并修正|修复错误|继续执行|continue|go on|fix errors)[。！!\s]*$/i;
function controlOnly(n){
  // Only a complete control utterance qualifies. Never substring-filter a research paragraph.
  return CONTROL.test((n.title||'').trim()) && (!(n.body||'').trim() || CONTROL.test(n.body.trim())) &&
    !(n.conditions||[]).length && !n.evidence;
}
function group(n){
  if(['evidence','experiment','task','decision'].includes(n.type))return 'material';
  const authors=(n.authors||[]).map(x=>String(x).trim().toLowerCase());
  const user=authors.some(x=>/^(user|用户)$/.test(x));
  const ai=authors.some(x=>/^(assistant(?: (?:interpretation|observation))?|ai|codex)$/.test(x));
  const other=authors.some(x=>!/^(user|用户|assistant(?: (?:interpretation|observation))?|ai|codex)$/.test(x));
  if(other)return 'unknown';
  return user&&ai?'shared':user?'user':ai?'assistant':'unknown';
}
function visible(model){
  const v=model.visible(),hidden=v.nodes.filter(controlOnly).filter(n=>n.id!==model.state.entry);
  const nodes=v.nodes.filter(n=>!hidden.includes(n)),entry=model.nodes.get(model.state.entry);
  if(entry && model.inProject(entry) && !nodes.some(n=>n.id===entry.id))nodes.unshift(entry);
  const ids=new Set(nodes.map(n=>n.id));
  // Keep only actual canonical edges; adding the anchor does not invent a connector.
  const edges=[...model.edges.values()].filter(e=>ids.has(e.source)&&ids.has(e.target)&&
    (!model.state.filters.relation||e.type===model.state.filters.relation));
  return {nodes,edges,hidden};
}
function layout(nodes,entry){
  const groups={user:[],assistant:[],shared:[],material:[],unknown:[]},boxes={};
  const ordered=[...nodes].sort((a,b)=>a.title.localeCompare(b.title,'zh')||a.id.localeCompare(b.id));
  for(const n of ordered){if(n.id===entry)boxes[n.id]={id:n.id,x:0,y:0,w:240,h:112,group:'entry'};else groups[group(n)].push(n);}
  for(const [kind,x] of [['user',-432],['assistant',432]])groups[kind].forEach((n,i)=>{
    const row=i===0?0:Math.ceil(i/2)*(i%2?-1:1);boxes[n.id]={id:n.id,x,y:row*192,w:44,h:44,shape:'circle',group:kind};
  });
  let top=-216;
  for(const kind of ['shared','material','unknown']){
    groups[kind].forEach((n,i)=>boxes[n.id]={id:n.id,x:groups[kind].length===1?0:(i%2?144:-144),y:kind==='shared'?216+Math.floor(i/2)*192:top-Math.floor(i/2)*192,w:44,h:44,shape:'circle',group:kind});
    if(kind!=='shared'&&groups[kind].length)top-=Math.ceil(groups[kind].length/2)*192;
  }
  // A circle is small; its external title still occupies space and blocks other edges.
  for(const b of Object.values(boxes))if(b.shape==='circle')b.obstacle={x:b.x,y:b.y+36,w:208,h:128};
  return boxes;
}
function inside(p,b,padding=0){b=b.obstacle||b;return p.x>b.x-b.w/2-padding&&p.x<b.x+b.w/2+padding&&p.y>b.y-b.h/2-padding&&p.y<b.y+b.h/2+padding;}
function segmentHits(a,b,box,padding=0){
  box=box.obstacle||box;
  const x1=box.x-box.w/2-padding,x2=box.x+box.w/2+padding,y1=box.y-box.h/2-padding,y2=box.y+box.h/2+padding;
  if(Math.abs(a.x-b.x)<1e-6)return a.x>x1&&a.x<x2&&Math.max(a.y,b.y)>y1&&Math.min(a.y,b.y)<y2;
  if(Math.abs(a.y-b.y)<1e-6)return a.y>y1&&a.y<y2&&Math.max(a.x,b.x)>x1&&Math.min(a.x,b.x)<x2;
  return true; // Dialogue routes must be orthogonal, so reject unverified diagonals.
}
function compact(points){
  const out=[];
  for(const p of points){if(out.length&&Math.hypot(p.x-out.at(-1).x,p.y-out.at(-1).y)<1e-6)continue;
    while(out.length>1){const a=out.at(-2),b=out.at(-1);if(Math.abs((b.x-a.x)*(p.y-b.y)-(b.y-a.y)*(p.x-b.x))>1e-6)break;out.pop();}out.push({x:p.x,y:p.y});}
  return out;
}
function straighten(points,clear){
  const out=[points[0]];
  for(let i=0;i<points.length-1;){
    let next=i+1,best=[points[i],points[next]];
    for(let j=points.length-1;j>i+1;j--){
      const a=points[i],b=points[j],candidates=[compact([a,{x:b.x,y:a.y},b]),compact([a,{x:a.x,y:b.y},b])];
      const candidate=candidates.find(p=>p.slice(1).every((v,k)=>clear(p[k],v)));
      if(candidate){next=j;best=candidate;break;}
    }
    out.push(...best.slice(1));i=next;
  }
  return compact(out);
}
function route(boxes,edges){
  const nodes=Object.values(boxes),step=8,pad=16,margin=80,issues=[],paths={};
  if(!nodes.length)return {paths,issues,crossings:0,overlaps:0};
  const obstacles=nodes.map(n=>n.obstacle||n);
  const minX=Math.floor((Math.min(...obstacles.map(b=>b.x-b.w/2))-margin)/step)*step;
  const minY=Math.floor((Math.min(...obstacles.map(b=>b.y-b.h/2))-margin)/step)*step;
  const cols=Math.ceil((Math.max(...obstacles.map(b=>b.x+b.w/2))+margin-minX)/step)+1;
  const rows=Math.ceil((Math.max(...obstacles.map(b=>b.y+b.h/2))+margin-minY)/step)+1;
  if(cols*rows>240000 || edges.length>200){return {paths,issues:['当前展开范围超过安全绕线预算，请收起部分分支；全部关系仍可在详情中查看。'],crossings:0,overlaps:0};}
  const base=Array.from({length:rows},(_,y)=>Array.from({length:cols},(_,x)=>nodes.some(b=>inside({x:minX+x*step,y:minY+y*step},b,pad))?1:0));
  const cell=p=>[Math.round((p.x-minX)/step),Math.round((p.y-minY)/step)],point=([x,y])=>({x:minX+x*step,y:minY+y*step});
  const incidence=new Map(),order=[...edges].sort((a,b)=>a.id.localeCompare(b.id));
  const sides={};
  for(const e of order){
    const a=boxes[e.source],b=boxes[e.target];if(!a||!b||a.id===b.id){issues.push(`无法安全绕线：${e.id}`);continue;}
    const horizontal=Math.abs(b.x-a.x)>=Math.abs(b.y-a.y);
    let sa=horizontal?(b.x>a.x?'E':'W'):(b.y>a.y?'S':'N'),sb={E:'W',W:'E',N:'S',S:'N'}[sa];
    // Bottom ports on a circle would cut through its external title.
    if(a.shape==='circle'&&sa==='S')sa=b.x>=a.x?'E':'W';
    if(b.shape==='circle'&&sb==='S')sb=a.x>=b.x?'E':'W';
    sides[e.id]=[sa,sb];
    for(const [n,s] of [[a,sa],[b,sb]]){const k=n.id+':'+s;if(!incidence.has(k))incidence.set(k,[]);incidence.get(k).push(e.id);}
  }
  const port=(box,side,id)=>{
    const list=incidence.get(box.id+':'+side),i=list.indexOf(id),span=(side==='E'||side==='W'?box.h:box.w)-(box.shape==='circle'?12:32);
    const gap=Math.min(step,Math.floor(span/Math.max(1,list.length-1)/step)*step);
    const offset=Math.round(((i-(list.length-1)/2)*gap)/step)*step;
    const p={x:box.x,y:box.y},radius=box.w/2;
    const extent=box.shape==='circle'?Math.sqrt(radius*radius-offset*offset):(side==='E'||side==='W'?box.w:box.h)/2;
    if(side==='E'||side==='W'){p.x+=(side==='E'?1:-1)*extent;p.y+=offset;}else{p.y+=(side==='S'?1:-1)*extent;p.x+=offset;}
    const o=box.obstacle||box,escape={...p};if(side==='E'||side==='W')escape.x=o.x+(side==='E'?1:-1)*(o.w/2+pad+step);else escape.y=o.y+(side==='S'?1:-1)*(o.h/2+pad+step);
    return {p,escape};
  };
  const used=new Set(),deadline=Date.now()+1200;
  for(const e of order){
    if(Date.now()>deadline){issues.push('绕线达到本轮时间预算，剩余关系保留，收起分支可重试。');break;}
    if(!sides[e.id])continue;
    const [sa,sb]=sides[e.id],a=boxes[e.source],b=boxes[e.target],start=port(a,sa,e.id),end=port(b,sb,e.id),s=cell(start.escape),t=cell(end.escape);
    let found=[];
    // First reserve earlier paths. If the topology needs crossings, allow them explicitly.
    for(const reserve of [true,false]){
      const matrix=base.map(row=>row.slice());
      if(reserve)for(const k of used){const [x,y]=k.split(',').map(Number);matrix[y][x]=1;}
      if(base[s[1]]?.[s[0]]!==0||base[t[1]]?.[t[0]]!==0)break;
      matrix[s[1]][s[0]]=0;matrix[t[1]][t[0]]=0;
      found=new PF.AStarFinder({allowDiagonal:false}).findPath(...s,...t,new PF.Grid(cols,rows,matrix));
      if(found.length)break;
    }
    if(!found.length){issues.push(`无法安全绕线：${e.id}`);continue;}
    const raw=compact([start.p,...found.map(point),end.p]);
    const points=straighten(raw,(a,b)=>{
      if(nodes.some(n=>segmentHits(a,b,n,n.id===e.source||n.id===e.target?0:4)))return false;
      const distance=Math.hypot(b.x-a.x,b.y-a.y),count=Math.ceil(distance/step);
      for(let i=1;i<count;i++){const p={x:a.x+(b.x-a.x)*i/count,y:a.y+(b.y-a.y)*i/count};if(used.has(cell(p).join(',')))return false;}
      return true;
    });
    const bad=points.slice(1).some((p,i)=>nodes.some(n=>n.id!==e.source&&n.id!==e.target&&segmentHits(points[i],p,n,4)));
    if(bad){issues.push(`绕线核对失败：${e.id}`);continue;}
    paths[e.id]=points;
    for(let j=1;j<points.length;j++){const a=points[j-1],b=points[j],count=Math.ceil(Math.hypot(b.x-a.x,b.y-a.y)/step);for(let i=0;i<=count;i++)used.add(cell({x:a.x+(b.x-a.x)*i/count,y:a.y+(b.y-a.y)*i/count}).join(','));}
  }
  let crossings=0,overlaps=0;const entries=Object.entries(paths);
  for(let i=0;i<entries.length;i++)for(let j=i+1;j<entries.length;j++){
    const [,a]=entries[i],[,b]=entries[j];
    for(let ai=1;ai<a.length;ai++)for(let bi=1;bi<b.length;bi++){
      const a0=a[ai-1],a1=a[ai],b0=b[bi-1],b1=b[bi],ah=a0.y===a1.y,bh=b0.y===b1.y;
      if(ah===bh){const c=ah?'y':'x',v=ah?'x':'y';if(a0[c]===b0[c]&&Math.min(Math.max(a0[v],a1[v]),Math.max(b0[v],b1[v]))-Math.max(Math.min(a0[v],a1[v]),Math.min(b0[v],b1[v]))>.1)overlaps++;}
      else{const h=ah?[a0,a1]:[b0,b1],v=ah?[b0,b1]:[a0,a1];if(v[0].x>Math.min(h[0].x,h[1].x)&&v[0].x<Math.max(h[0].x,h[1].x)&&h[0].y>Math.min(v[0].y,v[1].y)&&h[0].y<Math.max(v[0].y,v[1].y))crossings++;}
    }
  }
  return {paths,issues,crossings,overlaps};
}
function cyStyle(points,a,b){
  const dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy),interior=points.slice(1,-1);
  if(!interior.length)interior.push({x:(points[0].x+points.at(-1).x)/2,y:(points[0].y+points.at(-1).y)/2});
  return {'curve-style':'segments','edge-distances':'node-position','segment-weights':interior.map(p=>((p.x-a.x)*dx+(p.y-a.y)*dy)/(len*len)),
    'segment-distances':interior.map(p=>(dx*(p.y-a.y)-dy*(p.x-a.x))/len),
    'source-endpoint':[points[0].x-a.x,points[0].y-a.y],'target-endpoint':[points.at(-1).x-b.x,points.at(-1).y-b.y]};
}
module.exports={GROUPS,controlOnly,group,visible,layout,route,cyStyle,inside,segmentHits};
