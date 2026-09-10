#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta


class ProxyListScraper:
    def __init__(self):
        self.url = "https://proxy-socks5.com/proxy_list"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

    def scrape_proxy_list(self):
        """抓取代理列表"""
        try:
            print(f"正在抓取代理列表: {self.url}")
            response = requests.get(self.url, headers=self.headers, timeout=30)
            response.raise_for_status()
            response.encoding = 'utf-8'

            soup = BeautifulSoup(response.text, 'html.parser')

            table = soup.find('table')
            if not table:
                print("未找到代理数据表格")
                return []

            proxies = []
            rows = table.find_all('tr')[1:]

            for row in rows:
                cells = row.find_all('td')
                if len(cells) >= 4:
                    protocol = cells[0].text.strip()
                    ip = cells[1].text.strip()
                    port = cells[2].text.strip()
                    location = cells[3].text.strip() if len(cells) > 3 else "未知"

                    # 清理位置信息
                    location = location.replace('复制', '').replace('已复制', '').replace('已', '').strip()
                    location = ' '.join(location.split())

                    # 清理 protocol
                    protocol = protocol.split()[0] if protocol else ''

                    # 清理 IP 和端口
                    if ' ' in ip:
                        ip = ip.split()[-1]
                    if ':' in ip:
                        parts = ip.rsplit(':', 2)
                        if len(parts) == 3:
                            ip = parts[0]
                            port = parts[1]
                        elif len(parts) == 2:
                            ip = parts[0]
                            port = parts[1]

                    port = port.split(':')[0] if ':' in port else port

                    if protocol and ip and port:
                        proxies.append({
                            'protocol': protocol,
                            'ip': ip,
                            'port': port,
                            'location': location
                        })

            print(f"成功抓取到 {len(proxies)} 个代理")
            return proxies

        except requests.RequestException as e:
            print(f"网络请求错误: {e}")
            return []
        except Exception as e:
            print(f"抓取错误: {e}")
            return []

    def save_to_file(self, proxies, filename='proxy.txt'):
        """保存代理列表到文件"""
        try:
            # 北京时间
            beijing_tz = timezone(timedelta(hours=8))
            now = datetime.now(beijing_tz)
            time_str = now.strftime('%m-%d %H:%M')

            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"# 代理列表更新时间: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# 总计: {len(proxies)} 个代理\n")
                f.write(f"# 实时抓取于免费公共代理池: https://proxy-socks5.com\n")
                f.write(f"# 最好用的代理资源\n\n")

                for p in proxies:
                    # 格式：协议://ip:port        入库时间：XX-XX XX:XX	[位置]
                    line = f"{p['protocol']}://{p['ip']}:{p['port']}        入库时间：{time_str}\t{p['location']}"
                    f.write(f"{line}\n")

            print(f"代理列表已保存到 {filename}")
            return True

        except Exception as e:
            print(f"保存文件错误: {e}")
            return False


def main():
    scraper = ProxyListScraper()
    proxies = scraper.scrape_proxy_list()

    if proxies:
        scraper.save_to_file(proxies)
        print("代理列表抓取完成！")
    else:
        print("未能获取到代理数据")


if __name__ == "__main__":
    main()
