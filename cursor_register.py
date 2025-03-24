import os
import csv
import copy
import argparse
import concurrent.futures
import sys
import hydra
from faker import Faker
from datetime import datetime
from omegaconf import OmegaConf, DictConfig
from DrissionPage import ChromiumOptions, Chromium

# 设置控制台输出编码为UTF-8，避免中文字符编码问题
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        # Python 3.6及更早版本没有reconfigure方法
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from temp_mails import Tempmail_io, Guerillamail_com
from helper.cursor_register import CursorRegister
from helper.email import *

# Parameters for debugging purpose
hide_account_info = os.getenv('HIDE_ACCOUNT_INFO', 'false').lower() == 'true'
enable_headless = os.getenv('ENABLE_HEADLESS', 'false').lower() == 'true'
enable_browser_log = os.getenv('ENABLE_BROWSER_LOG', 'true').lower() == 'true' or not enable_headless

def register_cursor_core(register_config, options):

    try:
        # Maybe fail to open the browser
        browser = Chromium(options)
    except Exception as e:
        print(e)
        return None
    
    if register_config.email_server.name == "temp_email_server":
        email_server = eval(register_config.temp_email_server.name)(browser)
        email_address = email_server.get_email_address()
    elif register_config.email_server.name == "imap_email_server":
        # 使用每个邮箱各自的IMAP配置
        email_address = register_config.email_server.email_address
        imap_config = register_config.email_server.imap_config
        
        imap_server = imap_config.imap_server
        imap_port = imap_config.imap_port
        imap_username = imap_config.username
        imap_password = imap_config.password
        
        email_server = Imap(imap_server, imap_port, imap_username, imap_password, email_to=email_address)

    register = CursorRegister(browser, email_server)
    tab_signin, status = register.sign_in(email_address)
    #tab_signup, status = register.sign_up(email_address)
    token = register.get_cursor_cookie(tab_signin)

    if token is not None:
        user_id = token.split("%3A%3A")[0]
        delete_low_balance_account = register_config.delete_low_balance_account
        if register_config.email_server.name == "imap_email_server" and delete_low_balance_account:
            delete_low_balance_account_threshold = register_config.delete_low_balance_account_threshold

            usage = register.get_usage(user_id)
            balance = usage["gpt-4"]["maxRequestUsage"] - usage["gpt-4"]["numRequests"]
            if balance <= delete_low_balance_account_threshold:
                print(f"[Low Balance] Account balance ({balance}) is less than or equal to threshold ({delete_low_balance_account_threshold}), executing delete and re-register")
                register.delete_account()
                print("[Low Balance] Account deleted, starting re-registration")
                # 使用sign_up而不是sign_in来确保重新注册账号
                tab_signup, status = register.sign_up(email_address)
                token = register.get_cursor_cookie(tab_signup)
                if token is not None:
                    print("[Low Balance] Re-registration successful")
                else:
                    print("[Low Balance] Re-registration failed")

    if status or not enable_browser_log:
        register.browser.quit(force=True, del_data=True)

    if status and not hide_account_info:
        print(f"[Register] Cursor Email: {email_address}")
        print(f"[Register] Cursor Token: {token}")

    ret = {
        "username": email_address,
        "token": token
    }

    return ret

