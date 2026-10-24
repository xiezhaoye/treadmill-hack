// 分段逻辑单元测试（与 index.html 中的 checkChange 保持同步）
const MERGE_WINDOW = 15000;   // 15 秒合并窗口
const STABLE_HOLD  = 60000;   // 稳定 1 分钟才记录
const INC_STEP     = 1;

function makeRun(){
  return {
    start: 0, end: null,
    segments: [{t:0, speed:4.0, incline:0, fromSpeed:null, fromIncline:null}],
    pending: null,
  };
}

function checkChange(run, now, state){
  const segs = run.segments;
  const last = segs[segs.length - 1];
  const spdNow = +state.speed.toFixed(1);
  const incRaw = state.incline;
  const incNow = Math.round(incRaw);

  const spdDiff = Math.abs(spdNow - last.speed) >= 0.2;
  const incDiff = Math.abs(incNow - last.incline) >= INC_STEP && incNow !== last.incline;

  if (!spdDiff && !incDiff){
    if (run.pending && now - run.pending.lastChange >= STABLE_HOLD){
      run.pending = null;
      return 'discard';
    }
    return 'stable';
  }

  if (run.pending){
    const same = Math.abs(run.pending.speed - spdNow) < 0.2 && run.pending.incline === incNow;
    if (!same){
      run.pending = { speed: spdNow, incline: incNow, since: now, lastChange: now };
      return 'merge-update';
    }
    if (now - run.pending.lastChange >= STABLE_HOLD){
      segs.push({t: run.pending.lastChange, speed: run.pending.speed,
                 incline: run.pending.incline, fromSpeed: last.speed, fromIncline: last.incline});
      run.pending = null;
      return 'new-segment';
    }
    return 'pending-wait';
  }

  run.pending = { speed: spdNow, incline: incNow, since: now, lastChange: now };
  return 'pending-start';
}

let pass=0, fail=0;
function assert(c, m){ if(c){pass++;console.log('  ✅',m);}else{fail++;console.log('  ❌',m);} }

console.log('【测试 1】15 秒内连续调整合并成一条');
{
  const r = makeRun();
  checkChange(r, 5000,  {speed:5.0, incline:0});     // 调速度
  checkChange(r, 12000, {speed:5.0, incline:3});     // 7 秒后调坡度 → 合并更新
  assert(r.segments.length === 1, '仍然 1 段（未切段）');
  assert(r.pending.incline === 3, '挂起值已更新为坡度 3');
  checkChange(r, 73000, {speed:5.0, incline:3});     // 稳定满 1 分钟
  assert(r.segments.length === 2, '稳定后切成 2 段');
  assert(r.segments[1].speed === 5.0 && r.segments[1].incline === 3, '新段记录 5.0 km/h + 3%');
}

console.log('\n【测试 2】间隔超过 15 秒的调整算新的变化');
{
  const r = makeRun();
  checkChange(r, 5000,  {speed:5.0, incline:0});
  const p1 = {...r.pending};
  checkChange(r, 25000, {speed:5.0, incline:3});     // 20 秒后 → 重置计时
  assert(r.pending.lastChange === 25000, '计时重置到 25 秒');
  assert(r.pending.incline === 3, '挂起值更新为 3');
}

console.log('\n【测试 3】变化后 1 分钟内变回去 → 丢弃');
{
  const r = makeRun();
  checkChange(r, 5000,  {speed:5.0, incline:0});
  assert(r.pending !== null, '已挂起');
  checkChange(r, 20000, {speed:4.0, incline:0});     // 变回原值
  checkChange(r, 85000, {speed:4.0, incline:0});     // 稳定满 1 分钟 → 丢弃
  assert(r.pending === null, '挂起已丢弃');
  assert(r.segments.length === 1, '仍然 1 段');
}

console.log('\n【测试 4】未满 1 分钟不切段');
{
  const r = makeRun();
  checkChange(r, 5000,  {speed:5.0, incline:0});
  checkChange(r, 40000, {speed:5.0, incline:0});     // 35 秒
  assert(r.segments.length === 1, '35 秒，还没切段');
  checkChange(r, 66000, {speed:5.0, incline:0});     // 61 秒
  assert(r.segments.length === 2, '61 秒，切段了');
}

console.log('\n【测试 5】坡度取整');
{
  const r = makeRun();
  checkChange(r, 5000,  {speed:4.0, incline:2.7});
  assert(r.pending.incline === 3, '2.7 → 3');
  const r2 = makeRun();
  checkChange(r2, 5000, {speed:4.0, incline:0.4});
  assert(r2.pending === null, '0.4 不算变化（取整为 0）');
}

console.log('\n【测试 6】15 秒滚动窗口（理解 A）');
{
  const r = makeRun();
  checkChange(r, 0,     {speed:5.0, incline:0});   // t=0 调速度
  checkChange(r, 12000, {speed:5.0, incline:3});   // t=12 调坡度（距上次 12s，合并）
  checkChange(r, 26000, {speed:6.0, incline:3});   // t=26 调速度（距上次 14s，合并）
  assert(r.pending.speed === 6.0 && r.pending.incline === 3, '三次调整合并为 6.0 + 3%');
  assert(r.pending.lastChange === 26000, '计时滚到最后一次调整');
}

console.log(`\n${'='.repeat(42)}`);
console.log(`通过 ${pass} 项，失败 ${fail} 项`);
process.exit(fail ? 1 : 0);
