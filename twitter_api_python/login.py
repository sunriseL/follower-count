import time
import json
import logging
import requests

logger = logging.getLogger(__name__)

class TwitterLogin:
    def __init__(self, headless=True, proxy=None):
        """
        初始化Twitter登录类（简化版，只支持token）
        
        Args:
            headless: 保留参数以兼容接口，但不再使用
            proxy: HTTP代理地址
        """
        self.proxy = proxy
        self.proxies = None
        if proxy:
            self.proxies = {
                'http': proxy,
                'https': proxy
            }
    
    def setup_driver(self):
        """
        设置驱动（简化版，只返回True）
        保留此方法以兼容接口
        """
        logger.info("Using simplified Twitter API - no browser driver needed")
        return True
    
    def login(self, auth_token=None):
        """
        登录方法（简化版，只支持token）
        
        Args:
            auth_token: 认证token
            
        Returns:
            dict: 包含认证信息的字典
        """
        logger.info("Using simplified Twitter API - direct token authentication")
        return {
            'method': 'token',
            'status': 'ready',
            'message': 'Direct token authentication mode',
            'auth_token': auth_token
        }
    
    def wait_for_login_success(self, timeout=30):
        """
        等待登录成功（简化版）
        保留此方法以兼容接口
        """
        logger.info("Login success check skipped in simplified mode")
        return True
    
    def get_guest_token(self):
        """
        获取访客token（使用HTTP请求）
        """
        try:
            url = "https://api.twitter.com/1.1/guest/activate.json"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs=1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA'
            }
            
            response = requests.post(url, headers=headers, proxies=self.proxies, timeout=10)
            if response.status_code == 200:
                data = response.json()
                guest_token = data.get('guest_token')
                logger.info(f"Successfully obtained guest token: {guest_token}")
                return guest_token
            else:
                logger.error(f"Failed to get guest token, status: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error getting guest token: {e}")
            return None 