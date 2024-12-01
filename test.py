import requests
from bs4 import BeautifulSoup

# 设置请求头以模拟浏览器
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

url = "https://blog.byer.top/atom.xml"  # 替换为你访问的实际URL
response = requests.get(url, headers=headers)

# 检查是否成功获取页面
if response.status_code == 200:
    soup = BeautifulSoup(response.text, 'html.parser')
    print(soup.prettify())  # 打印页面内容
else:
    print("无法获取页面，HTTP状态码:", response.status_code)
