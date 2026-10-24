# Web 控制面板

> 替代 ESPHome 自带的简陋页面，iOS 设计风格，适配移动端。

## 一、为什么需要这个

ESPHome 的 `web_server` 只能返回一个空壳页面：

```html
<esp-app></esp-app><script src="https://oi.esphome.io/v3/www.js"></script>
```

页面完全由外部 JS 渲染，**无法定制 HTML/CSS/布局**。可调的只有 `css_url` / `js_url` 两个地址。

所以要自定义界面，只能另起一个页面，通过 ESPHome 暴露的 REST/SSE 接口操作设备。

## 二、架构

```
浏览器
   │  http://192.168.199.74:8099/
   ▼
┌──────────────────────────────────┐
│  5095 · treadmill-web.service    │
│  python3 treadmill-web.py        │
│                                  │
│  /            → 静态 index.html  │
│  /events      → 转发 SSE         │
│  /sensor/...  → 转发 REST GET    │
│  /button/...  → 转发 REST POST   │
│  /number/...  → 转发 REST POST   │
│  /ha/history  → 转发 HA 历史查询  │
└──────────────────────────────────┘
   │  http://192.168.199.123:80
   ▼
ESP32-S3（balcony-treadmill）
```

**为什么走 5095 中转**：M1 有 macOS 本地网络隐私限制，Chrome 和命令行 Python 都连不上局域网设备（只有 `curl`/`nc` 可以）。5095 是 Ubuntu，没这个限制。

## 三、部署

### 3.1 文件位置（5095）

```
~/treadmill-web/
├── index.html          自定义页面
├── treadmill-web.py    反向代理服务
└── web.log
```

### 3.2 上传

```bash
scp web/index.html web/treadmill-web.py 5095:~/treadmill-web/
```

### 3.3 systemd 用户服务

`~/.config/systemd/user/treadmill-web.service`：

```ini
[Unit]
Description=Treadmill Web Panel
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/treadmill-web
ExecStart=/usr/bin/python3 %h/treadmill-web/treadmill-web.py
Restart=always
RestartSec=3
Environment=PORT=8099
Environment=ESP_HOST=192.168.199.123

[Install]
WantedBy=default.target
```

启用：

```bash
systemctl --user daemon-reload
systemctl --user enable --now treadmill-web
loginctl enable-linger $USER      # 开机自启（不依赖用户登录）
```

### 3.4 访问

```
http://192.168.199.74:8099/
```

同网段手机 / 电脑都能访问。也可经 tailnet 访问：`http://5095:8099/`。

## 四、ESPHome REST API（实测确认）

| 操作 | 方法 | 路径 | Body |
|---|---|---|---|
| 读传感器 | GET | `/sensor/<name>` | — |
| 按下按钮 | POST | `/button/<name>/press` | — |
| 设定数值 | POST | `/number/<name>/set` | `value=1.5` |
| 读二值传感器 | GET | `/binary_sensor/<name>` | — |
| 实时事件流 | GET | `/events` | — |

**踩坑**：
- `/button/<name>` （不带 `/press`）→ 404
- `/number/<name>` （不带 `/set`）→ 404
- POST 不带 `Content-Length` → 411

**返回格式**：

```json
{"id":"sensor/treadmill_current_speed","value":0,"state":"0.00 km/h"}
```

**SSE 事件流格式**：

```
event: state
data: {"id":"sensor/treadmill_current_speed","domain":"sensor",
       "name":"treadmill_current_speed","value":1,
       "state":"1.00 km/h","uom":"km/h"}
```

## 五、界面结构

```
┌─────────────────────────────────┐
│ 🏠  跑步机              ●       │  header
├─────────────────────────────────┤
│   实况    │    记录              │  标签栏（iOS 分段控件）
├─────────────────────────────────┤
│                                 │
│   [实况页]                       │
│   ┌───────────────────────┐    │
│   │      4.5  km/h        │    │  当前速度（大字）
│   │      当前速度          │    │
│   ├───────────────────────┤    │
│   │  2.0%       -77 dBm   │    │  坡度 / 信号
│   └───────────────────────┘    │
│   控制：[启动][停止][暂停][一键]  │
│   设定：速度滑块 / 坡度滑块        │
│   维护：解锁 / 请求控制权          │
│                                 │
│   [记录页]                       │
│   今天 11:39  1分 · 0.05km · 2段 │
│   今天 11:23  1分 · 0.06km · 2段 │
│   今天 10:19  46分 · 3.45km · 44段│
│   从历史数据导入            [导入] │
│                                 │
└─────────────────────────────────┘
```

**Home 图标下拉**：切换「跑步机」/「ESP32」两个子视图（ESP32 页显示芯片温度、
内存、WiFi、蓝牙状态等诊断信息）。

## 六、运行记录机制

### 6.1 自动识别

| 事件 | 判定 |
|---|---|
| **开始** | 速度 > 0.5 km/h 持续 3 秒 |
| **结束** | 速度归零持续 2 分钟 |
| **变动** | 速度变化 ≥ 0.2 km/h 或坡度变化 ≥ 0.5% |
| **合并** | 1 分钟内的多次变动合并为一条（记录最终值） |

不需要手动开始/停止，跑起来自动记录。

### 6.2 记录内容

每条记录是一组**变动片段**：

