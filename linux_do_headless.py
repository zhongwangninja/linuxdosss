# -*- coding: utf-8 -*-
"""
================================================================================
Linux.do 论坛自动浏览脚本 (无头版 / Headless)
================================================================================

适用场景：
    - GitHub Actions 定时任务
    - 服务器后台运行
    - 无 GUI 环境

功能：
    - 自动登录（支持 Cookie / 账号密码 两种方式，优先 Cookie）
    - 自动浏览多个板块
    - 随机点赞帖子
    - 防风控机制（随机间隔）
    - 支持代理

================================================================================
使用方法
================================================================================

【推荐】方式一：Cookie 登录（可绕过登录验证码，适合 GitHub Actions）
    1. 本地运行 `python extract_cookies.py`，手动登录后导出 cookie JSON
    2. 把那串 JSON 设为环境变量或 Secret：
       export LINUXDO_COOKIES='<JSON 字符串>'
       python linux_do_headless.py

方式二：账号密码登录（可能遇到验证码）
    export LINUXDO_USERNAME="你的用户名"
    export LINUXDO_PASSWORD="你的密码"
    python linux_do_headless.py

可选参数：
    --cookies       Cookie JSON 字符串（覆盖 LINUXDO_COOKIES）
    --cookies-file  从文件读取 cookies JSON
    --proxy         代理地址，如 127.0.0.1:7897
    --topics        浏览帖子数量，默认 30
    --like-rate     点赞概率，0-100，默认 30
    --no-headless   显示浏览器窗口（调试用）
    --debug         调试模式

================================================================================
GitHub Actions 配置
================================================================================

1. Fork 本仓库到你的账号，并设为私有

2. 添加 Secret（Settings -> Secrets and variables -> Actions）：
   - LINUXDO_COOKIES: 本地 `python extract_cookies.py` 导出的 JSON 字符串

   （可选回退）也可以同时配置以下 Secret，cookie 失效时尝试账号密码登录：
   - LINUXDO_USERNAME / LINUXDO_PASSWORD

3. 启用 Actions（Actions -> I understand my workflows, go ahead and enable them）

4. 定时任务会自动运行，也可以手动触发（Actions -> Run workflow）

注意：Cookie 通常会在几周到几个月后过期，过期后重跑 extract_cookies.py 更新 Secret 即可。

================================================================================
注意事项
================================================================================

1. 请合理设置运行频率，避免对服务器造成压力
2. 建议每天运行 1-2 次，每次浏览 30-50 个帖子
3. GitHub Actions 私有仓库每月有 2000 分钟免费额度
4. 单次运行时间建议控制在 30 分钟以内

================================================================================
"""

import os
import sys
import json
import platform
import random
import time
import argparse
from datetime import datetime

# 检查依赖
try:
    from DrissionPage import ChromiumPage, ChromiumOptions
except ImportError:
    print("错误: 请先安装 DrissionPage")
    print("运行: pip install DrissionPage")
    sys.exit(1)


# ============================================================================
# 配置
# ============================================================================

# 板块配置（可根据需要调整 enabled 字段）
CATEGORIES = [
    {"name": "开发调优", "url": "/c/develop/4", "enabled": True},
    {"name": "国产替代", "url": "/c/domestic/98", "enabled": True},
    {"name": "资源荟萃", "url": "/c/resource/14", "enabled": True},
    {"name": "网盘资源", "url": "/c/resource/cloud-asset/94", "enabled": True},
    {"name": "文档共建", "url": "/c/wiki/42", "enabled": True},
    {"name": "积分乐园", "url": "/c/credit/106", "enabled": False},  # 默认禁用
    {"name": "非我莫属", "url": "/c/job/27", "enabled": True},
    {"name": "读书成诗", "url": "/c/reading/32", "enabled": True},
    {"name": "扬帆起航", "url": "/c/startup/46", "enabled": False},  # 默认禁用
    {"name": "前沿快讯", "url": "/c/news/34", "enabled": True},
    {"name": "网络记忆", "url": "/c/feeds/92", "enabled": True},
    {"name": "福利羊毛", "url": "/c/welfare/36", "enabled": True},
    {"name": "搞七捻三", "url": "/c/gossip/11", "enabled": True},
    {"name": "社区孵化", "url": "/c/incubator/102", "enabled": False},  # 默认禁用
    {"name": "虫洞广场", "url": "/c/square/110", "enabled": True},
    {"name": "运营反馈", "url": "/c/feedback/2", "enabled": False},  # 默认禁用
]

