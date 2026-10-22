package com.treadmill.relay;

import android.app.Activity;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattDescriptor;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothManager;
import android.bluetooth.le.BluetoothLeScanner;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanFilter;
import android.bluetooth.le.ScanResult;
import android.bluetooth.le.ScanSettings;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import java.io.File;
import java.io.FileWriter;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

/**
 * BLE Relay —— 常驻模式
 *
 * 第一次启动：连接设备并「保持连接」，然后常驻后台。
 * 之后通过广播发送指令，无需重连。
 *
 * 启动（连接并常驻）：
 *   adb shell am start -n com.treadmill.relay/.Main \
 *       -e target AA:BB:CC:DD:EE:FF
 *
 * 发指令（App 已在运行时）：
 *   adb shell am broadcast -a com.treadmill.relay.SEND -e cmd "a301144405"
 *
 * 停止并断开：
 *   adb shell am broadcast -a com.treadmill.relay.STOP
 *
 * 日志：logcat TAG=BLERelay，同时写 /sdcard/ble.log
 */
public class Main extends Activity {
    static final String TAG = "BLERelay";
    static final String ACT_SEND = "com.treadmill.relay.SEND";
    static final String ACT_STOP = "com.treadmill.relay.STOP";
    static final File LOG = new File("/sdcard/ble.log");

    static final UUID SVC    = UUID.fromString("0000fff0-0000-1000-8000-00805f9b34fb");
    static final UUID NOTIFY = UUID.fromString("0000fff1-0000-1000-8000-00805f9b34fb");
    static final UUID WRITE  = UUID.fromString("0000fff2-0000-1000-8000-00805f9b34fb");

    // ★ 标准 FTMS（实测 App 真正用的通道）
    static final UUID FTMS_SVC  = UUID.fromString("00001826-0000-1000-8000-00805f9b34fb");
    static final UUID FTMS_CTRL = UUID.fromString("00002ad9-0000-1000-8000-00805f9b34fb"); // Control Point
    static final UUID FTMS_DATA = UUID.fromString("00002acd-0000-1000-8000-00805f9b34fb"); // Treadmill Data
    static final UUID FTMS_STAT = UUID.fromString("00002ada-0000-1000-8000-00805f9b34fb"); // Status
    // ★★★ 解锁码写入通道（HCI 抓包确认，handle 0x03d）
    static final UUID UNLOCK = UUID.fromString("d18d2c10-c44c-11e8-a355-529269fb1459");
    static final String UNLOCK_CODE = "0123456789ABCDEF";
    static final UUID CCCD   = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");

    // 常驻的静态引用（Activity 退出后仍可通过广播访问）
    static Main INSTANCE;

    BluetoothAdapter adapter;
    BluetoothLeScanner scanner;
    BluetoothGatt gatt;
    static BluetoothGattCharacteristic wc;
    static BluetoothGattCharacteristic ftmsCtrl;
    static BluetoothGattCharacteristic unlockCh;
    static java.util.List<BluetoothGattCharacteristic> subList = new java.util.ArrayList<>();
    static int subIdx = 0;
    static Handler ui = new Handler(Looper.getMainLooper());

    String wantTarget = "YPOO-M5-008264";
    int retry = 0;
    BluetoothDevice lastDev;
    String lastAddr;
    boolean connected = false;
    boolean quitting = false;

    BroadcastReceiver rx;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        INSTANCE = this;

        Intent it = getIntent();
        if (it != null) {
            String t = it.getStringExtra("target");
            if (t != null && !t.trim().isEmpty()) wantTarget = t.trim();
        }

        log("=== BLE Relay 启动（常驻模式）===");
        log("目标: " + wantTarget);

        if (!hasPerms()) {
            log("!! 缺少蓝牙/定位权限");
            finishSoon(1200);
            return;
        }

        BluetoothManager bm = (BluetoothManager) getSystemService(Context.BLUETOOTH_SERVICE);
        adapter = bm == null ? null : bm.getAdapter();
        if (adapter == null || !adapter.isEnabled()) {
            log("!! 蓝牙未开启");
            finishSoon(1200);
            return;
        }

        registerReceiver();
        startScan();

