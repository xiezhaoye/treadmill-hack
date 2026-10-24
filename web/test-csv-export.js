function csvEscape(v){
  const s = String(v);
  if (/[",\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
  return s;
}
function runDistance(r){
  let d = 0;
  for (const s of r.segments) d += s.speed * (s.durationSec / 3600);
  return +d.toFixed(2);
}

// 模拟一条记录
const runs = { list: [{
  start: new Date('2026-10-24T12:34:00+08:00').getTime(),
  end:   new Date('2026-10-24T12:36:16+08:00').getTime(),
  durationSec: 136,
  segments: [
    {t: new Date('2026-10-24T12:34:00+08:00').getTime(), speed:1.3, incline:0, durationSec:56, fromSpeed:null, fromIncline:null},
    {t: new Date('2026-10-24T12:34:56+08:00').getTime(), speed:2.0, incline:0, durationSec:79, fromSpeed:1.3, fromIncline:0},
    {t: new Date('2026-10-24T12:36:15+08:00').getTime(), speed:1.0, incline:0, durationSec:1,  fromSpeed:2.0, fromIncline:0},
  ]
}]};

const lines = [];
lines.push(['开始时间','结束时间','总时长(分)','距离(km)','段号','本段开始','本段时长(秒)','速度(km/h)','坡度(%)','速度变化','坡度变化'].map(csvEscape).join(','));

for (const r of runs.list){
  const startStr = new Date(r.start).toLocaleString('zh-CN');
  const endStr = new Date(r.end).toLocaleString('zh-CN');
  const dist = runDistance(r);
  r.segments.forEach((s, i) => {
    const segStart = new Date(s.t).toLocaleString('zh-CN');
    const spdChange = (s.fromSpeed !== null && Math.abs(s.fromSpeed - s.speed) >= 0.2)
      ? s.fromSpeed.toFixed(1) + '→' + s.speed.toFixed(1) : '';
    const incChange = (s.fromIncline !== null && s.fromIncline !== s.incline)
      ? s.fromIncline + '→' + s.incline : '';
    lines.push([startStr, endStr, (r.durationSec/60).toFixed(1), dist, i+1, segStart, s.durationSec, s.speed.toFixed(1), s.incline, spdChange, incChange].map(csvEscape).join(','));
  });
}

const csv = '\ufeff' + lines.join('\r\n');
console.log("=== 生成的 CSV ===");
console.log(csv.replace('\ufeff','[BOM]'));
console.log("\n=== 校验 ===");
const rows = csv.split('\r\n');
console.log("行数:", rows.length, "(1 表头 + 3 数据行)");
console.log("BOM 存在:", csv.charCodeAt(0) === 0xFEFF);
console.log("字段数一致:", rows.every(r => r.split(',').length === 11));
console.log("速度 1 位小数:", rows[1].includes('1.3') && rows[2].includes('2.0'));
console.log("坡度整数:", rows[1].split(',')[8] === '0');
console.log("变化标注:", rows[2].includes('1.3→2.0'));
