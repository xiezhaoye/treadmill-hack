#!/usr/bin/env python3
"""
FTMS 指令构造工具

用法:
    ./ftms.py start                 # 启动序列（00 + 07）
    ./ftms.py stop                  # 停止（0801）
    ./ftms.py pause                 # 暂停（0802）
    ./ftms.py speed 5.0             # 设速度 5.0 km/h
    ./ftms.py incline 4             # 设坡度 4%
    ./ftms.py full 5.0 4            # 完整序列：启动 + 速度5 + 坡度4
    ./ftms.py unlock <code>         # 生成解锁指令（十六进制）

输出可以直接喂给 BLE Relay：
    adb shell am broadcast -a com.treadmill.relay.SEND -e cmd "<输出>"
"""
import sys


def speed_cmd(kmh: float) -> str:
    """Set Target Speed: opcode 0x02 + uint16(0.01 km/h) little-endian"""
    v = int(round(kmh * 100))
    if not 0 <= v <= 0xFFFF:
        raise ValueError(f"速度超出范围: {kmh}")
    return f"02{v & 0xFF:02x}{v >> 8:02x}"


def incline_cmd(pct: float) -> str:
    """Set Target Inclination: opcode 0x03 + int16(0.1 %) little-endian"""
    v = int(round(pct * 10))
    if v < 0:
        v += 0x10000          # 负数用补码
    if not 0 <= v <= 0xFFFF:
        raise ValueError(f"坡度超出范围: {pct}")
    return f"03{v & 0xFF:02x}{v >> 8:02x}"


def resistance_cmd(level: int) -> str:
    """Set Target Resistance: opcode 0x04 + uint8"""
    return f"04{level & 0xFF:02x}"


CMDS = {
    'request-control': '00',
    'reset': '01',
    'start': '07',
    'resume': '07',
    'stop': '0801',
    'pause': '0802',
}


def usage():
    print(__doc__)
    sys.exit(1)


def main():
    if len(sys.argv) < 2:
        usage()
    act = sys.argv[1].lower()

    if act in CMDS:
        print(CMDS[act])

    elif act == 'speed':
        if len(sys.argv) < 3:
            usage()
        print(speed_cmd(float(sys.argv[2])))

    elif act == 'incline':
        if len(sys.argv) < 3:
            usage()
        print(incline_cmd(float(sys.argv[2])))

    elif act == 'resistance':
        if len(sys.argv) < 3:
            usage()
        print(resistance_cmd(int(sys.argv[2])))

    elif act == 'full':
        if len(sys.argv) < 4:
            print("用法: ftms.py full <速度> <坡度>", file=sys.stderr)
            sys.exit(1)
        spd, inc = float(sys.argv[2]), float(sys.argv[3])
        # 分行输出，方便逐条发送
        print('00', end=' ')            # Request Control
        print('07', end=' ')            # Start
        print(speed_cmd(spd), end=' ')
        print(incline_cmd(inc))

    elif act == 'unlock':
        if len(sys.argv) < 3:
            print("用法: ftms.py unlock <hex码>", file=sys.stderr)
            print("例:   ftms.py unlock 0123456789ABCDEF", file=sys.stderr)
            sys.exit(1)
        print(sys.argv[2].lower())

    else:
        usage()


if __name__ == '__main__':
    main()
