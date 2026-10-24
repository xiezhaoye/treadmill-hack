#pragma once
#include <string>
#include <vector>
#include <cstdint>

// 十六进制字符串 -> 字节数组
// ESPHome 2026.x 移除了 esphome::ble_client::hex_to_bytes，这里自己实现
inline std::vector<uint8_t> tm_hex_to_bytes(const std::string &hex) {
  std::vector<uint8_t> out;
  out.reserve(hex.size() / 2);
  auto nib = [](char c) -> int {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
  };
  for (size_t i = 0; i + 1 < hex.size(); i += 2) {
    int hi = nib(hex[i]), lo = nib(hex[i + 1]);
    if (hi < 0 || lo < 0) break;
    out.push_back(static_cast<uint8_t>((hi << 4) | lo));
  }
  return out;
}
