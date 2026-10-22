#!/usr/bin/env python3
"""
btsnoop 解析器 —— 专为 BLE GATT 分析设计

用法:
    ./parse-btsnoop.py btsnoop.log              # 完整解析
    ./parse-btsnoop.py btsnoop.log --writes     # 只看写入指令
    ./parse-btsnoop.py btsnoop.log --notifies   # 只看通知数据
    ./parse-btsnoop.py btsnoop.log --tree       # 只看服务/特征值表

输出:
    - 服务表（Read By Group Response）
    - 特征值表（Read By Type Response）
    - 所有 ATT 写入（含 handle + hex）
    - 所有通知数据
"""
import struct
import sys
import uuid
from collections import Counter

# HCI packet type (btsnoop 第一字节)
HCI_CMD, HCI_ACL, HCI_EVENT = 0x01, 0x02, 0x04

# ATT opcodes
ATT = {
    0x01: 'Error Rsp',
    0x02: 'MTU Req',
    0x03: 'MTU Rsp',
    0x04: 'Find Info Req',
    0x05: 'Find Info Rsp',
    0x08: 'Read By Type Req',
    0x09: 'Read By Type Rsp',
    0x0A: 'Read Req',
    0x0B: 'Read Rsp',
    0x10: 'Read By Group Req',
    0x11: 'Read By Group Rsp',
    0x12: 'Write Req',
    0x13: 'Write Rsp',
    0x1B: 'Notify',
    0x1D: 'Indicate',
    0x1E: 'Handle Value Ntf',
    0x52: 'Write Cmd',
}

# 常见 GATT UUID
NICE_UUID = {
    '1800': 'Generic Access',
    '1801': 'Generic Attribute',
    '180a': 'Device Information',
    '180f': 'Battery',
    '1812': 'HID',
    '1816': 'Cycling Speed and Cadence',
    '181a': 'Environmental Sensing',
    '1826': '★ Fitness Machine Service (FTMS)',
    '2a00': 'Device Name',
    '2a01': 'Appearance',
    '2a04': 'Peripheral Preferred Conn Params',
    '2a05': 'Service Changed',
    '2a29': 'Manufacturer Name',
    '2a24': 'Model Number',
    '2a25': 'Serial Number',
    '2a27': 'Hardware Revision',
    '2a26': 'Firmware Revision',
    '2a28': 'Software Revision',
    '2acd': '★ Treadmill Data',
    '2ad9': '★ Fitness Machine Control Point',
    '2ada': 'Fitness Machine Status',
    '2ad3': 'Training Status',
    '2ad4': 'Supported Speed Range',
    '2ad5': 'Supported Inclination Range',
    '2ad6': 'Supported Resistance Level Range',
    '2acc': 'Fitness Machine Feature',
    '2902': 'Client Characteristic Configuration (CCCD)',
}


def nice(u: str) -> str:
    """给 UUID 加人类可读注记"""
    short = u[:8].lower() if len(u) >= 8 else u.lower()
    key = short[4:] if short.startswith('0000') else short
    name = NICE_UUID.get(key)
    return f'{u}' + (f'  ({name})' if name else '')


def parse_btsnoop(path):
    """返回 [(ts, hci_type, payload_bytes)]"""
    d = open(path, 'rb').read()
    if d[:8] != b'btsnoop\x00':
        sys.exit('❌ 不是 btsnoop 文件（magic 不对）')
    ver, datalink = struct.unpack('>II', d[8:16])
    if datalink not in (1001, 1002, 1003, 1004):
        print(f'⚠️  datalink={datalink}，可能不是蓝牙流量')
    pos, out = 16, []
    while pos + 24 <= len(d):
        olen, ilen, flags, drops, ts, tus = struct.unpack('>IIIIII', d[pos:pos + 24])
        pos += 24
        if pos + ilen > len(d):
            break
        pkt = d[pos:pos + ilen]
        pos += ilen
        out.append((ts + tus / 1e6, pkt[0], pkt[1:]))
    return out


def att_packets(recs):
    """从 ACL 包中提取 ATT 层"""
    for ts, hci, pkt in recs:
        if hci != HCI_ACL or len(pkt) < 4:
            continue
        dlen = struct.unpack('<H', pkt[2:4])[0]
        body = pkt[4:4 + dlen]
        if len(body) < 4:
            continue
        l2len, cid = struct.unpack('<HH', body[0:4])
        if cid != 4:                 # 只要 ATT
            continue
        att = body[4:4 + l2len]
        if att:
            yield ts, att


