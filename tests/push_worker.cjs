const vm=require('node:vm'),assert=require('node:assert/strict');
let input='';process.stdin.on('data',s=>input+=s);process.stdin.on('end',async()=>{
 try{
  const {sw,js}=JSON.parse(input);
  const handlers={};let displayed=0,reported=0,task;
  const context={self:{addEventListener:(n,f)=>handlers[n]=f,registration:{showNotification:async()=>{displayed++}}},AbortController,setTimeout,clearTimeout,
   fetch:(_u,{signal})=>{reported++;return new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>reject(Error('timeout'))))}};
  vm.runInNewContext(sw,context);
  handlers.push({data:{json:()=>({verification_token:'test'})},waitUntil:p=>task=p});
  await new Promise(r=>setImmediate(r));
  assert.equal(displayed,1,'visible notification must precede a stalled verification fetch');assert.equal(reported,1);
  // Real call: no page/client is open and no fetch is required to display.
  handlers.push({data:{json:()=>({title:'Call',body:'Room 1'})},waitUntil:p=>task=p});await task;assert.equal(displayed,2);
  const sub={endpoint:'https://push.example/pwa',options:{applicationServerKey:new Uint8Array([1])},toJSON(){return{endpoint:this.endpoint}},unsubscribe(){throw Error('must not unsubscribe when server row is missing')}};
  let registrations=0;
  const ready={pushManager:{getSubscription:async()=>sub,subscribe:async()=>{throw Error('must preserve live subscription')}}};
  const doc={readyState:'loading',getElementById:()=>null,addEventListener(){},querySelector:s=>s==='.userbox'?{}:null,querySelectorAll:()=>[]};
  const sandbox={document:doc,window:{VAPID_PUBLIC_KEY:'AQ',addEventListener(){},matchMedia:()=>({matches:true}),navigator:{}},navigator:{serviceWorker:{register:async()=>({update:async()=>{}}),ready:Promise.resolve(ready)},platform:'Test',userAgent:'Test'},PushManager:{},Notification:{permission:'granted'},setInterval(){},Uint8Array,atob,fetch:async url=>{if(url==='/api/push/subscribe')registrations++;return{ok:true,json:async()=>({force_resubscribe:true})}}};
  Object.assign(sandbox.window,{PushManager:sandbox.PushManager,Notification:sandbox.Notification});
  vm.runInNewContext(js,sandbox);
  const promises=[sandbox.ensurePushHealthy(),sandbox.ensurePushHealthy(),sandbox.ensurePushHealthy()];
  assert.equal(promises[0],promises[1]);assert.deepEqual(await Promise.all(promises),[true,true,true]);assert.equal(registrations,1);
  assert.equal(sandbox.pushDeviceMeta().display_mode,'pwa');sandbox.window.matchMedia=()=>({matches:false});assert.equal(sandbox.pushDeviceMeta().display_mode,'browser');
  console.log('PASS: worker display without clients, stalled receipt request, preserved subscription and single-flight repair');
 }catch(e){console.error(e);process.exitCode=1}
});