# 默认配置
DEFAULT_CONFIG = {
    "base_url": "https://linux.do",
    "like_rate": 0.3,  # 点赞概率 30%
    "scroll_min": 3,  # 最小滚动次数
    "scroll_max": 8,  # 最大滚动次数
    "wait_min": 1,  # 最小等待时间（秒）
    "wait_max": 3,  # 最大等待时间（秒）
}


def _find_chrome_path():
    """探测 Chrome 二进制路径，返回第一个存在的，找不到返回 None。

    优先用 CHROME_PATH 环境变量，否则按操作系统试常见路径。
    DrissionPage 默认探测不到 .app 包内部的可执行文件，需要显式给出。
    """
    env = os.environ.get("CHROME_PATH")
    if env and os.path.exists(env):
        return env

    system = platform.system()
    if system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/System/Volumes/Data/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            os.path.expanduser(
                "~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            ),
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
        ]
    elif system == "Linux":
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
        ]
    elif system == "Windows":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
    else:
        candidates = []

    for path in candidates:
        if os.path.exists(path):
            return path
    return None


# ============================================================================
# 日志工具
# ============================================================================


class Logger:
    """简单的日志工具"""

    def __init__(self, debug=False):
        self.debug_mode = debug

    def _timestamp(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def info(self, msg):
        print(f"[{self._timestamp()}] [INFO] {msg}")

    def success(self, msg):
        print(f"[{self._timestamp()}] [OK] {msg}")

    def warning(self, msg):
        print(f"[{self._timestamp()}] [WARN] {msg}")

    def error(self, msg):
        print(f"[{self._timestamp()}] [ERROR] {msg}")

    def debug(self, msg):
        if self.debug_mode:
            print(f"[{self._timestamp()}] [DEBUG] {msg}")


class ErrorCaptureLogger(Logger):
    """在普通 Logger 基础上收集 error 日志，供任务结束后写入通知邮件正文。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.errors = []

    def error(self, msg):
        self.errors.append(msg)
        super().error(msg)


# ============================================================================
# 核心类
# ============================================================================


class LinuxDoBot:
    """Linux.do 自动浏览机器人（无头版）"""

    def __init__(self, username=None, password=None, cookies=None, config=None, logger=None):
        """
        初始化机器人

        Args:
            username: Linux.do 用户名（cookie 登录时可省略）
            password: Linux.do 密码（cookie 登录时可省略）
            cookies:  cookie 列表 list[dict]，优先于账号密码使用
            config:   配置字典，可选
            logger:   日志工具，可选
        """
        self.username = username
        self.password = password
        self.cookies = cookies
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.log = logger or Logger()
        self.page = None
        self.stats = {
            "topics": 0,  # 浏览帖子数
            "likes": 0,  # 点赞数
            "floors": 0,  # 爬楼数
        }

    def _random_delay(self, min_sec=None, max_sec=None, reason=""):
        """随机延迟（防风控）"""
        min_sec = min_sec or self.config["wait_min"]
        max_sec = max_sec or self.config["wait_max"]
        delay = random.uniform(min_sec, max_sec)
        if reason:
            self.log.debug(f"等待 {delay:.1f}s ({reason})")
        time.sleep(delay)

    def start_browser(self, headless=True, proxy=None):
        """
        启动浏览器

        Args:
            headless: 是否无头模式
            proxy: 代理地址，如 "127.0.0.1:7897"

        Returns:
            bool: 是否成功
        """
        self.log.info("启动浏览器...")

        try:
            options = ChromiumOptions()

            # 显式指定 Chrome 路径（DrissionPage 默认探测不到 .app 包内部路径）
            chrome_path = _find_chrome_path()
            if chrome_path:
                self.log.debug(f"使用 Chrome: {chrome_path}")
                options.set_browser_path(chrome_path)
            else:
                self.log.warning(
                    "未自动找到 Chrome，DrissionPage 会用默认探测。"
                    "若启动失败请设置 CHROME_PATH 环境变量。"
                )

            # 无头模式
            if headless:
                options.set_argument("--headless=new")
                self.log.info("无头模式已启用")

            # 代理设置
            if proxy:
                options.set_proxy(proxy)
                self.log.info(f"代理已设置: {proxy}")

            # 反自动化检测
            options.set_argument("--disable-blink-features=AutomationControlled")
            options.set_argument("--no-sandbox")
            options.set_argument("--disable-dev-shm-usage")
            options.set_argument("--disable-gpu")
            options.set_argument("--window-size=1920,1080")

            # 设置 User-Agent
            options.set_argument(
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

            self.page = ChromiumPage(options)
            self.log.success("浏览器启动成功")
            return True

        except Exception as e:
            self.log.error(f"浏览器启动失败: {e}")
            return False

    def login(self):
        """
        登录 Linux.do

        优先级：cookies > 账号密码

        Returns:
            bool: 是否成功
        """
        if self.cookies:
            if self._login_with_cookies():
                return True
            # cookie 失效时，如果还配了账号密码就回退
            if self.username and self.password:
                self.log.warning("Cookie 登录失败，回退到账号密码登录")
            else:
                return False

        if not (self.username and self.password):
            self.log.error("既无有效 cookie，也未提供账号密码，无法登录")
            return False

        return self._login_with_password()

    def _login_with_cookies(self):
        """使用 cookie 登录"""
        self.log.info("使用 Cookie 登录...")
        try:
            # 先打开域名，再写 cookie，避免被浏览器丢弃
            self.page.get(self.config["base_url"])
            self._random_delay(1, 2, "首页加载")

            # DrissionPage 接受 list[dict] 或 "name=value;name2=value2" 字符串
            self.page.set.cookies(self.cookies)
            self.log.debug(f"已写入 {len(self.cookies)} 条 cookie")

            # 刷新让 cookie 生效
            self.page.get(self.config["base_url"])
            self._random_delay(2, 3, "验证登录态")

            if self.page.ele("#current-user", timeout=5):
                self.log.success("Cookie 登录成功")
                return True

            self.log.warning("Cookie 已失效或不完整")
            return False
        except Exception as e:
            self.log.error(f"Cookie 登录出错: {e}")
            return False

    def _login_with_password(self):
        """
        使用账号密码登录 Linux.do

        Returns:
            bool: 是否成功
        """
        self.log.info("开始登录（账号密码）...")

        try:
            # 访问登录页面
            login_url = f"{self.config['base_url']}/login"
            self.page.get(login_url)
            self._random_delay(2, 4, "页面加载")

            # 输入用户名
            self.log.debug("输入用户名...")
            username_input = self.page.ele("#login-account-name", timeout=10)
            if not username_input:
                self.log.error("未找到用户名输入框")
                return False
            username_input.clear()
            username_input.input(self.username)
            self._random_delay(0.5, 1, "输入用户名后")

            # 输入密码
            self.log.debug("输入密码...")
            password_input = self.page.ele("#login-account-password", timeout=5)
            if not password_input:
                self.log.error("未找到密码输入框")
                return False
            password_input.clear()
            password_input.input(self.password)
            self._random_delay(0.5, 1, "输入密码后")

            # 点击登录按钮
            self.log.debug("点击登录按钮...")
            login_btn = self.page.ele("#login-button", timeout=5)
            if not login_btn:
                self.log.error("未找到登录按钮")
                return False
            login_btn.click()

            # 等待登录完成
            self._random_delay(3, 5, "等待登录")

            # 验证登录状态
            if self._check_login():
                self.log.success("登录成功")
                return True
            else:
                self.log.error("登录失败，请检查用户名和密码")
                return False

        except Exception as e:
            self.log.error(f"登录过程出错: {e}")
            return False

    def _check_login(self):
        """检查是否已登录"""
        try:
            # 访问首页
            self.page.get(self.config["base_url"])
            self._random_delay(2, 3)

            # 检查用户头像元素
            user_ele = self.page.ele("#current-user", timeout=5)
            return user_ele is not None
        except:
            return False

    def get_topics(self, category):
        """
        获取板块帖子列表

        Args:
            category: 板块配置字典

        Returns:
            list: 帖子列表
        """
        url = self.config["base_url"] + category["url"]
        self.log.info(f"进入板块: {category['name']}")

        try:
            self.page.get(url)
            self._random_delay(2, 4, "板块加载")

            # 使用 JS 获取帖子列表
            topics = self.page.run_js("""
            function getTopics() {
                const rows = document.querySelectorAll('tr.topic-list-item');
                const topics = [];
                rows.forEach(row => {
                    const link = row.querySelector('a.title.raw-link.raw-topic-link');
                    if (link) {
                        const href = link.getAttribute('href');
                        const title = link.textContent.trim();
                        // 跳过置顶帖
                        if (href && title && !row.classList.contains('pinned')) {
                            topics.push({
                                url: href,
                                title: title.substring(0, 50)
                            });
                        }
                    }
                });
                return topics;
            }
            return getTopics();
            """)

            self.log.debug(f"找到 {len(topics or [])} 个帖子")
            return topics or []

        except Exception as e:
            self.log.error(f"获取帖子列表失败: {e}")
            return []

    def browse_topic(self, topic):
        """
        浏览单个帖子

        Args:
            topic: 帖子信息字典

        Returns:
            bool: 是否成功
        """
        url = topic["url"]
        if url.startswith("/"):
            url = self.config["base_url"] + url

        title = (
            topic["title"][:30] + "..." if len(topic["title"]) > 30 else topic["title"]
        )
        self.log.info(f"浏览: {title}")

        try:
            self.page.get(url)
            self._random_delay(2, 3, "帖子加载")

            # 滚动阅读
            scroll_count = random.randint(
                self.config["scroll_min"], self.config["scroll_max"]
            )

            for i in range(scroll_count):
                # 随机滚动距离
                distance = random.randint(300, 800)
                self.page.run_js(f"window.scrollBy(0, {distance})")
                self._random_delay(1, 2.5, f"滚动 {i + 1}/{scroll_count}")

                # 检查是否到底部
                at_bottom = self.page.run_js("""
                return (window.innerHeight + window.scrollY) >= document.body.offsetHeight - 100;
                """)
                if at_bottom:
                    self.log.debug("已到达页面底部")
                    break

            self.stats["topics"] += 1
            self.stats["floors"] += scroll_count

            # 随机点赞
            if random.random() < self.config["like_rate"]:
                self._do_like()

            return True

        except Exception as e:
            self.log.error(f"浏览帖子失败: {e}")
            return False

    def _do_like(self):
        """点赞主帖"""
        try:
            result = self.page.run_js("""
            function clickLike() {
                const buttons = document.querySelectorAll('button.btn-toggle-reaction-like');
                if (buttons.length > 0) {
                    const btn = buttons[0];
                    if (!btn.classList.contains('has-like') && !btn.classList.contains('my-likes')) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            }
            return clickLike();
            """)

            if result:
                self.stats["likes"] += 1
                self.log.success("点赞成功")
                self._random_delay(0.5, 1.5, "点赞后")

        except Exception as e:
            self.log.debug(f"点赞失败: {e}")

    def run(self, target_topics=30, headless=True, proxy=None):
        """
        运行自动浏览任务

        Args:
            target_topics: 目标浏览帖子数
            headless: 是否无头模式
            proxy: 代理地址

        Returns:
            dict: 统计结果
        """
        self.log.info("=" * 60)
        self.log.info("Linux.do 自动浏览任务开始")
        self.log.info(f"目标: 浏览 {target_topics} 个帖子")
        self.log.info("=" * 60)

        start_time = time.time()

        try:
            # 启动浏览器
            if not self.start_browser(headless=headless, proxy=proxy):
                return self.stats

            # 登录
            if not self.login():
                return self.stats

            # 获取启用的板块
            enabled_categories = [c for c in CATEGORIES if c.get("enabled", True)]
            random.shuffle(enabled_categories)

            self.log.info(f"将浏览 {len(enabled_categories)} 个板块")

            # 开始浏览
            while self.stats["topics"] < target_topics:
                for category in enabled_categories:
                    if self.stats["topics"] >= target_topics:
                        break

                    # 获取帖子列表
                    topics = self.get_topics(category)
                    if not topics:
                        continue

                    # 随机选择几个帖子
                    count = min(random.randint(2, 5), len(topics))
                    selected = random.sample(topics, count)

                    for topic in selected:
                        if self.stats["topics"] >= target_topics:
                            break

                        self.browse_topic(topic)
                        self._random_delay(reason="切换帖子")

                # 如果一轮结束还没达到目标，重新打乱板块顺序
                random.shuffle(enabled_categories)

        except KeyboardInterrupt:
            self.log.warning("用户中断")

        except Exception as e:
            self.log.error(f"运行出错: {e}")

        finally:
            # 关闭浏览器
            if self.page:
                try:
                    self.page.quit()
                except:
                    pass

        # 统计结果
        elapsed = time.time() - start_time
        elapsed_min = int(elapsed / 60)
        elapsed_sec = int(elapsed % 60)

        self.log.info("=" * 60)
        self.log.info("任务完成")
        self.log.info(f"用时: {elapsed_min}分{elapsed_sec}秒")
        self.log.info(f"浏览帖子: {self.stats['topics']}")
        self.log.info(f"点赞数: {self.stats['likes']}")
        self.log.info(f"滚动次数: {self.stats['floors']}")
        self.log.info("=" * 60)

        return self.stats


# ============================================================================
# 命令行入口
# ============================================================================


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Linux.do 论坛自动浏览脚本（无头版）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python linux_do_headless.py -u myuser -p mypass
  python linux_do_headless.py -u myuser -p mypass --topics 50
  python linux_do_headless.py -u myuser -p mypass --proxy 127.0.0.1:7897

环境变量:
  LINUXDO_USERNAME  用户名
  LINUXDO_PASSWORD  密码
  LINUXDO_PROXY     代理地址（可选）
        """,
    )

    parser.add_argument(
        "-u", "--username", help="Linux.do 用户名（或设置环境变量 LINUXDO_USERNAME）"
    )
    parser.add_argument(
        "-p", "--password", help="Linux.do 密码（或设置环境变量 LINUXDO_PASSWORD）"
    )
    parser.add_argument(
        "--cookies",
        help="Cookie JSON 字符串，list[dict] 格式，可用 extract_cookies.py 生成；"
        "或环境变量 LINUXDO_COOKIES。优先于账号密码使用。",
    )
    parser.add_argument(
        "--cookies-file", help="从文件读取 cookies JSON（与 --cookies 二选一）"
    )
    parser.add_argument("--proxy", help="代理地址，如 127.0.0.1:7897")
    parser.add_argument("--topics", type=int, default=30, help="浏览帖子数量，默认 30")
    parser.add_argument(
        "--like-rate", type=int, default=30, help="点赞概率（0-100），默认 30"
    )
    parser.add_argument(
        "--no-headless", action="store_true", help="禁用无头模式（显示浏览器窗口）"
    )
    parser.add_argument("--debug", action="store_true", help="调试模式")

    return parser.parse_args()


def _load_cookies(cookies_arg, cookies_file_arg, logger):
    """从命令行 / 环境变量 / 文件加载 cookies，返回 list[dict] 或 None"""
    raw = cookies_arg or os.environ.get("LINUXDO_COOKIES")
    if not raw and cookies_file_arg:
        try:
            with open(cookies_file_arg, "r", encoding="utf-8") as f:
                raw = f.read().strip()
        except OSError as e:
            logger.error(f"读取 cookies 文件失败: {e}")
            return None

    if not raw:
        return None

    try:
        cookies = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"Cookies JSON 解析失败: {e}")
        return None

    if not isinstance(cookies, list) or not cookies:
        logger.error("Cookies 必须是非空的 list[dict]")
        return None

    return cookies


