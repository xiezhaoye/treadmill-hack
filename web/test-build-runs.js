// 用真实 HA 数据验证 buildRuns 算法
const START_SPEED = 0.5, MIN_RUN_SEC = 20, MERGE_WINDOW = 15000;
const FIRMWARE_FIX_TS = Date.UTC(2026, 9, 24, 3, 20, 46);

function toSeries(pts){
  const out = [];
  for (const p of pts){
    const v = parseFloat(p.state);
    if (isNaN(v)) continue;
    const t = new Date(p.last_changed || p.lu).getTime();
    if (isNaN(t)) continue;
    out.push([t, v]);
  }
  return out.sort((a,b)=>a[0]-b[0]);
}
function valueAt(s, t){ let v=0; for (const [ts,val] of s){ if(ts<=t) v=val; else break; } return v; }

function buildRuns(speed, incline){
  const found = []; let cur = null;
  for (const [t,v] of speed){
    if (v > START_SPEED){ if(!cur) cur={start:t,pts:[]}; cur.pts.push([t,v]); }
    else if (cur){ cur.end=t; found.push(cur); cur=null; }
  }
  if (cur){ cur.end = speed.length?speed[speed.length-1][0]:cur.start; found.push(cur); }

  const result = [];
  for (const r of found){
    const durSec = (r.end - r.start)/1000;
    if (durSec < MIN_RUN_SEC) continue;

    const events = [];
    let prevS = r.pts[0][1];
    const legacyRun = r.start < FIRMWARE_FIX_TS;
    let prevI = legacyRun ? 0 : Math.round(valueAt(incline, r.start));
    events.push({t:r.start, speed:+prevS.toFixed(1), incline: legacyRun?0:prevI, kind:'start'});

    for (const [t,v] of r.pts){
      if (t <= r.start) continue;
      const s = +v.toFixed(1);
      if (Math.abs(s-prevS) >= 0.2){
        events.push({t, speed:s, incline: legacyRun?0:Math.round(valueAt(incline,t)), kind:'speed'});
        prevS = s;
      }
    }
    if (!legacyRun) for (const [t,v] of incline){
      if (t <= r.start || t >= r.end) continue;
      const i = Math.round(v);
      if (i !== prevI){
        events.push({t, speed:+valueAt(speed,t).toFixed(1), incline:i, kind:'incline'});
        prevI = i;
      }
    }
    events.sort((a,b)=>a.t-b.t);

    const segments = [];
    for (const ev of events){
      const last = segments[segments.length-1];
      if (last && ev.t - last.lastChange <= MERGE_WINDOW){
        last.speed = ev.speed; last.incline = ev.incline; last.lastChange = ev.t;
      } else {
        segments.push({t:ev.t, speed:ev.speed, incline:ev.incline, lastChange:ev.t,
                       fromSpeed: last?last.speed:null, fromIncline: last?last.incline:null});
      }
    }
    for (let i=0;i<segments.length;i++){
      const segEnd = segments[i+1] ? segments[i+1].t : r.end;
      segments[i].durationSec = Math.round((segEnd - segments[i].t)/1000);
    }
    result.push({start:r.start, end:r.end, durationSec:Math.round(durSec), segments});
  }
  return result.sort((a,b)=>b.start-a.start);
}

// 用真实数据
const speedRaw = require('/tmp/ha_speed.json');
const incRaw = require('/tmp/ha_inc.json');
const S = toSeries(speedRaw[0] || []);
const I = toSeries(incRaw[0] || []);
console.log(`速度数据点: ${S.length}, 坡度数据点: ${I.length}\n`);

const runs = buildRuns(S, I);
console.log(`识别出 ${runs.length} 次跑步:\n`);
for (const r of runs){
  const d = new Date(r.start);
  console.log(`【${d.getMonth()+1}/${d.getDate()} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}】 时长 ${r.durationSec}秒, ${r.segments.length} 段`);
  for (const s of r.segments){
    const ts = new Date(s.t);
    console.log(`   ${String(ts.getHours()).padStart(2,'0')}:${String(ts.getMinutes()).padStart(2,'0')}  速度 ${s.speed} 坡度 ${s.incline}%  持续 ${s.durationSec}秒`);
  }
  console.log();
}
