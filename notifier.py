# -*- coding: utf-8 -*-
"""
================================================================================
邮件通知模块（Gmail SMTP）
================================================================================

提供通用邮件发送接口，供任意脚本在执行完毕后通知执行结果。

渠道配置以字符串形式传入 EMAIL_CONFIG，结构：
    {EMAIL_SENDER}|{EMAIL_PASS}|{EMAIL_TO}
示例：
    sender@gmail.com|passwordxx|to@gmail.com

说明：
    - 使用 Gmail SMTP（smtp.gmail.com:587 + STARTTLS）。
    - EMAIL_PASS 建议使用 Gmail「应用专用密码」，而非账号登录密码。
    - EMAIL_TO 可以为单个地址，也可以用逗号分隔多个地址。

对外接口：
    - parse_email_config(config_str)   解析配置字符串
    - send_email(subject, body, email_config, ...)  通用发送
    - notify_result(...)               按执行结果构建标题/正文并发送（通用）
    - notify_linuxdo_result(...)       针对 linux_do_headless.py 的便捷封装

================================================================================
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate


# Gmail SMTP 固定参数
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


# ============================================================================
# 配置解析
# ============================================================================


def parse_email_config(config_str):
    """解析 EMAIL_CONFIG 字符串。

    结构: {EMAIL_SENDER}|{EMAIL_PASS}|{EMAIL_TO}

    Args:
        config_str: 配置字符串，可为空（返回 None）

    Returns:
        dict: {"sender": ..., "password": ..., "to": [addr, ...]}
              输入为空则返回 None

    Raises:
        ValueError: 格式不正确
    """
    if not config_str:
        return None

    parts = config_str.split("|")
    if len(parts) != 3:
        raise ValueError(
            "EMAIL_CONFIG 格式错误，应为 {SENDER}|{PASS}|{TO}，"
            f"实际收到 {len(parts)} 段"
        )

    sender, password, to_raw = (p.strip() for p in parts)
    if not sender or not password or not to_raw:
        raise ValueError("EMAIL_CONFIG 中 SENDER / PASS / TO 均不能为空")

    # 支持逗号分隔多个收件人
    to_list = [addr.strip() for addr in to_raw.split(",") if addr.strip()]
    if not to_list:
        raise ValueError("EMAIL_CONFIG 中 TO 解析后没有有效收件地址")

    return {"sender": sender, "password": password, "to": to_list}


# ============================================================================
# 通用发送
# ============================================================================


def send_email(subject, body, email_config, html=False, subtype=None):
    """通过 Gmail SMTP 发送邮件。

    Args:
        subject:       邮件标题
        body:          邮件正文
        email_config:  配置字符串（{SENDER}|{PASS}|{TO}）或已解析的 dict
        html:          正文是否为 HTML（默认纯文本）
        subtype:       显式指定 MIME subtype，优先级高于 html

    Returns:
        bool: 是否发送成功
    """
    try:
        cfg = (
            email_config
            if isinstance(email_config, dict)
            else parse_email_config(email_config)
        )
        if not cfg:
            return False

        sender = cfg["sender"]
        password = cfg["password"]
        to_list = cfg["to"]

        if subtype is None:
            subtype = "html" if html else "plain"

        msg = MIMEMultipart("alternative")
        msg["From"] = sender
        msg["To"] = ", ".join(to_list)
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg.attach(MIMEText(body, subtype, "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(sender, password)
            smtp.sendmail(sender, to_list, msg.as_string())

        return True

    except Exception as e:
        print(f"[Notifier] 邮件发送失败: {e}")
        return False


# ============================================================================
# 通用结果通知
# ============================================================================


def notify_result(success, title_prefix, body_lines, email_config):
    """根据执行结果构建标题并发送通知。

    Args:
        success:       是否成功
        title_prefix:  标题前缀，如 "Linux.do"
        body_lines:    正文行列表（每行一个字符串），按顺序拼接

    Returns:
        bool: 是否发送成功
    """
    status = "成功" if success else "失败"
    subject = f"{title_prefix} 执行{status}"
    body = "\n".join(body_lines)
    return send_email(subject, body, email_config)


# ============================================================================
# 针对 linux_do_headless.py 的便捷封装
# ============================================================================


def _format_elapsed(elapsed):
    """把秒数格式化成 X分Y秒 / Y秒"""
    if elapsed is None:
        return "未知"
    elapsed = int(elapsed)
    minutes, seconds = divmod(elapsed, 60)
    if minutes > 0:
        return f"{minutes}分{seconds}秒"
    return f"{seconds}秒"


def notify_linuxdo_result(success, stats, elapsed, error_messages, email_config):
    """构建 Linux.do 任务结果通知并发送。

    Args:
        success:         任务是否成功（通常以 stats["topics"] > 0 判定）
        stats:           统计字典，需包含 topics / likes（floors 可选）
        elapsed:         任务耗时（秒）
        error_messages:  执行过程中收集到的错误信息列表（可为空）
        email_config:    EMAIL_CONFIG 字符串或已解析 dict

    Returns:
        bool: 是否发送成功
    """
    stats = stats or {}
    topics = stats.get("topics", 0)
    likes = stats.get("likes", 0)
    floors = stats.get("floors", 0)

    body_lines = []

    if success:
        body_lines.append("Linux.do 自动浏览任务执行成功 ✅")
        body_lines.append("")
        body_lines.append(f"任务耗时: {_format_elapsed(elapsed)}")
        body_lines.append(f"浏览帖子数: {topics}")
        body_lines.append(f"点赞数量: {likes}")
        if floors:
            body_lines.append(f"滚动次数: {floors}")
    else:
        body_lines.append("Linux.do 自动浏览任务执行失败 ❌")
        body_lines.append("")
        body_lines.append(f"任务耗时: {_format_elapsed(elapsed)}")
        body_lines.append(f"浏览帖子数: {topics}")
        body_lines.append(f"点赞数量: {likes}")
        body_lines.append("")

        if error_messages:
            body_lines.append("失败原因 / 错误信息:")
            for msg in error_messages:
                body_lines.append(f"  - {msg}")
        else:
            # 未捕获到明确错误时的兜底提示
            body_lines.append("失败原因: 未能浏览到任何帖子，可能原因如下:")
            body_lines.append("  - 浏览器启动失败（Chrome 未安装或路径错误）")
            body_lines.append("  - Cookie 失效或账号密码错误，登录失败")
            body_lines.append("  - 网络异常 / 代理不可用")
            body_lines.append("  - 目标板块无可用帖子")

    return notify_result(success, "Linux.do", body_lines, email_config)
