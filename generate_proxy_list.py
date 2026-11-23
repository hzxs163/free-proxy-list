#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抓取代理列表 -> proxy.txt

设计目标：让 GitHub Actions 每天稳定跑下去，不因源站偶发问题把链路打断。

要点：
1. 账号/地址优先从环境变量读取（GitHub Secrets），缺省回落到内置值，
   原有配置保持不变也能工作。
2. 登录与抓取都带重试 + 退避，遇到 429/5xx/网络抖动自动重试。
3. 只有成功解析到代理，才覆盖 proxy.txt；失败时保留上一次的有效数据。
4. 每次运行都写 last_run.txt 心跳文件（状态/数量/原因/时间），
   这样即使抓取失败也会有提交，仓库保持活跃，
   GitHub 不会因为"仓库 60 天无活动"而自动停用定时任务。
5. 任何异常都不抛出到外层，脚本始终以 0 退出，失败信息写进 last_run.txt，
   由工作流决定是否开 Issue 提醒。
"""

import os
import re
import sys
import time
import random
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup

# 保证在任意终端编码（如 Windows GBK）下都不会因为输出字符崩掉
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:  # noqa: BLE001
        pass

BEIJING_TZ = timezone(timedelta(hours=8))

BASE_URL = (os.environ.get('PROXY_BASE_URL') or 'https://proxy-socks5.com').strip().rstrip('/')
USERNAME = (os.environ.get('PROXY_USERNAME') or 'hzxs55555').strip()
PASSWORD = (os.environ.get('PROXY_PASSWORD') or 'hzxs55555').strip()
LOGIN_URL = f'{BASE_URL}/login'
PROXY_URL = f'{BASE_URL}/proxy_list'

OUTPUT_FILE = 'proxy.txt'
HEARTBEAT_FILE = 'last_run.txt'

USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
)

# 命中这些特征说明拿到的是风控/地区限制页，而不是正常页面
BLOCK_MARKERS = ('访问受限', '地区暂不支持', 'Just a moment', 'Attention Required', 'cf-error-details')

IP_RE = re.compile(r'(\d{1,3}(?:\.\d{1,3}){3})(?::(\d{1,5}))?')

HTTP_READY = (200, 301, 302, 303, 307, 308)


def log(msg):
    print(msg, flush=True)


def now_beijing():
    return datetime.now(BEIJING_TZ)


class ProxyListScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
        })
        self.errors = []

    # ---------- 基础请求：带重试 ----------
    def request(self, method, url, tries=3, **kwargs):
        kwargs.setdefault('timeout', 30)
        last_exc = None
        for attempt in range(1, tries + 1):
            try:
                resp = self.session.request(method, url, **kwargs)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < tries:
                    wait = min(2 ** attempt + random.random() * 2, 20)
                    log(f'  ↻ {url} 返回 {resp.status_code}，{wait:.1f}s 后重试（{attempt}/{tries}）')
                    time.sleep(wait)
                    continue
                return resp
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < tries:
                    wait = min(2 ** attempt + random.random() * 2, 20)
                    log(f'  ↻ 请求异常: {exc}，{wait:.1f}s 后重试（{attempt}/{tries}）')
                    time.sleep(wait)
        if last_exc:
            raise last_exc
        return None

    @staticmethod
    def is_blocked(resp):
        if resp is None:
            return False
        text = resp.text or ''
        if resp.status_code == 403 and any(m in text for m in BLOCK_MARKERS):
            return True
        return any(m in text for m in BLOCK_MARKERS)

    # ---------- 登录 ----------
    def login(self):
        for attempt in range(1, 4):
            try:
                log(f'正在登录: {LOGIN_URL}')
                resp = self.request(
                    'POST', LOGIN_URL,
                    data={'username': USERNAME, 'password': PASSWORD},
                    allow_redirects=True,
                )
                if resp is None:
                    self.errors.append('登录无响应')
                    continue
                if self.is_blocked(resp):
                    snippet = re.sub(r'\s+', ' ', BeautifulSoup(resp.text, 'html.parser').get_text(' ')).strip()[:160]
                    self.errors.append(f'登录页被拦截(HTTP {resp.status_code})：{snippet}')
                    log('  ⚠ 登录页返回限制页，稍后重试')
                    time.sleep(10 * attempt)
                    continue

                body = resp.text or ''
                low = body.lower()
                if ('登录' in body and 'logout' not in low and '退出' not in body
                        and '退出登录' not in body):
                    self.errors.append('登录失败：账号或密码可能已失效')
                    log('  ⚠ 登录失败，检查账号密码')
                    return False

                log('✅ 登录成功')
                return True

            except Exception as exc:  # noqa: BLE001
                self.errors.append(f'登录请求异常: {exc}')
                log(f'  ⚠ 登录异常: {exc}')
                time.sleep(5 * attempt)
        return False

    # ---------- 抓取 ----------
    def scrape(self):
        try:
            log(f'正在抓取代理列表: {PROXY_URL}')
            resp = self.request('GET', PROXY_URL)
            if resp is None:
                self.errors.append('抓取无响应')
                return []
            if self.is_blocked(resp):
                snippet = re.sub(r'\s+', ' ', BeautifulSoup(resp.text, 'html.parser').get_text(' ')).strip()[:160]
                self.errors.append(f'抓取页被拦截(HTTP {resp.status_code})：{snippet}')
                return []
            if resp.status_code not in HTTP_READY:
                self.errors.append(f'抓取失败：HTTP {resp.status_code}')
                return []

            resp.encoding = resp.apparent_encoding or 'utf-8'
            proxies, masked, has_table = self.parse_page(resp.text)
            if not has_table:
                self.errors.append('页面中没有找到数据表格（页面结构可能已变化）')
                return []
            if masked:
                self.errors.append(f'有 {masked} 条 IP 被脱敏（可能未真正登录）')
            log(f'成功抓取到 {len(proxies)} 个代理')
            return proxies

        except Exception as exc:  # noqa: BLE001
            self.errors.append(f'抓取异常: {exc}')
            log(f'  ⚠ 抓取异常: {exc}')
            return []

    # ---------- 解析 ----------
    @staticmethod
    def parse_page(html):
        """把代理页面 HTML 解析成 [(protocol, ip, port, location)]。

        返回 (proxies, masked_count, has_table)。
        """
        soup = BeautifulSoup(html or '', 'html.parser')
        table = soup.find('table')
        if not table:
            return [], 0, False

        proxies, masked, seen = [], 0, set()
        for row in table.find_all('tr')[1:]:
            cells = row.find_all('td')
            if len(cells) < 3:
                continue

            first_text = cells[0].get_text(strip=True)
            protocol = first_text.split()[0].lower() if first_text else ''
            ip_raw = cells[1].get_text(' ', strip=True)
            port = cells[2].get_text(strip=True)
            location = cells[3].get_text(' ', strip=True) if len(cells) > 3 else '未知'

            # 清理位置字段里的按钮文字
            location = location.replace('已复制', '').replace('复制', '')
            location = ' '.join(location.split()).rstrip('已').strip()

            # IP 里可能混入 "ip:port"；被脱敏的（如 115.79.X.22）记为 masked 后跳过
            match = IP_RE.search(ip_raw)
            if match:
                ip = match.group(1)
                if match.group(2):
                    port = match.group(2)
            else:
                if re.search(r'\d{1,3}\.\d{1,3}\.[^\s:.]+\.[\dXx]+', ip_raw):
                    masked += 1
                continue

            port = re.sub(r'\D', '', port)[:5]
            if not protocol or not port:
                continue

            key = (protocol, ip, port)
            if key in seen:
                continue
            seen.add(key)

            proxies.append({
                'protocol': protocol,
                'ip': ip,
                'port': port,
                'location': location or '未知',
            })

        return proxies, masked, True

    # ---------- 保存 ----------
    @staticmethod
    def save_to_file(proxies, filename=OUTPUT_FILE):
        try:
            now = now_beijing()
            time_str = now.strftime('%m-%d %H:%M')
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"# 代理列表更新时间: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# 总计: {len(proxies)} 个代理\n")
                f.write("# 实时抓取于免费公共代理池: https://proxy-socks5.com\n")
                f.write("# 最好用的代理资源\n\n")
                for p in proxies:
                    f.write(
                        f"{p['protocol']}://{p['ip']}:{p['port']}"
                        f"        入库时间：{time_str}\t{p['location']}\n"
                    )
            log(f'代理列表已保存到 {filename}')
            return True
        except Exception as exc:  # noqa: BLE001
            log(f'保存文件错误: {exc}')
            return False


def write_heartbeat(status, count, reason, elapsed, masked=0):
    """每次运行都写心跳文件，保证仓库有提交、定时任务不被 GitHub 自动停用。"""
    now = now_beijing()
    utc = datetime.now(timezone.utc)
    reason = re.sub(r'\s+', ' ', (reason or '')).strip()[:500]
    lines = [
        f"time_beijing={now.strftime('%Y-%m-%d %H:%M:%S')}",
        f"time_utc={utc.strftime('%Y-%m-%d %H:%M:%S')}",
        f"status={status}",
        f"count={count}",
        f"masked={masked}",
        f"elapsed={elapsed:.1f}s",
        f"source={PROXY_URL}",
        f"runner={os.environ.get('RUNNER_NAME', '')}",
        f"reason={reason}",
    ]
    try:
        with open(HEARTBEAT_FILE, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        log('心跳文件已写入 last_run.txt')
    except Exception as exc:  # noqa: BLE001
        log(f'写入心跳文件失败: {exc}')


def join_errors(errors):
    """去重后拼接错误信息，避免同一个限制页重复三遍。"""
    uniq = []
    for e in errors:
        e = re.sub(r'\s+', ' ', e or '').strip()
        if e and e not in uniq:
            uniq.append(e)
    return '; '.join(uniq)[:300]


def main():
    started = time.time()
    log(f'=== 代理列表抓取开始 {now_beijing().strftime("%Y-%m-%d %H:%M:%S")} ===')
    log(f'数据源: {BASE_URL}')

    status, count, reason = 'FAILED', 0, ''
    scraper = ProxyListScraper()

    try:
        if not scraper.login():
            reason = join_errors(scraper.errors) or '登录失败'
        else:
            proxies = scraper.scrape()
            if proxies:
                if scraper.save_to_file(proxies):
                    status, count = 'OK', len(proxies)
                    if scraper.errors:
                        log('提示: ' + join_errors(scraper.errors))
                else:
                    reason = '保存文件失败'
            else:
                reason = join_errors(scraper.errors) or '未获取到代理数据'
    except Exception as exc:  # noqa: BLE001
        reason = f'未捕获异常: {exc}'
        log(f'  ⚠ {reason}')

    elapsed = time.time() - started
    if status == 'OK':
        log(f'✅ 完成，共 {count} 个代理，用时 {elapsed:.1f}s')
    else:
        log(f'❌ 本次未更新（保留上次数据），原因: {reason}')

    write_heartbeat(status, count, reason, elapsed)
    return 0


if __name__ == '__main__':
    sys.exit(main())
