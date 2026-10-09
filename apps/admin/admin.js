'use strict';
let token = '', user = null, threads = [], selectedThread = '', refreshBusy = false;
let creditKey = '', creditPayload = '';
const $ = id => document.getElementById(id);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = fils => (fils/1000).toFixed(3)+' د.أ';
const statuses = {pending:'بانتظار كابتن',accepted:'تم القبول',picked_up:'في الطريق',delivered:'تم التسليم',cancelled:'ملغي'};
const roles = {admin:'أدمن',captain:'كابتن',store:'متجر / مطعم'};
function notice(message, error=false){ $('notice').textContent=message; $('notice').className=error?'error':''; $('notice').style.display='block'; }
async function api(path, data){
  const response = await fetch('/api'+path,{method:data===undefined?'GET':'POST',headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},body:data===undefined?undefined:JSON.stringify(data)});
  const result=await response.json();
  if(!response.ok){if(response.status===401 && token) exit();throw Error(result.error||'تعذر الاتصال');}return result;
}
function exit(){token='';user=null;selectedThread='';$('workspace').hidden=true;$('login-panel').hidden=false;$('logout').hidden=true;$('identity').textContent='';$('messages').textContent='';}
function safeAction(fn){return async event=>{try{await fn(event);}catch(error){notice(error.message,true);}};}
function formData(form){return Object.fromEntries(new FormData(form));}
function key(){return globalThis.crypto?.randomUUID?.() || Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);}
$('login').addEventListener('submit',safeAction(async event=>{
  event.preventDefault();const result=await api('/login',formData(event.target));token=result.token;user=result.user;
  if(user.role!=='admin'){await api('/logout',{});exit();throw Error('هذه اللوحة لحساب الإدارة؛ استخدم تطبيق المتجر أو الكابتن');}
  event.target.reset();$('workspace').hidden=false;$('login-panel').hidden=true;$('logout').hidden=false;
  $('identity').textContent=user.name+' · '+(user.region==='*'?'كل المناطق':user.region);notice('تم تسجيل الدخول');await refresh();
}));
$('logout').addEventListener('click',safeAction(async()=>{await api('/logout',{});exit();}));
$('refresh').addEventListener('click',safeAction(refresh));
document.querySelector('nav').addEventListener('click',event=>{const button=event.target.closest('[data-tab]');if(!button)return;document.querySelectorAll('.tab').forEach(el=>el.hidden=el.id!==button.dataset.tab);document.querySelectorAll('nav button').forEach(el=>el.classList.toggle('active',el===button));});
function captainOptions(captains, region){return captains.filter(c=>!region || c.region===region).map(c=>`<option value="${escapeHTML(c.id)}">${escapeHTML(c.name)} · ${c.online?'متاح':'غير متاح'}</option>`).join('');}
async function refresh(){
  if(!token||refreshBusy)return;refreshBusy=true;
  try{
    const [orders,captains,accounts,newThreads]=await Promise.all([api('/orders'),api('/captains'),api('/accounts'),api('/threads')]);threads=newThreads;
    $('stats').innerHTML=[['طلبات بانتظار كابتن',orders.filter(o=>o.status==='pending').length],['طلبات نشطة',orders.filter(o=>['accepted','picked_up'].includes(o.status)).length],['كباتن متاحون',captains.filter(c=>c.online).length],['طلبات مكتملة',orders.filter(o=>o.status==='delivered').length]].map(([label,count])=>`<div class="stat"><strong>${count}</strong><span>${label}</span></div>`).join('');
    const selectedCaptains=new Map([...$('order-list').querySelectorAll('select')].map(el=>[el.id,el.value]));
    $('order-list').innerHTML=orders.length?orders.map(o=>`<article class="card"><div class="order-top"><h3>${escapeHTML(o.customer_name)} <small>#${o.id.slice(0,8)}</small></h3><span class="badge ${o.status}">${statuses[o.status]}</span></div><p>${escapeHTML(o.address)}</p><div class="details"><span>${escapeHTML(o.region)}</span><span>التوصيل ${money(o.fee)}</span><span>العمولة ${money(o.commission)}</span><span>الطريق: ${escapeHTML(o.route_group)}</span><span>${new Date(o.scheduled_at*1000).toLocaleString('ar-JO')}</span></div><p>${escapeHTML(o.notes)}</p><small>الكابتن: ${escapeHTML(captains.find(c=>c.id===o.captain_id)?.name||'لم يُعيّن')}</small>${['pending','accepted'].includes(o.status)?`<div class="actions"><select id="assign-${o.id}" aria-label="اختيار كابتن"><option value="">اختار كابتن</option>${captainOptions(captains,o.region)}</select><button data-assign="${o.id}">${o.captain_id?'تحويل الطلب':'إسناد الطلب'}</button><button data-cancel="${o.id}">إلغاء الطلب</button></div>`:''}</article>`).join(''):'<div class="card">لا توجد طلبات بعد.</div>';
    selectedCaptains.forEach((value,id)=>{if($(id))$(id).value=value;});
    $('captain-list').innerHTML=captains.map(c=>{
      const hasLocation=c.lat!==null&&c.lng!==null;
      const age=c.location_at?Math.max(0,Math.floor((Date.now()/1000-c.location_at)/60)):null;
      const map=hasLocation?`<iframe class="map" title="موقع ${escapeHTML(c.name)}" loading="lazy" referrerpolicy="no-referrer" src="https://www.openstreetmap.org/export/embed.html?bbox=${c.lng-.01}%2C${c.lat-.01}%2C${c.lng+.01}%2C${c.lat+.01}&amp;layer=mapnik&amp;marker=${c.lat}%2C${c.lng}"></iframe>`:'';
      return `<article class="card"><h3>${escapeHTML(c.name)} <span class="badge">${c.online?'متاح':'غير متاح'}</span></h3><p>${escapeHTML(c.phone)} · ${escapeHTML(c.region)}</p><div class="details"><span>الرصيد ${money(c.balance)}</span><span>المحجوز ${money(c.reserved)}</span></div><p>${age===null?'الموقع لم يصل بعد':age>2?'آخر موقع قديم · قبل '+age+' دقيقة':'آخر تحديث قبل '+age+' دقيقة'}</p>${map}</article>`;
    }).join('')||'<div class="card">أضف أول كابتن من الحسابات.</div>';
    const previous=$('credit-captain').value;$('credit-captain').innerHTML='<option value="">اختار كابتن</option>'+captainOptions(captains);$('credit-captain').value=previous;
    $('account-list').innerHTML=`<table><thead><tr><th>الاسم</th><th>الهاتف</th><th>نوع الحساب</th><th>المنطقة</th></tr></thead><tbody>${accounts.map(a=>`<tr><td>${escapeHTML(a.name)}</td><td>${escapeHTML(a.phone)}</td><td>${roles[a.role]}</td><td>${escapeHTML(a.region)}</td></tr>`).join('')}</tbody></table>`;
    $('thread-list').innerHTML=threads.map(t=>`<button class="thread" data-thread="${escapeHTML(t.id)}">${escapeHTML(t.owner_name)} · ${roles[t.owner_role]}<br><small>${t.kind==='support'?'دعم الإدارة':'شات طلب'} · ${escapeHTML(t.last_message||'لا توجد رسائل')}</small></button>`).join('')||'<p>لا توجد محادثات.</p>';
    if(selectedThread)await readMessages();
  }finally{refreshBusy=false;}
}
$('order-list').addEventListener('click',safeAction(async event=>{
  const button=event.target.closest('button');if(!button)return;
  if(button.dataset.assign){const id=button.dataset.assign;const captain_id=$('assign-'+id).value;if(!captain_id)throw Error('اختار كابتن أولاً');await api('/orders/'+id+'/assign',{captain_id});}
  if(button.dataset.cancel){if(!confirm('تأكيد إلغاء الطلب؟'))return;await api('/orders/'+button.dataset.cancel+'/status',{status:'cancelled'});}
  notice('تم تحديث الطلب');await refresh();
}));
$('create-account').addEventListener('submit',safeAction(async event=>{event.preventDefault();await api('/accounts',formData(event.target));event.target.reset();notice('تم إنشاء الحساب');await refresh();}));
$('credit').addEventListener('submit',safeAction(async event=>{
  event.preventDefault();const data=formData(event.target);data.amount=Math.round(Number(data.amount)*1000);
  const signature=JSON.stringify(data);if(signature!==creditPayload){creditPayload=signature;creditKey=key();}
  await api('/wallet/credit',{...data,idempotency_key:creditKey});creditKey='';creditPayload='';event.target.reset();notice('تم شحن المحفظة');await refresh();
}));
$('thread-list').addEventListener('click',safeAction(async event=>{const button=event.target.closest('[data-thread]');if(!button)return;selectedThread=button.dataset.thread;$('chat-title').textContent=threads.find(t=>t.id===selectedThread)?.owner_name||'محادثة';await readMessages();}));
async function readMessages(){const messages=await api('/threads/'+selectedThread+'/messages');$('messages').innerHTML=messages.map(m=>`<div class="message"><small>${escapeHTML(m.sender_name)} · ${new Date(m.created_at*1000).toLocaleTimeString('ar-JO')}</small>${escapeHTML(m.body)}</div>`).join('');}
$('send-message').addEventListener('submit',safeAction(async event=>{event.preventDefault();if(!selectedThread)throw Error('اختار محادثة أولاً');await api('/threads/'+selectedThread+'/messages',formData(event.target));event.target.reset();await readMessages();}));
setInterval(()=>{if(token)refresh().catch(error=>notice(error.message,true));},10000);
