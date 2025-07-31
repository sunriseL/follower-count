import asyncio
import aiosqlite
import sqlite3
import pandas as pd
import matplotlib
# Set matplotlib backend for Windows compatibility
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
import requests
import json
from io import BytesIO
import base64
from datetime import datetime
from typing import Optional, List
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging

from config import settings

# 配置日志
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 创建FastAPI应用
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 调度器
scheduler = AsyncIOScheduler()

# Pydantic模型
class FollowerData(BaseModel):
    platform: str
    username: str
    follower_count: int
    time: datetime

class FollowerResponse(BaseModel):
    platform: str
    username: str
    follower_count: int
    time: str

class UserRequest(BaseModel):
    platform: str
    username: str

class UserResponse(BaseModel):
    id: int
    platform: str
    username: str
    created_at: str
    is_active: bool

class UserValidationResponse(BaseModel):
    id: int
    platform: str
    username: str
    created_at: str
    is_active: bool
    validation_result: dict

# 数据库初始化
async def init_database():
    """初始化数据库"""
    async with aiosqlite.connect(settings.db_path) as db:
        # 创建粉丝数据表
        await db.execute('''
        CREATE TABLE IF NOT EXISTS social_media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            username TEXT NOT NULL,
            follower_count INTEGER NOT NULL,
            time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );''')
        
        # 创建用户管理表
        await db.execute('''
        CREATE TABLE IF NOT EXISTS tracked_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            username TEXT NOT NULL,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(platform, username)
        );''')
        
        await db.commit()
        
        # 插入默认用户（如果不存在）
        await db.execute('''
        INSERT OR IGNORE INTO tracked_users (platform, username, is_active) 
        VALUES (?, ?, 1)
        ''', ("instagram", settings.default_instagram_user))
        
        await db.execute('''
        INSERT OR IGNORE INTO tracked_users (platform, username, is_active) 
        VALUES (?, ?, 1)
        ''', ("twitter", settings.default_twitter_user))
        
        await db.commit()
        logger.info("Database initialized successfully")

# 获取所有活跃用户
async def get_active_users():
    """获取所有活跃的跟踪用户"""
    async with aiosqlite.connect(settings.db_path) as db:
        cursor = await db.execute(
            "SELECT id, platform, username, created_at, is_active FROM tracked_users WHERE is_active = 1"
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row[0],
                "platform": row[1],
                "username": row[2],
                "created_at": row[3],
                "is_active": bool(row[4])
            }
            for row in rows
        ]

# 验证用户是否可以获取follower count
async def validate_user(platform: str, username: str):
    """验证用户是否可以获取follower count"""
    try:
        if platform.lower() == "instagram":
            follower_count = await fetch_instagram_followers(username)
            if follower_count is not None:
                return {
                    "valid": True,
                    "follower_count": follower_count,
                    "message": f"Successfully fetched {follower_count} followers"
                }
            else:
                return {
                    "valid": False,
                    "follower_count": None,
                    "message": "Failed to fetch Instagram followers"
                }
        elif platform.lower() == "twitter":
            follower_count = await fetch_twitter_followers(username)
            if follower_count is not None:
                return {
                    "valid": True,
                    "follower_count": follower_count,
                    "message": f"Successfully fetched {follower_count} followers"
                }
            else:
                return {
                    "valid": False,
                    "follower_count": None,
                    "message": "Failed to fetch Twitter followers"
                }
        else:
            return {
                "valid": False,
                "follower_count": None,
                "message": f"Unsupported platform: {platform}"
            }
    except Exception as e:
        logger.error(f"Error validating user {username} on {platform}: {e}")
        return {
            "valid": False,
            "follower_count": None,
            "message": f"Validation error: {str(e)}"
        }

# Instagram粉丝数抓取
async def fetch_instagram_followers(username: str = None):
    """抓取Instagram粉丝数"""
    if username is None:
        username = settings.default_instagram_user
        
    try:
        url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
        headers = {
            "User-Agent": "Instagram 76.0.0.15.395 Android (24/7.0; 640dpi; 1440x2560; samsung; SM-G930F; herolte; samsungexynos8890; en_US; 138226743)"
        }
        
        response = requests.get(url, headers=headers, proxies=settings.proxy_config, timeout=10)
        response.raise_for_status()
        
        result = response.json()
        count = result["data"]["user"]["edge_followed_by"]["count"]
        
        # 保存到数据库
        async with aiosqlite.connect(settings.db_path) as db:
            await db.execute(
                "INSERT INTO social_media (platform, username, follower_count, time) VALUES (?, ?, ?, datetime('now'))",
                ("instagram", username, count)
            )
            await db.commit()
        
        logger.info(f"Instagram followers for {username}: {count}")
        return count
        
    except Exception as e:
        logger.error(f"Error fetching Instagram followers for {username}: {e}")
        return None

