#pragma once

// 跑步机实时数据解析 —— 订阅 FTMS 的 Treadmill Data (0x2ACD)
//
// 为什么需要这个：
//   ESPHome 2026.x 里 ble_client 的 characteristic 传感器只把数据当 float 给出，
//   拿不到原始字节数组，无法解析自定义帧。这里继承 BLEClientNode，
//   直接挂 GATTC 回调读取 notify 的原始字节。
//
// 帧格式（实测 YPOO M5，其他机型需重新核对）:
//   9c25 <speed:2 LE> <incline:2 LE> 0000 00ff7f ...
//        offset 0-1: 帧头 9c25
//        offset 2-3: 速度 ×100 小端
//        offset 4-5: 坡度 ×10 小端

#include "esphome.h"
#include "esphome/components/ble_client/ble_client.h"
#include "esphome/components/esp32_ble_tracker/esp32_ble_tracker.h"

namespace esphome {
namespace treadmill {

static const char *const TAG_TM = "treadmill";

static const uint16_t FTMS_SVC_UUID16 = 0x1826;
static const uint16_t TREADMILL_DATA_CHAR_UUID16 = 0x2ACD;

class TmDataHandler : public Component, public ble_client::BLEClientNode {
 public:
  void set_client(ble_client::BLEClient *c) { this->client_ = c; }

  float get_speed() const { return this->speed_kmh_; }
  float get_incline() const { return this->incline_pct_; }
  bool connected() const { return this->connected_; }

  void setup() override {
    ESP_LOGI(TAG_TM, "TmDataHandler setup 完成（已在 __init__ 中注册到 ble_client）");
  }

  void dump_config() override {
    ESP_LOGCONFIG(TAG_TM, "跑步机数据解析器: 等待 0x2ACD 通知");
  }

  void gattc_event_handler(esp_gattc_cb_event_t event, esp_gatt_if_t gattc_if,
                           esp_ble_gattc_cb_param_t *param) override {
    switch (event) {
      case ESP_GATTC_OPEN_EVT:
        this->connected_ = (param->open.status == ESP_GATT_OK);
        break;

      case ESP_GATTC_DISCONNECT_EVT:
        this->connected_ = false;
        break;

      case ESP_GATTC_REG_FOR_NOTIFY_EVT:
        if (param->reg_for_notify.status == ESP_GATT_OK) {
          ESP_LOGI(TAG_TM, "notify 注册成功 handle=0x%04X", param->reg_for_notify.handle);
          this->node_state = esphome::esp32_ble_tracker::ClientState::ESTABLISHED;
        } else {
          ESP_LOGW(TAG_TM, "notify 注册失败: %d", param->reg_for_notify.status);
        }
        break;

      case ESP_GATTC_SEARCH_CMPL_EVT: {
        // 服务发现完成后，找到 0x2ACD 并逐个订阅
        auto *id = this->parent()->get_characteristic(FTMS_SVC_UUID16, TREADMILL_DATA_CHAR_UUID16);
        if (id == nullptr) {
          ESP_LOGW(TAG_TM, "没找到 0x2ACD 特征值");
          break;
        }
        this->data_handle_ = id->handle;
        esp_err_t status = this->parent()->register_for_notify(id->handle);
        if (status != ESP_OK) {
          ESP_LOGW(TAG_TM, "订阅 0x2ACD 失败: %s", esp_err_to_name(status));
        } else {
          ESP_LOGI(TAG_TM, "已订阅 0x2ACD (handle=0x%04X)", id->handle);
        }
        break;
      }

      case ESP_GATTC_NOTIFY_EVT: {
        if (this->data_handle_ != 0 && param->notify.handle != this->data_handle_) {
          break;
        }
        // 打印原始字节（前 24 个）
        char buf[128] = {0};
        int n = param->notify.value_len < 24 ? param->notify.value_len : 24;
        for (int i = 0; i < n; i++) {
          snprintf(buf + i * 3, 4, "%02x ", param->notify.value[i]);
        }
        ESP_LOGI(TAG_TM, "NOTIFY len=%d handle=0x%04X data=[%s]",
                 param->notify.value_len, param->notify.handle, buf);
        this->parse(param->notify.value, param->notify.value_len);
        break;
      }

      default:
        break;
    }
  }