        // 界面不显示，但进程保留
        moveTaskToBack(true);
    }

    void registerReceiver() {
        rx = new BroadcastReceiver() {
            @Override public void onReceive(Context c, Intent i) {
                String a = i.getAction();
                if (ACT_SEND.equals(a)) {
                    String cmd = i.getStringExtra("cmd");
                    if (cmd != null) sendHex(cmd);
                } else if (ACT_STOP.equals(a)) {
                    log("收到停止命令，断开连接");
                    quitting = true;
                    closeAll(500);
                }
            }
        };
        IntentFilter f = new IntentFilter();
        f.addAction(ACT_SEND);
        f.addAction(ACT_STOP);
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(rx, f, Context.RECEIVER_EXPORTED);
        } else {
            registerReceiver(rx, f);
        }
    }

    boolean hasPerms() {
        if (Build.VERSION.SDK_INT >= 31) {
            return checkSelfPermission("android.permission.BLUETOOTH_SCAN") == PackageManager.PERMISSION_GRANTED
                && checkSelfPermission("android.permission.BLUETOOTH_CONNECT") == PackageManager.PERMISSION_GRANTED;
        }
        boolean loc = checkSelfPermission(android.Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
                || checkSelfPermission(android.Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED;
        log("权限检查 sdk=" + Build.VERSION.SDK_INT + " loc=" + loc);
        return loc;
    }

    // ---------------------------------------------------------------- 扫描

    void startScan() {
        scanner = adapter.getBluetoothLeScanner();
        if (scanner == null) { log("!! 无 scanner"); finishSoon(1000); return; }

        log("开始扫描…");
        ScanSettings st = new ScanSettings.Builder()
                .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build();

        List<ScanFilter> filters = null;
        if (wantTarget.matches("([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")) {
            filters = new ArrayList<>();
            filters.add(new ScanFilter.Builder()
                    .setDeviceAddress(wantTarget.toUpperCase(Locale.US)).build());
        }
        scanner.startScan(filters, st, scanCb);

        ui.postDelayed(() -> {
            if (gatt == null && !quitting) {
                stopScan();
                log(wantTarget.equalsIgnoreCase("__ALL__") ? "=== 列举结束 ===" : "!! 扫描超时");
                if (!wantTarget.equalsIgnoreCase("__ALL__")) finishSoon(600);
            }
        }, 25000);
    }

    void stopScan() {
        try { if (scanner != null) scanner.stopScan(scanCb); } catch (Exception ignored) {}
    }

    final ScanCallback scanCb = new ScanCallback() {
        @Override public void onScanResult(int type, ScanResult r) {
            BluetoothDevice d = r.getDevice();
            String name = null;
            try { name = d.getName(); } catch (Exception ignored) {}
            String addr = d.getAddress();

            boolean hit;
            if (wantTarget.matches("([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")) {
                hit = addr.equalsIgnoreCase(wantTarget);
            } else {
                hit = name != null && name.contains(wantTarget);
            }
            if (hit) {
                log("★ 找到: " + name + "  " + addr + "  rssi=" + r.getRssi());
                stopScan();
                connect(d, addr);
            } else if (wantTarget.equalsIgnoreCase("__ALL__")) {
                log("  [扫描] " + addr + "  name=" + name + "  rssi=" + r.getRssi());
            }
        }
        @Override public void onScanFailed(int e) { log("!! 扫描失败 " + e); finishSoon(600); }
    };

    // ---------------------------------------------------------------- 连接

    void connect(BluetoothDevice dev, String addr) {
        lastDev = dev; lastAddr = addr;
        retry++;
        log("连接中… (第 " + retry + " 次)");
        try { if (gatt != null) { gatt.close(); gatt = null; } } catch (Exception ignored) {}
        if (Build.VERSION.SDK_INT >= 23) {
            gatt = dev.connectGatt(this, false, gattCb, BluetoothDevice.TRANSPORT_LE);
        } else {
            gatt = dev.connectGatt(this, false, gattCb);
        }
    }

    void retryConnect() {
        if (quitting) return;
        if (retry >= 5) { log("!! 重试 5 次仍失败"); return; }
        ui.postDelayed(() -> { if (lastDev != null && !quitting) connect(lastDev, lastAddr); }, 2000);
    }

    final BluetoothGattCallback gattCb = new BluetoothGattCallback() {
        @Override public void onConnectionStateChange(BluetoothGatt g, int status, int newState) {
            log("连接状态: status=" + status + " state=" + newState
                    + (newState == 2 ? " (CONNECTED)" : newState == 0 ? " (DISCONNECTED)" : ""));
            if (newState == 2) {
                connected = true;
                retry = 0;
                g.discoverServices();
            } else if (newState == 0) {
                connected = false;
                wc = null;
                if (!quitting) {
                    log("连接断开，准备重连");
                    retryConnect();
                }
            }
        }

        @Override public void onServicesDiscovered(BluetoothGatt g, int status) {
            log("服务发现: status=" + status);
            if (status != 0) { log("!! 服务发现失败"); closeAll(500); return; }

            // 打印全部服务与特征值
            for (BluetoothGattService sv0 : g.getServices()) {
                log("服务 " + sv0.getUuid());
                for (BluetoothGattCharacteristic c0 : sv0.getCharacteristics()) {
                    log("   └ " + c0.getUuid() + " props=0x" + Integer.toHexString(c0.getProperties()));
                }
            }

            // 先抓 FTMS 控制点（App 真正用的）
            BluetoothGattService fs = g.getService(FTMS_SVC);
            if (fs != null) {
                ftmsCtrl = fs.getCharacteristic(FTMS_CTRL);
                log("FTMS 控制点 2ad9: " + (ftmsCtrl != null ? "找到 ✓" : "未找到"));
            } else {
                log("!! 没有 FTMS 服务");
            }

            BluetoothGattService s = g.getService(SVC);
            if (s != null) {
                wc = s.getCharacteristic(WRITE);
            }

            // 找解锁通道（遍历所有服务的所有特征值，手写比对）
            for (BluetoothGattService svc : g.getServices()) {
                for (BluetoothGattCharacteristic ch : svc.getCharacteristics()) {
                    if (ch.getUuid().toString().equalsIgnoreCase(UNLOCK.toString())) {
                        unlockCh = ch;
                        break;
                    }
                }
                if (unlockCh != null) break;
            }
            log("解锁通道 5914fb69-...: " + (unlockCh != null ? "找到 ✓" : "未找到 ✗"));

            if (wc == null && ftmsCtrl == null) { log("!! 无任何可写特征"); closeAll(500); return; }

            // ★ 先写解锁码（App 的第一步）
            if (unlockCh != null) {
                byte[] uc = hexToBytes(UNLOCK_CODE);
                boolean ok;
                int wt = BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE;
                if (Build.VERSION.SDK_INT >= 33) {
                    ok = g.writeCharacteristic(unlockCh, uc, wt) == 0;
                } else {
                    unlockCh.setWriteType(wt);
                    unlockCh.setValue(uc);
                    ok = g.writeCharacteristic(unlockCh);
                }
                log("★ 写解锁码 " + UNLOCK_CODE + "  ok=" + ok);
                // 解锁后等 2 秒再订阅（跑步机会重置 GATT 会话）
                ui.postDelayed(() -> {
                    log("解锁完成，开始订阅");
                    subList.clear();
                    for (BluetoothGattService sv : g.getServices()) {
                        for (BluetoothGattCharacteristic ch2 : sv.getCharacteristics()) {
                            int p2 = ch2.getProperties();
                            if ((p2 & 0x10) != 0 || (p2 & 0x20) != 0) subList.add(ch2);
                        }
                    }
                    subIdx = 0;
                    log("待订阅 " + subList.size() + " 个");
                    subscribeNext(g);
                }, 2000);
                return;   // 不继续走下面的订阅
            }

            // ★ 顺序订阅：Android 的 GATT 队列一次只能处理一个 descriptor 写入
            subList.clear();
            for (BluetoothGattService svc2 : g.getServices()) {
                for (BluetoothGattCharacteristic ch : svc2.getCharacteristics()) {
                    int pr = ch.getProperties();
                    if ((pr & 0x10) != 0 || (pr & 0x20) != 0) subList.add(ch);
                }
            }
            log("待订阅 " + subList.size() + " 个特征值，逐个处理");
            subIdx = 0;
            subscribeNext(g);
            log("★★★ 已就绪，保持连接中。用 broadcast 发指令：");
            log("    adb shell am broadcast -a " + ACT_SEND + " -e cmd \"a301144405\"");
        }

        @Override public void onDescriptorWrite(BluetoothGatt g, BluetoothGattDescriptor d, int st) {
            log("  CCCD[" + subIdx + "] status=" + st);
            subIdx++;
            ui.postDelayed(() -> subscribeNext(g), 150);
        }

        @Override public void onCharacteristicWrite(BluetoothGatt g, BluetoothGattCharacteristic c, int st) {
            log("写入完成 status=" + st);
        }

        @Override public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic c) {
            log("★ 通知: " + bytesToHex(c.getValue()));
        }

        @Override public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic c, byte[] v) {
            log("★ 通知: " + bytesToHex(v));
        }
    };

    // ---------------------------------------------------------------- 发送


    static void subscribeNext(BluetoothGatt g) {
        if (INSTANCE == null) return;
        if (subIdx >= subList.size()) {
            INSTANCE.log("★★★ 全部订阅完成，保持连接中");
            return;
        }
        BluetoothGattCharacteristic ch = subList.get(subIdx);
        int pr = ch.getProperties();
        boolean canNotify = (pr & 0x10) != 0;
        g.setCharacteristicNotification(ch, true);
        BluetoothGattDescriptor dd = ch.getDescriptor(CCCD);
        if (dd != null) {
            byte[] val = canNotify
                    ? BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                    : BluetoothGattDescriptor.ENABLE_INDICATION_VALUE;
            if (Build.VERSION.SDK_INT >= 33) {
                g.writeDescriptor(dd, val);
            } else {
                dd.setValue(val);
                g.writeDescriptor(dd);
            }
            INSTANCE.log("订阅[" + subIdx + "] " + ch.getUuid()
                    + (canNotify ? " [NOTIFY]" : " [INDICATE]"));
        } else {
            subIdx++;
            ui.postDelayed(() -> subscribeNext(g), 100);
        }
    }

    void sendHex(String hexIn) {
        String s = hexIn.replaceAll("\\s+", "").replace("0x", "");
        if (s.length() % 2 != 0 || s.isEmpty()) { log("!! 指令格式错误: " + hexIn); return; }
        if (!connected || gatt == null) { log("!! 未连接，无法发送"); return; }

        // ★ 优先 FTMS 控制点（App 实际用的通道），回退到私有 fff2
        BluetoothGattCharacteristic target = (ftmsCtrl != null) ? ftmsCtrl : wc;
        if (target == null) { log("!! 无可用写入特征"); return; }

        byte[] cmd = hexToBytes(s);
        boolean ok;
        int wt = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT;   // FTMS 必须带响应
        if (Build.VERSION.SDK_INT >= 33) {
            ok = gatt.writeCharacteristic(target, cmd, wt) == 0;
        } else {
            target.setWriteType(wt);
            target.setValue(cmd);
            ok = gatt.writeCharacteristic(target);
        }
        log("发送[" + target.getUuid().toString().substring(4, 8) + "] " + s + "  ok=" + ok);
    }

    // ---------------------------------------------------------------- 工具

    void closeAll(long delay) {
        try { if (gatt != null) { gatt.disconnect(); gatt.close(); } } catch (Exception ignored) {}
        gatt = null; wc = null; connected = false;
        log("=== 已断开 ===");
        finishSoon(delay);
    }

    void finishSoon(long d) {
        ui.postDelayed(() -> { try { finish(); } catch (Exception ignored) {} }, d);
    }

    @Override protected void onDestroy() {
        stopScan();
        try { if (rx != null) unregisterReceiver(rx); } catch (Exception ignored) {}
        // 注意：不在这里断开 GATT，让连接随进程存活
        if (quitting) {
            try { if (gatt != null) { gatt.disconnect(); gatt.close(); } } catch (Exception ignored) {}
        }
        if (INSTANCE == this) INSTANCE = null;
        super.onDestroy();
    }

    static byte[] hexToBytes(String s) {
        int n = s.length() / 2;
        byte[] o = new byte[n];
        for (int i = 0; i < n; i++) o[i] = (byte) Integer.parseInt(s.substring(i*2, i*2+2), 16);
        return o;
    }

    static String bytesToHex(byte[] b) {
        if (b == null) return "(null)";
        StringBuilder sb = new StringBuilder();
        for (byte x : b) sb.append(String.format("%02x", x & 0xff));
        return sb.toString();
    }

    void log(String s) {
        String line = new java.text.SimpleDateFormat("HH:mm:ss.SSS", Locale.US).format(new Date()) + " " + s;
        Log.i(TAG, s);
        try (FileWriter w = new FileWriter(LOG, true)) { w.write(line + "\n"); } catch (Exception ignored) {}
    }
}