# 导入Twitter API Python库
from twitter_api_python import TwitterAPI

# Twitter粉丝数抓取
async def fetch_twitter_followers(username: str = None):
    """抓取Twitter粉丝数"""
    if username is None:
        username = settings.default_twitter_user
        
    try:
        # 初始化Twitter API客户端
        proxy_url = settings.proxy_config.get('http') if settings.proxy_config else None
        twitter_api = TwitterAPI(
            auth_token=getattr(settings, 'twitter_auth_token', None),
            proxy=proxy_url
        )
        
        # 获取用户信息
        user = twitter_api.get_user(username)
        if user and user.get('followers_count') is not None:
            count = user['followers_count']
            
            # 保存到数据库
            async with aiosqlite.connect(settings.db_path) as db:
                await db.execute(
                    "INSERT INTO social_media (platform, username, follower_count, time) VALUES (?, ?, ?, datetime('now'))",
                    ("twitter", username, count)
                )
                await db.commit()
            
            logger.info(f"Twitter followers for {username}: {count}")
            return count
        else:
            logger.error(f"Failed to get user data for {username}")
            return None
            
    except Exception as e:
        logger.error(f"Error fetching Twitter followers for {username}: {e}")
        return None

# 定时任务 - 支持多个用户
async def scheduled_instagram_fetch():
    """定时抓取Instagram数据 - 支持多个用户"""
    users = await get_active_users()
    instagram_users = [user for user in users if user["platform"] == "instagram"]
    
    for user in instagram_users:
        try:
            await fetch_instagram_followers(user["username"])
        except Exception as e:
            logger.error(f"Error fetching Instagram data for {user['username']}: {e}")

async def scheduled_twitter_fetch():
    """定时抓取Twitter数据 - 支持多个用户"""
    users = await get_active_users()
    twitter_users = [user for user in users if user["platform"] == "twitter"]
    
    for user in twitter_users:
        try:
            await fetch_twitter_followers(user["username"])
        except Exception as e:
            logger.error(f"Error fetching Twitter data for {user['username']}: {e}")

# 启动时初始化
@app.on_event("startup")
async def startup_event():
    """应用启动时的初始化"""
    await init_database()
    
    # 启动调度器
    scheduler.start()
    
    # 添加定时任务
    scheduler.add_job(
        scheduled_instagram_fetch,
        IntervalTrigger(minutes=settings.fetch_interval),
        id="instagram_fetch",
        replace_existing=True
    )
    
    scheduler.add_job(
        scheduled_twitter_fetch,
        IntervalTrigger(minutes=settings.fetch_interval),
        id="twitter_fetch",
        replace_existing=True
    )
    
    logger.info(f"Scheduler started with {settings.fetch_interval}-minute intervals")

# API端点

@app.get("/")
async def root():
    """根端点"""
    return {
        "message": settings.app_name,
        "version": settings.app_version,
        "status": "running"
    }

@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

# 用户管理API端点
@app.get("/api/users", response_model=List[UserResponse])
async def get_users():
    """获取所有跟踪的用户"""
    try:
        async with aiosqlite.connect(settings.db_path) as db:
            cursor = await db.execute(
                "SELECT id, platform, username, created_at, is_active FROM tracked_users ORDER BY platform, username"
            )
            rows = await cursor.fetchall()
            
            return [
                UserResponse(
                    id=row[0],
                    platform=row[1],
                    username=row[2],
                    created_at=row[3],
                    is_active=bool(row[4])
                )
                for row in rows
            ]
            
    except Exception as e:
        logger.error(f"Error fetching users: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/users", response_model=UserValidationResponse)
