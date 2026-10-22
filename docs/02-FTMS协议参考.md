# FTMS 协议参考

> **FTMS** = Fitness Machine Service，Bluetooth SIG 标准（[官方规范](https://www.bluetooth.com/specifications/specs/fitness-machine-service-1-0/)）
> UUID: `0x1826` — 跑步机、椭圆机、划船机、动感单车都用这套

---

## 一、服务与特征值

| UUID | 名称 | 属性 | 用途 |
|---|---|---|---|
| `0x1826` | Fitness Machine Service | — | 主服务 |
| **`0x2AD9`** | **Fitness Machine Control Point** | Write + Indicate | **发指令**（核心） |
| `0x2ACD` | Treadmill Data | Notify | 跑步机实时数据 |
| `0x2ADA` | Fitness Machine Status | Notify | 状态变化 |
| `0x2AD4` | Supported Speed Range | Read | 支持的速度范围 |
| `0x2AD5` | Supported Inclination Range | Read | 支持的坡度范围 |
| `0x2AD6` | Supported Resistance Level Range | Read | 阻力范围（单车） |
| `0x2ACC` | Fitness Machine Feature | Read | 设备能力标志 |
| `0x2AD3` | Training Status | Notify + Read | 训练状态 |

---

## 二、控制点指令（写入 `0x2AD9`）

### 2.1 指令格式

```
[opcode] [parameters...]
```

用 `WRITE_TYPE_DEFAULT`（带响应的写），不支持 `WRITE_TYPE_NO_RESPONSE`。

### 2.2 常用指令

| Opcode | 指令名 | 参数 | 说明 |
|---|---|---|---|
| **`0x00`** | **Request Control** | 无 | **必须先发**，否则后续指令被拒 |
| **`0x01`** | Reset | 无 | 复位 |
| **`0x02`** | **Set Target Speed** | `uint16` (0.01 km/h) | 目标速度，小端 |
| **`0x03`** | **Set Target Inclination** | `int16` (0.1%) | 目标坡度，小端 |
| `0x04` | Set Target Resistance | `uint8` | 阻力（单车） |
| `0x05` | Set Target Power | `int16` (W) | 目标功率 |
| `0x06` | Set Target Heart Rate | `uint8` (bpm) | 目标心率 |
| **`0x07`** | **Start / Resume** | 无 | 开始或继续 |
| **`0x08`** | **Stop / Pause** | `uint8` | `0x01`=Stop, `0x02`=Pause |
| `0x11` | Set Targeted Cadence | `uint16` (0.5/min) | 步频 |
| `0x12` | Set Target Distance | `uint24` (m) | 目标距离 |

### 2.3 完整示例

```python
# 1. 请求控制权
"00"

# 2. 启动
"07"

# 3. 设速度 5.0 km/h
#    5.0 × 100 = 500 = 0x01F4 → 小端 f401
"02f401"

# 4. 设坡度 4.0%
#    4.0 × 10 = 40 = 0x0028 → 小端 2800
"032800"

# 5. 停止
"0801"

# 6. 暂停
"0802"
```

---

## 三、响应格式（`0x2AD9` 的 Indicate）

```
80 [opcode] [result] [parameters...]
```

### 3.1 Result 码

| Code | 含义 | 说明 |
|---|---|---|
| **`0x01`** | **Success** | ✅ 成功 |
| `0x02` | Op Code Not Supported | 不支持该指令 |
| `0x03` | Invalid Parameter | 参数错误（超范围） |
| `0x04` | Operation Failed | 执行失败 |
| **`0x05`** | **Invalid Parameter / Not Authorized** | ⚠️ **通常是没解锁！** |

### 3.2 实例

```
发送 00          → 接收 800001      （Request Control 成功）
发送 07          → 接收 800701      （Start 成功）
发送 02c800      → 接收 800205c800  （速度设置成功，回显参数）
发送 0801        → 接收 800801      （停止成功）
```

**未解锁时的表现**：
```
发送 00          → 接收 800005      （05 = 拒绝）
```

---

## 四、实时数据（`0x2ACD` 通知）

### 4.1 标准 FTMS Treadmill Data 格式

| 偏移 | 长度 | 字段 | 说明 |
|---|---|---|---|
| 0 | 2 | Flags | 位标志，决定后续字段是否存在 |
| 2+ | 2 | Instantaneous Speed | 0.01 km/h |
| 4+ | 2 | Average Speed | 0.01 km/h |
| 6+ | 3 | Total Distance | 米 |
| 9+ | 2 | Inclination | 0.1% |
| 11+ | 1 | Ramp Angle | 度 |
| 12+ | 2 | Positive Elevation | 米 |
| ... | ... | ... | 见官方规范 |

### 4.2 ⚠️ 厂商可能不完全合规

我实测的 YPOO M5 数据帧是**私有变体**：

```
9c25 f401 0000 0028 00ff7f 0100 00000000 1200 0000 0600 0000 00
```

| 偏移 | 值 | 推断含义 | 换算 |
|---|---|---|---|
| 0x00 | `9c25` | 帧头（固定） | — |
| **0x02** | **`f401`** | 当前速度 | ÷100 = 5.00 km/h |
| **0x04** | **`0028`** | 当前坡度 | ÷10 = 4.0% |
| 0x06 | `0000` | 保留 | — |
| 0x08 | `00ff7f` | flags | 固定 |
| 0x0C | `01000000` | 状态位 | — |
| 0x10 | `1200` | 时间或距离 | 递增 |
| 0x14 | `0600` | 步数/卡路里 | 递增 |

> **务必用自己的抓包验证字段映射**——别照抄我的偏移。

---

## 五、Range 查询（了解设备能力）

读 `0x2AD4`（速度范围）和 `0x2AD5`（坡度范围）可以知道设备上限：

```
2AD4: min(2) max(2) min_increment(2)  — 单位 0.01 km/h
2AD5: min(2) max(2) min_increment(2)  — 单位 0.1%
```

**在发指令前读一下**，避免超出范围被拒（`0x03` Invalid Parameter）。

---

## 六、调试建议

1. **先读 `0x2ACC`（Feature）** —— 确认设备支持哪些指令
2. **读 `0x2AD4`/`0x2AD5`** —— 确认速度/坡度范围
3. **发 `00` 看响应** —— 如果返回 `05`，说明需要解锁
4. **逐步验证**：先 `00`，再 `07`，再小速度测试

---

## 七、参考

- [Bluetooth SIG - Fitness Machine Service 1.0](https://www.bluetooth.com/specifications/specs/fitness-machine-service-1-0/)
- [GATT Specification Supplement](https://www.bluetooth.com/specifications/gss/)
- 开源实现：
  - [python-pyftms](https://github.com/dudanov/python-pyftms) — Python FTMS 客户端库
  - [ESPHome-Treadmill-FTMS](https://github.com/samsonovss/ESPHome-Treadmill-FTMS) — ESP32 FTMS 控制器
  - [hass-walkingpad](https://github.com/mcdax/hass-walkingpad) — Home Assistant 集成