def main():
    """主函数"""
    args = parse_args()

    # 创建日志工具（顺便收集 error，用于通知邮件正文）
    logger = ErrorCaptureLogger(debug=args.debug)

    # 获取认证信息（优先 cookies，其次账号密码）
    cookies = _load_cookies(args.cookies, args.cookies_file, logger)
    username = args.username or os.environ.get("LINUXDO_USERNAME")
    password = args.password or os.environ.get("LINUXDO_PASSWORD")
    proxy = args.proxy or os.environ.get("LINUXDO_PROXY")

    # 验证必要参数
    if not cookies and not (username and password):
        print("错误: 请提供 cookies 或账号密码")
        print()
        print("方式一（推荐，可绕过验证码）: cookies")
        print("  本地先运行: python extract_cookies.py")
        print("  然后:  export LINUXDO_COOKIES='<上一步输出的 JSON>'")
        print("        python linux_do_headless.py")
        print()
        print("方式二: 账号密码")
        print("  export LINUXDO_USERNAME='用户名'")
        print("  export LINUXDO_PASSWORD='密码'")
        print("  python linux_do_headless.py")
        sys.exit(1)

    if cookies:
        logger.info(f"使用 Cookie 登录（{len(cookies)} 条）")
    else:
        logger.info("使用账号密码登录")

    # 配置
    config = {
        "like_rate": args.like_rate / 100,  # 转换为小数
    }

    # 创建机器人并运行
    bot = LinuxDoBot(
        username=username,
        password=password,
        cookies=cookies,
        config=config,
        logger=logger,
    )

    run_start = time.time()
    try:
        stats = bot.run(
            target_topics=args.topics, headless=not args.no_headless, proxy=proxy
        )
        success = stats["topics"] > 0
    except Exception as e:
        logger.error(f"主流程异常: {e}")
        stats = {"topics": 0, "likes": 0, "floors": 0}
        success = False
    elapsed = time.time() - run_start

    # 发送执行结果通知（仅当配置了 EMAIL_CONFIG 时）
    email_config = os.environ.get("EMAIL_CONFIG")
    if email_config:
        try:
            from notifier import notify_linuxdo_result

            notify_linuxdo_result(
                success=success,
                stats=stats,
                elapsed=elapsed,
                error_messages=logger.errors,
                email_config=email_config,
            )
        except Exception as e:
            logger.error(f"发送通知失败: {e}")

    # 返回状态码
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
