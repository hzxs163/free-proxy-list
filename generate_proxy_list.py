#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
from bs4 import BeautifulSoup
from datetime import datetime

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

            # 查找包含代理数据的表格
            table = soup.find('table')
            if not table:
                print("未找到代理数据表格")
                return []

            proxies = []
            rows = table.find_all('tr')[1:]  # 跳过表头

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

                    # 清理 protocol（去掉多余内容）
                    protocol = protocol.split()[0] if protocol else ''

                    # 清理 IP 和端口（处理 "socks5 171.252.X.168:1080:1080" 这种格式）
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

                    # 清理端口（去掉重复）
                    port = port.split(':')[0] if ':' in port else port

                    if protocol and ip and port:
                        proxy = f"{protocol}://{ip}:{port} [{location}]"
                        proxies.append(proxy)

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
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"# 代理列表更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# 总计: {len(proxies)} 个代理\n\n")
                for proxy in proxies:
                    f.write(f"{proxy}\n")

            print(f"代理列表已保存到 {filename}")
            return True

        except Exception as e:
            print(f"保存文件错误: {e}")
            return False


def main():
    """主函数"""
    scraper = ProxyListScraper()
    proxies = scraper.scrape_proxy_list()

    if proxies:
        scraper.save_to_file(proxies)
        print("代理列表抓取完成！")
    else:
        print("未能获取到代理数据")


if __name__ == "__main__":
    main()
