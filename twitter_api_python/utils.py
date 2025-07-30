import json
import time
import logging
import requests
from urllib.parse import urlencode
from .constants import BASE_URL, GQL_FEATURES, BEARER_TOKEN, GQL_MAP
from .login import TwitterLogin

logger = logging.getLogger(__name__)

class TwitterUtils:
    def __init__(self, auth_token=None, proxy=None):
        self.auth_token = auth_token
        self.proxy = proxy
        self.cookies = {}
        self.guest_token = None
        self.csrf_token = None
        
        # 设置代理
        self.proxies = None
        if proxy:
            self.proxies = {
                'http': proxy,
                'https': proxy
            }
    
    def get_auth(self):
        """获取认证信息"""
        if self.auth_token:
            return {
                'token': self.auth_token
            }
        return None
    
    def token_to_cookie(self, token):
        """将token转换为cookie"""
        if not token:
            # 如果没有token，获取访客token并返回空的cookies
            self.get_guest_token()
            return {}
        
        # 如果已经有cookies和csrf_token，直接返回
        if self.cookies and self.csrf_token:
            return self.cookies
        
        # 如果有token，尝试获取CSRF token
        try:
            # 设置代理
            proxies = None
            if self.proxy:
                proxies = {'http': self.proxy, 'https': self.proxy}
            
            # 设置cookies
            cookies = {'auth_token': token}
            
            # 设置headers
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
            
            # 访问 Twitter 主页获取 CSRF token
            response = requests.get(
                'https://x.com',
                headers=headers,
                cookies=cookies,
                proxies=proxies,
                timeout=30
            )
            
            if response.status_code == 200:
                # 从 cookies 中获取 CSRF token
                ct0_cookie = response.cookies.get('ct0')
                if ct0_cookie:
                    self.csrf_token = ct0_cookie
                    self.cookies = {
                        'auth_token': token,
                        'ct0': ct0_cookie
                    }
                    return self.cookies
                
                # 如果cookies中没有，尝试从页面内容中提取
                import re
                try:
                    content = response.text
                    if content:
                        csrf_match = re.search(r'"ct0":"([^"]+)"', content)
                        if csrf_match:
                            csrf_token = csrf_match.group(1)
                            self.csrf_token = csrf_token
                            self.cookies = {
                                'auth_token': token,
                                'ct0': csrf_token
                            }
                            return self.cookies
                except Exception as e:
                    logger.warning(f"Failed to extract CSRF token from content: {e}")
        
        except Exception as e:
            logger.error(f"Failed to get CSRF token: {e}")
        
        # 如果有auth token但无法获取CSRF token，直接使用auth token
        if token:
            logger.warning("Failed to get CSRF token, but using auth token directly")
            self.cookies = {'auth_token': token}
            return self.cookies
        
        # 如果都失败了，返回访客token
        return self.get_guest_token()
    
    def get_guest_token(self):
        """获取访客token"""
        if self.guest_token:
            return self.guest_token
        
        try:
            url = "https://api.twitter.com/1.1/guest/activate.json"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs=1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA'
            }
            
            response = requests.post(url, headers=headers, proxies=self.proxies, timeout=10)
            if response.status_code == 200:
                data = response.json()
                self.guest_token = data.get('guest_token')
                logger.info(f"Successfully obtained guest token: {self.guest_token}")
                return self.guest_token
            else:
                logger.error(f"Failed to get guest token, status: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Failed to get guest token: {e}")
            return None
    
    def twitter_request(self, url, params, allow_no_auth=False):
        """发送Twitter API请求"""
        auth = self.get_auth()
        
        if not auth and not allow_no_auth:
            logger.warning("No valid Twitter token found, but continuing with guest mode")
            # 在简化模式下，即使没有认证也继续执行
        
        # 构建请求URL
        request_url = f"{url}?{urlencode(params)}"
        
        # 获取cookies
        cookies = self.token_to_cookie(auth['token'] if auth else None)
        
        # 构建headers
        headers = {
            'authority': 'x.com',
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'authorization': BEARER_TOKEN,
            'cache-control': 'no-cache',
            'content-type': 'application/json',
            'dnt': '1',
            'pragma': 'no-cache',
            'referer': 'https://x.com/',
            'x-twitter-active-user': 'yes',
            'x-twitter-client-language': 'en',
        }
        
        # 添加认证相关headers
        if auth and auth['token']:
            headers['x-twitter-auth-type'] = 'OAuth2Session'
            if self.csrf_token:
                headers['x-csrf-token'] = self.csrf_token
        elif not auth and self.guest_token:
            # 只有在没有auth token的情况下才使用访客token
            headers['x-guest-token'] = self.guest_token
        
        try:
            response = requests.get(
                request_url,
                headers=headers,
                cookies=cookies,
                proxies=self.proxies,
                timeout=30
            )
            
            # 检查响应状态
            if response.status_code == 200:
                try:
                    logger.info(f"Response text: {response.text[:500]}...")
                    return response.json()
                except Exception as e:
                    logger.error(f"Failed to parse JSON response: {e}")
                    logger.error(f"Response content: {response.text[:500]}...")
                    return None
            elif response.status_code == 429:
                logger.warning("Rate limit exceeded")
                time.sleep(60)  # 等待1分钟
                return self.twitter_request(url, params, allow_no_auth)
            elif response.status_code in [401, 403]:
                logger.error(f"Authentication failed: {response.status_code}")
                # 尝试重新登录
                if auth:
                    self.cookies = {}
                    self.csrf_token = None
                    cookies = self.token_to_cookie(auth['token'])
                    if cookies:
                        return self.twitter_request(url, params, allow_no_auth)
            else:
                logger.error(f"Request failed: {response.status_code} - {response.text}")
            
            return None
            
        except Exception as e:
            logger.error(f"Request error: {e}")
            return None
    
    def pagination_tweets(self, endpoint, user_id=None, variables=None, path=None):
        """分页获取推文"""
        if variables is None:
            variables = {}
        
        params = {
            'variables': json.dumps({**variables, 'userId': user_id}),
            'features': json.dumps(GQL_FEATURES.get(endpoint, {}))
        }
        
        url = f"{BASE_URL}{GQL_MAP[endpoint]}"
        
        data = self.twitter_request(url, params, allow_no_auth=True)
        if not data:
            logger.warning(f"No data returned for endpoint {endpoint}")
            return []
        
        # 解析instructions
        instructions = self.get_instructions(data, path)
        if not instructions:
            logger.warning(f"No instructions found for endpoint {endpoint}")
            return []
        
        # 提取推文条目 - 根据原始TypeScript代码更新
        module_items = None
        entries = None
        
        for instruction in instructions:
            if instruction.get('type') == 'TimelineAddToModule':
                module_items = instruction.get('moduleItems')
            elif instruction.get('type') == 'TimelineAddEntries':
                entries = instruction.get('entries')
        
        result = module_items or entries or []
        logger.info(f"Found {len(result)} items for endpoint {endpoint}")
        return result
    
    def get_instructions(self, data, path=None):
        """从响应数据中提取instructions"""
        if path:
            instructions = data
            for p in path:
                instructions = instructions.get(p, {})
            return instructions.get('instructions', [])
        
        # 默认路径 - 根据原始TypeScript代码更新
        # 原始代码: data?.user?.result?.timeline_v2?.timeline?.instructions
        instructions = data.get('user', {}).get('result', {}).get('timeline_v2', {}).get('timeline', {}).get('instructions', [])
        if not instructions:
            # 尝试其他可能的路径
            instructions = data.get('data', {}).get('user', {}).get('result', {}).get('timeline_v2', {}).get('timeline', {}).get('instructions', [])
        
        if not instructions:
            logger.debug(f"Instructions not found in data: {json.dumps(data, indent=2)[:500]}...")
        
        return instructions
    
    def gather_legacy_from_data(self, entries, filter_nested=None, user_id=None):
        """从数据中提取legacy格式的推文"""
        tweets = []
        filtered_entries = []
        
        # 过滤条目 - 根据原始TypeScript代码更新
        for entry in entries:
            entry_id = entry.get('entryId')
            if entry_id:
                if entry_id.startswith('tweet-'):
                    filtered_entries.append(entry)
                elif entry_id.startswith('profile-grid-0-tweet-'):
                    filtered_entries.append(entry)
                
                # 处理嵌套条目
                if filter_nested and any(entry_id.startswith(f) for f in filter_nested):
                    items = entry.get('content', {}).get('items', [])
                    filtered_entries.extend(items)
        
        # 处理推文数据
        for entry in filtered_entries:
            if entry.get('entryId'):
                content = entry.get('content') or entry.get('item')
                tweet = content.get('content', {}).get('tweetResult', {}).get('result') or \
                       content.get('itemContent', {}).get('tweet_results', {}).get('result')
                
                if tweet and tweet.get('tweet'):
                    tweet = tweet['tweet']
                
                if tweet:
                    retweet = tweet.get('legacy', {}).get('retweeted_status_result', {}).get('result')
                    
                    # 处理推文和转发推文
                    for t in [tweet, retweet]:
                        if not t or not t.get('legacy'):
                            continue
                        
                        # 设置用户信息
                        user_result = t.get('core', {}).get('user_result', {}).get('result') or \
                                    t.get('core', {}).get('user_results', {}).get('result')
                        if user_result:
                            t['legacy']['user'] = user_result.get('legacy')
                        
                        # 设置ID - 避免在其他地方回退到conversation_id_str
                        t['legacy']['id_str'] = t.get('rest_id')
                        
                        # 处理引用推文
                        quote = t.get('quoted_status_result', {}).get('result', {}).get('tweet') or \
                               t.get('quoted_status_result', {}).get('result')
                        if quote:
                            t['legacy']['quoted_status'] = quote.get('legacy')
                            quote_user = quote.get('core', {}).get('user_result', {}).get('result') or \
                                       quote.get('core', {}).get('user_results', {}).get('result')
                            if quote_user:
                                t['legacy']['quoted_status']['user'] = quote_user.get('legacy')
                        
                        # 处理note tweet
                        if t.get('note_tweet'):
                            note_result = t['note_tweet']['note_tweet_results']['result']
                            t['legacy']['entities']['hashtags'] = note_result['entity_set']['hashtags']
                            t['legacy']['entities']['symbols'] = note_result['entity_set']['symbols']
                            t['legacy']['entities']['urls'] = note_result['entity_set']['urls']
                            t['legacy']['entities']['user_mentions'] = note_result['entity_set']['user_mentions']
                            t['legacy']['full_text'] = note_result['text']
                    
                    legacy = tweet.get('legacy')
                    if legacy:
                        if retweet:
                            legacy['retweeted_status'] = retweet.get('legacy')
                        
                        # 根据用户ID过滤
                        if user_id is None or legacy.get('user_id_str') == str(user_id):
                            tweets.append(legacy)
        
        logger.info(f"Extracted {len(tweets)} tweets from {len(filtered_entries)} entries")
        return tweets 