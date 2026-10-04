// One utterance per interval includes every open room; refreshed data prevents stale alarms.
function createWallboardRepeater(now,announce){
  let enabled=false,last=0,calls=[],interval=120000,updated=0;
  return {
    enable(){enabled=true;last=now()},
    update(items,seconds){calls=items.filter(c=>!c.timer_stop&&!c.arrived_at&&!c.resolved_at&&!['arrived','resolved','closed','ready'].includes(c.status));interval=Math.max(1,Number(seconds)||120)*1000;updated=now()},
    tick(){const t=now();if(!enabled||!calls.length||t-updated>10000||t-last<interval)return;last=t;announce(calls)}
  };
}
// Recall changes are independent of call ID and scheduled reminders.
function createWallboardRecallAnnouncements(isEnabled,announce){
  const seen=new Map();
  return {update(calls){for(const c of calls){
    const count=Math.max(0,Number(c.recall_count)||0),previous=seen.get(c.id);
    seen.set(c.id,count);
    if(previous===undefined||count<=previous||!isEnabled())continue;
    if(c.timer_stop||c.arrived_at||c.resolved_at||['arrived','resolved','closed','ready'].includes(c.status))continue;
    announce(c);
  }}};
}
