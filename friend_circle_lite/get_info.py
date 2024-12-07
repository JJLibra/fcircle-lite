import logging
from datetime import datetime, timedelta, timezone
from dateutil import parser
import requests
import re
import feedparser
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup

# 标准化的请求头
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

timeout = (10, 15) # 连接超时和读取超时，防止requests接受时间过长

def format_published_time(time_str):
    """
    格式化发布时间为统一格式 YYYY-MM-DD HH:MM

    参数:
    time_str (str): 输入的时间字符串，可能是多种格式。

    返回:
    str: 格式化后的时间字符串，若解析失败返回空字符串。
    """
    # 尝试自动解析输入时间字符串
    try:
        parsed_time = parser.parse(time_str, fuzzy=True)
    except (ValueError, parser.ParserError):
        # 定义支持的时间格式
        time_formats = [
            '%a, %d %b %Y %H:%M:%S %z',  # Mon, 11 Mar 2024 14:08:32 +0000
            '%a, %d %b %Y %H:%M:%S GMT',   # Wed, 19 Jun 2024 09:43:53 GMT
            '%Y-%m-%dT%H:%M:%S%z',         # 2024-03-11T14:08:32+00:00
            '%Y-%m-%dT%H:%M:%SZ',          # 2024-03-11T14:08:32Z
            '%Y-%m-%d %H:%M:%S',           # 2024-03-11 14:08:32
            '%Y-%m-%d'                     # 2024-03-11
        ]
        for fmt in time_formats:
            try:
                parsed_time = datetime.strptime(time_str, fmt)
                break
            except ValueError:
                continue
        else:
            logging.warning(f"无法解析时间字符串：{time_str}")
            return ''

    # 处理时区转换
    if parsed_time.tzinfo is None:
        parsed_time = parsed_time.replace(tzinfo=timezone.utc)
    shanghai_time = parsed_time.astimezone(timezone(timedelta(hours=8)))
    return shanghai_time.strftime('%Y-%m-%d %H:%M')

def check_feed(blog_url, session):
    """
    检查博客的 RSS 或 Atom 订阅链接。

    此函数接受一个博客地址，尝试在其后拼接常见的 RSS 路径，并检查这些链接是否可访问。
    如果都不可访问，则尝试解析网页，自动发现 RSS 链接。

    参数：
    blog_url (str): 博客的基础 URL。
    session (requests.Session): 用于请求的会话对象。

    返回：
    list: 包含类型和拼接后的链接的列表。如果找到有效的 RSS 链接，返回 ['feed_type', feed_url]；
            否则返回 ['none', blog_url]。
    """
    possible_feeds = [
        ('atom', '/atom.xml'),
        ('rss', '/rss.xml'), # 2024-07-26 添加 /rss.xml内容的支持
        ('rss2', '/rss2.xml'),
        ('feed', '/feed'),
        ('feed2', '/feed.xml'), # 2024-07-26 添加 /feed.xml内容的支持
        ('feed3', '/feed/'),
        ('index', '/index.xml') # 2024-07-25 添加 /index.xml内容的支持
    ]

    for feed_type, path in possible_feeds:
        feed_url = blog_url.rstrip('/') + path
        try:
            response = session.get(feed_url, headers=headers, timeout=timeout)
            if response.status_code == 200 and ('<rss' in response.text or '<feed' in response.text):
                return [feed_type, feed_url]
        except requests.RequestException:
            continue

    # 自动发现 RSS 链接
    try:
        response = session.get(blog_url, headers=headers, timeout=timeout)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            links = soup.find_all('link', rel='alternate')
            for link in links:
                type_attr = link.get('type', '')
                if 'rss' in type_attr or 'atom' in type_attr:
                    href = link.get('href', '')
                    if not href.startswith('http'):
                        href = blog_url.rstrip('/') + '/' + href.lstrip('/')
                    return ['auto', href]
    except requests.RequestException:
        pass

    logging.warning(f"无法找到 {blog_url} 的订阅链接")
    return ['none', blog_url]