async def add_user(user: UserRequest):
    """添加新的跟踪用户，并验证用户是否可以获取follower count"""
    try:
        # 首先验证用户
        validation_result = await validate_user(user.platform, user.username)
        
        # 如果验证失败，不添加到数据库
        if not validation_result["valid"]:
            return UserValidationResponse(
                id=0,
                platform=user.platform,
                username=user.username,
                created_at="",
                is_active=False,
                validation_result=validation_result
            )
        
        # 验证成功，添加到数据库
        async with aiosqlite.connect(settings.db_path) as db:
            cursor = await db.execute(
                "INSERT INTO tracked_users (platform, username, is_active) VALUES (?, ?, 1)",
                (user.platform, user.username)
            )
            await db.commit()
            
            # 获取插入的用户信息
            cursor = await db.execute(
                "SELECT id, platform, username, created_at, is_active FROM tracked_users WHERE id = ?",
                (cursor.lastrowid,)
            )
            row = await cursor.fetchone()
            
            return UserValidationResponse(
                id=row[0],
                platform=row[1],
                username=row[2],
                created_at=row[3],
                is_active=bool(row[4]),
                validation_result=validation_result
            )
            
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="User already exists")
    except Exception as e:
        logger.error(f"Error adding user: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/users/{user_id}")
async def delete_user(user_id: int):
    """删除用户（软删除，设置为非活跃）"""
    try:
        async with aiosqlite.connect(settings.db_path) as db:
            cursor = await db.execute(
                "UPDATE tracked_users SET is_active = 0 WHERE id = ?",
                (user_id,)
            )
            await db.commit()
            
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="User not found")
            
            return {"message": "User deleted successfully"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/users/{user_id}/activate")
async def activate_user(user_id: int):
    """激活用户"""
    try:
        async with aiosqlite.connect(settings.db_path) as db:
            cursor = await db.execute(
                "UPDATE tracked_users SET is_active = 1 WHERE id = ?",
                (user_id,)
            )
            await db.commit()
            
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="User not found")
            
            return {"message": "User activated successfully"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error activating user: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/users/validate")
async def validate_user_endpoint(user: UserRequest):
    """验证用户是否可以获取follower count（不添加到数据库）"""
    try:
        validation_result = await validate_user(user.platform, user.username)
        return {
            "platform": user.platform,
            "username": user.username,
            "validation_result": validation_result
        }
    except Exception as e:
        logger.error(f"Error validating user: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/followers", response_model=List[FollowerResponse])
async def get_followers(
    platform: Optional[str] = Query(None, description="平台名称 (instagram/twitter)"),
    username: Optional[str] = Query(None, description="用户名"),
    limit: int = Query(100, description="返回记录数量限制")
):
    """获取粉丝数据"""
    try:
        async with aiosqlite.connect(settings.db_path) as db:
            query = "SELECT platform, username, follower_count, time FROM social_media"
            params = []
            
            if platform or username:
                query += " WHERE"
                if platform:
                    query += " platform = ?"
                    params.append(platform)
                if username:
                    if platform:
                        query += " AND"
                    query += " username = ?"
                    params.append(username)
            
            query += " ORDER BY time DESC LIMIT ?"
            params.append(limit)
            
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            
            return [
                FollowerResponse(
                    platform=row[0],
                    username=row[1],
                    follower_count=row[2],
                    time=row[3]
                )
                for row in rows
            ]
            
    except Exception as e:
        logger.error(f"Error fetching followers: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/followers/latest")
async def get_latest_followers():
    """获取最新的粉丝数据"""
    try:
        async with aiosqlite.connect(settings.db_path) as db:
            cursor = await db.execute("""
                SELECT platform, username, follower_count, time 
                FROM social_media 
                WHERE id IN (
                    SELECT MAX(id) 
                    FROM social_media 
                    GROUP BY platform, username
                )
                ORDER BY platform, username
            """)
            rows = await cursor.fetchall()
            
            return [
                FollowerResponse(
                    platform=row[0],
                    username=row[1],
                    follower_count=row[2],
                    time=row[3]
                )
                for row in rows
            ]
            
    except Exception as e:
        logger.error(f"Error fetching latest followers: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/chart/{platform}/{username}")
async def generate_chart(platform: str, username: str):
    """生成粉丝趋势图表"""
    try:
        # 检查数据库文件是否存在
        if not os.path.exists(settings.db_path):
            raise HTTPException(status_code=404, detail=f"Database not found: {settings.db_path}")
        
        # 连接数据库
        conn = sqlite3.connect(settings.db_path)
        df = pd.read_sql_query(
            'SELECT platform, username, follower_count, time FROM social_media WHERE platform = ? AND username = ?',
            conn,
            params=(platform, username)
        )
        conn.close()

        if df.empty:
            raise HTTPException(status_code=404, detail=f"No data found for {platform}/{username}")

        # 处理时间：更安全的时间解析
        try:
            # 尝试解析时间，支持多种格式
            df['time'] = pd.to_datetime(df['time'], errors='coerce')
            
            # 如果解析失败，尝试其他格式
            if df['time'].isna().any():
                logger.warning(f"Some timestamps could not be parsed for {platform}/{username}")
                # 移除无效的时间戳
                df = df.dropna(subset=['time'])
                
            if df.empty:
                raise HTTPException(status_code=404, detail=f"No valid data found for {platform}/{username}")
                
        except Exception as time_error:
            logger.error(f"Error parsing timestamps: {time_error}")
            raise HTTPException(status_code=500, detail=f"Error parsing timestamps: {str(time_error)}")

        # 按时间排序
        df = df.sort_values('time')

        # 绘图
        plt.figure(figsize=(14, 6))
        sns.set(style="whitegrid")
        
        # 确保数据不为空
        if len(df) == 0:
            raise HTTPException(status_code=404, detail=f"No valid data points for {platform}/{username}")
            
        sns.lineplot(
            data=df, x='time', y='follower_count',
            marker='o', linewidth=1, markersize=5, alpha=0.9, markeredgewidth=0
        )
        
        generate_time = datetime.now().strftime('Created at: %Y-%m-%d %H:%M:%S')
        plt.text(
            0.99, 0.01, generate_time,
            fontsize=8, color='gray',
            ha='right', va='bottom',
            transform=plt.gca().transAxes
        )
        
        plt.title(f"{username} - {platform}")
        ax = plt.gca()
        
        # 根据数据量调整时间轴间隔
        if len(df) > 24:
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=24))
        elif len(df) > 6:
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
        else:
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
            
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))

        plt.xlabel("Time")
        plt.ylabel("Follower Count")
        plt.xticks(rotation=45)
        plt.tight_layout()

        # 保存到内存
        buffer = BytesIO()
        plt.savefig(buffer, format='png', dpi=100, bbox_inches='tight')
        buffer.seek(0)
        plt.close()

        # 返回图片
        return Response(content=buffer.getvalue(), media_type="image/png")

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error generating chart for {platform}/{username}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error generating chart: {str(e)}")

