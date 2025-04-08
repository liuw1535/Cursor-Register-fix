import os
import re
import queue
import threading
from faker import Faker
from DrissionPage import Chromium
from helper.email import EmailServer

enable_register_log = True

class CursorRegister:
    CURSOR_URL = "https://www.cursor.com/"
    CURSOR_SIGNIN_URL = "https://authenticator.cursor.sh"
    CURSOR_PASSWORD_URL = "https://authenticator.cursor.sh/password"
    CURSOR_MAGAIC_CODE_URL = "https://authenticator.cursor.sh/magic-code"
    CURSOR_SIGNUP_URL = "https://authenticator.cursor.sh/sign-up"
    CURSOR_SIGNUP_PASSWORD_URL = "https://authenticator.cursor.sh/sign-up/password"
    CURSOR_EMAIL_VERIFICATION_URL = "https://authenticator.cursor.sh/email-verification"
    CURSOR_SETTING_URL = "https://www.cursor.com/settings"
    CURSOR_USAGE_URL = "https://www.cursor.com/api/usage"

    def __init__(self, 
                 browser: Chromium,
                 email_server: EmailServer = None):

        self.browser = browser
        self.email_server = email_server
        self.email_queue = queue.Queue()
        self.email_thread = None

        self.thread_id = threading.current_thread().ident
        self.retry_times = 5

    def sign_in(self, email, password = None):

        assert any(x is not None for x in (self.email_server, password)), "Should provide email server or password. At least one of them."
 
        if self.email_server is not None:
            self.email_thread = threading.Thread(target=self.email_server.wait_for_new_message_thread,
                                                 args=(self.email_queue, ), 
                                                 daemon=True)
            self.email_thread.start()

        tab = self.browser.new_tab(self.CURSOR_SIGNIN_URL)
        # Input email
        for retry in range(self.retry_times):
            try:
                if enable_register_log: print(f"[Register][{self.thread_id}][{retry}] Input email")
                tab.ele("xpath=//input[@name='email']").input(email, clear=True)
                tab.ele("@type=submit").click()

                # If not in password page, try pass turnstile page
                if not tab.wait.url_change(self.CURSOR_PASSWORD_URL, timeout=3) and self.CURSOR_SIGNIN_URL in tab.url:
                    if enable_register_log: print(f"[Register][{self.thread_id}][{retry}] Try pass Turnstile for email page")
                    self._cursor_turnstile(tab)

            except Exception as e:
                print(f"[Register][{self.thread_id}] Exception when handlding email page.")
                print(e)

            # In password page or data is validated, continue to next page
            if tab.wait.url_change(self.CURSOR_PASSWORD_URL, timeout=5):
                print(f"[Register][{self.thread_id}] Continue to password page")
                break

            tab.refresh()
            # Kill the function since time out 
            if retry == self.retry_times - 1:
                print(f"[Register][{self.thread_id}] Timeout when inputing email address")
                return tab, False

        # Use email sign-in code in password page
        for retry in range(self.retry_times):
            try:
                if enable_register_log: print(f"[Register][{self.thread_id}][{retry}] Input password")
                if password is None:
                    tab.ele("xpath=//button[@value='magic-code']").click()

                # If not in verification code page, try pass turnstile page
                if not tab.wait.url_change(self.CURSOR_MAGAIC_CODE_URL, timeout=3) and self.CURSOR_PASSWORD_URL in tab.url:
                    if enable_register_log: print(f"[Register][{self.thread_id}][{retry}] Try pass Turnstile for password page")
                    self._cursor_turnstile(tab)

            except Exception as e:
                print(f"[Register][{self.thread_id}] Exception when handling password page.")
                print(e)

            # In code verification page or data is validated, continue to next page
            if tab.wait.url_change(self.CURSOR_MAGAIC_CODE_URL, timeout=5):
                print(f"[Register][{self.thread_id}] Continue to email code page")
                break

            if tab.wait.eles_loaded("xpath=//p[contains(text(), 'Authentication blocked, please contact your admin')]", timeout=3):
                print(f"[Register][{self.thread_id}][Error] Authentication blocked, please contact your admin.")
                return tab, False

            if tab.wait.eles_loaded("xpath=//div[contains(text(), 'Sign up is restricted.')]", timeout=3):
                print(f"[Register][{self.thread_id}][Error] Sign up is restricted.")
                return tab, False

            tab.refresh()
            # Kill the function since time out 
            if retry == self.retry_times - 1:
                if enable_register_log: print(f"[Register][{self.thread_id}] Timeout when inputing password")
                return tab, False

        # Get email verification code
        try:
            verify_code = None

            data = self.email_queue.get(timeout=60)
            assert data is not None, "Fail to get code from email."

            verify_code = self.parse_cursor_verification_code(data)
            assert verify_code is not None, "Fail to parse code from email."
        except Exception as e:
            print(f"[Register][{self.thread_id}] Fail to get code from email.")
            return tab, False

        # Input email verification code
        for retry in range(self.retry_times):
            try:
                if enable_register_log: print(f"[Register][{self.thread_id}][{retry}] Input email verification code")

                for idx, digit in enumerate(verify_code, start = 0):
                    tab.ele(f"xpath=//input[@data-index={idx}]").input(digit, clear=True)
                    tab.wait(0.1, 0.3)
                tab.wait(0.5, 1.5)

                if not tab.wait.url_change(self.CURSOR_URL, timeout=3) and self.CURSOR_MAGAIC_CODE_URL in tab.url:
                    if enable_register_log: print(f"[Register][{self.thread_id}][{retry}] Try pass Turnstile for email code page.")
                    self._cursor_turnstile(tab)

            except Exception as e:
                print(f"[Register][{self.thread_id}] Exception when handling email code page.")
                print(e)

            if tab.wait.url_change(self.CURSOR_URL, timeout=3):
                break

            tab.refresh()
            # Kill the function since time out 
            if retry == self.retry_times - 1:
                if enable_register_log: print(f"[Register][{self.thread_id}] Timeout when inputing email verification code")
                return tab, False

        return tab, True

    def sign_up(self, email, password = None):

        assert self.email_server is not None, "Should provide email server."
 
        if self.email_server is not None:
            self.email_thread = threading.Thread(target=self.email_server.wait_for_new_message_thread,
                                                 args=(self.email_queue, ), 
                                                 daemon=True)
            self.email_thread.start()

        if password is None:
            fake = Faker()
            password = fake.password(length=12, special_chars=True, digits=True, upper_case=True, lower_case=True)

        tab = self.browser.new_tab(self.CURSOR_SIGNUP_URL)
        # Input email
        for retry in range(self.retry_times):
            try:
                if enable_register_log: print(f"[Register][{self.thread_id}][{retry}] Input email")
                tab.ele("xpath=//input[@name='email']").input(email, clear=True)
                tab.ele("@type=submit").click()

                # If not in password page, try pass turnstile page
                if not tab.wait.url_change(self.CURSOR_SIGNUP_PASSWORD_URL, timeout=3) and self.CURSOR_SIGNUP_URL in tab.url:
                    if enable_register_log: print(f"[Register][{self.thread_id}][{retry}] Try pass Turnstile for email page")
                    self._cursor_turnstile(tab)

            except Exception as e:
                print(f"[Register][{self.thread_id}] Exception when handlding email page.")
                print(e)

            # In password page or data is validated, continue to next page
            if tab.wait.url_change(self.CURSOR_SIGNUP_PASSWORD_URL, timeout=5):
                print(f"[Register][{self.thread_id}] Continue to password page")
                break

            tab.refresh()
            # Kill the function since time out 
            if retry == self.retry_times - 1:
                print(f"[Register][{self.thread_id}] Timeout when inputing email address")
                return tab, False

        # Use email sign-in code in password page
        for retry in range(self.retry_times):
            try:
                if enable_register_log: print(f"[Register][{self.thread_id}][{retry}] Input password")
                tab.ele("xpath=//input[@name='password']").input(password, clear=True)
                tab.ele('@type=submit').click()

                # If not in verification code page, try pass turnstile page
                if not tab.wait.url_change(self.CURSOR_EMAIL_VERIFICATION_URL, timeout=3) and self.CURSOR_SIGNUP_PASSWORD_URL in tab.url:
                    if enable_register_log: print(f"[Register][{self.thread_id}][{retry}] Try pass Turnstile for password page")
                    self._cursor_turnstile(tab)

            except Exception as e:
                print(f"[Register][{self.thread_id}] Exception when handling password page.")
                print(e)

            # In code verification page or data is validated, continue to next page
            if tab.wait.url_change(self.CURSOR_EMAIL_VERIFICATION_URL, timeout=5):
                print(f"[Register][{self.thread_id}] Continue to email code page")
                break

            if tab.wait.eles_loaded("xpath=//div[contains(text(), 'Sign up is restricted.')]", timeout=3):
                print(f"[Register][{self.thread_id}][Error] Sign up is restricted.")
                return tab, False

            tab.refresh()
            # Kill the function since time out 
            if retry == self.retry_times - 1:
                if enable_register_log: print(f"[Register][{self.thread_id}] Timeout when inputing password")
                return tab, False

        # Get email verification code
        try:
            data = self.email_queue.get(timeout=60)
            assert data is not None, "Fail to get code from email."

            verify_code = None
            if "body_text" in data:
                message_text = data["body_text"]
                message_text = message_text.replace(" ", "")
                verify_code = re.search(r'(?:\r?\n)(\d{6})(?:\r?\n)', message_text).group(1)
            elif "preview" in data:
                message_text = data["preview"]
                verify_code = re.search(r'Your verification code is (\d{6})\. This code expires', message_text).group(1)
            # Handle HTML format
            elif "content" in data:
                message_text = data["content"]
                message_text = re.sub(r"<[^>]*>", "", message_text)
                message_text = re.sub(r"&#8202;", "", message_text)
                message_text = re.sub(r"&nbsp;", "", message_text)
                message_text = re.sub(r'[\n\r\s]', "", message_text)
                verify_code = re.search(r'openbrowserwindow\.(\d{6})Thiscodeexpires', message_text).group(1)
            assert verify_code is not None, "Fail to get code from email."

        except Exception as e:
            print(f"[Register][{self.thread_id}] Fail to get code from email.")
            return tab, False

        # Input email verification code
        for retry in range(self.retry_times):
            try:
                if enable_register_log: print(f"[Register][{self.thread_id}][{retry}] Input email verification code")

                for idx, digit in enumerate(verify_code, start = 0):
                    tab.ele(f"xpath=//input[@data-index={idx}]").input(digit, clear=True)
                    tab.wait(0.1, 0.3)
                tab.wait(0.5, 1.5)

                if not tab.wait.url_change(self.CURSOR_URL, timeout=3) and self.CURSOR_EMAIL_VERIFICATION_URL in tab.url:
                    if enable_register_log: print(f"[Register][{self.thread_id}][{retry}] Try pass Turnstile for email code page.")
                    self._cursor_turnstile(tab)

            except Exception as e:
                print(f"[Register][{self.thread_id}] Exception when handling email code page.")
                print(e)

            if tab.wait.url_change(self.CURSOR_URL, timeout=3):
                break

            tab.refresh()
            # Kill the function since time out 
            if retry == self.retry_times - 1:
                if enable_register_log: print(f"[Register][{self.thread_id}] Timeout when inputing email verification code")
                return tab, False

        return tab, True
    
    def get_usage(self, user_id):
        tab = self.browser.new_tab(f"{self.CURSOR_USAGE_URL}?user={user_id}")
        return tab.json

    # tab: A tab has signed in 
    def delete_account(self):
        tab = self.browser.new_tab(self.CURSOR_SETTING_URL)
        tab.ele("xpath=//div[contains(text(), 'Advanced')]").click()
        tab.ele("xpath=//button[contains(text(), 'Delete Account')]").click()
        tab.ele("""xpath=//input[@placeholder="Type 'Delete' to confirm"]""").input("Delete", clear=True)
        tab.ele("xpath=//span[contains(text(), 'Delete')]").click()
        return tab

    def parse_cursor_verification_code(self, email_data):
        message = ""
        verify_code = None

        if "content" in email_data:
            message = email_data["content"]
            message = message.replace(" ", "")
            verify_code = re.search(r'(?:\r?\n)(\d{6})(?:\r?\n)', message).group(1)
        elif "text" in email_data:
            message = email_data["text"]
            message = message.replace(" ", "")
            verify_code = re.search(r'(?:\r?\n)(\d{6})(?:\r?\n)', message).group(1)

        return verify_code

    def get_cursor_cookie(self, tab):
        try:
            import secrets
            import hashlib
            import base64
            import uuid
            import threading
            import requests
            import time
            from datetime import datetime

            # 生成PKCE验证器和挑战码对
            def generate_pkce_pair():
                """生成PKCE验证器和挑战码对，用于OAuth 2.0 PKCE流程"""
                # 生成一个安全的随机码作为验证器
                code_verifier = secrets.token_urlsafe(43)  # 43字符长度会产生一个足够长的verifier

                # 计算挑战码 (code_challenge)
                code_challenge_digest = hashlib.sha256(code_verifier.encode('utf-8')).digest()
                code_challenge = base64.urlsafe_b64encode(code_challenge_digest).decode('utf-8').rstrip('=')

                return code_verifier, code_challenge

            # 轮询API获取cookie的函数
            def poll_for_cookie(uuid_str, verifier, stop_event):
                """持续轮询API获取cookie，直到获取成功或手动停止"""
                api_url = f"https://api2.cursor.sh/auth/poll?uuid={uuid_str}&verifier={verifier}"

                # 简化的请求头部
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.6834.210 Safari/537.36",
                    "Accept": "*/*",
                    "Origin": "vscode-file://vscode-app",
                    "x-ghost-mode": "true"
                }

                attempt = 0
                print(f"[Register][{self.thread_id}] Starting API polling for cookie...")

                while not stop_event.is_set():
                    attempt += 1
                    try:
                        print(f"[Register][{self.thread_id}] Attempt #{attempt}...")

                        # 直接发送GET请求获取cookie
                        response = requests.get(api_url, headers=headers, timeout=5)

                        if response.status_code == 200:
                            data = response.json()

                            if 'accessToken' in data:
                                token = data['accessToken']
                                print(f"[Register][{self.thread_id}] Successfully obtained Cookie!")
                                return token
                        else:
                            print(f"[Register][{self.thread_id}] Attempt #{attempt}: Request failed, status code: {response.status_code}")
                    except requests.exceptions.Timeout:
                        print(f"[Register][{self.thread_id}] Attempt #{attempt}: Request timed out")
                    except Exception as e:
                        print(f"[Register][{self.thread_id}] Attempt #{attempt}: Exception - {e}")

                    time.sleep(1)  # 每秒轮询一次

                print(f"[Register][{self.thread_id}] Polling stopped")
                return None

            # 使用PKCE流程生成UUID、验证器和挑战码
            uuid_str = str(uuid.uuid4())
            verifier, challenge = generate_pkce_pair()
            
            # 生成确认页面URL
            confirm_url = f"https://www.cursor.com/cn/loginDeepControl?challenge={challenge}&uuid={uuid_str}&mode=login"
            
            print(f"[Register][{self.thread_id}] Confirmation page URL: {confirm_url}")
            
            # 创建停止事件
            stop_event = threading.Event()
            
            # 在新线程中开始轮询
            poll_thread = threading.Thread(target=poll_for_cookie, args=(uuid_str, verifier, stop_event))
            poll_thread.daemon = True
            poll_thread.start()
            
            # 打开确认页面
            tab.get(confirm_url)
            
            # 等待"Yes, Log In"按钮加载并点击
            try:
                # 根据页面等待按钮加载
                if tab.wait.eles_loaded("xpath=//span[contains(text(), 'Yes, Log In')]", timeout=15):
                    # 点击按钮
                    tab.ele("xpath=//span[contains(text(), 'Yes, Log In')]").click()
                    print(f"[Register][{self.thread_id}] Confirmation button clicked")
                elif tab.wait.eles_loaded("xpath=//button[contains(@class, 'relative inline-flex')]//span[contains(text(), 'Yes, Log In')]", timeout=5):
                    # 尝试使用更精确的XPath定位方式
                    tab.ele("xpath=//button[contains(@class, 'relative inline-flex')]//span[contains(text(), 'Yes, Log In')]").click()
                    print(f"[Register][{self.thread_id}] Confirmation button clicked through alternative method")
                else:
                    print(f"[Register][{self.thread_id}] Confirmation button not found")
                    stop_event.set()
                    return None
            except Exception as e:
                print(f"[Register][{self.thread_id}] Error clicking confirmation button: {e}")
                stop_event.set()
                return None
            
            # 等待轮询线程完成(最多等待20秒)
            poll_thread.join(20)
            
            # 如果线程仍在运行，则停止它
            if poll_thread.is_alive():
                stop_event.set()
                print(f"[Register][{self.thread_id}] Polling timeout")
                return None
            
            # 获取结果
            token = None
            for _ in range(5):  # 尝试5次
                try:
                    # 直接发送GET请求获取cookie
                    api_url = f"https://api2.cursor.sh/auth/poll?uuid={uuid_str}&verifier={verifier}"
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.6834.210 Safari/537.36",
                        "Accept": "*/*",
                        "Origin": "vscode-file://vscode-app",
                        "x-ghost-mode": "true"
                    }
                    response = requests.get(api_url, headers=headers, timeout=5)
                    
                    if response.status_code == 200:
                        data = response.json()
                        if 'accessToken' in data:
                            token = data['accessToken']
                            break
                except Exception as e:
                    print(f"[Register][{self.thread_id}] Error getting final result: {e}")
                time.sleep(1)
            
            if enable_register_log:
                if token is not None:
                    print(f"[Register][{self.thread_id}] Successfully obtained OAuth Token!")
                else:
                    print(f"[Register][{self.thread_id}] Failed to get OAuth Token!")

            return token
            
        except Exception as e:
            print(f"[Register][{self.thread_id}] Exception while getting cookie: {e}")
            return None

    def _cursor_turnstile(self, tab, retry_times = 5):
        for retry in range(retry_times): # Retry times
            try:
                if enable_register_log: print(f"[Register][{self.thread_id}][{retry}] Passing Turnstile")
                challenge_shadow_root = tab.ele('@id=cf-turnstile').child().shadow_root
                challenge_shadow_button = challenge_shadow_root.ele("tag:iframe", timeout=30).ele("tag:body").sr("xpath=//input[@type='checkbox']")
                if challenge_shadow_button:
                    challenge_shadow_button.click()
                    break
            except:
                pass
            if retry == retry_times - 1:
                print("[Register] Timeout when passing turnstile")
