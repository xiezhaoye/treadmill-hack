#!/usr/bin/env python3
"""
分析 2ACD 数据帧，找出哪些字节位在递增

用途：确定「累计时间」「累计距离」等字段的确切偏移。

用法：
    # 1. 从手机抓取帧（跑步机上跑一段，速度/距离都在变）
    adb logcat -d | grep "★ 通知: 9c25" > frames.txt

    # 2. 分析
    ./analyze-frames.py frames.txt

输出：
    - 每字节位的变化情况（恒定 / 递增 / 波动）
    - 推测哪个字段是累计距离、累计时间
"""
import re
import sys
from collections import defaultdict


def load_frames(path):
    """从 logcat 输出里提取 hex 帧"""
    frames = []
    for line in open(path, encoding='utf-8', errors='ignore'):
        # 匹配 "★ 通知: 9c25xxxx"
        m = re.search(r'(9c2[0-9a-f])([0-9a-f]{20,})', line, re.I)
        if m:
            h = (m.group(1) + m.group(2)).lower()
            if len(h) % 2 == 0:
                frames.append(bytes.fromhex(h))
    return frames


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)

    frames = load_frames(sys.argv[1])
    if len(frames) < 10:
        sys.exit(f'❌ 只找到 {len(frames)} 帧，至少需要 10 帧\n'
                 f'   确认跑步机在运行（有数据变化）')

    print(f'=== 共 {len(frames)} 帧')
    lens = {len(f) for f in frames}
    print(f'=== 帧长度: {sorted(lens)}')
    minlen = min(lens)
    frames = [f for f in frames if len(f) == minlen]

    print(f'\n=== 逐字节分析（{minlen} 字节）')
    print(f'{"偏移":>4}  {"样本值":^28}  {"分类":<10} 说明')
    print('-' * 76)

    for i in range(minlen):
        vals = [f[i] for f in frames]
        uniq = sorted(set(vals))
        head = ' '.join(f'{v:02x}' for v in vals[:8])

        if len(uniq) == 1:
            cat, note = '恒定', f'固定值 0x{uniq[0]:02x}'
        else:
            # 判断是否单调递增
            inc = all(b >= a for a, b in zip(vals, vals[1:]))
            dec = all(b <= a for a, b in zip(vals, vals[1:]))
            if inc and len(uniq) > 1:
                step = vals[-1] - vals[0]
                cat, note = '递增★', f'{uniq[0]:02x}→{uniq[-1]:02x} (增 {step})'
            elif dec and len(uniq) > 1:
                cat, note = '递减', f'{uniq[0]:02x}→{uniq[-1]:02x}'
            else:
                cat, note = '波动', f'{len(uniq)} 种取值'
        print(f'{i:>4}  {head:<28}  {cat:<10} {note}')

    # 多字节字段分析（小端 uint16 / uint24 / uint32）
    print(f'\n=== 多字节字段（小端）')
    print(f'{"偏移":>6}  {"宽":>2}  {"首值":>10}  {"末值":>10}  {"变化":>10}  分类')
    print('-' * 76)

    def read_le(f, off, width):
        return int.from_bytes(f[off:off + width], 'little')

    candidates = []
    for width in (2, 3, 4):
        for off in range(0, minlen - width + 1):
            vals = [read_le(f, off, width) for f in frames]
            if len(set(vals)) == 1:
                continue
            inc = all(b >= a for a, b in zip(vals, vals[1:]))
            if inc and vals[-1] - vals[0] > 0:
                candidates.append((off, width, vals[0], vals[-1], '递增★'))

    # 按变化量排序，变化大的更可能是累计值
    candidates.sort(key=lambda x: -(x[3] - x[2]))
    for off, width, v0, v1, cat in candidates[:20]:
        print(f'{off:>6}  {width:>2}  {v0:>10}  {v1:>10}  {v1 - v0:>10}  {cat}')

    if not candidates:
        print('  （没有单调递增的多字节字段——可能跑步机没在跑，或帧太短）')

    # 关键提示
    print(f'\n=== 如何确认「累计距离」')
    print('''  1. 在跑步机上跑一个已知距离（比如屏幕显示 1.00 km）
  2. 找到变化量 ≈ 1000 的字段（单位米）
     或 ≈ 1 的字段（单位 km）
  3. 或跑 60 秒，找变化量 ≈ 60 的字段（单位秒）

  实测 YPOO M5 的帧结构（部分）：
    [0:2]  9c25      帧头
    [2:4]  速度×100   小端
    [4:6]  坡度×10    小端
    [16:19] 递增字段（疑似时间或距离）
    [19:23] 递增字段（疑似步数或卡路里）
''')


if __name__ == '__main__':
    main()
