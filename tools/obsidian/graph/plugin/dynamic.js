"use strict";
// Geometry only. Forces are supplied by the already pinned Juggl d3-force engine.
const finite=p=>p&&Number.isFinite(p.x)&&Number.isFinite(p.y);
function seed(nodes,entry,edges,saved={}){
  const ids=new Set(nodes.map(n=>n.id)),adj=new Map(nodes.map(n=>[n.id,[]]));
  for(const e of edges)if(ids.has(e.source)&&ids.has(e.target)){adj.get(e.source).push(e.target);adj.get(e.target).push(e.source);}
  // Neighbourhood traversal supplies deterministic seeds, not a causal or temporal tree.
  const seen=new Set(entry?[entry]:[]),ordered=[],queue=entry?[entry]:[];
  for(let i=0;i<queue.length;i++)for(const id of [...adj.get(queue[i])||[]].sort())if(!seen.has(id)){seen.add(id);ordered.push(id);queue.push(id);}
  for(const n of [...nodes].sort((a,b)=>a.id.localeCompare(b.id)))if(!seen.has(n.id)){seen.add(n.id);ordered.push(n.id);}
  const positions={};if(ids.has(entry))positions[entry]={x:0,y:0};
  ordered.forEach((id,i)=>{
    const angle=-Math.PI/2+2*Math.PI*i/Math.max(1,ordered.length),radius=Math.max(260,Math.sqrt(ordered.length)*112);
    positions[id]={...((finite(saved[id])&&saved[id])||{x:radius*Math.cos(angle),y:radius*Math.sin(angle)})};
  });
  // Improve the starting order using actual connections. Authorship is deliberately absent.
  if(ordered.length<=24&&!ordered.some(id=>finite(saved[id])))untangle(positions,edges,entry);
  return positions;
}
function untangle(positions,edges,entry){
  const keys=Object.keys(positions).filter(id=>id!==entry),pairs=[...new Map(edges.filter(e=>e.source!==e.target&&positions[e.source]&&positions[e.target]).map(e=>[[e.source,e.target].sort().join('|'),e])).values()];
  const cost=()=>{
    let score=0;
    for(let i=0;i<pairs.length;i++){
      const e=pairs[i],a=positions[e.source],b=positions[e.target];score+=Math.hypot(a.x-b.x,a.y-b.y)*.01;
      for(let j=i+1;j<pairs.length;j++){const f=pairs[j];if([e.source,e.target].some(id=>id===f.source||id===f.target))continue;score+=segmentRelation(a,b,positions[f.source],positions[f.target]).crossing*100;}
      if(e.source!==entry&&e.target!==entry){const root=positions[entry];if(root)for(let t=.1;t<1;t+=.1)if(hits({x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t},box(root,'entry')))score+=30;}
    }return score;
  };
  let best=cost();for(let pass=0;pass<5;pass++){let changed=false;
    for(let i=0;i<keys.length;i++)for(let j=i+1;j<keys.length;j++){
      const a=keys[i],b=keys[j];[positions[a],positions[b]]=[positions[b],positions[a]];const next=cost();
      if(next<best-.01){best=next;changed=true;}else [positions[a],positions[b]]=[positions[b],positions[a]];
    }if(!changed)break;
  }
}
function constrain(p,kind){if(kind==='entry'){p.x=0;p.y=0;}return p;}
function box(p,kind){return kind==='entry'?{x:p.x,y:p.y,w:252,h:124}:{x:p.x,y:p.y+30,w:190,h:116};}
function intersects(a,b,gap=12){return Math.abs(a.x-b.x)<(a.w+b.w)/2+gap&&Math.abs(a.y-b.y)<(a.h+b.h)/2+gap;}
function resolve(nodes,entry,groups,pins={},iterations=8){
  const fixed=n=>n.id===entry||finite(pins[n.id]);
  for(const n of nodes){
    if(n.id===entry){n.x=0;n.y=0;n.fx=0;n.fy=0;}
    else if(finite(pins[n.id])){Object.assign(n,constrain({...pins[n.id]},groups[n.id]));n.fx=n.x;n.fy=n.y;}
    else constrain(n,groups[n.id]);
  }
  for(let k=0;k<iterations;k++)for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){
    const a=nodes[i],b=nodes[j],ab=box(a,groups[a.id]),bb=box(b,groups[b.id]);
    if(!intersects(ab,bb)||fixed(a)&&fixed(b))continue;
    const dx=(ab.w+bb.w)/2+13-Math.abs(ab.x-bb.x),dy=(ab.h+bb.h)/2+13-Math.abs(ab.y-bb.y);
    const axis=dx<dy?'x':'y',amount=(axis==='x'?dx:dy),sign=(bb[axis]>=ab[axis]?1:-1);
    if(!fixed(a))a[axis]-=amount*sign*(fixed(b)?1:.5);
    if(!fixed(b))b[axis]+=amount*sign*(fixed(a)?1:.5);
    constrain(a,groups[a.id]);constrain(b,groups[b.id]);
  }
  return nodes;
}
function overlaps(nodes,groups){const out=[];for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++)if(intersects(box(nodes[i],groups[nodes[i].id]),box(nodes[j],groups[nodes[j].id]),0))out.push([nodes[i].id,nodes[j].id]);return out;}
function port(p,c,entry){
  let dx=c.x-p.x,dy=c.y-p.y,len=Math.hypot(dx,dy)||1;
  if(entry){const scale=Math.min(120/Math.max(.001,Math.abs(dx)),56/Math.max(.001,Math.abs(dy)));return {x:p.x+dx*scale,y:p.y+dy*scale};}
  // External titles are below the circles: keep the connector out of that sector.
  if(dy>0&&dy/len>.45){dx=dx>=0?1:-1;dy=.35;len=Math.hypot(dx,dy);}
  return {x:p.x+dx/len*23,y:p.y+dy/len*23};
}
function quadratic(a,c,b,t){const u=1-t;return {x:u*u*a.x+2*u*t*c.x+t*t*b.x,y:u*u*a.y+2*u*t*c.y+t*t*b.y};}
function hits(p,b){return Math.abs(p.x-b.x)<b.w/2+3&&Math.abs(p.y-b.y)<b.h/2+3;}
function segmentRelation(a,b,c,d){
  const ax=b.x-a.x,ay=b.y-a.y,bx=d.x-c.x,by=d.y-c.y,al=Math.hypot(ax,ay),bl=Math.hypot(bx,by),cross=ax*by-ay*bx;
  if(al<.01||bl<.01)return {crossing:0,overlap:0};
  if(Math.abs(cross)>.03*al*bl){
    const x=c.x-a.x,y=c.y-a.y,t=(x*by-y*bx)/cross,u=(x*ay-y*ax)/cross;
    return {crossing:t>0&&t<1&&u>0&&u<1?1:0,overlap:0};
  }
  const distance=Math.abs((c.x-a.x)*ay-(c.y-a.y)*ax)/al;
  const t1=((c.x-a.x)*ax+(c.y-a.y)*ay)/al,t2=((d.x-a.x)*ax+(d.y-a.y)*ay)/al;
  return {crossing:0,overlap:distance<5&&Math.min(al,Math.max(t1,t2))-Math.max(0,Math.min(t1,t2))>10?1:0};
}
function curvePoints(path,count=16){
  const controls=path.controls||(path.control?[path.control]:[]);if(!controls.length)return [];
  const result=[],steps=Math.max(8,Math.ceil(count/controls.length));
  controls.forEach((c,j)=>{const a=j===0?path.start:{x:(controls[j-1].x+c.x)/2,y:(controls[j-1].y+c.y)/2},b=j===controls.length-1?path.end:{x:(c.x+controls[j+1].x)/2,y:(c.y+controls[j+1].y)/2};
    for(let i=j===0?0:1;i<=steps;i++)result.push(quadratic(a,c,b,i/steps));});return result;
}
function pathInteractions(path,others){
  const points=curvePoints(path);let crossings=0,overlaps=0;
  for(const other of others){const q=other.samples||curvePoints(other);
    for(let i=1;i<points.length;i++)for(let j=1;j<q.length;j++){
      // Endpoints are allowed to meet at their entity; no lane merging elsewhere.
      if([path.start,path.end].some(p=>[other.start,other.end].some(v=>Math.hypot(p.x-v.x,p.y-v.y)<48)&&
        Math.hypot(points[i].x-p.x,points[i].y-p.y)<55&&Math.hypot(q[j].x-p.x,q[j].y-p.y)<55))continue;
      const result=segmentRelation(points[i-1],points[i],q[j-1],q[j]);crossings+=result.crossing;overlaps+=result.overlap;
    }
  }return {crossings,overlaps};
}
function route(nodes,edges,entry,groups,previous={}){
  const byId=Object.fromEntries(nodes.map(n=>[n.id,n])),paths={},issues=[],used=new Map();
  if(nodes.length>100||edges.length>180)return {paths:Object.fromEntries(edges.map(e=>[e.id,{style:{'curve-style':'bezier'}}])),issues:edges.map(e=>e.id),budget:true,crossings:null,overlaps:null};
  const started=Date.now(),ordered=[...edges].sort((a,b)=>a.id.localeCompare(b.id));
  for(const e of ordered){
    const a=byId[e.source],b=byId[e.target];if(!a||!b)continue;
    if(Date.now()-started>1000){paths[e.id]={style:{'curve-style':'bezier'},budget:true};issues.push(e.id);continue;}
    if(a.id===b.id){paths[e.id]={style:{'curve-style':'bezier','loop-direction':'-45deg','loop-sweep':'55deg'}};continue;}
    const dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy)||1,key=[a.id,b.id].sort().join('|'),flip=a.id<b.id?1:-1;
    const taken=used.get(key)||[];
    const candidates=[previous[e.id]?.distance,30,-30,75,-75,130,-130,190,-190,260,-260,350,-350].filter(d=>Number.isFinite(d)&&Math.abs(d)<=350);
    let best;
    for(const weights of [[.5],[0,.5,1],[0,.25,.5,.75,1]])for(const d of [...new Set(candidates)])for(const orientation of weights.length===1?[[1,1]]:[[1,1],[-1,1],[1,-1],[-1,-1]])for(const fraction of weights.length===1?[.5]:[.5,.25,.75]){
      if(weights.length===5&&best&&!best.collisions&&!best.interaction.overlaps)continue;
      if(taken.some(x=>Math.abs(x-d*flip)<30))continue;
      const mid={x:a.x+dx*fraction-dy/len*d,y:a.y+dy*fraction+dx/len*d};
      const shoulder=(n,flip)=>{
        if(n.id===entry){const p=port(n,mid,true);return {x:n.x+(p.x-n.x)*1.4,y:n.y+(p.y-n.y)*1.4};}
        // A local horizontal shoulder clears a circle's own external title before bending.
        const direction=(mid.x-n.x>=0?1:-1)*flip;
        return {x:n.x+direction*145,y:n.y+Math.min(0,(mid.y-n.y)*.22)};
      };
      const sa=shoulder(a,orientation[0]),sb=shoulder(b,orientation[1]);
      const controls=weights.length===1?[mid]:weights.length===3?[sa,mid,sb]:[sa,{x:sa.x,y:mid.y},mid,{x:sb.x,y:mid.y},sb],c=mid,start=port(a,controls[0],a.id===entry),end=port(b,controls.at(-1),b.id===entry);
      const controlWeights=controls.map(p=>((p.x-a.x)*dx+(p.y-a.y)*dy)/(len*len)),controlDistances=controls.map(p=>(dx*(p.y-a.y)-dy*(p.x-a.x))/len);

      let collisions=0;
      for(const p of curvePoints({start,controls,end},40).slice(1,-1)){
        for(const n of nodes){
          const endpoint=n.id===a.id||n.id===b.id;
          const obstacle=endpoint?(n.id===entry?null:{x:n.x,y:n.y+47,w:178,h:36}):box(n,groups[n.id]);
          if(obstacle&&hits(p,obstacle))collisions++;
        }
      }
      const interaction=pathInteractions({start,controls,end},Object.values(paths).filter(p=>p.control));
      const score=collisions*100000+interaction.overlaps*10000+interaction.crossings*180+Math.abs(d)+(weights.length-1)*35+Math.abs(fraction-.5)*60+(orientation[0]<0?25:0)+(orientation[1]<0?25:0)+(previous[e.id]?.distance===d?-28:0);
      if(!best||score<best.score)best={score,collisions,interaction,distance:d,start,control:c,controls,end,style:{'curve-style':'unbundled-bezier','edge-distances':'node-position',
        'control-point-weights':controlWeights,'control-point-distances':controlDistances,'source-endpoint':[start.x-a.x,start.y-a.y],'target-endpoint':[end.x-b.x,end.y-b.y]}};
    }
    if(!best){best={style:{'curve-style':'bezier'},collisions:1};}
    best.samples=curvePoints(best);paths[e.id]=best;if(best.collisions)issues.push(e.id);taken.push(best.distance*flip);used.set(key,taken);
  }
  const all=Object.values(paths).filter(p=>p.control);let crossings=0,overlaps=0;
  all.forEach((p,i)=>{const r=pathInteractions(p,all.slice(i+1));crossings+=r.crossings;overlaps+=r.overlaps;});
  return {paths,issues,crossings,overlaps,budget:Object.values(paths).some(p=>p.budget)};
}
module.exports={seed,constrain,box,intersects,resolve,overlaps,route,quadratic,finite,pathInteractions,curvePoints};
