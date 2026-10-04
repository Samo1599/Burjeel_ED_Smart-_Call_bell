/* Scoped operational dashboard presentation. Existing API actions remain in app.js. */
window.openOpsReassign=function(key){
 const source=document.getElementById('ops-reassign-'+key),dialog=document.getElementById('opsReassignDialog');
 if(!source||!dialog)return;
 document.getElementById('opsReassignContent').replaceChildren(source.content.cloneNode(true));
 dialog.showModal();
};
let opsChargeFilter='all';
window.applyOpsChargeFilter=function(){
 document.querySelectorAll('.charge-room-card').forEach(card=>card.hidden=opsChargeFilter==='active'&&card.dataset.active!=='true');
 document.querySelectorAll('[data-charge-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.chargeFilter===opsChargeFilter)));
};
document.addEventListener('click',event=>{
 const button=event.target.closest('[data-charge-filter]');
 if(button){opsChargeFilter=button.dataset.chargeFilter;applyOpsChargeFilter();}
});
async function syncOpsNotifications(){
 if(!document.body.classList.contains('ops-workspace')||!window.NATIVE_PUSH_SESSION)return;
 const b=document.querySelector('[data-notification-button]');if(!b)return;
 try{const r=await fetch('/api/mobile/status',{cache:'no-store'});if(!r.ok)throw Error();const s=await r.json();b.textContent=s.registered?'Device registered · Manage':'Check notifications';}
 catch(_){b.textContent='Notification status unavailable';}
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',syncOpsNotifications);else syncOpsNotifications();
window.addEventListener('focus',syncOpsNotifications);