```json
{
  "start": 1792812189575,      // 开始时间戳
  "end":   1792812289502,      // 结束时间戳
  "segments": [
    { "t": ..., "speed": 2.1, "incline": 0.0,
      "fromSpeed": null, "fromIncline": null },   // 起步
    { "t": ..., "speed": 1.0, "incline": 0.0,
      "fromSpeed": 2.1, "fromIncline": 0.0 }      // 速度 2.1 → 1.0
  ]
}
```

详情页按时间线展示：

```
运行明细
├─ 开始    今天 11:23
├─ 时长    1 分
├─ 距离    0.06 km
└─ 变动    2 段

● 11:23 · 持续 1 分
  速度 2.1 km/h · 坡度 0%
● 11:24 · 持续 1 秒
  速度 1.0 km/h · 坡度 0%
  速度 2.1 → 1.0
```

### 6.3 存储

- **位置**：浏览器 `localStorage`（键 `treadmill_runs_v2`）
- **容量**：最近 100 条
- **优点**：不占 ESP32 闪存，不依赖服务端数据库
- **缺点**：换浏览器/清缓存会丢

### 6.4 从历史导入

页面无法直接访问 HA API（跨域 + 需要令牌），所以由代理服务转发：

```
浏览器 → /ha/history?entity=xxx&start=2026-10-24T00:00:00+00:00
       → 代理读 /tmp/ha_token
       → HA /api/history/period/...
```

点「从历史数据导入」会：
1. 拉当天所有速度/坡度历史
2. 自动切分出跑步时段（速度 > 0.5）
3. 生成变动片段
4. 按 start 时间去重后追加

**部署要求**：HA 令牌要放到 5095 的 `/tmp/ha_token`（权限 600）。

## 七、页面设计

### 7.1 风格

- **iOS 风格**：系统字体栈、圆角卡片、分组列表、蓝色主色调
- **自动深色模式**：`prefers-color-scheme`
- **移动优先**：`viewport-fit=cover` + `safe-area-inset` 适配刘海屏
- **可加到主屏幕**：`apple-mobile-web-app-capable`，隐藏 Safari 地址栏

配色取自 iOS 系统色：

```
--blue:  #007aff      --green: #34c759
--orange:#ff9500      --red:   #ff3b30
--bg:    #f2f2f7（浅色） / #000000（深色）
--card:  #ffffff（浅色） / #1c1c1e（深色）
```

### 7.2 结构

```
┌─────────────────────────────┐
│ 阳台跑步机          ● 已就绪 │
├─────────────────────────────┤
│         4.8                 │  ← 超大数字，运行时变绿
│         km/h                │
│        当前速度              │
│  ─────────────────────────  │
│    2.0%        -77 dBm      │
│    坡度         信号强度      │
├─────────────────────────────┤
│ 控制                         │
│ ┌─────────┬─────────┐      │
│ │ ▶ 启动  │ ■ 停止  │      │
│ ├─────────┼─────────┤      │
│ │ ‖ 暂停  │ ⚡ 一键  │      │
│ └─────────┴─────────┘      │
├─────────────────────────────┤
│ 设定                         │
│ 速度              0.5 km/h  │
│ ●────────────────────────   │
│ 0.5        7          14    │
│                             │
│ 坡度                   0 % │
│ ●────────────────────────   │
│ 0          7          15    │
├─────────────────────────────┤
│ 维护                         │
│ 解锁              [ 解锁 ]  │
│ 请求控制权        [ 请求 ]  │
└─────────────────────────────┘
```

### 7.3 交互细节

| 功能 | 实现 |
|---|---|
| 实时数据 | `EventSource('/events')`，断线自动重连（递增退避） |
| 滑块防抖 | 拖动时 260ms 后才发请求，避免刷爆 |
| 未连接保护 | 所有控制按钮和滑块 `disabled` |
| 操作反馈 | 底部 Toast 提示 |
| 状态联动 | 速度 > 0 时数字变绿、状态显示「运行中」 |
| 回前台刷新 | `visibilitychange` 时重连 SSE |

## 八、维护

### 8.1 改页面后重新部署

```bash
scp web/index.html 5095:~/treadmill-web/
# 静态文件无需重启服务，刷新浏览器即可
```

### 8.2 改代理逻辑后

```bash
scp web/treadmill-web.py 5095:~/treadmill-web/
ssh 5095 'systemctl --user restart treadmill-web'
```

### 8.3 看日志

```bash
ssh 5095 'journalctl --user -u treadmill-web -f'
# 或
ssh 5095 'tail -f ~/treadmill-web/web.log'
```

### 8.4 健康检查

```bash
curl http://192.168.199.74:8099/health
# {"ok": true, "esp": "http://192.168.199.123:80"}
```

## 九、已知限制

1. **ESP32 的 IP 写死在环境变量里**（`ESP_HOST=192.168.199.123`）。如果路由器重新分配 IP，需要改配置并重启服务。建议在 iStoreOS 里给 ESP32 绑定静态 IP。

2. **无鉴权**。同网段任何人都能访问并控制跑步机。家用环境可接受，若需暴露到公网必须加认证。

3. **页面走 HTTP**。同源的 `/events` 和 REST 不受影响，但如果以后加 HTTPS，需要同步调整代理。

4. **ESP32 断电时**：页面能正常打开（静态文件在 5095），但所有控制失效，状态显示「未连接」。SSE 会持续重连。
