import {verifications,jobs} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {VerificationStatus,DiffType} from '../constants/enums.js';
import {esc,date,notify} from '../utils/dom.js';
let timer=null;
function vStatus(v){return '<span class="status verify-'+esc(v.status)+'">'+esc(VerificationStatus[v.status]||v.status)+'</span>';}
function diffText(d){
 const head=DiffType[d.type]||d.type;
 if(d.message)return head+'：'+d.message;
 if(d.type==='metric_mismatch')return head+' · '+d.label+'：原成绩 '+esc(fmtVal(d.expected))+' → 复算 '+esc(fmtVal(d.actual));
 if(d.type==='segment_mismatch')return head+' · '+d.segment_id+' · '+d.field+'：原成绩 '+esc(fmtVal(d.expected))+' → 复算 '+esc(fmtVal(d.actual));
 if(d.type==='metric_missing'||d.type==='metric_extra')return head+' · '+d.label;
 if(d.type==='segment_missing'||d.type==='segment_extra')return head+' · '+d.segment_id;
 if(d.type==='result_mismatch')return head+' · '+d.field;
 return head;
}
function fmtVal(v){return v===null||v===undefined?'—':(typeof v==='object'?JSON.stringify(v):String(v));}
export async function verificationPage(){
 const [list,allJobs]=await Promise.all([verifications.list(),jobs.list()]);
 workspace.verifications=list;workspace.jobs=allJobs;
 const jobName=id=>(allJobs.find(j=>j.id===id)||{}).name||('#'+id);
 const selectedId=workspace.selectedVerification&&list.some(v=>v.job_id===workspace.selectedVerification)?workspace.selectedVerification:(list[0]?.job_id??null);
 workspace.selectedVerification=selectedId;
 const sel=list.find(v=>v.job_id===selectedId)||null;
 const canStart=session.user.role!=='viewer';
 const cards=list.map(v=>'<button class="verify-item" data-select="'+v.job_id+'"'+(v.job_id===selectedId?' data-active="1"':'')+'><div class="verify-item-head"><strong>'+esc(jobName(v.job_id))+'</strong>'+vStatus(v)+'</div><small>规则版本 '+esc(v.rule_version||'—')+' · 尝试 '+v.attempts+' 次</small>'+(v.status==='running'?'<div class="progress"><i style="width:'+v.progress+'%"></i></div>':'')+'<small>'+(v.sealed_at?('封存于 '+date(v.sealed_at)):'无封存时间')+'</small></button>').join('');
 return heading('05 / VERIFICATION','验真复算与封存凭据','新试验完成即封存原输入、参数、规则版本与独立计算依据；升级后按原版复算，逐段分诊与指标任一差异或缺件即判失败，原成绩不被修改。','<button class="button" id="refresh-verifications">刷新 ↻</button>')
 +'<div class="verify-grid"><section class="panel"><div class="section-title"><h2>试验验真清单</h2><span>'+list.length+' 条</span></div><div class="verify-list">'+(cards||'<p class="empty">尚无已完成试验。</p>')+'</div></section><section class="panel">'+(sel?detailPanel(sel,canStart):'<div class="empty">选择左侧试验查看验真进度与差异原因。</div>')+'</section></div>';
}
function detailPanel(v,canStart){
 const running=v.status==='running'||v.status==='pending';
 const diffs=v.differences||[];
 return '<div class="section-title"><h2>验真详情 #'+v.job_id+'</h2>'+vStatus(v)+'</div>'
 +'<div class="verify-meta"><div><span>规则版本</span><strong>'+esc(v.rule_version||'—')+'</strong></div><div><span>封存指纹</span><strong class="mono">'+esc((v.evidence_hash||'无').slice(0,20))+'…</strong></div><div><span>封存完整性</span><strong>'+(v.seal_intact?'完好':'已失效')+'</strong></div><div><span>最近复算</span><strong>'+(v.checked_at?date(v.checked_at):'—')+'</strong></div></div>'
 +(running?'<div class="progress big"><i style="width:'+v.progress+'%"></i></div><p class="hint">复算进行中（进度 '+v.progress+'%）。中断后会由后台恢复同次核验，可停留本页自动刷新。</p>':'')
 +'<div class="verify-actions"><button class="primary" id="start-verification" '+(canStart&&!running&&v.has_evidence&&v.status!=='passed'?'':'disabled')+'>'+(v.status==='failed'?'重新发起验真复算':'发起验真复算')+' ↗</button>'+(v.id?'<button class="button" id="download-evidence" '+(v.seal_intact?'':'disabled')+'>下载封存凭据 JSON ↓</button>':'')+'</div>'
 +(v.status==='unverifiable'?'<p class="warning">该历史试验完成时未封存计算依据，已明确标记为不可验真；系统不会使用新版规则补算冒充。</p>':'')
 +(v.status==='passed'?'<p class="passed-note">验真通过：原版规则复算的逐段分诊、指标与成果指纹均与封存原成绩一致，凭据对应当前成果，方可批准与分发。</p>':'')
 +'<div class="section-title" style="margin-top:24px"><h2>差异与原因</h2><span>'+diffs.length+' 条</span></div>'
 +(diffs.length?'<ul class="diff-list">'+diffs.map(d=>'<li class="diff-'+esc(d.type)+'">'+diffText(d)+'</li>').join('')+'</ul>':'<p class="hint">'+(v.status==='passed'?'无差异。':'尚未产生差异记录。')+'</p>');
}
function stopPolling(){if(timer){clearInterval(timer);timer=null;}}
export function bindVerifications(refresh){
 stopPolling();
 document.querySelector('#refresh-verifications')?.addEventListener('click',refresh);
 document.querySelectorAll('[data-select]').forEach(b=>b.addEventListener('click',()=>{workspace.selectedVerification=Number(b.dataset.select);refresh();}));
 document.querySelector('#start-verification')?.addEventListener('click',async()=>{
   try{await verifications.start(workspace.selectedVerification);notify('验真复算已发起，同次核验可断点恢复');await refresh();}
   catch(e){notify(e.message,true);}
 });
 document.querySelector('#download-evidence')?.addEventListener('click',async()=>{
   try{
     const v=workspace.verifications.find(x=>x.job_id===workspace.selectedVerification);
     const data=await verifications.evidence(v.id);
     const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'}),u=URL.createObjectURL(blob),a=document.createElement('a');
     a.href=u;a.download='verification-evidence-job-'+v.job_id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);
   }catch(e){notify(e.message,true);}
 });
 const anyRunning=(workspace.verifications||[]).some(v=>v.status==='running'||v.status==='pending');
 if(anyRunning){timer=setInterval(()=>{const still=(workspace.verifications||[]).some(v=>v.status==='running'||v.status==='pending');if(!still){stopPolling();}refresh();},4000);}
}
export function stopVerificationPolling(){stopPolling();}