 protected:
  void parse(const uint8_t *d, uint16_t len) {
    if (len < 6) return;
    // 帧头校验：9c25
    if (!(d[0] == 0x9c && d[1] == 0x25)) return;

    // 帧偏移（2026-10-24 逐帧实测确认，298 帧验证）
    //   [0:2]  9c25               帧头
    //   [2:4]  速度 ×100    小端   0x01c2 = 450  → 4.50 km/h
    //   [4:6]  累计距离 ×10 小端   2 km/h 跑 18 秒 +10 → 米
    //   [6:8]  坡度 ×10     大端   0x0028 = 40 → 4.0%, 0x003c = 60 → 6.0%, 0x0050 = 80 → 8.0%
    //   [8:11] 00 ff 7f           固定
    //   [11:]  递增计数（跑动时）
    //
    // ⚠️ 注意：[6:8] 是大端，[2:4]/[4:6] 是小端，混用！
    uint16_t raw_speed   = static_cast<uint16_t>(d[2] | (d[3] << 8));
    uint16_t raw_dist    = static_cast<uint16_t>(d[4] | (d[5] << 8));
    uint16_t raw_incline = static_cast<uint16_t>((d[6] << 8) | d[7]);   // 大端

    float spd = raw_speed / 100.0f;
    float dist_m = raw_dist / 10.0f;
    float inc = raw_incline / 10.0f;

    // 首帧必须发布（否则 0 -> 0 的差值判断会永远跳过）
    if (!this->got_first_frame_) {
      this->got_first_frame_ = true;
      this->speed_kmh_ = spd;
      this->incline_pct_ = inc;
      if (this->speed_sensor_ != nullptr) this->speed_sensor_->publish_state(spd);
      if (this->incline_sensor_ != nullptr) this->incline_sensor_->publish_state(inc);
      if (this->dist_sensor_ != nullptr) this->dist_sensor_->publish_state(dist_m);
      ESP_LOGI(TAG_TM, "首帧: 速度 %.2f km/h, 坡度 %.1f%%, 距离 %.1f 米", spd, inc, dist_m);
      return;
    }

    if (fabsf(spd - this->speed_kmh_) > 0.01f) {
      ESP_LOGD(TAG_TM, "速度 %.2f -> %.2f", this->speed_kmh_, spd);
      this->speed_kmh_ = spd;
      if (this->speed_sensor_ != nullptr) this->speed_sensor_->publish_state(spd);
    }
    // 累计距离
    if (fabsf(dist_m - this->dist_m_) > 0.5f) {
      this->dist_m_ = dist_m;
      if (this->dist_sensor_ != nullptr) this->dist_sensor_->publish_state(dist_m);
    }
  }

  ble_client::BLEClient *client_{nullptr};
  uint16_t data_handle_{0};
  bool connected_{false};
  bool got_first_frame_{false};
  float dist_m_{0.0f};
  float speed_kmh_{0.0f};
  float incline_pct_{0.0f};

 public:
  void set_speed_sensor(sensor::Sensor *s) { this->speed_sensor_ = s; }
  void set_incline_sensor(sensor::Sensor *s) { this->incline_sensor_ = s; }
  void set_dist_sensor(sensor::Sensor *s) { this->dist_sensor_ = s; }

 protected:
  sensor::Sensor *speed_sensor_{nullptr};
  sensor::Sensor *incline_sensor_{nullptr};
  sensor::Sensor *dist_sensor_{nullptr};
};

}  // namespace treadmill
}  // namespace esphome