def is_bad_link(link):
    """
    判断链接是否是IP地址+端口、localhost+端口或缺少域名的链接

    参数：
    link (str): 要检查的链接

    返回：
    bool: 如果是IP地址+端口、localhost+端口或缺少域名，返回True；否则返回False
    """
    if '://' not in link:
        return True  # 缺少协议的链接视为坏链接

    protocol_end = link.find('://')
    link = link[protocol_end + 3:]  # 去掉协议部分

    if '/' in link:
        host = link.split('/')[0]
    else:
        host = link

    if host in ['localhost', '::1', '127.0.0.1']:
        return True

    ipv4_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if re.match(ipv4_pattern, host):
        return True

    # 检查IPv6地址（不完善）
    if host.startswith('[') and host.endswith(']'):
        return True

    if not host:
        return True

    return False

def ensure_https(url):
    """
    确保链接使用 https 协议

    参数：
    url (str): 原始链接

    返回：
    str: 使用 https 协议的链接
    """
    if url.startswith('http://'):
        return 'https://' + url[7:]
    elif url.startswith('https://'):
        return url
    else:
        return 'https://' + url

def replace_non_domain(link, blog_url):
    """
    修复链接，将IP地址、localhost或缺少域名的链接替换为blog_url的域名，并确保使用HTTPS

    参数：
    link (str): 原始链接
    blog_url (str): 博客的URL

    返回：
    str: 修复后的链接
    """
    if not link or not blog_url:
        return link

    protocol_end = blog_url.find('://')
    blog_domain = blog_url[protocol_end + 3:] if protocol_end != -1 else blog_url
    blog_domain = blog_domain.split('/')[0]

    if '://' not in link:
        link = 'http://' + link
    protocol_end = link.find('://')
    link_domain = link[protocol_end + 3:] if protocol_end != -1 else link
    link_domain = link_domain.split('/')[0]

    # http -> https
    if link.startswith('http://'):
        link = 'https://' + link[7:]

    if is_bad_link(link):
        link = link.replace(link_domain, blog_domain)
        link = 'https://' + link.split('://')[1]  # https

    return link

import cloudscraper

def parse_feed(url, session, count=5, blog_url=None):
    """
    解析 Atom 或 RSS2 feed 并返回包含网站名称、作者、原链接和每篇文章详细内容的字典。

    此函数接受一个 feed 的地址（atom.xml 或 rss2.xml），解析其中的数据，并返回一个字典结构，
    其中包括网站名称、作者、原链接和每篇文章的详细内容。

    参数：
    url (str): Atom 或 RSS2 feed 的 URL。
    session (requests.Session): 用于请求的会话对象。
    count (int): 获取文章数的最大数。如果小于则全部获取，如果文章数大于则只取前 count 篇文章。

    返回：
    dict: 包含网站名称、作者、原链接和每篇文章详细内容的字典。
    """
    try:
        scraper = cloudscraper.create_scraper()  # cloudscraper：cloudflare反爬
        response = scraper.get(url, headers=headers, timeout=timeout)
        response.encoding = 'utf-8'
        feed = feedparser.parse(response.text, sanitize_html=True)
        
        if feed.bozo:
            logging.error(f"解析 RSS 源时出现错误：{feed.bozo_exception}")
            return {
                'website_name': '',
                'author': '',
                'link': '',
                'articles': []
            }

        result = {
            'website_name': feed.feed.title if 'title' in feed.feed else '',
            'author': feed.feed.author if 'author' in feed.feed else '',
            'link': feed.feed.link if 'link' in feed.feed else '',
            'articles': []
        }
        
        for entry in feed.entries:
            if 'published' in entry:
                published = format_published_time(entry.published)
            elif 'updated' in entry:
                published = format_published_time(entry.updated)
                # 输出警告信息
                logging.warning(f"文章 {entry.title} 未包含发布时间，已使用更新时间 {published}")
            else:
                published = ''
                logging.warning(f"文章 {entry.title} 未包含任何时间信息, 请检查原文, 设置为默认时间")
            entry_link = entry.link if 'link' in entry else ''
            article_link = replace_non_domain(entry_link, blog_url)
            article = {
                'title': entry.title if 'title' in entry else '',
                'author': result['author'],
                'link': article_link,
                'published': published,
                'summary': entry.summary if 'summary' in entry else '',
                'content': entry.content[0].value if 'content' in entry and entry.content else entry.description if 'description' in entry else ''
            }
            result['articles'].append(article)
        
        result['articles'] = sorted(result['articles'], key=lambda x: datetime.strptime(x['published'], '%Y-%m-%d %H:%M') if x['published'] else datetime.min, reverse=True)
        if count < len(result['articles']):
            result['articles'] = result['articles'][:count]
        
        return result
    except Exception as e:
        logging.error(f"无法解析FEED地址：{url} ，请自行排查原因！")
        return {
            'website_name': '',
            'author': '',
            'link': '',
            'articles': []
        }

