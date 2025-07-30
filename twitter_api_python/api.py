import json
import logging
from .constants import BASE_URL, GQL_MAP, GQL_FEATURES
from .utils import TwitterUtils

logger = logging.getLogger(__name__)

class TwitterAPI:
    def __init__(self, auth_token=None, proxy=None):
        """
        初始化Twitter API客户端
        
        Args:
            auth_token: Twitter认证token
            proxy: HTTP代理地址
        """
        self.utils = TwitterUtils(
            auth_token=auth_token,
            proxy=proxy
        )
    
    def get_user_data(self, user_id):
        """获取用户数据"""
        if user_id.startswith('+'):
            # 使用用户ID
            variables = {
                'userId': user_id[1:],
                'withSafetyModeUserFields': True
            }
            features = GQL_FEATURES['UserByRestId']
            endpoint = GQL_MAP['UserByRestId']
        else:
            # 使用用户名
            variables = {
                'screen_name': user_id,
                'withSafetyModeUserFields': True
            }
            features = GQL_FEATURES['UserByScreenName']
            endpoint = GQL_MAP['UserByScreenName']
        
        params = {
            'variables': json.dumps(variables),
            'features': json.dumps(features),
            'fieldToggles': json.dumps({
                'withAuxiliaryUserLabels': False
            })
        }
        
        url = f"{BASE_URL}{endpoint}"
        data = self.utils.twitter_request(url, params, allow_no_auth=True)
        return data
    
    def get_user(self, user_id):
        """获取用户信息"""
        user_data = self.get_user_data(user_id)
        logger.info(f"User data response: {user_data}")
        if user_data:
            user_result = user_data.get('data', {}).get('user') or user_data.get('data', {}).get('user_result')
            logger.info(f"User result: {user_result}")
            if user_result:
                legacy_data = user_result.get('result', {}).get('legacy')
                logger.info(f"Legacy data: {legacy_data}")
                return legacy_data
        return None
    
    def get_user_tweets(self, user_id, params=None):
        """获取用户推文"""
        if params is None:
            params = {}
        
        def fetch_tweets(id, params):
            variables = {
                **params,
                'count': 20,
                'includePromotedContent': True,
                'withQuickPromoteEligibilityTweetFields': True,
                'withVoice': True,
                'withV2Timeline': True
            }
            
            entries = self.utils.pagination_tweets('UserTweets', id, variables)
            return self.utils.gather_legacy_from_data(entries)
        
        return self._cache_try_get(user_id, params, fetch_tweets)
    
    def get_user_tweets_and_replies(self, user_id, params=None):
        """获取用户推文和回复"""
        if params is None:
            params = {}
        
        def fetch_tweets_and_replies(id, params):
            variables = {
                **params,
                'count': 20,
                'includePromotedContent': True,
                'withCommunity': True,
                'withVoice': True,
                'withV2Timeline': True
            }
            
            entries = self.utils.pagination_tweets('UserTweetsAndReplies', id, variables)
            return self.utils.gather_legacy_from_data(entries, ['profile-conversation-'], id)
        
        return self._cache_try_get(user_id, params, fetch_tweets_and_replies)
    
    def get_user_media(self, user_id, params=None):
        """获取用户媒体推文"""
        if params is None:
            params = {}
        
        def fetch_media(id, params):
            variables = {
                **params,
                'count': 20,
                'includePromotedContent': False,
                'withClientEventToken': False,
                'withBirdwatchNotes': False,
                'withVoice': True,
                'withV2Timeline': True
            }
            
            # 先获取cursor
            cursor_source = self.utils.pagination_tweets('UserMedia', id, variables)
            cursor = None
            for item in cursor_source:
                if item.get('content', {}).get('cursorType') == 'Top':
                    cursor = item['content']['value']
                    break
            
            if cursor:
                variables['cursor'] = cursor
                entries = self.utils.pagination_tweets('UserMedia', id, variables)
                return self.utils.gather_legacy_from_data(entries)
            
            return []
        
        return self._cache_try_get(user_id, params, fetch_media)
    
    def get_user_likes(self, user_id, params=None):
        """获取用户点赞的推文"""
        if params is None:
            params = {}
        
        def fetch_likes(id, params):
            variables = {
                **params,
                'includeHasBirdwatchNotes': False,
                'includePromotedContent': False,
                'withBirdwatchNotes': False,
                'withVoice': False,
                'withV2Timeline': True
            }
            
            entries = self.utils.pagination_tweets('Likes', id, variables)
            return self.utils.gather_legacy_from_data(entries)
        
        return self._cache_try_get(user_id, params, fetch_likes)
    
    def get_user_tweet(self, tweet_id, params=None):
        """获取单条推文详情"""
        if params is None:
            params = {}
        
        def fetch_tweet(id, params):
            variables = {
                **params,
                'includeHasBirdwatchNotes': False,
                'includePromotedContent': False,
                'withBirdwatchNotes': False,
                'withVoice': False,
                'withV2Timeline': True
            }
            
            entries = self.utils.pagination_tweets(
                'TweetDetail', 
                id, 
                variables, 
                ['threaded_conversation_with_injections_v2']
            )
            return self.utils.gather_legacy_from_data(entries, ['homeConversation-', 'conversationthread-'])
        
        return self._cache_try_get(tweet_id, params, fetch_tweet)
    
    def search(self, keywords, params=None):
        """搜索推文"""
        if params is None:
            params = {}
        
        variables = {
            **params,
            'rawQuery': keywords,
            'count': 20,
            'querySource': 'typed_query',
            'product': 'Latest'
        }
        
        entries = self.utils.pagination_tweets(
            'SearchTimeline', 
            None, 
            variables, 
            ['search_by_raw_query', 'search_timeline', 'timeline']
        )
        return self.utils.gather_legacy_from_data(entries)
    
    def get_list(self, list_id, params=None):
        """获取列表推文"""
        if params is None:
            params = {}
        
        variables = {
            **params,
            'listId': list_id,
            'count': 20
        }
        
        entries = self.utils.pagination_tweets(
            'ListLatestTweetsTimeline', 
            None, 
            variables, 
            ['list', 'tweets_timeline', 'timeline']
        )
        return self.utils.gather_legacy_from_data(entries)
    
    def get_home_timeline(self, user_id=None, params=None):
        """获取主页时间线"""
        if params is None:
            params = {}
        
        variables = {
            **params,
            'count': 20,
            'includePromotedContent': True,
            'latestControlAvailable': True,
            'requestContext': 'launch',
            'withCommunity': True
        }
        
        entries = self.utils.pagination_tweets(
            'HomeTimeline', 
            None, 
            variables, 
            ['home', 'home_timeline_urt']
        )
        return self.utils.gather_legacy_from_data(entries)
    
    def get_home_latest_timeline(self, user_id=None, params=None):
        """获取主页最新时间线"""
        if params is None:
            params = {}
        
        variables = {
            **params,
            'count': 20,
            'includePromotedContent': True,
            'latestControlAvailable': True,
            'requestContext': 'launch',
            'withCommunity': True
        }
        
        entries = self.utils.pagination_tweets(
            'HomeLatestTimeline', 
            None, 
            variables, 
            ['home', 'home_timeline_urt']
        )
        return self.utils.gather_legacy_from_data(entries)
    
    def _cache_try_get(self, user_id, params, func):
        """缓存尝试获取数据"""
        # 这里简化了缓存逻辑，实际使用时可以添加Redis或内存缓存
        try:
            # 如果user_id是数字，说明已经是rest_id，直接使用
            if str(user_id).isdigit():
                return func(user_id, params)
            
            # 否则先获取用户信息来获取rest_id
            user_data = self.get_user_data(user_id)
            if not user_data:
                raise Exception('User not found')
            
            user_result = user_data.get('data', {}).get('user') or user_data.get('data', {}).get('user_result')
            if not user_result:
                raise Exception('User not found')
            
            rest_id = user_result.get('result', {}).get('rest_id')
            if not rest_id:
                raise Exception('User not found')
            
            return func(rest_id, params)
            
        except Exception as e:
            logger.error(f"Error in _cache_try_get: {e}")
            return [] 