import requests
import re
import random
import time
import logging
import socket
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import pytz
import jdatetime
import timeit
import json

# تنظیمات لاگ
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# لیست User-Agent برای درخواست‌های HTTP
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36'
]

def get_random_user_agent():
    return random.choice(USER_AGENTS)

def check_proxy_status(server, port, timeout=3):
    """چک کردن وضعیت پروکسی با اتصال سوکت"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((server, int(port)))
        sock.close()
        if result == 0:
            logging.info(f"Proxy {server}:{port} is online")
            return True
        else:
            logging.warning(f"Proxy {server}:{port} is offline or unreachable")
            return False
    except (socket.timeout, socket.gaierror, ConnectionRefusedError) as e:
        logging.error(f"Error checking proxy {server}:{port}: {e}")
        return False

def measure_proxy_ping(server, port, timeout=3, tries=1):
    """اندازه‌گیری پینگ پروکسی (میانگین زمان اتصال در میلی‌ثانیه)"""
    total_time = 0
    successful_tries = 0
    for _ in range(tries):
        start_time = timeit.default_timer()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((server, int(port)))
            sock.close()
            if result == 0:
                elapsed = (timeit.default_timer() - start_time) * 1000  # تبدیل به میلی‌ثانیه
                total_time += elapsed
                successful_tries += 1
                logging.debug(f"Ping for {server}:{port}: {elapsed:.2f}ms")
            else:
                logging.warning(f"Ping failed for {server}:{port}")
        except (socket.timeout, socket.gaierror, ConnectionRefusedError) as e:
            logging.error(f"Ping error for {server}:{port}: {e}")
        time.sleep(0.1)  # فاصله بین تلاش‌ها
    if successful_tries > 0:
        average_ping = total_time / successful_tries
        logging.info(f"Average ping for {server}:{port}: {average_ping:.2f}ms")
        return average_ping
    return None

def fetch_proxies_from_url(url, proxy_type, max_proxies=50):
    """استخراج پروکسی‌ها از لینک متنی یا JSON با پشتیبانی از MTProto"""
    proxies = []
    headers = {'User-Agent': get_random_user_agent()}
    pattern_ip_port = r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{1,5}$'  # فرمت IP:PORT
    pattern_mtproto = r'^tg://proxy\?server=([^&]+)&port=(\d+)&secret=([^\s]+)$'  # فرمت MTProto
    
    try:
        logging.info(f"Fetching {proxy_type} proxies from {url}")
        response = requests.get(url, headers=headers, timeout=20)  # افزایش زمان‌اوت
        response.raise_for_status()
        proxy_checks = []
        
        if proxy_type == 'MTPROTO':
            # پردازش پروکسی‌های MTProto
            lines = response.text.splitlines()
            for line in lines[:max_proxies]:
                line = line.strip()
                if not line:
                    continue
                # تبدیل https://t.me/proxy به tg://proxy برای یکپارچگی
                line = line.replace('https://t.me/proxy', 'tg://proxy')
                match = re.match(pattern_mtproto, line)
                if match:
                    server, port, secret = match.groups()
                    proxy = f"tg://proxy?server={server}&port={port}&secret={secret}"
                    proxy_checks.append((proxy, server, port))
                else:
                    logging.debug(f"Invalid {proxy_type} proxy format: {line}")
        elif url.endswith('.json'):
            # پردازش فایل JSON
            try:
                data = json.loads(response.text)
                if isinstance(data, list):
                    for item in data[:max_proxies]:
                        if 'ip' in item and 'port' in item:
                            server = str(item['ip']).strip()
                            port = str(item['port']).strip()
                            proxy = f"{server}:{port}"
                            if re.match(pattern_ip_port, proxy):
                                proxy_checks.append((proxy, server, port))
                            else:
                                logging.debug(f"Invalid {proxy_type} proxy format in JSON: {proxy}")
                        else:
                            logging.debug(f"Missing ip or port in JSON item: {item}")
                else:
                    logging.error(f"JSON data is not a list: {url}")
            except json.JSONDecodeError as e:
                logging.error(f"Invalid JSON format in {url}: {e}")
        else:
            # پردازش فایل متنی
            lines = response.text.splitlines()
            for line in lines[:max_proxies]:
                line = line.strip()
                if not line:
                    continue
                if re.match(pattern_ip_port, line):
                    server, port = line.split(':')
                    proxy_checks.append((line, server, port))
                else:
                    logging.debug(f"Invalid {proxy_type} proxy format: {line}")
        
        # چک کردن وضعیت پروکسی‌ها و پینگ (فقط برای غیر MTProto)
        if proxy_type != 'MTPROTO':
            with ThreadPoolExecutor(max_workers=20) as executor:  # کاهش max_workers
                future_to_proxy = {executor.submit(check_proxy_status, server, port): (proxy, server, port) for proxy, server, port in proxy_checks}
                for future in as_completed(future_to_proxy):
                    proxy, server, port = future_to_proxy[future]
                    try:
                        if future.result():
                            ping = measure_proxy_ping(server, port)
                            if ping is not None:
                                proxies.append((proxy, ping))
                                logging.info(f"Valid and online {proxy_type} proxy: {proxy} (Ping: {ping:.2f}ms)")
                            else:
                                logging.warning(f"Skipping {proxy_type} proxy {proxy} due to ping failure")
                        else:
                            logging.warning(f"Skipping offline {proxy_type} proxy: {proxy}")
                    except Exception as e:
                        logging.error(f"Error checking {proxy_type} proxy {proxy}: {e}")
        else:
            # برای MTProto فقط لینک‌ها رو جمع‌آوری می‌کنیم (بدون پینگ)
            for proxy, server, port in proxy_checks:
                proxies.append((proxy, 0))  # پینگ صفر برای MTProto
                logging.info(f"Valid {proxy_type} proxy: {proxy}")
        
        logging.info(f"Fetched {len(proxies)} valid {proxy_type} proxies from {url}")
        if not proxies:
            logging.warning(f"No valid proxies found for {proxy_type} from {url}")
    except requests.RequestException as e:
        logging.error(f"HTTP error fetching {url}: {e}")
    return proxies

def save_proxies_to_file(proxies, proxy_type):
    """ذخیره پروکسی‌ها در فایل توی پوشه فعلی"""
    filename = f"./{proxy_type.lower()}.txt"
    try:
        unique_proxies = list(set(proxy[0] for proxy in proxies))
        with open(filename, 'w', encoding='utf-8') as file:
            if unique_proxies:
                for proxy in unique_proxies:
                    file.write(proxy + '\n')
            else:
                file.write('')
                logging.warning(f"No proxies to save for {proxy_type} in {filename}")
        logging.info(f"Saved {len(unique_proxies)} unique {proxy_type} proxies to {filename}")
        if os.path.exists(filename):
            logging.info(f"Confirmed: {filename} exists in the current directory")
        else:
            logging.error(f"Failed: {filename} was not created")
        return proxies
    except IOError as e:
        logging.error(f"Error writing to {filename}: {e}")
        return []

def update_readme(proxy_dict):
    """بروزرسانی README با جدول‌های زیبا برای هر نوع پروکسی"""
    try:
        utc_now = datetime.now(pytz.UTC)
        iran_tz = pytz.timezone('Asia/Tehran')
        iran_now = utc_now.astimezone(iran_tz)
        jalali_date = jdatetime.datetime.fromgregorian(datetime=iran_now)
        update_time_iran = jalali_date.strftime('%H:%M %d-%m-%Y')
        logging.info(f"Updating README with Iranian timestamp: {update_time_iran}")

        table_rows = ""
        for proxy_type, proxies in proxy_dict.items():
            table_rows += f"\n### 🔗 {proxy_type} Proxies\n"
            if proxy_type == 'MTPROTO':
                table_rows += "| # | سرور (Server) | پورت (Port) | وضعیت |\n"
                table_rows += "|---|---------------|-------------|-------|\n"
            else:
                table_rows += "| # | سرور (Server) | پورت (Port) | پینگ (Ping) | وضعیت |\n"
                table_rows += "|---|---------------|-------------|-------------|-------|\n"
            sample_proxies = random.sample(proxies, min(5, len(proxies))) if proxies else []
            if not sample_proxies:
                table_rows += f"| - | - | - | بدون پروکسی فعال |\n"
            for i, (proxy, ping) in enumerate(sample_proxies, 1):
                if proxy_type == 'MTPROTO':
                    match = re.match(r'^tg://proxy\?server=([^&]+)&port=(\d+)&secret=([^\s]+)$', proxy)
                    if match:
                        server, port, _ = match.groups()
                        table_rows += f"| {i} | `{server}` | `{port}` | ✅ فعال |\n"
                else:
                    server, port = proxy.split(':')
                    table_rows += f"| {i} | `{server}` | `{port}` | {ping:.2f}ms | ✅ فعال |\n"

        readme_content = f"""# 📊 استخراج پروکسی‌ها (آخرین بروزرسانی: {update_time_iran})