def process_friend(friend, session, count, specific_RSS=[]):
    """
    处理单个朋友的博客信息。

    参数：
    friend (list): 包含朋友信息的列表 [name, blog_url, avatar]。
    session (requests.Session): 用于请求的会话对象。
    count (int): 获取每个博客的最大文章数。
    specific_RSS (list): 包含特定 RSS 源的字典列表 [{name, url}]

    返回：
    dict: 包含朋友博客信息的字典。
    """
    name, blog_url, avatar = friend
    
    # 如果 specific_RSS 中有对应的 name，则直接返回 feed_url
    if specific_RSS is None:
        specific_RSS = []
    rss_feed = next((rss['url'] for rss in specific_RSS if rss['name'] == name), None)
    if rss_feed:
        feed_url = rss_feed
        feed_type = 'specific'
        logging.info(f"“{name}”的博客“ {blog_url} ”为特定RSS源“ {feed_url} ”")
    else:
        feed_type, feed_url = check_feed(blog_url, session)
        logging.info(f"“{name}”的博客“ {blog_url} ”的feed类型为“{feed_type}”, feed地址为“ {feed_url} ”")

    if feed_type != 'none':
        feed_info = parse_feed(feed_url, session, count, blog_url)
        articles = [
            {
                'title': article['title'],
                'created': article['published'],
                'link': article['link'],
                'author': name,
                'avatar': avatar
            }
            for article in feed_info['articles']
        ]
        
        for article in articles:
            logging.info(f"{name} 发布了新文章：{article['title']}，时间：{article['created']}，链接：{article['link']}")
        
        return {
            'name': name,
            'status': 'active',
            'articles': articles
        }
    else:
        logging.warning(f"{name} 的博客 {blog_url} 无法访问")
        return {
            'name': name,
            'status': 'error',
            'articles': []
        }

