#!/usr/bin/env bash
# 一键从手机拉取 btsnoop 日志（自动查找路径）
#
# 用法: ./pull-btsnoop.sh [输出文件名]
set -uo pipefail

OUT="${1:-btsnoop.log}"
ADB="${ADB:-adb}"

if ! command -v "$ADB" >/dev/null 2>&1; then
  echo "❌ 找不到 adb。macOS: brew install android-platform-tools" >&2
  exit 1
fi

echo "==> 检查设备"
DEV=$("$ADB" devices | awk 'NR>1 && $2=="device" {print $1; exit}')
if [ -z "$DEV" ]; then
  echo "❌ 没有已授权的设备。" >&2
  echo "   1. USB 连接手机" >&2
  echo "   2. 开启「USB 调试」" >&2
  echo "   3. 手机上点「允许」" >&2
  exit 1
fi
echo "    设备: $DEV"

echo "==> 搜索 btsnoop 文件"
FOUND=$("$ADB" -s "$DEV" shell \
  "find /sdcard /storage/emulated/0 /data/misc/bluetooth -name '*btsnoop*' 2>/dev/null" \
  | tr -d '\r' | head -5)

if [ -z "$FOUND" ]; then
  echo "❌ 没找到 btsnoop 文件。检查：" >&2
  echo "   1. 开发者选项里「启用蓝牙 HCI 信息收集日志」是否打开" >&2
  echo "   2. 打开后是否重启过蓝牙（关掉再开）" >&2
  echo "   3. 是否已经连过设备（需要有蓝牙活动）" >&2
  exit 1
fi

echo "    找到:"
echo "$FOUND" | sed 's/^/      /'

# 取第一个（通常是 MIUI 路径或标准路径）
SRC=$(echo "$FOUND" | head -1)
echo "==> 拉取 $SRC"
"$ADB" -s "$DEV" pull "$SRC" "$OUT" || exit 1

SIZE=$(wc -c < "$OUT" | tr -d ' ')
echo "==> 完成: $OUT ($SIZE 字节)"

if [ "$SIZE" -lt 100 ]; then
  echo "⚠️  文件太小，可能没有有效数据。" >&2
  exit 1
fi

echo ""
echo "下一步："
echo "  ./parse-btsnoop.py $OUT"