def register_cursor(register_config):

    options = ChromiumOptions()
    options.auto_port()
    options.new_env()
    # Use turnstilePatch from https://github.com/TheFalloutOf76/CDP-bug-MouseEvent-.screenX-.screenY-patcher
    turnstile_patch_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "turnstilePatch"))
    options.add_extension(turnstile_patch_path)

    # If fail to pass the cloudflare in headless mode, try to align the user agent with your real browser
    if enable_headless: 
        from platform import platform
        if platform == "linux" or platform == "linux2":
            platformIdentifier = "X11; Linux x86_64"
        elif platform == "darwin":
            platformIdentifier = "Macintosh; Intel Mac OS X 10_15_7"
        elif platform == "win32":
            platformIdentifier = "Windows NT 10.0; Win64; x64"
        # Please align version with your Chrome
        chrome_version = "130.0.0.0"        
        options.set_user_agent(f"Mozilla/5.0 ({platformIdentifier}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_version} Safari/537.36")
        options.headless()

    number = register_config.number
    max_workers = register_config.max_workers
    print(f"[Register] Start to register {number} accounts in {max_workers} threads")

    # Run the code using multithreading
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for idx in range(number):
            register_config_thread = copy.deepcopy(register_config)
            use_custom_address = register_config.email_server.use_custom_address
            
            if use_custom_address and register_config.email_server.name == "imap_email_server":
                # 获取指定索引的自定义邮箱配置
                if hasattr(register_config.email_server, 'custom_email_addresses') and idx < len(register_config.email_server.custom_email_addresses):
                    email_config = register_config.email_server.custom_email_addresses[idx]
                    # 设置邮箱地址和对应的IMAP配置
                    register_config_thread.email_server.email_address = email_config.email
                    register_config_thread.email_server.imap_config = email_config
                else:
                    print(f"[Register] Warning: No email configuration found for index {idx}")
                    continue
            
            options_thread = copy.deepcopy(options)
            futures.append(executor.submit(register_cursor_core, register_config_thread, options_thread))
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result is not None:
                results.append(result)

    results = [result for result in results if result["token"] is not None]

    if len(results) > 0:
        formatted_date = datetime.now().strftime("%Y-%m-%d")

        fieldnames = results[0].keys()
        # Write username, token into a csv file
        with open(f"./output_{formatted_date}.csv", 'a', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writerows(results)
        # Only write token to csv file, without header
        tokens = [{'token': row['token']} for row in results]
        with open( f"./token_{formatted_date}.csv", 'a', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=['token'])
            writer.writerows(tokens)

    return results

@hydra.main(config_path="config", config_name="config", version_base=None)
def main(config: DictConfig):
    OmegaConf.set_struct(config, False)
    
    # 从环境变量获取是否使用配置文件
    use_config_file = os.getenv('USE_CONFIG_FILE', 'true').lower() == 'true'
    email_configs_str = os.getenv('EMAIL_CONFIGS', '[]')
    
    if not use_config_file:
        try:
            import json
            email_configs = json.loads(email_configs_str)
            if not isinstance(email_configs, list):
                raise ValueError('EMAIL_CONFIGS must be a list')
            # 使用环境变量中的邮箱配置覆盖配置文件
            config.register.email_server.custom_email_addresses = email_configs
            print(f'Using {len(email_configs)} email configurations from environment variables')
        except json.JSONDecodeError as e:
            print(f'Error parsing EMAIL_CONFIGS: {e}')
            return
    else:
        print('Using email configurations from config.yaml')
    
    # Validate the config
    email_server_name = config.register.email_server.name
    use_custom_address = config.register.email_server.use_custom_address
    
    assert email_server_name in ["temp_email_server", "imap_email_server"], "email_server_name should be either temp_email_server or imap_email_server"
    assert use_custom_address and email_server_name == "imap_email_server" or not use_custom_address, "use_custom_address should be True only when email_server_name is imap_email_server"
    
    if use_custom_address and email_server_name == "imap_email_server":
        # 检查和使用自定义邮箱配置
        if hasattr(config.register.email_server, 'custom_email_addresses'):
            config.register.number = len(config.register.email_server.custom_email_addresses)
            print(f"[Register] Parameter register.number is overwritten by the length of custom_email_addresses: {config.register.number}")
        else:
            raise ValueError("custom_email_addresses is required when use_custom_address=true with imap_email_server")
    
    account_infos = register_cursor(config.register)
    tokens = list(set([row['token'] for row in account_infos]))
    print(f"[Register] Register {len(tokens)} accounts successfully")
    
    if config.oneapi.enabled and len(account_infos) > 0:
        from tokenManager.oneapi_manager import OneAPIManager
        from tokenManager.cursor import Cursor

        oneapi_url = config.oneapi.url
        oneapi_token = config.oneapi.token
        oneapi_channel_url = config.oneapi.channel_url

        oneapi = OneAPIManager(oneapi_url, oneapi_token)
        # Send request by batch to avoid "Too many SQL variables" error in SQLite.
        # If you use MySQL, better to set the batch_size as len(tokens)
        batch_size = min(10, len(tokens))
        for i in range(0, len(tokens), batch_size):
            batch_tokens = tokens[i:i+batch_size]
            oneapi.batch_add_channel(batch_tokens, oneapi_channel_url)

if __name__ == "__main__":
    main()
