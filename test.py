import subprocess

curl_command = [
    "curl", "-v", "-A", "Mozilla/5.0 (Windows; U; Windows NT 6.1; en-us) AppleWebKit/534.50 (KHTML, like Gecko) Version/5.1 Safari/534.50", 
    "https://qcqx.cn/atom.xml"
]

try:
    result = subprocess.run(curl_command, capture_output=True, text=True, check=True)
    print(result.stdout)
except subprocess.CalledProcessError as e:
    print(f"Error occurred while calling curl: {e}")