این پروژه یک اسکریپت پایتون برای جمع‌آوری پروکسی‌های SOCKS، SOCKS5، SOCKS4، HTTPS و MTPROTO از منابع متنی و JSON است. پروکسی‌ها در فایل‌های جداگانه (`socks.txt`, `socks5.txt`, `socks4.txt`, `https.txt`, `mtproto.txt`) ذخیره می‌شوند.

## ✨ درباره پروژه
این اسکریپت پروکسی‌های SOCKS، SOCKS5، SOCKS4، HTTPS و MTPROTO را از لینک‌های متنی و JSON (مانند مخازن گیت‌هاب) جمع‌آوری کرده و پس از بررسی وضعیت آنلاین بودن (و پینگ برای غیر MTPROTO)، در فایل‌های مربوطه ذخیره می‌کند.

## 🚀 ویژگی‌ها
- 🌐 جمع‌آوری پروکسی از منابع متنی و JSON
- 🗑 حذف پروکسی‌های تکراری
- 📊 اندازه‌گیری پینگ پروکسی‌ها (برای SOCKS، SOCKS5، SOCKS4، HTTPS)
- 📝 ذخیره در فایل‌های جداگانه برای هر نوع پروکسی

## 📋 پیش‌نیازها
- 🐍 پایتون 3.9
- 📦 کتابخانه‌های مورد نیاز: `requests`, `pytz`, `jdatetime`, `json`
- نصب وابستگی‌ها با: `pip install -r requirements.txt`

