"""Compact notification progress shown inside the native app login card."""
SCRIPT = r"""
(function(){
 if(window.nativeProgress)return;
 const form=document.querySelector('form[action="/login"]');if(!form)return;
 const button=form.querySelector('button.btn');
 const box=document.createElement('div');box.id='native-notification-progress';
 box.style.cssText='border:1px solid #8bbaff;background:#f8fbff;border-radius:12px;padding:12px;margin:16px 0;color:#12417e;text-align:left';
 box.innerHTML='<b style="font-size:13px">🔔 Notifications Required</b><div id="native-progress-message" style="font-size:11px;margin:7px 0">Notifications are required. Sign in to verify your device.</div><div style="display:flex;gap:5px"><span>Permission</span><span>Push Subscription</span><span>Test Alert</span><span>Device Confirmed</span></div>';
 const pills=box.lastElementChild.children;
 for(const p of pills)p.style.cssText='flex:1;min-width:0;text-align:center;font-size:9px;border:1px solid #c6d8ef;border-radius:20px;padding:6px 2px;background:white';
 button.before(box);
 let receiptWatchdog;
 function reportFailure(message){fetch('/api/client-error',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source:'native-notifications',path:'/api/mobile/ready-received',type:'NativeVerificationFailure',message}),keepalive:true}).catch(()=>{});}
 window.nativeProgress=function(stage,message,action){
  if(action)reportFailure(message);
  if(stage>=3||action){clearTimeout(receiptWatchdog);receiptWatchdog=null;}
  if(stage===2&&!action&&!receiptWatchdog)receiptWatchdog=setTimeout(()=>{reportFailure('Device test alert was not confirmed within 65 seconds.');nativeProgress(2,'Test alert was not confirmed. Check notifications and retry.','Retry');receiptWatchdog=null;},65000);
  document.getElementById('native-progress-message').textContent=message;
  for(let i=0;i<4;i++){pills[i].style.background=i<stage?'#eaffef':'white';pills[i].style.borderColor=i<stage?'#38ce71':'#c6d8ef';pills[i].style.color=i<stage?'#087c38':'#12417e';}
  button.textContent=action||(stage===0&&location.pathname!=='/mobile/setup'?'Verifying Credentials…':stage===4?'Opening Workspace…':'Verifying Notifications…');button.disabled=!action;
 };
 if(location.pathname==='/mobile/setup'){
  for(const input of form.querySelectorAll('input'))input.disabled=true;
  form.addEventListener('submit',e=>{e.preventDefault();if(window.BurjeelNative)window.BurjeelNative.postMessage(JSON.stringify({command:'retry'}));});
  document.querySelector('.demo')?.remove();
 }else{form.addEventListener('submit',()=>nativeProgress(0,'Verifying your sign-in details…',''));}
})();
"""
