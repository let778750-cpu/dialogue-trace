"use strict";
const {Modal,Component,MarkdownRenderer,Notice}=require('obsidian');
const labels={user:'用户',assistant:'AI 公开回答／说明',context:'来源上下文',tool:'工具',lifecycle:'生命周期'};
function add(parent,tag,text,cls=''){const n=parent.createEl(tag,{cls});if(text!==undefined)n.textContent=String(text);return n;}
function json(parent,value){add(parent,'pre',JSON.stringify(value,null,2),'rt-log');}
function tabsFor(detail){return detail.kind==='tool'?['概览','输入','结果','工具定义','时序','原始字段','来源']:['概览','预览','原始字段','来源'];}
class EventInspector extends Modal{
  constructor(view,row){super(view.app);this.view=view;this.row=row;this.renderer=new Component();}
  async onOpen(){
    this.modalEl.addClass('rt-reader');this.renderer.load();
    const close=add(this.contentEl,'button','返回时间线','rt-button');close.onclick=()=>this.close();
    const loading=add(this.contentEl,'p','正在核对来源…');
    try{
      const detail=await this.view.backend('event.detail',{event_id:this.row.source_event_id||this.row.id});
      if(this.closed)return;loading.remove();this.detail=detail;
      add(this.contentEl,'h2',labels[detail.kind]||detail.kind);
      add(this.contentEl,'p',detail.source.session+' · '+(detail.source.turn_id?'来源轮次 '+detail.source.turn_id:'来源未提供轮次'),'rt-muted');
      const tabs=add(this.contentEl,'div',undefined,'rt-inspector-tabs');tabs.setAttribute('role','tablist');
      this.panel=add(this.contentEl,'div',undefined,'rt-inspector-panel');this.panel.setAttribute('role','tabpanel');
      for(const name of tabsFor(detail)){const b=add(tabs,'button',name,'rt-button');b.setAttribute('role','tab');b.onclick=()=>this.show(name,tabs).catch(e=>new Notice(e.message));}
      await this.show('概览',tabs);
    }catch(e){loading.textContent='来源详情暂不可用：'+e.message;}
  }
  async show(name,tabs){
    const d=this.detail,p=this.panel;p.empty();
    for(const b of tabs.children)b.setAttribute('aria-selected',String(b.textContent===name));
    if(name==='概览'){
      add(p,'p','状态：'+(d.status==='not_recorded'?'来源未提供':d.status));
      if(d.phase)add(p,'p','公开消息阶段：'+d.phase);
      if(d.ambiguous_call)add(p,'p','调用标识重复，未推断唯一的父子关系。','rt-failure');
      add(p,'p','来源哈希已核对；缺失耗时、用量与工具定义均保留为未知。','rt-muted');
      if(Object.keys(d.usage).length)json(p,d.usage);
      add(p,'p',d.preview.text.slice(0,700),'rt-preview');
    }else if(name==='预览')await this.view.renderBody(p,this.row,d.preview,this.renderer);
    else if(name==='来源'){
      json(p,d.source);
      for(const id of d.related_ids.filter(x=>x!==d.source.event_id)){const b=add(p,'button','关联记录 · '+id.slice(0,18),'rt-button');b.onclick=()=>this.view.inspectSource(id);}
    }else if(name==='原始字段'){
      add(p,'p','已归档的公开事件字段；不等同于完整宿主请求，不含隐藏推理。','rt-muted');json(p,d.raw_public_event);
    }else{
      const value={输入:d.inputs,结果:d.outputs,工具定义:d.schemas,时序:d.timing}[name];
      if(!value||!Object.keys(value).length)add(p,'p','来源未提供此项。','rt-muted');else json(p,value);
      if(name==='时序')add(p,'p','仅使用来源明确记录的时间指标；发生时间与采集时间之差不作为执行耗时。','rt-muted');
    }
  }
  onClose(){this.closed=true;this.renderer.unload();this.contentEl.empty();}
}
module.exports={EventInspector,tabsFor};