@app.post("/api/fetch/instagram")
async def manual_fetch_instagram(username: str = None):
    """手动触发Instagram数据抓取"""
    count = await fetch_instagram_followers(username)
    if count is not None:
        return {"message": "Instagram data fetched successfully", "follower_count": count}
    else:
        raise HTTPException(status_code=500, detail="Failed to fetch Instagram data")

@app.post("/api/fetch/twitter")
async def manual_fetch_twitter(username: str = None):
    """手动触发Twitter数据抓取"""
    count = await fetch_twitter_followers(username)
    if count is not None:
        return {"message": "Twitter data fetched successfully", "follower_count": count}
    else:
        raise HTTPException(status_code=500, detail="Failed to fetch Twitter data")

@app.get("/api/stats")
async def get_stats():
    """获取统计信息"""
    try:
        async with aiosqlite.connect(settings.db_path) as db:
            # 总记录数
            cursor = await db.execute("SELECT COUNT(*) FROM social_media")
            total_records = (await cursor.fetchone())[0]
            
            # 平台统计
            cursor = await db.execute("SELECT platform, COUNT(*) FROM social_media GROUP BY platform")
            platform_stats = await cursor.fetchall()
            
            # 用户统计
            cursor = await db.execute("SELECT platform, username, COUNT(*) FROM social_media GROUP BY platform, username")
            user_stats = await cursor.fetchall()
            
            # 活跃用户统计
            cursor = await db.execute("SELECT platform, COUNT(*) FROM tracked_users WHERE is_active = 1 GROUP BY platform")
            active_users = await cursor.fetchall()
            
            return {
                "total_records": total_records,
                "platform_stats": {row[0]: row[1] for row in platform_stats},
                "user_stats": [{"platform": row[0], "username": row[1], "records": row[2]} for row in user_stats],
                "active_users": {row[0]: row[1] for row in active_users}
            }
            
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port) 