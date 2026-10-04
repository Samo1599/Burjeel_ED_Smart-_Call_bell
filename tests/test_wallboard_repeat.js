const fs=require('fs'),vm=require('vm'),assert=require('assert');
vm.runInThisContext(fs.readFileSync('ui/nurse/wallboard-repeat.js','utf8'));
let now=0,announced=[];const r=createWallboardRepeater(()=>now,c=>announced.push(c.map(x=>x.id)));
const calls=[{id:1,room:'ED-01',status:'acknowledged'},{id:2,room:'ED-02',status:'taken_over'},{id:3,status:'arrived',timer_stop:'x'}];
r.update(calls,4);now=4000;r.tick();assert.equal(announced.length,0);
r.enable();r.tick();assert.equal(announced.length,0);
now=8000;r.update(calls,4);r.tick();assert.deepEqual(announced,[[1,2]]);
now=12000;r.update(calls,4);r.tick();assert.equal(announced.length,2);
r.update([{id:1,status:'resolved'},{id:2,status:'arrived'}],4);now=16000;r.tick();assert.equal(announced.length,2);
r.update(calls,2);now=30000;r.tick();assert.equal(announced.length,2); // stale/disconnected
r.update(calls,2);r.tick();assert.equal(announced.length,3);
console.log('PASS: sound enable, custom interval, all rooms, ack/takeover, arrival/closure, stale suppression');