def build_tree(recs):
    """从 Read By Group/Type Response 提取服务与特征值"""
    services, chars = [], {}
    for ts, a in att_packets(recs):
        op = a[0]
        if op == 0x11:               # Read By Group Response
            p, ln = a[2:], a[1]
            while len(p) >= ln and ln >= 6:
                sh, eh = struct.unpack('<HH', p[0:4])
                services.append((sh, eh, uuid_str(p[4:ln])))
                p = p[ln:]
        elif op == 0x09:             # Read By Type Response
            # 响应格式（当请求 type=0x2803 特征声明时）:
            #   [decl_handle(2)] [props(1)] [value_handle(2)] [uuid(2 或 16)]
            p, ln = a[2:], a[1]
            while len(p) >= ln and ln >= 5:
                v = p[2:ln]           # 去掉 decl_handle
                if len(v) >= 5:
                    props = v[0]
                    vh = struct.unpack('<H', v[1:3])[0]
                    u = uuid_str(v[3:])
                    # 只收录看起来合理的（排除 CCCD 等）
                    if len(v[3:]) in (2, 16):
                        chars[vh] = (props, u)
                p = p[ln:]
    return services, chars


def uuid_str(b: bytes) -> str:
    """128 位 UUID 按 BLE 惯例解析（小端字节序 → 标准字符串）"""
    if len(b) == 2:
        return f'{struct.unpack("<H", b)[0]:04x}'
    if len(b) == 16:
        try:
            return str(uuid.UUID(bytes_le=b))
        except Exception:
            return b.hex()
    return b.hex()


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    path = sys.argv[1]
    flags = set(sys.argv[2:])

    recs = parse_btsnoop(path)
    print(f'=== 共 {len(recs)} 条 HCI 记录')
    print(f'=== 类型分布: {dict(Counter(r[1] for r in recs))}  (1=Cmd 2=ACL 4=Event)\n')

    services, chars = build_tree(recs)
    atts = list(att_packets(recs))

    show_all = not flags

    if show_all or '--tree' in flags:
        print('=' * 70)
        print('★ 服务表')
        print('=' * 70)
        seen = set()
        for sh, eh, u in services:
            if (sh, u) in seen:
                continue
            seen.add((sh, u))
            print(f'  0x{sh:03x} - 0x{eh:03x}   {nice(u)}')

        print('\n' + '=' * 70)
        print('★ 特征值表')
        print('=' * 70)
        seen = set()
        for vh in sorted(chars):
            props, u = chars[vh]
            if (vh, u) in seen:
                continue
            seen.add((vh, u))
            print(f'  value=0x{vh:03x}  props=0x{props:02x}  {nice(u)}')
        print()

    if show_all or '--writes' in flags:
        print('=' * 70)
        print('★ 写入指令（Write Cmd / Write Req）')
        print('=' * 70)
        n = 0
        for ts, a in atts:
            if a[0] not in (0x52, 0x12):
                continue
            hv = struct.unpack('<H', a[1:3])[0]
            val = a[3:]
            nm = ATT.get(a[0], '?')
            uu = nice(chars.get(hv, ('', ''))[1]) if hv in chars else ''
            print(f'  {ts:12.2f}  0x{hv:03x} {nm:10} {val.hex():<40} {uu}')
            n += 1
        print(f'  共 {n} 条\n')

    if show_all or '--notifies' in flags:
        print('=' * 70)
        print('★ 通知数据（Notify / Indicate）')
        print('=' * 70)
        n = 0
        for ts, a in atts:
            if a[0] not in (0x1b, 0x1d):
                continue
            hv = struct.unpack('<H', a[1:3])[0]
            val = a[3:]
            nm = ATT.get(a[0], '?')
            print(f'  {ts:12.2f}  0x{hv:03x} {nm:10} {val.hex()[:70]}')
            n += 1
            if n >= 40:              # 通知太多，只显示前 40 条
                print(f'  ...（共需显示更多，请用 --notifies 单独查看）')
                break
        print(f'  共 {n} 条（已截断显示）\n')

    print('=' * 70)
    print('💡 提示：')
    print('  - 找控制指令：看 --writes 里 handle 对应 2ad9 的条目')
    print('  - 找解锁码：看 --writes 里最前面几条（通常是绑定后的第一条）')
    print('  - 解数据格式：看 --notifies 里 2acd 的帧结构')
    print('=' * 70)


if __name__ == '__main__':
    main()
