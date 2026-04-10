import time
import json
import random
import threading
import requests
from urllib.parse import quote
from faker import Faker
from abc import ABC, abstractmethod

class BaseBrowserController(ABC):
    """
    所有浏览器通用的接口和共享逻辑
    """

    def __init__(self):
        with open('config.json', 'r', encoding='utf-8') as f:
            data = json.load(f) 
        self.wait_time = data['bot_protection_wait'] * 1000
        self.max_captcha_retries = data['max_captcha_retries']
        self.enable_oauth2 = data["oauth2"]['enable_oauth2']
        self.oauth_client_id = data["oauth2"].get('client_id', '')
        self.proxy = data['proxy']
        playwright_config = data.get("playwright", {})
        self.no_system_proxy = bool(playwright_config.get("no_system_proxy", False))
        manual_captcha = data.get("manual_captcha", {})
        self.enable_manual_captcha = manual_captcha.get("enabled", False)
        self.manual_captcha_timeout_seconds = manual_captcha.get("timeout_seconds", 300)
        self.manual_captcha_poll_interval_seconds = manual_captcha.get("poll_interval_seconds", 2)
        proxy_pool = data.get("proxy_pool", {})
        self.enable_auto_rotate_proxy = proxy_pool.get("enable_auto_rotate", False)
        self.proxy_pool_api_url = proxy_pool.get("api_url", "http://127.0.0.1:5010/get/?type=https")
        self.proxy_pool_retry_interval = proxy_pool.get("retry_interval_seconds", 2)
        self.max_proxy_retries = proxy_pool.get("max_proxy_retries", 0)
        self.fetch_retries_per_round = proxy_pool.get("fetch_retries_per_round", 3)
        self.proxy_pool_delete_api_url = proxy_pool.get("delete_api_url", "http://127.0.0.1:5010/delete/")
        self.report_bad_proxy_on_probe_fail = proxy_pool.get("report_bad_proxy_on_probe_fail", True)
        self.report_bad_proxy_on_register_fail = proxy_pool.get("report_bad_proxy_on_register_fail", False)
        self.enable_proxy_probe = proxy_pool.get("enable_probe_before_switch", True)
        self.proxy_probe_url = proxy_pool.get(
            "probe_url",
            "https://outlook.live.com/mail/0/?prompt=create_account"
        )
        self.proxy_probe_timeout = proxy_pool.get("probe_timeout_seconds", 8)
        self.proxy_probe_success_status_codes = set(
            proxy_pool.get("probe_success_status_codes", [200, 301, 302, 303, 307, 308, 401, 403, 405])
        )
        self.proxy_probe_accept_non_5xx = proxy_pool.get("probe_accept_non_5xx", True)

        self.thread_local = threading.local()
        self.cleanup_lock = threading.Lock()
        self.active_resources = []  # 记录资源以便关闭


    @abstractmethod
    def launch_browser(self):
        """
        获取浏览器实例,返回playwright_instance, browser_instance
        """
        pass

    @abstractmethod
    def handle_captcha(self, page):
        """
        验证码处理流程
        """
        pass

    @abstractmethod 
    def clean_up(self, page=None, type = "all_browser"):
        """
        清理自己创建的内容
        一个是单进程结束后关闭进程，另一个是程序结束后清除所有内容
        """
        pass

    @abstractmethod
    def get_thread_page(self):
        """
        返回页面
        """


    def get_thread_browser(self):
        """
        通用逻辑:获取不同进程的浏览器
        """

        if not hasattr(self.thread_local,"browser"):

            p, b  = self.launch_browser()
            if not p:
                return None

            self.thread_local.playwright = p
            self.thread_local.browser = b

            with self.cleanup_lock:
                self.active_resources.append((p, b))

        return self.thread_local.browser

    def get_current_proxy(self):
        return getattr(self.thread_local, "proxy", self.proxy)

    def build_browser_launch_args(self):
        args = ['--lang=zh-CN']
        current_proxy = str(self.get_current_proxy() or "").strip()
        if self.no_system_proxy and not current_proxy:
            args.append('--no-proxy-server')
        return args

    def build_browser_proxy_settings(self):
        current_proxy = str(self.get_current_proxy() or "").strip()
        if not current_proxy:
            return None
        return {
            "server": current_proxy,
            "bypass": "localhost",
        }

    def close_thread_browser(self):
        p = getattr(self.thread_local, "playwright", None)
        b = getattr(self.thread_local, "browser", None)

        if b:
            try:
                b.close()
            except Exception:
                pass
        if p:
            try:
                p.stop()
            except Exception:
                pass

        with self.cleanup_lock:
            self.active_resources = [
                (rp, rb) for rp, rb in self.active_resources
                if rp is not p and rb is not b
            ]

        if hasattr(self.thread_local, "playwright"):
            del self.thread_local.playwright
        if hasattr(self.thread_local, "browser"):
            del self.thread_local.browser

    def _extract_proxy_raw(self, proxy_url):
        if not proxy_url:
            return ""
        if "://" in proxy_url:
            return proxy_url.split("://", 1)[1]
        return proxy_url

    def _normalize_pool_proxy_payload(self, payload):
        if not isinstance(payload, dict):
            return None

        proxy_raw = str(payload.get("proxy", "")).strip()
        if not proxy_raw:
            return None

        proxy_type = str(payload.get("proxy_type", "http")).strip().lower() or "http"
        if "://" in proxy_raw:
            scheme, raw = proxy_raw.split("://", 1)
            scheme = (scheme or "").lower()
            proxy_raw = raw
            if scheme in ("socks5", "socks5h"):
                proxy_type = "socks5"
            elif scheme in ("http", "https"):
                proxy_type = "http"

        scheme = "socks5" if proxy_type == "socks5" else "http"
        proxy_url = f"{scheme}://{proxy_raw}"
        return {
            "proxy_url": proxy_url,
            "proxy_raw": proxy_raw,
            "proxy_type": proxy_type
        }

    def _requests_proxy_url(self, proxy_url, proxy_type):
        if proxy_type == "socks5":
            if proxy_url.startswith("socks5://"):
                return "socks5h://" + proxy_url[len("socks5://"):]
            if proxy_url.startswith("socks5h://"):
                return proxy_url
        return proxy_url

    def get_current_proxy_meta(self):
        proxy_url = self.get_current_proxy()
        proxy_type = getattr(
            self.thread_local,
            "proxy_type",
            "socks5" if str(proxy_url).startswith("socks5://") else "http"
        )
        proxy_raw = getattr(self.thread_local, "proxy_raw", self._extract_proxy_raw(proxy_url))
        return proxy_url, proxy_raw, proxy_type

    def fetch_proxy_from_pool(self):
        if not self.proxy_pool_api_url:
            return None

        try:
            response = requests.get(self.proxy_pool_api_url, timeout=10)
            response.raise_for_status()
            payload = response.json()
            return self._normalize_pool_proxy_payload(payload)
        except Exception:
            return None

    def report_bad_proxy_to_pool(self, proxy_raw, proxy_type="http"):
        if not self.proxy_pool_delete_api_url or not proxy_raw:
            return False

        try:
            delete_url = (
                f"{self.proxy_pool_delete_api_url}?proxy={quote(proxy_raw)}"
                f"&type={quote(proxy_type or 'http')}"
            )
            response = requests.get(delete_url, timeout=8)
            return response.ok
        except Exception:
            return False

    def probe_proxy_reachability(self, proxy_url):
        """
        中文：切换代理前探测目标站连通性，减少无效重试。
        English: Probe target-site reachability before proxy switch to reduce invalid retries.
        """
        if not self.enable_proxy_probe:
            return True

        _, _, proxy_type = self.get_current_proxy_meta()
        requests_proxy = self._requests_proxy_url(proxy_url, proxy_type)
        proxies = {"http": requests_proxy, "https": requests_proxy}
        try:
            response = requests.get(
                self.proxy_probe_url,
                proxies=proxies,
                timeout=self.proxy_probe_timeout,
                allow_redirects=False
            )
            status_code = response.status_code
            if status_code in self.proxy_probe_success_status_codes:
                return True
            if self.proxy_probe_accept_non_5xx and status_code < 500 and status_code != 407:
                return True
            return False
        except Exception:
            return False

    def wait_for_manual_captcha(self, page):
        """
        中文：人工模式下等待用户手动完成验证码，检测到页面进入下一步后返回成功。
        English: In manual mode, wait for user to solve CAPTCHA and return success once the page advances.
        """
        print("[ManualCaptcha] - 请在浏览器中手动完成人机验证，完成后程序会自动继续。")
        deadline = time.time() + self.manual_captcha_timeout_seconds
        poll_interval_ms = max(1, int(self.manual_captcha_poll_interval_seconds * 1000))
        last_hint_at = 0
        seen_captcha_frame = False
        frame_disappeared_rounds = 0

        while time.time() < deadline:
            try:
                frame_count = 0
                for selector in (
                    'iframe#enforcementFrame',
                    'iframe[title="验证质询"]',
                    'iframe[title="Verification challenge"]'
                ):
                    try:
                        frame_count += page.locator(selector).count()
                    except Exception:
                        pass

                if frame_count > 0:
                    seen_captcha_frame = True
                    frame_disappeared_rounds = 0
                elif seen_captcha_frame:
                    frame_disappeared_rounds += 1
                    if frame_disappeared_rounds >= 3:
                        print("[ManualCaptcha] - 检测到验证码窗口已结束，继续执行。")
                        return True

                if page.locator('[aria-label="新邮件"]').count() > 0:
                    print("[ManualCaptcha] - 检测到邮箱主界面，继续执行。")
                    return True

                if page.get_by_text('一些异常活动').count() > 0:
                    print("[ManualCaptcha] - 页面提示异常活动，验证失败。")
                    return False

                if page.get_by_text('此站点正在维护，暂时无法使用，请稍后重试。').count() > 0:
                    print("[ManualCaptcha] - 页面提示站点保护中，验证失败。")
                    return False
            except Exception:
                pass

            if time.time() - last_hint_at >= 15:
                remain = max(0, int(deadline - time.time()))
                print(f"[ManualCaptcha] - 请继续手动验证，剩余约 {remain} 秒。")
                last_hint_at = time.time()

            page.wait_for_timeout(poll_interval_ms)

        print(f"[ManualCaptcha] - 超时未完成验证（{self.manual_captcha_timeout_seconds} 秒）。")
        return False

    def rotate_proxy_for_retry(self, attempt_index):
        if not self.enable_auto_rotate_proxy:
            return False

        fetch_retries = self.fetch_retries_per_round if self.fetch_retries_per_round > 0 else 1
        tried_proxies = set()
        for _ in range(fetch_retries):
            new_proxy_info = self.fetch_proxy_from_pool()
            if new_proxy_info:
                new_proxy = new_proxy_info["proxy_url"]
                proxy_raw = new_proxy_info["proxy_raw"]
                proxy_type = new_proxy_info["proxy_type"]

                proxy_dedup_key = f"{proxy_type}|{proxy_raw}"
                if proxy_dedup_key in tried_proxies:
                    continue
                tried_proxies.add(proxy_dedup_key)

                self.thread_local.proxy = new_proxy
                self.thread_local.proxy_raw = proxy_raw
                self.thread_local.proxy_type = proxy_type

                if not self.probe_proxy_reachability(new_proxy):
                    print(f"[Info: ProxyProbe] - 代理探测未通过，跳过: {new_proxy}")
                    if self.report_bad_proxy_on_probe_fail:
                        self.report_bad_proxy_to_pool(proxy_raw, proxy_type)
                    continue

                self.close_thread_browser()
                print(f"[Info: Proxy] - 第 {attempt_index} 次重试切换代理: {new_proxy}")
                return True
            time.sleep(self.proxy_pool_retry_interval)

        return False

    def outlook_register(self, page, email, password):

        """
        通用逻辑:注册邮箱
        """
        fake = Faker()

        lastname = fake.last_name()
        firstname = fake.first_name()
        year = str(random.randint(1960, 2005))
        month = str(random.randint(1, 12))
        day = str(random.randint(1, 28))

        try:

            page.goto("https://outlook.live.com/mail/0/?prompt=create_account", timeout=20000, wait_until="domcontentloaded")
            page.get_by_text('同意并继续').wait_for(timeout=30000)
            start_time = time.time()
            page.wait_for_timeout(0.1 * self.wait_time)
            page.get_by_text('同意并继续').click(timeout=30000)

        except: 

            print("[Error: IP] - IP质量不佳，无法进入注册界面。 ")
            return False
        
        try:

            page.locator('[aria-label="新建电子邮件"]').type(email,delay=0.006 * self.wait_time,timeout=10000)
            page.locator('[data-testid="primaryButton"]').click(timeout=5000)
            page.wait_for_timeout(0.02 * self.wait_time)
            page.locator('[type="password"]').type(password,delay=0.004 * self.wait_time, timeout=10000)
            page.wait_for_timeout(0.02 * self.wait_time)
            page.locator('[data-testid="primaryButton"]').click(timeout=5000)
            
            page.wait_for_timeout(0.03 * self.wait_time)
            page.locator('[name="BirthYear"]').fill(year,timeout=10000)

            try:

                page.wait_for_timeout(0.02 * self.wait_time)
                page.locator('[name="BirthMonth"]').select_option(value=month,timeout=1000)
                page.wait_for_timeout(0.05 * self.wait_time)
                page.locator('[name="BirthDay"]').select_option(value=day)
            
            except:

                page.locator('[name="BirthMonth"]').click()
                page.wait_for_timeout(0.02 * self.wait_time)
                page.locator(f'[role="option"]:text-is("{month}月")').click()
                page.wait_for_timeout(0.04 * self.wait_time)
                page.locator('[name="BirthDay"]').click()
                page.wait_for_timeout(0.03 * self.wait_time)
                page.locator(f'[role="option"]:text-is("{day}日")').click()
                page.locator('[data-testid="primaryButton"]').click(timeout=5000)

            page.locator('#lastNameInput').type(lastname,delay=0.002 * self.wait_time,timeout=10000)
            page.wait_for_timeout(0.02 * self.wait_time)
            page.locator('#firstNameInput').fill(firstname,timeout=10000)

            if time.time() - start_time < self.wait_time / 1000:
                page.wait_for_timeout(self.wait_time - (time.time() - start_time) * 1000)
            
            page.locator('[data-testid="primaryButton"]').click(timeout=5000)
            page.locator('span > [href="https://go.microsoft.com/fwlink/?LinkID=521839"]').wait_for(state='detached',timeout=22000)

            page.wait_for_timeout(400)

            if page.get_by_text('一些异常活动').count() or page.get_by_text('此站点正在维护，暂时无法使用，请稍后重试。').count() > 0:
                print("[Error: IP or browser] - 当前IP注册频率过快。检查IP与是否为指纹浏览器并关闭了无头模式。")
                return False

            if (not self.enable_manual_captcha) and page.locator('iframe#enforcementFrame').count() > 0:
                print("[Error: FunCaptcha] - 验证码类型错误，非按压验证码。 ")
                return False
            

            captcha_result = self.handle_captcha(page)

            if not captcha_result:
                raise TimeoutError

        except Exception as e:
            print(e)
            print(f"[Error: IP] - 加载超时或因触发机器人检测导致按压次数达到最大仍未通过。")
            return False 
        
        if not self.enable_oauth2:
            try:
                page.locator('[aria-label="新邮件"]').wait_for(timeout=26000)
            except Exception:
                print('[Error: Timeout] - 邮箱未初始化，无法正常收件。')
                return False

            with open('Results\\unlogged_email.txt', 'a', encoding='utf-8') as f:
                f.write(f"{email}@outlook.com: {password}\n")
            print(f'[Success: Email Registration] - {email}@outlook.com: {password}')
            return True
        
        try:
            page.get_by_text('取消').click(timeout=20000)

        except:
            print(f"[Error: Timeout] - 无法找到按钮。")
            return False   

        try:

            try:
                # 这个不确定是不是一定出现
                page.get_by_text('无法创建通行密钥').wait_for(timeout=25000)
                page.get_by_text('取消').click(timeout=7000)

            except:
                pass

            page.locator('[aria-label="新邮件"]').wait_for(timeout=26000)
            with open('Results\\logged_email.txt', 'a', encoding='utf-8') as f:
                f.write(f"{email}@outlook.com: {password}\n")
            print(f'[Success: Email Registration] - {email}@outlook.com: {password}')
            return True

        except:

            print(f'[Error: Timeout] - 邮箱未初始化，无法正常收件。')
            return False
