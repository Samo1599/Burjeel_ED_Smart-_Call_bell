/* Nurse presentation only: existing call endpoints and native enrollment stay intact. */
(() => {
  if(!document.getElementById('nurse-live-root'))return;
  let roomFilter='all', handoverRoomId=null, handoverBusy=false;
  const dialog=document.getElementById('handoverDialog');
  function applyRoomFilter() {
    const cards=[...document.querySelectorAll('.nw-room')];
    cards.forEach(card=>card.hidden=roomFilter==='active'&&card.dataset.active!=='true');
    document.querySelectorAll('[data-room-filter]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.roomFilter===roomFilter)));
    const empty=document.getElementById('roomFilterEmpty');
    if(empty){empty.hidden=cards.some(card=>!card.hidden);empty.textContent=roomFilter==='active'?'No active calls in your rooms.':'No rooms assigned to you yet.';}
  }
  document.addEventListener('click',event=>{
    const filter=event.target.closest('[data-room-filter]');
    if(filter){roomFilter=filter.dataset.roomFilter;applyRoomFilter();}
    const handover=event.target.closest('[data-handover-room]');
    if(handover){
      handoverRoomId=Number(handover.dataset.handoverRoom);
      document.getElementById('handoverTitle').textContent='Handover '+handover.dataset.roomCode;
      const select=document.getElementById('handoverRecipient');
      select.replaceChildren(...[...document.getElementById('nwColleagues').options].map(option=>option.cloneNode(true)));
      document.getElementById('handoverError').hidden=true;
      dialog.showModal();
    }
    const menu=document.querySelector('.nw-account');
    if(menu&&menu.open&&!menu.contains(event.target))menu.open=false;
  });
  window.closeNurseHandover=()=>{if(!handoverBusy)dialog.close();};
  dialog.addEventListener('cancel',event=>{if(handoverBusy)event.preventDefault();});
  window.submitNurseHandover=async()=>{
    const select=document.getElementById('handoverRecipient'),error=document.getElementById('handoverError'),button=document.getElementById('handoverSend');
    if(handoverBusy)return;
    if(!select.value){error.textContent='Select a nurse to continue.';error.hidden=false;select.focus();return;}
    handoverBusy=true;button.disabled=true;button.textContent='Sending…';error.hidden=true;
    try{
      const response=await fetch('/api/handover',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({room_id:handoverRoomId,to_nurse_id:select.value})});
      if(!response.ok)throw Error('Handover could not be sent. Please try again.');
      dialog.close();location.reload();
    }catch(e){error.textContent=e.message||'Check your connection and try again.';error.hidden=false;}
    finally{handoverBusy=false;button.disabled=false;button.textContent='Send request';}
  };
  async function syncWorkspaceNotifications(){
    if(!window.NATIVE_PUSH_SESSION){await syncNotificationUi();return;}
    const button=document.querySelector('[data-notification-button]');
    if(button){button.textContent='Manage';button.title='Manage Android notifications';}
    try{
      const response=await fetch('/api/mobile/status',{cache:'no-store'});
      if(!response.ok)throw Error();
      const state=await response.json();
      setPushHealthBadge(state.registered?'ok':'warn',state.registered?'Device registered':'Check notifications');
      if(button)button.textContent='Manage';
    }catch(_){setPushHealthBadge('warn','Status unavailable');}
  }
  applyRoomFilter();syncWorkspaceNotifications();
  startSilentRefresh('#nurse-live-root',3000,applyRoomFilter);
  window.addEventListener('focus',syncWorkspaceNotifications);
  window.addEventListener('online',syncWorkspaceNotifications);
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')syncWorkspaceNotifications();});
})();
