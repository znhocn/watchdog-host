#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
可靠的每月流量监控脚本（字节级精度，支持系统重启）

功能：
- 监控指定网卡每月总流量（收 + 发）
- 本月已用流量以字节精确存储（used_bytes）
- 支持告警比例（默认95%）和超限自动关机
- 使用 notifier.py 发送企业微信/钉钉/邮件通知
- 重启后统计连续准确（增量采样 + 持久化）
- 所有日志显示 UTC 时间，前缀为 [Watchdog]
"""

import os
import time
import json
import argparse
import yaml
import psutil
import re
from datetime import datetime, timezone
from watchdog_host.notifier import WatchdogNotifier


def parse_bandwidth(value):
    """解析流量阈值，返回 GB 为单位的 float"""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().lower()
    match = re.match(r"([\d\.]+)\s*(gb|g|tb|t)?", s)
    if not match:
        raise ValueError(f"Cannot parse bandwidth_max: {value}")
    number, unit = match.groups()
    number = float(number)
    if unit in ["t", "tb"]:
        return number * 1024
    return number


def load_config(path):
    """加载 YAML 配置文件"""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_data(data_file):
    """加载持久化数据，支持旧版本兼容"""
    if os.path.exists(data_file):
        try:
            with open(data_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if "used_gb" in loaded and "used_bytes" not in loaded:
                    loaded["used_bytes"] = int(loaded["used_gb"] * (1024 ** 3))
                    del loaded["used_gb"]
                return loaded
        except Exception as e:
            print_log(f"Warning: Data file corrupted or unreadable ({e}), reinitializing")
    
    return {
        "month": datetime.now(timezone.utc).month,
        "used_bytes": 0,
        "last_total_bytes": None,
        "alert_sent": False
    }


def save_data(data_file, data):
    """安全保存数据到 JSON 文件"""
    try:
        os.makedirs(os.path.dirname(data_file), exist_ok=True)
        with open(data_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except Exception as e:
        print_log(f"Error: Cannot save data to {data_file} - {e}")


def get_total_bytes(interfaces):
    """获取当前所有监控网卡的总流量字节数"""
    counters = psutil.net_io_counters(pernic=True)
    total = 0
    for iface in interfaces:
        if iface in counters:
            total += counters[iface].bytes_recv + counters[iface].bytes_sent
    return total


def bytes_to_gb(byte_count):
    """字节转换为 GB（保留2位小数）"""
    return round(byte_count / (1024 ** 3), 2)


def print_log(message: str):
    """
    统一日志输出函数，带 UTC 时间戳
    格式：2025-12-31 23:59:59 UTC [Watchdog] Message
    """
    utc_now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"{utc_now} [Watchdog] {message}")


def main():
    parser = argparse.ArgumentParser(description="Monthly bandwidth monitor with alert and shutdown")
    parser.add_argument("-c", "--config", required=True, help="Path to config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    hostname = config.get("hostname", "unknown-host")
    notifier = WatchdogNotifier(args.config)

    bw_config = config.get("bandwidth", {})
    interfaces = bw_config.get("interfaces", ["eth0"])
    bandwidth_max_gb = parse_bandwidth(bw_config.get("bandwidth_max", 1000))
    bandwidth_max_bytes = int(bandwidth_max_gb * (1024 ** 3))
    data_file_rel = bw_config.get("data_file", "bandwidth_usage.json")
    check_interval = bw_config.get("check_interval", 60)
    alarm_rate = bw_config.get("alarm_rate", 95) / 100.0
    shutdown_enabled = bw_config.get("shutdown", True)

    # data_file 转为绝对路径
    if not os.path.isabs(data_file_rel):
        config_dir = os.path.dirname(os.path.abspath(args.config))
        data_file = os.path.join(config_dir, data_file_rel)
    else:
        data_file = os.path.abspath(data_file_rel)

    # 检查网卡是否存在
    available = psutil.net_io_counters(pernic=True).keys()
    missing = [i for i in interfaces if i not in available]
    if missing:
        print_log(f"Error: Interfaces not found: {', '.join(missing)}")
        return

    data = load_data(data_file)

    # 启动信息：一行显示
    print_log(f"Started | "
              f"Host: {hostname} | "
              f"Interfaces: {', '.join(interfaces)} | "
              f"Threshold: {bandwidth_max_gb:.2f} GB | "
              f"Alert: {alarm_rate * 100:.0f}%")

    while True:
        current_month = datetime.now(timezone.utc).month
        current_total_bytes = get_total_bytes(interfaces)

        # 新月份检测
        if data.get("month") != current_month:
            print_log(f"New month detected ({current_month}), resetting statistics")
            data["month"] = current_month
            data["used_bytes"] = 0
            data["alert_sent"] = False
            data["last_total_bytes"] = current_total_bytes
            save_data(data_file, data)
            time.sleep(check_interval)
            continue

        # 计算增量
        if data["last_total_bytes"] is not None:
            delta_bytes = current_total_bytes - data["last_total_bytes"]
            if delta_bytes > 0:
                data["used_bytes"] += delta_bytes

        data["last_total_bytes"] = current_total_bytes

        used_gb = bytes_to_gb(data["used_bytes"])
        usage_percent = used_gb / bandwidth_max_gb * 100 if bandwidth_max_gb > 0 else 0

        print_log(f"Current usage: {used_gb:.2f} GB / {bandwidth_max_gb:.2f} GB ({usage_percent:.1f}%)")

        # 告警触发
        if data["used_bytes"] >= int(bandwidth_max_gb * alarm_rate * (1024 ** 3)) and not data.get("alert_sent"):
            msg = (
                f"【Watchdog Host Traffic Alert】\n"
                f"Host: {hostname}\n"
                f"Monthly usage: {used_gb:.2f} GB\n"
                f"Percentage: {usage_percent:.1f}%\n"
                f"Threshold: {bandwidth_max_gb:.2f} GB\n"
                f"Warning: Approaching limit!"
            )
            print_log("Alert threshold reached, sending notification")
            notifier.send_alert(msg)
            data["alert_sent"] = True

        # 超限处理
        if data["used_bytes"] >= bandwidth_max_bytes:
            msg = (
                f"【Watchdog Host Traffic Exceeded】\n"
                f"Host: {hostname}\n"
                f"Monthly usage: {used_gb:.2f} GB\n"
                f"Exceeded threshold: {bandwidth_max_gb:.2f} GB\n"
                f"System shutting down now!"
            )
            print_log("Threshold exceeded, sending final alert")

            # 先保存数据，再关机
            save_data(data_file, data)

            notifier.send_alert(msg)

            if shutdown_enabled:
                print_log("Executing shutdown command...")
                os.system("shutdown -h now")
            break

        # 正常循环保存
        save_data(data_file, data)

        time.sleep(check_interval)


if __name__ == "__main__":
    main()