## 🛠 نحوه استفاده
1. فایل‌های پروکسی (`socks.txt`, `socks5.txt`, `socks4.txt`, `https.txt`, `mtproto.txt`) را از پوشه پروژه دانلود کنید.
2. از پروکسی‌ها در ابزارها یا کلاینت‌های خود (مانند تلگرام برای MTPROTO) استفاده کنید.

## 🌍 منابع پروکسی
- [openproxylist](https://github.com/roosterkid/openproxylist)
- [KangProxy](https://github.com/officialputuid/KangProxy)
- [Proxifly](https://github.com/proxifly/free-proxy-list)
- [hookzof/socks5_list](https://github.com/hookzof/socks5_list)
- [TheSpeedX/PROXY-List](https://github.com/TheSpeedX/PROXY-List)
- [fyvri/fresh-proxy-list](https://github.com/fyvri/fresh-proxy-list)
- [jetkai/proxy-list](https://github.com/jetkai/proxy-list)
- [proxyscrape](https://proxyscrape.com)
- [MahsaNetConfigTopic/proxy](https://github.com/MahsaNetConfigTopic/proxy)
- [SoliSpirit/mtproto](https://github.com/SoliSpirit/mtproto)

## 📈 نمونه پروکسی‌ها
جدول‌های زیر نمونه‌ای از پروکسی‌های فعال را با پینگ آن‌ها (برای غیر MTPROTO) نمایش می‌دهند:

{table_rows}

> **💡 نکته**: برای دسترسی به لیست کامل و به‌روز، فایل‌های مربوطه را دانلود کنید. برای اضافه کردن لینک‌های پروکسی، فایل README را به‌صورت دستی ویرایش کنید.

## 📜 لایسنس
این پروژه تحت [لایسنس MIT] منتشر شده است.
"""

        filename = "./README.md"
        try:
            with open(filename, 'w', encoding='utf-8') as file:
                file.write(readme_content)
            logging.info(f"Successfully updated {filename}")
            if os.path.exists(filename):
                logging.info(f"Confirmed: {filename} exists in the current directory")
            else:
                logging.error(f"Failed: {filename} was not created")
        except Exception as e:
            logging.error(f"Error updating {filename}: {e}")

if __name__ == "__main__":
    proxy_urls = {
        'SOCKS': [
            "https://raw.githubusercontent.com/hookzof/socks5_list/master/tg/socks.json",
            "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt",
            "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks4.txt",
            "https://raw.githubusercontent.com/fyvri/fresh-proxy-list/main/proxies/socks5.txt",
            "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-socks5.txt",
            "https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies&proxytype=socks5"
        ],
        'SOCKS5': [
            "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS5_RAW.txt",
            "https://raw.githubusercontent.com/officialputuid/KangProxy/KangProxy/socks5/socks5.txt",
            "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks5/data.txt",
            "https://raw.githubusercontent.com/hookzof/socks5_list/refs/heads/master/proxy.txt"
        ],
        'SOCKS4': [
            "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS4_RAW.txt",
            "https://raw.githubusercontent.com/officialputuid/KangProxy/KangProxy/socks4/socks4.txt",
            "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks4/data.txt",
        ],
        'HTTPS': [
            "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt",
            "https://raw.githubusercontent.com/officialputuid/KangProxy/KangProxy/https/https.txt",
            "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/http/data.txt",
        ],
        'MTPROTO': [
            "https://raw.githubusercontent.com/MahsaNetConfigTopic/proxy/main/proxies.txt",
            "https://raw.githubusercontent.com/SoliSpirit/mtproto/master/all_proxies.txt"
        ]
    }

    proxy_dict = {}
    for proxy_type, urls in proxy_urls.items():
        all_proxies = []
        for url in urls:
            proxies = fetch_proxies_from_url(url, proxy_type)
            all_proxies.extend(proxies)
        proxy_dict[proxy_type] = all_proxies
        save_proxies_to_file(all_proxies, proxy_type)

    update_readme(proxy_dict)
