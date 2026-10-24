// 模拟刷新流程，验证不报错
const _emptyEl = {
  title:'', textContent:'', innerHTML:'', value:'', style:{},
  classList:{add(){},remove(){},toggle(){},contains(){return false}},
  onclick:null,
};
const $ = id => _emptyEl;

// 模拟真实返回数据
const snapshots = {
  'sensor/treadmill_current_speed': {value: 4.5, state: '4.5 km/h'},
  'sensor/treadmill_current_incline': {value: 3, state: '3 %'},
  'binary_sensor/treadmill_connected': {value: true, state: 'ON'},
  'sensor/esp32_uptime': {value: 8520, state: '8520 s'},
};

const state = {
  connected:false, speed:0, incline:0, bleRssi:null,
  temp:null, freeRam:null, minFreeRam:null, maxBlock:null,
  frag:null, psram:null, loop:null, wifiRssi:null, uptime:null
};

const MAP = {
  'sensor/treadmill_current_speed':   v => state.speed = parseFloat(v) || 0,
  'sensor/treadmill_current_incline': v => state.incline = parseFloat(v) || 0,
  'binary_sensor/treadmill_connected':v => state.connected = (v === true || v === 'ON'),
  'sensor/esp32_uptime':              v => state.uptime = (v === null ? null : parseFloat(v)),
};

let errors = [];
function handleState(ev){
  try {
    let d; try{ d = JSON.parse(ev); }catch(e){ return; }
    const id = d.id || '';
    const fn = MAP[id];
    if (fn){ fn(d.value); return; }
  } catch(e){
    errors.push(e.message);
  }
}

function renderEsp32(){
  try {
    // 模拟所有 DOM 操作（用安全代理，不会崩）
    const t = state.temp;
    $('vTemp').innerHTML = t === null ? '—' : t.toFixed(1);
    $('vUptime').textContent = state.uptime === null ? '—' : Math.floor(state.uptime) + ' 秒';
    $('vIp').textContent = '192.168.199.74';
    const _d2 = $('dot');
    if (_d2) _d2.title = state.uptime === null ? '读取中…' : '在线';
  } catch(e){
    errors.push('renderEsp32: ' + e.message);
  }
}

// 模拟 pullSnapshot
async function pullSnapshot(){
  for (const [key, val] of Object.entries(snapshots)){
    handleState(JSON.stringify({id: key, value: val.value, state: val.state}));
  }
  renderEsp32();
}

(async () => {
  await pullSnapshot();
  console.log('=== 刷新模拟结果 ===');
  console.log('速度:', state.speed);
  console.log('坡度:', state.incline);
  console.log('连接:', state.connected);
  console.log('运行时长:', state.uptime);
  console.log('错误:', errors.length ? errors : '无 ✅');
  process.exit(errors.length ? 1 : 0);
})();
