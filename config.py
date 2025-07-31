import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """应用配置类"""
    
    # 基础配置
    app_name: str = "Follower Tracker"
    app_version: str = "1.0.0"
    debug: bool = False
    
    # 服务器配置
    host: str = "0.0.0.0"
    port: int = 8000
    
    # 数据库配置
    data_dir: str = "./data"
    db_path: str = "./data.db"
    
    # 代理配置
    http_proxy: Optional[str] = None
    https_proxy: Optional[str] = None
    
    # 定时任务配置
    fetch_interval: int = 10  # 分钟
    
    # 日志配置
    log_level: str = "INFO"
    
    # 默认用户配置
    default_instagram_user: str = "kohinata_mika"
    default_twitter_user: str = "kohinatamika"
    
    # Twitter API配置
    twitter_auth_token: Optional[str] = None
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        # 允许从环境变量加载，支持大写和下划线格式
        env_prefix = ""
        alias_generator = lambda string: string.upper().replace(".", "_")
        # 允许额外的字段
        extra = "ignore"

    def model_post_init(self, __context):
        """初始化后处理"""
        # 确保数据目录存在
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        
        # 如果db_path是相对路径，则相对于data_dir
        if not os.path.isabs(self.db_path):
            # 清理路径，移除开头的 ./
            clean_db_path = self.db_path.lstrip('./')
            # 确保使用正斜杠，特别是在Docker环境中
            if self.data_dir.startswith('/'):
                # Docker环境，使用Unix风格路径
                self.db_path = f"{self.data_dir}/{clean_db_path}"
            else:
                # 本地环境，使用os.path.join
                self.db_path = os.path.join(self.data_dir, clean_db_path)
        
        # 优先使用当前目录的数据库文件（本地开发时）
        current_dir_db = os.path.join(os.getcwd(), 'data.db')
        if os.path.exists(current_dir_db):
            # 如果当前目录有数据库文件，优先使用它
            self.db_path = current_dir_db
    
    @property
    def proxy_config(self) -> dict:
        """获取代理配置"""
        config = {}
        if self.http_proxy:
            config["http"] = self.http_proxy
        if self.https_proxy:
            config["https"] = self.https_proxy
        return config

# 全局配置实例
settings = Settings() 