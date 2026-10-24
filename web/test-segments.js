// 单独抽出分段逻辑做单元测试
const START_SPEED = 0.5;
const CHANGE_GAP  = 60000;
const MIN_SEG_MS  = 60000;
const INC_STEP    = 1;

function makeRun() {
  return { start: 0, end: null, segments: [], pending: null, speed: 0, incline: 0 };
}

function checkChange(run, now, state) {
  const segs = run.segments;
  const last = segs[segs.length - 1];
  const spdNow = +state.speed.toFixed(1);
  const incRaw = state.incline;
  const incNow = Math.round(incRaw);

  const spdDiff = Math.abs(spdNow - last.speed) >= 0.2;
  const incDiff = Math.abs(incNow - last.incline) >= INC_STEP && incNow !== last.incline;

  if (!spdDiff && !incDiff){
    if (run.pending) run.pending = null;
    return 'reset';
  }

  if (run.pending &&
      Math.abs(run.pending.speed - spdNow) < 0.2 &&
      run.pending.incline === incNow){
    if (now - run.pending.since >= MIN_SEG_MS){
      segs.push({ t: run.pending.since, speed: spdNow, incline: incNow,
                  fromSpeed: last.speed, fromIncline: last.incline });
      run.pending = null;
      return 'new-segment';
    }
    return 'pending-wait';
  }

  run.pending = { speed: spdNow, incline: incNow, since: now };
  return 'pending-start';
}

// ── 测试 ──
let pass = 0, fail = 0;
function assert(cond, msg){
  if (cond) { pass++; console.log('  ✅', msg); }
  else { fail++; console.log('  ❌', msg); }
}

console.log('【测试 1】坡度小数抖动不应分段');
{
  const run = makeRun();
  run.segments.push({t:0, speed:4.0, incline:0, fromSpeed:null, fromIncline:null});
  // 坡度 0 → 0.4（不足 1，不算变化）
  const r1 = checkChange(run, 10000, {speed:4.0, incline:0.4});
  assert(r1 === 'reset', '坡度 0→0.4 视为无变化');
  const r2 = checkChange(run, 20000, {speed:4.0, incline:0.9});
  assert(r2 === 'pending-start', '坡度 0→0.9 四舍五入为 1，算变化（挂起）');
  run.pending = null;  // 清理，不影响后续
  assert(run.segments.length === 1, '仍然只有 1 段');
}

console.log('\n【测试 2】坡度变化满 1 分钟才切段');
{
  const run = makeRun();
  run.segments.push({t:0, speed:4.0, incline:0, fromSpeed:null, fromIncline:null});
  // t=10s 坡度变 3
  const r1 = checkChange(run, 10000, {speed:4.0, incline:3});
  assert(r1 === 'pending-start', '开始挂起');
  assert(run.segments.length === 1, '还没切段');
  // t=40s 仍在挂起（30 秒）
  const r2 = checkChange(run, 40000, {speed:4.0, incline:3});
  assert(r2 === 'pending-wait', '挂起中，未满 1 分钟');
  assert(run.segments.length === 1, '仍然 1 段');
  // t=71s 满 1 分钟
  const r3 = checkChange(run, 71000, {speed:4.0, incline:3});
  assert(r3 === 'new-segment', '满 1 分钟，切段');
  assert(run.segments.length === 2, '现在 2 段');
  assert(run.segments[1].incline === 3, '新段坡度 = 3（整数）');
}

console.log('\n【测试 3】1 分钟内变回去，应取消挂起');
{
  const run = makeRun();
  run.segments.push({t:0, speed:4.0, incline:0, fromSpeed:null, fromIncline:null});
  checkChange(run, 10000, {speed:4.0, incline:3});   // 挂起
  const r = checkChange(run, 30000, {speed:4.0, incline:0});  // 变回去
  assert(r === 'reset', '回到原值，取消挂起');
  assert(run.pending === null, 'pending 已清空');
  assert(run.segments.length === 1, '仍然 1 段');
}

console.log('\n【测试 4】速度变化同样需要持续 1 分钟');
{
  const run = makeRun();
  run.segments.push({t:0, speed:4.0, incline:0, fromSpeed:null, fromIncline:null});
  checkChange(run, 5000, {speed:6.0, incline:0});
  assert(run.segments.length === 1, '刚开始变，未切段');
  checkChange(run, 66000, {speed:6.0, incline:0});
  assert(run.segments.length === 2, '满 1 分钟切段');
  assert(run.segments[1].speed === 6.0, '新段速度 6.0');
  assert(run.segments[1].fromSpeed === 4.0, '记录了从 4.0 变来');
}

console.log('\n【测试 5】坡度取整验证');
{
  const run = makeRun();
  run.segments.push({t:0, speed:4.0, incline:0, fromSpeed:null, fromIncline:null});
  checkChange(run, 5000, {speed:4.0, incline:2.7});
  checkChange(run, 66000, {speed:4.0, incline:2.7});
  assert(run.segments[1].incline === 3, '坡度 2.7 → 取整为 3');
}

console.log(`\n${'='.repeat(40)}`);
console.log(`通过 ${pass} 项，失败 ${fail} 项`);
process.exit(fail ? 1 : 0);
