import time
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from get_token import get_access_token
from controllers.patchright_controller import PatchrightController
from controllers.playwright_controller import PlaywrightController
from utils import random_email, generate_strong_password


def process_single_flow(controller):
    attempt = 1
    while True:
        page = None
        proxy_url, proxy_raw, proxy_type = controller.get_current_proxy_meta()
        thread_id = threading.get_ident()
        display_proxy = f"{proxy_type}://{proxy_raw}" if proxy_raw else "no-proxy"
        print(f"[Info: Attempt] - Thread {thread_id}, attempt {attempt}, proxy {display_proxy}")
        try:
            page = controller.get_thread_page()
            if page is None:
                raise RuntimeError("[Error: Browser] - 浏览器启动失败，可能是代理不可用。")

            email = random_email()
            password = generate_strong_password()

            result = controller.outlook_register(page, email, password)

            if result and not controller.enable_oauth2:
                print(f"[Info: Attempt] - Thread {thread_id}, attempt {attempt} succeeded with {display_proxy}")
                return True
            if not result:
                raise RuntimeError("[Error: Register] - 注册流程失败。")

            token_result = get_access_token(page, email)
            if token_result[0]:
                refresh_token, access_token, expire_at = token_result
                with open(r"Results\outlook_token.txt", "a") as f2:
                    f2.write(
                        f"{email}@outlook.com---{password}---{refresh_token}---{access_token}---{expire_at}\n"
                    )
                with open(r"Results\outlook_token_export.txt", "a") as f3:
                    f3.write(
                        f"{email}@outlook.com----{password}----{controller.oauth_client_id}----{refresh_token}\n"
                    )
                print(f"[Success: TokenAuth] - {email}@outlook.com")
                print(f"[Info: Attempt] - Thread {thread_id}, attempt {attempt} succeeded with {display_proxy}")
                return True

            raise RuntimeError("[Error: OAuth2] - Token 获取失败。")

        except Exception as e:
            print(e)
            print(f"[Warn: Attempt] - Thread {thread_id}, attempt {attempt} failed with {display_proxy}")
            if getattr(controller, "report_bad_proxy_on_register_fail", False):
                try:
                    _, proxy_raw, proxy_type = controller.get_current_proxy_meta()
                    if proxy_raw:
                        controller.report_bad_proxy_to_pool(proxy_raw, proxy_type)
                        print(f"[Info: Proxy] - 已回传失败代理到池: {proxy_type}://{proxy_raw}")
                except Exception:
                    pass

        finally:
            controller.clean_up(page, "done_browser")

        if not controller.enable_auto_rotate_proxy:
            print(f"[Info: Attempt] - Auto rotate disabled, thread {thread_id} stop after attempt {attempt}.")
            return False

        if controller.max_proxy_retries > 0 and attempt >= controller.max_proxy_retries:
            print(f"[Error: Retry] - 已达到最大代理重试次数 {controller.max_proxy_retries}，停止当前任务。")
            return False

        next_attempt = attempt + 1
        rotated = controller.rotate_proxy_for_retry(next_attempt)
        if not rotated:
            print("[Error: ProxyPool] - 代理池未取到可用代理，停止当前任务。")
            return False

        attempt = next_attempt


def run_concurrent_flows(controller, concurrent_flows=10, max_tasks=100):
    task_counter = 0
    succeeded_tasks = 0
    failed_tasks = 0
    progress_step = max(1, max_tasks // 2)

    with ThreadPoolExecutor(max_workers=concurrent_flows) as executor:
        running_futures = set()

        while task_counter < max_tasks or len(running_futures) > 0:
            done_futures = {f for f in running_futures if f.done()}
            for future in done_futures:
                try:
                    if future.result():
                        succeeded_tasks += 1
                    else:
                        failed_tasks += 1
                except Exception as e:
                    failed_tasks += 1
                    print(e)
                running_futures.remove(future)

            while len(running_futures) < concurrent_flows and task_counter < max_tasks:
                new_future = executor.submit(process_single_flow, controller)
                running_futures.add(new_future)
                task_counter += 1
                if task_counter % progress_step == 0 or task_counter == max_tasks:
                    print(f"已提交 {task_counter}/{max_tasks} 任务.")

            time.sleep(0.5)

    print(f"\n[Result] - 共: {max_tasks}, 成功 {succeeded_tasks}, 失败 {failed_tasks}")
    return succeeded_tasks, failed_tasks


if __name__ == "__main__":
    with open("config.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    os.makedirs("Results", exist_ok=True)

    max_tasks = data["max_tasks"]
    concurrent_flows = data["concurrent_flows"]

    if data["choose_browser"] == "patchright":
        selected_controller = PatchrightController()
    elif data["choose_browser"] == "playwright":
        selected_controller = PlaywrightController()
    else:
        raise ValueError("不支持的浏览器类型，请填写 patchright 或 playwright。")

    try:
        run_concurrent_flows(selected_controller, concurrent_flows, max_tasks)
    finally:
        selected_controller.clean_up(type="all_browser")
