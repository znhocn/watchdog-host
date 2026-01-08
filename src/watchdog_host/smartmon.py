#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import json
import argparse
import yaml
import subprocess
from datetime import datetime, timezone
from watchdog_host.notifier import WatchdogNotifier

def print_log(message: str):
    """输出统一的日志信息，带 UTC 时间戳"""
    utc_now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"{utc_now} [Watchdog-Disk] {message}")

def load_config(path):
    """加载 YAML 配置文件"""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def get_smart_data_json(device):
    """通过 smartctl 获取 JSON 格式的数据"""
    try:
        # -a: 获取全部信息, -j: JSON 格式
        cmd = ["smartctl", "-a", "-j", f"/dev/{device}"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        
        # smartctl 在权限不足时通常会返回错误码 2 或 4
        if result.returncode != 0 and not result.stdout.strip():
            print_log(f"Permission denied or error accessing /dev/{device}. Return code: {result.returncode}")
            return None
            
        return json.loads(result.stdout)
    except Exception as e:
        print_log(f"Error executing smartctl for /dev/{device}: {e}")
        return None

def process_nvme(data, cfg):
    """解析 NVMe 协议特定的健康指标"""
    issues = []
    log = data.get('nvme_smart_health_information_log', {})
    
    # 介质错误
    media_err = log.get('media_errors', 0)
    if media_err > cfg.get('alarm_media_errors', 0):
        issues.append(f"Media Errors: {media_err} (Limit: {cfg.get('alarm_media_errors')})")
    
    # 寿命百分比
    perc_used = log.get('percentage_used', 0)
    if perc_used > cfg.get('alarm_percentage_used', 90):
        issues.append(f"Percentage Used: {perc_used}% (Limit: {cfg.get('alarm_percentage_used')}%)")
        
    temp = log.get('temperature', 0)
    poh = log.get('power_on_hours', 0)
    return issues, temp, poh

def process_hdd(data, cfg):
    """解析 HDD (ATA/SATA) 协议特定的健康指标"""
    issues = []
    # 获取 ATA 属性表并建立 ID 映射
    table = data.get('ata_smart_attributes', {}).get('table', [])
    attrs = {a['id']: a['raw']['value'] for a in table if 'id' in a}
    
    # ID 5: 重映射扇区, ID 197: 待处理扇区, ID 198: 不可纠正扇区
    reallocated = attrs.get(5, 0)
    if reallocated > cfg.get('alarm_reallocated_sectors', 0):
        issues.append(f"Reallocated Sectors: {reallocated}")
        
    pending = attrs.get(197, 0)
    if pending > cfg.get('alarm_pending_sectors', 0):
        issues.append(f"Pending Sectors: {pending}")
        
    uncorrectable = attrs.get(198, 0)
    if uncorrectable > cfg.get('alarm_uncorrectable_sectors', 0):
        issues.append(f"Uncorrectable Sectors: {uncorrectable}")

    # 温度通常在 current 字段或属性 ID 194
    temp = data.get('temperature', {}).get('current', attrs.get(194, 0))
    poh = attrs.get(9, 0)  # ID 9: 通电时长
    return issues, temp, poh

def main():
    parser = argparse.ArgumentParser(description="Reliable Disk SMART Monitor")
    parser.add_argument("-c", "--config", required=True, help="Path to config.yaml")
    args = parser.parse_args()

    # 加载配置和初始化通知器
    config = load_config(args.config)
    hostname = config.get("hostname", "unknown-host")
    notifier = WatchdogNotifier(args.config)
    smart_cfg = config.get("disk-smart", {})
    
    print_log(f"Disk watchdog started. Monitoring: {', '.join(smart_cfg.get('interfaces', []))}")

    while True:
        all_device_reports = [] 

        for dev_name in smart_cfg.get("interfaces", []):
            data = get_smart_data_json(dev_name)
            
            # --- 读取失败处理 ---
            if not data:
                all_device_reports.append(f"[!] Device: /dev/{dev_name}\nStatus: FAILED to fetch SMART data")
                continue

            model = data.get('model_name', 'Unknown')
            sn = data.get('serial_number', 'Unknown')
            protocol = data.get('device', {}).get('protocol', '').upper()
            
            # --- 协议分支处理 ---
            if protocol == "NVME":
                issues, temp, poh = process_nvme(data, smart_cfg)
            else:
                issues, temp, poh = process_hdd(data, smart_cfg)

            # --- 公共指标检查 ---
            # 1. SMART 健康自检结果
            assessment = data.get('smart_status', {}).get('passed')
            if assessment is False or (assessment is None and smart_cfg.get('alarm_assessment') == "PASSED"):
                issues.insert(0, "SMART Health Assessment: FAILED")
            
            # 2. 温度检查
            if temp > smart_cfg.get('alarm_temperature', 70):
                issues.append(f"Temperature high: {temp}C (Limit: {smart_cfg['alarm_temperature']}C)")
            
            # 3. 通电时长检查
            if poh > smart_cfg.get('alarm_power_on_hours', 43800):
                issues.append(f"Power-on hours: {poh} hrs")

            # --- 汇总设备故障 (纯文本格式) ---
            if issues:
                report = (f"ALERT Device: /dev/{dev_name} ({protocol})\n"
                          f"Model: {model}\n"
                          f"S/N: {sn}\n"
                          f"Issues:\n" + "\n".join([f"  - {i}" for i in issues]))
                all_device_reports.append(report)
            else:
                print_log(f"Device /dev/{dev_name} is healthy.")

        # --- 发送纯文本聚合告警 ---
        if all_device_reports:
            current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            # 使用简单的分隔符连接多个设备报告
            final_text_msg = (
                f"【Watchdog Host Disk Health Alert】\n"
                f"Host: {hostname}\n"
                f"Time: {current_time}\n"
                f"------------------------------------\n\n"
                + "\n\n------------------------------------\n\n".join(all_device_reports)
            )
            print_log(f"Detected issues. Sending aggregated text report.")
            notifier.send_alert(final_text_msg)

        time.sleep(smart_cfg.get("check_interval", 86400))

if __name__ == "__main__":
    main()
