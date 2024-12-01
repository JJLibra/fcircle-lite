import requests

headers = {
    "User-Agent": "Mozilla/5.0 (Windows; U; Windows NT 6.1; en-us) AppleWebKit/534.50 (KHTML, like Gecko) Version/5.1 Safari/534.50"
}
response = requests.get("https://blog.byer.top/atom.xml", headers=headers)
print(response.text)