def fetch_and_process_data(json_url, specific_RSS=[], count=5):
    """
    读取 JSON 数据并处理订阅信息，返回统计数据和文章信息。

    参数：
    json_url (str): 包含朋友信息的 JSON 文件的 URL。
    count (int): 获取每个博客的最大文章数。
    specific_RSS (list): 包含特定 RSS 源的字典列表 [{name, url}]

    返回：
    dict: 包含统计数据和文章信息的字典。
    """
    session = requests.Session()
    
    try:
        response = session.get(json_url, headers=headers, timeout=timeout)
        friends_data = response.json()
    except Exception as e:
        logging.error(f"无法获取链接：{json_url} ：{e}", exc_info=True)
        return None

    total_friends = len(friends_data['friends'])
    active_friends = 0
    error_friends = 0
    total_articles = 0
    article_data = []
    error_friends_info = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_friend = {
            executor.submit(process_friend, [friend['name'], friend['url'], friend['avatar']], session, count, specific_RSS): friend
            for friend in friends_data['friends']
        }
        
        for future in as_completed(future_to_friend):
            friend = future_to_friend[future]
            try:
                result = future.result()
                if result['status'] == 'active':
                    active_friends += 1
                    article_data.extend(result['articles'])
                    total_articles += len(result['articles'])
                else:
                    error_friends += 1
                    error_friends_info.append([friend['name'], friend['url'], friend['avatar']])
            except Exception as e:
                logging.error(f"处理 {friend['name']} 时发生错误: {e}", exc_info=True)
                error_friends += 1
                error_friends_info.append([friend['name'], friend['url'], friend['avatar']])

    result = {
        'statistical_data': {
            'friends_num': total_friends,
            'active_num': active_friends,
            'error_num': error_friends,
            'article_num': total_articles,
            'last_updated_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        },
        'article_data': article_data
    }
    
    logging.info(f"数据处理完成，总共有 {total_friends} 位朋友，其中 {active_friends} 位博客可访问，{error_friends} 位博客无法访问")

    return result, error_friends_info

def sort_articles_by_time(data):
    """
    对文章数据按时间排序

    参数：
    data (dict): 包含文章信息的字典

    返回：
    dict: 按时间排序后的文章信息字典
    """
    # 先确保每个元素存在时间
    for article in data['article_data']:
        if article['created'] == '' or article['created'] == None:
            article['created'] = '2024-01-01 00:00'
            # 输出警告信息
            logging.warning(f"文章 {article['title']} 未包含时间信息，已设置为默认时间 2024-01-01 00:00")
    
    if 'article_data' in data:
        sorted_articles = sorted(
            data['article_data'],
            key=lambda x: datetime.strptime(x['created'], '%Y-%m-%d %H:%M'),
            reverse=True
        )
        data['article_data'] = sorted_articles
    return data

def marge_data_from_json_url(data, marge_json_url):
    """
    从另一个 JSON 文件中获取数据并合并到原数据中。

    参数：
    data (dict): 包含文章信息的字典
    marge_json_url (str): 包含另一个文章信息的 JSON 文件的 URL。

    返回：
    dict: 合并后的文章信息字典，已去重处理
    """
    try:
        response = requests.get(marge_json_url, headers=headers, timeout=timeout)
        marge_data = response.json()
    except Exception as e:
        logging.error(f"无法获取链接：{marge_json_url}，出现的问题为：{e}", exc_info=True)
        return data
    
    if 'article_data' in marge_data:
        logging.info(f"开始合并数据，原数据共有 {len(data['article_data'])} 篇文章，第三方数据共有 {len(marge_data['article_data'])} 篇文章")
        data['article_data'].extend(marge_data['article_data'])
        data['article_data'] = list({v['link']:v for v in data['article_data']}.values())
        logging.info(f"合并数据完成，现在共有 {len(data['article_data'])} 篇文章")
    return data

def marge_errors_from_json_url(errors, marge_json_url):
    """
    从另一个网络 JSON 文件中获取错误信息并遍历，删除在errors中，
    不存在于marge_errors中的友链信息。

    参数：
    errors (list): 包含错误信息的列表
    marge_json_url (str): 包含另一个错误信息的 JSON 文件的 URL。

    返回：
    list: 合并后的错误信息列表
    """
    try:
        response = requests.get(marge_json_url, timeout=10)  # 设置请求超时时间
        marge_errors = response.json()
    except Exception as e:
        logging.error(f"无法获取链接：{marge_json_url}，出现的问题为：{e}", exc_info=True)
        return errors

    # 提取 marge_errors 中的 URL
    marge_urls = {item[1] for item in marge_errors}

    # 使用过滤器保留 errors 中在 marge_errors 中出现的 URL
    filtered_errors = [error for error in errors if error[1] in marge_urls]

    logging.info(f"合并错误信息完成，合并后共有 {len(filtered_errors)} 位朋友")
    return filtered_errors

def deal_with_large_data(result):
    """
    处理文章数据，保留前150篇及其作者在后续文章中的出现。
    
    参数：
    result (dict): 包含统计数据和文章数据的字典。
    
    返回：
    dict: 处理后的数据，只包含需要的文章。
    """
    result = sort_articles_by_time(result)
    article_data = result.get("article_data", [])

    # 检查文章数量是否大于 150
    max_articles = 150
    if len(article_data) > max_articles:
        logging.info("数据量较大，开始进行处理...")
        # 获取前 max_articles 篇文章的作者集合
        top_authors = {article["author"] for article in article_data[:max_articles]}

        # 从第 {max_articles + 1} 篇开始过滤，只保留前 max_articles 篇出现过的作者的文章
        filtered_articles = article_data[:max_articles] + [
            article for article in article_data[max_articles:]
            if article["author"] in top_authors
        ]

        # 更新结果中的 article_data
        result["article_data"] = filtered_articles
        # 更新结果中的统计数据
        result["statistical_data"]["article_num"] = len(filtered_articles)
        logging.info(f"数据处理完成，保留 {len(filtered_articles)} 篇文章")

    return result