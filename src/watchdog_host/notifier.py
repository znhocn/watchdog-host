#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import yaml
import time
import requests
import hashlib
import hmac
import base64
import smtplib
from urllib.parse import quote_plus
from email.mime.text import MIMEText
from email.header import Header


class WatchdogNotifier:
    def __init__(self, config_path='config.yaml'):
        """
        初始化通知器
        :param config_path: 配置文件路径，默认为 config.yaml
        """
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

        # 读取 notify 配置段
        self.notify_config = self.config.get('notify', {})

        # 各通道上次发送时间，用于冷却控制
        self.cooldown_tracker = {
            'email': 0,
            'dingtalk': 0,
            'wecom': 0
        }

    def _can_send(self, channel: str) -> bool:
        """
        判断指定通道是否允许发送（是否在冷却期内）
        :param channel: 通道名称（email/dingtalk/wecom）
        :return: True 表示可以发送
        """
        cfg = self.notify_config.get(channel, {})
        if not cfg.get('enabled', False):
            return False

        cooldown = cfg.get('cooldown', 3600)  # 默认 1 小时
        now = time.time()
        last = self.cooldown_tracker.get(channel, 0)
        return now - last >= cooldown

    def _update_cooldown(self, channel: str):
        """更新通道的最后发送时间"""
        self.cooldown_tracker[channel] = time.time()

    def send_email(self, message: str) -> bool:
        """发送邮件通知"""
        cfg = self.notify_config.get('email', {})
        if not cfg.get('enabled', False) or not self._can_send('email'):
            return False

        content = cfg.get('message', '{message}').format(message=message)

        msg = MIMEText(content, 'plain', 'utf-8')
        msg['Subject'] = Header(cfg.get('subject', 'Watchdog Alert'), 'utf-8')
        msg['From'] = cfg['from_addr']
        msg['To'] = ', '.join(cfg['to_addrs'])

        try:
            server = smtplib.SMTP(cfg['smtp_server'], cfg['smtp_port'])
            server.starttls()
            server.login(cfg['username'], cfg['password'])
            server.sendmail(cfg['from_addr'], cfg['to_addrs'], msg.as_string())
            server.quit()
            print("[NOTIFY] Email sent successfully")
            self._update_cooldown('email')
            return True
        except Exception as e:
            print(f"[NOTIFY] Email send failed: {e}")
            return False

    def send_dingtalk(self, message: str) -> bool:
        """发送钉钉群机器人通知（支持密钥加签）"""
        cfg = self.notify_config.get('dingtalk', {})
        if not cfg.get('enabled', False) or not self._can_send('dingtalk'):
            return False

        access_token = cfg['access_token']
        secret = cfg.get('secret')

        url = f"https://oapi.dingtalk.com/robot/send?access_token={access_token}"

        # 如果配置了 secret，则启用加签
        if secret:
            timestamp = str(int(time.time() * 1000))
            string_to_sign = f'{timestamp}\n{secret}'
            hmac_code = hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha256).digest()
            sign = quote_plus(base64.b64encode(hmac_code))
            url += f"&timestamp={timestamp}&sign={sign}"

        content = cfg.get('message', '{message}').format(message=message)

        payload = {
            "msgtype": "text",
            "text": {"content": content}
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            result = resp.json()
            if result.get('errcode') == 0:
                print("[NOTIFY] DingTalk message sent successfully")
                self._update_cooldown('dingtalk')
                return True
            else:
                print(f"[NOTIFY] DingTalk send failed: {result.get('errmsg')}")
                return False
        except Exception as e:
            print(f"[NOTIFY] DingTalk request exception: {e}")
            return False

    def send_wecom(self, message: str) -> bool:
        """发送企业微信群机器人通知（Webhook 方式）"""
        cfg = self.notify_config.get('wecom', {})
        if not cfg.get('enabled', False) or not self._can_send('wecom'):
            return False

        webhook_key = cfg.get('webhook_key')
        if not webhook_key:
            print("[NOTIFY] Enterprise WeChat webhook_key not configured")
            return False

        url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={webhook_key}"

        content = cfg.get('message', '{message}').format(message=message)

        payload = {
            "msgtype": "text",
            "text": {
                "content": content
            }
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            result = resp.json()
            if result.get('errcode') == 0:
                print("[NOTIFY] Enterprise WeChat message sent successfully")
                self._update_cooldown('wecom')
                return True
            else:
                print(f"[NOTIFY] Enterprise WeChat send failed: {result.get('errmsg')}")
                return False
        except Exception as e:
            print(f"[NOTIFY] Enterprise WeChat request exception: {e}")
            return False

    def send_alert(self, message: str):
        """
        统一告警发送入口
        会依次尝试所有启用的通知通道，只要有一个成功即视为发送成功
        """
        results = []

        if self.notify_config.get('email', {}).get('enabled'):
            results.append(self.send_email(message))

        if self.notify_config.get('dingtalk', {}).get('enabled'):
            results.append(self.send_dingtalk(message))

        if self.notify_config.get('wecom', {}).get('enabled'):
            results.append(self.send_wecom(message))

        if any(results):
            print("[NOTIFY] Alert sent successfully (at least one channel succeeded)")
        else:
            print("[NOTIFY] All notification channels failed or disabled")


# # 直接运行此文件时进行测试
# if __name__ == '__main__':
#     notifier = WatchdogNotifier('config.yaml')
#     notifier.send_alert("Test Alert: Notification system working properly?\nTime: 2025-12-31")
