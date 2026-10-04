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
let recalls=[],sound=true;
const observer=createWallboardRecallAnnouncements(()=>sound,c=>recalls.push([c.id,c.recall_count]));
observer.update([{id:8,status:'new',recall_count:0}]);
observer.update([{id:8,status:'acknowledged',recall_count:1}]);
observer.update([{id:8,status:'acknowledged',recall_count:1}]);
assert.deepEqual(recalls,[[8,1]]);
sound=false;observer.update([{id:8,status:'new',recall_count:2}]);sound=true;
observer.update([{id:8,status:'new',recall_count:2}]);assert.equal(recalls.length,1);
observer.update([{id:8,status:'taken_over',recall_count:3}]);assert.deepEqual(recalls,[[8,1],[8,3]]);
observer.update([{id:9,status:'new',recall_count:2}]);assert.equal(recalls.length,2); // baseline, no historical replay
observer.update([{id:9,status:'arrived',recall_count:3,timer_stop:'x'}]);assert.equal(recalls.length,2);
console.log('PASS: new recalls announce once, ack/takeover, sound off, historical baseline and arrival suppression');
