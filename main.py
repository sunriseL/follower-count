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
        
        # 检查数据点数量，如果太少可能导致图表生成问题
        if len(df) < 1:
            raise HTTPException(status_code=404, detail=f"Insufficient data points for {platform}/{username} (minimum 1 required)")

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

        # 设置图表样式
        plt.style.use('seaborn-v0_8')
        fig, ax = plt.subplots(figsize=(16, 8))
        
        # 确保数据不为空
        if len(df) == 0:
            raise HTTPException(status_code=404, detail=f"No valid data points for {platform}/{username}")
        
        # 计算Y轴范围，不从0开始，让数据差异更明显
        min_followers = df['follower_count'].min()
        max_followers = df['follower_count'].max()
        follower_range = max_followers - min_followers
        
        # 设置Y轴范围，留出10%的边距，但不从0开始
        if follower_range > 0:
            y_margin = follower_range * 0.1
            y_min = max(0, min_followers - y_margin)  # 确保不小于0
            y_max = max_followers + y_margin
        else:
            # 如果所有数据点相同，设置一个合理的范围
            y_min = max(0, min_followers * 0.95)
            y_max = min_followers * 1.05
        
        # 数据点过少的特殊处理
        if len(df) == 1:
            # 只有一个数据点时，使用散点图而不是线图
            ax.scatter(df['time'], df['follower_count'], s=150, alpha=0.8, color='#2E86AB', zorder=5)
            ax.axhline(y=df['follower_count'].iloc[0], color='#A23B72', linestyle='--', alpha=0.6, linewidth=2)
        else:
            # 多个数据点时，使用线图
            ax.plot(df['time'], df['follower_count'], 
                   marker='o', linewidth=2.5, markersize=6, 
                   color='#2E86AB', alpha=0.9, markeredgewidth=0,
                   markerfacecolor='#2E86AB', markeredgecolor='white')
            
            # 添加渐变填充
            ax.fill_between(df['time'], df['follower_count'], 
                           alpha=0.3, color='#2E86AB')
        
        # 设置Y轴范围
        ax.set_ylim(y_min, y_max)
        
        # 设置标题和标签
        ax.set_title(f"{username} - {platform.title()} Follower Trend", 
                    fontsize=20, fontweight='bold', pad=20, color='#2C3E50')
        ax.set_xlabel("Time", fontsize=14, fontweight='bold', color='#2C3E50')
        ax.set_ylabel("Follower Count", fontsize=14, fontweight='bold', color='#2C3E50')
        
        # 优化Y轴格式，避免科学计数法
        def format_y_axis(x, pos):
            if x >= 1e6:
                return f'{x/1e6:.1f}M'
            elif x >= 1e3:
                return f'{x/1e3:.1f}K'
            else:
                return f'{int(x):,}'
        
        ax.yaxis.set_major_formatter(plt.FuncFormatter(format_y_axis))
        
        # 智能调整X轴刻度数量 - 先决定tick数量，再分配时间点
        data_points = len(df)
        time_range = df['time'].max() - df['time'].min()
        
        # 根据图表宽度和可读性决定理想的tick数量
        # 假设每个tick标签需要约80像素宽度，图表宽度约1200像素
        max_ticks = 10  # 降低最大tick数量，确保标签不重叠
        
        if data_points <= 5:
            # 数据点很少，显示所有点
            ax.set_xticks(df['time'])
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
        else:
            # 根据时间范围和数据点数量决定tick数量
            if time_range.days > 30:
                # 超过一个月，最多显示5个tick
                target_ticks = min(10, max_ticks)
                tick_interval = max(1, time_range.days // target_ticks)
                ax.xaxis.set_major_locator(mdates.DayLocator(interval=tick_interval))
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
            elif time_range.days > 7:
                # 超过一周，最多显示6个tick
                target_ticks = min(10, max_ticks)
                tick_interval = max(1, time_range.days // target_ticks)
                ax.xaxis.set_major_locator(mdates.DayLocator(interval=tick_interval))
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
            elif time_range.days > 1:
                # 超过一天，最多显示5个tick
                target_ticks = min(10, max_ticks)
                hours_range = int(time_range.total_seconds() / 3600)
                tick_interval = max(1, hours_range // target_ticks)
                ax.xaxis.set_major_locator(mdates.HourLocator(interval=tick_interval))
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
            else:
                # 一天内，最多显示6个tick
                target_ticks = min(10, max_ticks)
                hours_range = int(time_range.total_seconds() / 3600)
                tick_interval = max(1, hours_range // target_ticks)
                ax.xaxis.set_major_locator(mdates.HourLocator(interval=tick_interval))
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        
        # 设置网格样式
        ax.grid(True, alpha=0.3, linestyle='-', linewidth=0.5)
        ax.set_axisbelow(True)
        
        # 设置背景色
        ax.set_facecolor('#F8F9FA')
        fig.patch.set_facecolor('white')
        
        # 计算详细的统计信息
        current_followers = df['follower_count'].iloc[-1]
        initial_followers = df['follower_count'].iloc[0]
        max_followers = df['follower_count'].max()
        min_followers = df['follower_count'].min()
        
        # 总体增长率
        total_growth = current_followers - initial_followers
        total_growth_percent = (total_growth / initial_followers * 100) if initial_followers > 0 else 0
        
        # 计算每日增长率（如果有足够的数据点）
        daily_growth_info = ""
        if len(df) > 1:
            # 计算时间跨度
            time_span = (df['time'].max() - df['time'].min()).days
            if time_span > 0:
                daily_growth = total_growth / time_span
                daily_growth_percent = (total_growth_percent / time_span) if time_span > 0 else 0
                daily_growth_info = f"Daily: {format_y_axis(daily_growth, None)} ({daily_growth_percent:+.1f}%)"
            else:
                # 如果时间跨度小于1天，计算每小时增长率
                hours_span = (df['time'].max() - df['time'].min()).total_seconds() / 3600
                if hours_span > 0:
                    hourly_growth = total_growth / hours_span
                    hourly_growth_percent = (total_growth_percent / hours_span) if hours_span > 0 else 0
                    daily_growth_info = f"Hourly: {format_y_axis(hourly_growth, None)} ({hourly_growth_percent:+.1f}%)"
        
        # 计算最近一次变化（如果有多个数据点）
        recent_change_info = ""
        if len(df) > 1:
            recent_change = current_followers - df['follower_count'].iloc[-2]
            recent_change_percent = (recent_change / df['follower_count'].iloc[-2] * 100) if df['follower_count'].iloc[-2] > 0 else 0
            recent_change_info = f"Last: {format_y_axis(recent_change, None)} ({recent_change_percent:+.1f}%)"
        
        # 构建统计信息文本
        stats_text = f"Current: {format_y_axis(current_followers, None)}\n"
        stats_text += f"Total: {format_y_axis(total_growth, None)} ({total_growth_percent:+.1f}%)\n"
        if daily_growth_info:
            stats_text += f"{daily_growth_info}\n"
        if recent_change_info:
            stats_text += f"{recent_change_info}\n"
        stats_text += f"Range: {format_y_axis(min_followers, None)} - {format_y_axis(max_followers, None)}"
        
        # 在图表右下角添加统计信息
        ax.text(0.98, 0.02, stats_text,
                transform=ax.transAxes, fontsize=10,
                verticalalignment='bottom', horizontalalignment='right',
                bbox=dict(boxstyle='round,pad=0.5', facecolor='white', alpha=0.9, edgecolor='#BDC3C7'))
        
        # 添加生成时间
        generate_time = datetime.now().strftime('Generated: %Y-%m-%d %H:%M:%S')
        ax.text(0.02, 0.02, generate_time,
                fontsize=8, color='#7F8C8D',
                transform=ax.transAxes,
                verticalalignment='bottom')
        
        # 旋转X轴标签
        plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
        
        # 强制限制X轴tick数量，确保不超过设定值
        current_ticks = len(ax.get_xticks())
        if current_ticks > max_ticks:
            # 如果当前tick数量超过限制，手动设置tick位置
            if time_range.days > 30:
                # 对于长时间范围，手动选择几个关键时间点
                start_date = df['time'].min()
                end_date = df['time'].max()
                step_days = time_range.days // (max_ticks - 1)
                manual_ticks = [start_date + pd.Timedelta(days=i * step_days) for i in range(max_ticks)]
                ax.set_xticks(manual_ticks)
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
            elif time_range.days > 7:
                # 对于中等时间范围，手动选择几个关键时间点
                start_date = df['time'].min()
                end_date = df['time'].max()
                step_days = time_range.days // (max_ticks - 1)
                manual_ticks = [start_date + pd.Timedelta(days=i * step_days) for i in range(max_ticks)]
                ax.set_xticks(manual_ticks)
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
        
        # 调整布局
        plt.tight_layout()

        # 保存到内存
        buffer = BytesIO()
        
        # 设置保存参数
        save_kwargs = {
            'format': 'png',
            'dpi': 150,
            'bbox_inches': 'tight',
            'pad_inches': 0.2,
            'facecolor': 'white',
            'edgecolor': 'none'
        }
        
        # 如果数据点很少，使用更保守的设置
        if len(df) <= 2:
            save_kwargs['dpi'] = 100
        
        plt.savefig(buffer, **save_kwargs)
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

# 在现有的imports后添加新的helper函数
async def get_growth_data_from_date(platform: str, username: str, start_date: str):
    """获取指定日期开始的数据，计算增长量"""
    try:
        async with aiosqlite.connect(settings.db_path) as db:
            # 获取指定日期开始的所有数据
            cursor = await db.execute("""
                SELECT follower_count, time 
                FROM social_media 
                WHERE platform = ? AND username = ? AND date(time) >= date(?)
                ORDER BY time ASC
            """, (platform, username, start_date))
            rows = await cursor.fetchall()
            
            if len(rows) < 2:
                return None
            
            # 计算增长数据
            initial_count = rows[0][0]
            final_count = rows[-1][0]
            total_growth = final_count - initial_count
            growth_percentage = (total_growth / initial_count * 100) if initial_count > 0 else 0
            
            # 计算每日平均增长
            time_span = (pd.to_datetime(rows[-1][1]) - pd.to_datetime(rows[0][1])).days
            daily_growth = total_growth / time_span if time_span > 0 else 0
            
            return {
                "username": username,
                "platform": platform,
                "initial_count": initial_count,
                "final_count": final_count,
                "total_growth": total_growth,
                "growth_percentage": growth_percentage,
                "daily_growth": daily_growth,
                "time_span_days": time_span,
                "data_points": len(rows)
            }
            
    except Exception as e:
        logger.error(f"Error getting growth data for {platform}/{username}: {e}")
        return None

# 在现有的API端点后添加新的比较端点
@app.get("/api/compare/growth")
async def compare_users_growth(
    start_date: str = Query(..., description="起始日期 (YYYY-MM-DD格式)"),
    users: str = Query(..., description="要比较的用户，格式: platform1:username1,platform2:username2")
):
    """比较多个用户在指定日期开始的数据增长量"""
    try:
        # 解析用户列表
        user_list = []
        for user_str in users.split(','):
            if ':' in user_str:
                platform, username = user_str.strip().split(':', 1)
                user_list.append((platform.strip(), username.strip()))
            else:
                raise HTTPException(status_code=400, detail="用户格式错误，应为 platform:username 格式")
        
        if len(user_list) < 2:
            raise HTTPException(status_code=400, detail="至少需要2个用户进行比较")
        
        # 验证日期格式
        try:
            pd.to_datetime(start_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式错误，应为 YYYY-MM-DD 格式")
        
        # 获取每个用户的增长数据
        growth_data = []
        for platform, username in user_list:
            data = await get_growth_data_from_date(platform, username, start_date)
            if data:
                growth_data.append(data)
            else:
                logger.warning(f"No growth data available for {platform}/{username} from {start_date}")
        
        if len(growth_data) < 2:
            raise HTTPException(status_code=404, detail="没有足够的数据进行比较")
        
        return {
            "start_date": start_date,
            "comparison_data": growth_data,
            "summary": {
                "total_users": len(growth_data),
                "best_performer": max(growth_data, key=lambda x: x["growth_percentage"]),
                "worst_performer": min(growth_data, key=lambda x: x["growth_percentage"])
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error comparing users growth: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/compare/chart")
async def generate_comparison_chart(
    start_date: str = Query(..., description="起始日期 (YYYY-MM-DD格式)"),
    users: str = Query(..., description="要比较的用户，格式: platform1:username1,platform2:username2")
):
    """生成多用户增长比较图表"""
    try:
        # 解析用户列表
        user_list = []
        for user_str in users.split(','):
            if ':' in user_str:
                platform, username = user_str.strip().split(':', 1)
                user_list.append((platform.strip(), username.strip()))
            else:
                raise HTTPException(status_code=400, detail="用户格式错误，应为 platform:username 格式")
        
        if len(user_list) < 2:
            raise HTTPException(status_code=400, detail="至少需要2个用户进行比较")
        
        # 验证日期格式
        try:
            start_datetime = pd.to_datetime(start_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式错误，应为 YYYY-MM-DD 格式")
        
        # 连接数据库获取数据
        conn = sqlite3.connect(settings.db_path)
        
        # 为每个用户获取数据
        all_data = []
        for platform, username in user_list:
            df = pd.read_sql_query(
                'SELECT platform, username, follower_count, time FROM social_media WHERE platform = ? AND username = ? AND date(time) >= date(?) ORDER BY time ASC',
                conn,
                params=(platform, username, start_date)
            )
            if not df.empty:
                df['time'] = pd.to_datetime(df['time'])
                all_data.append(df)
        
        conn.close()
        
        if len(all_data) < 2:
            raise HTTPException(status_code=404, detail="没有足够的数据进行比较")
        
        # 创建图表 - 只保留一个子图
        plt.style.use('seaborn-v0_8')
        fig, ax = plt.subplots(1, 1, figsize=(16, 10))
        
        # 颜色配置
        colors = ['#2E86AB', '#A23B72', '#F18F01', '#C73E1D', '#8B5A96', '#2E8B57']
        
        # 增长量趋势图（纵坐标是增长量）
        for i, df in enumerate(all_data):
            color = colors[i % len(colors)]
            username = df['username'].iloc[0]
            platform = df['platform'].iloc[0]
            label = f"{username} ({platform})"
            
            # 计算相对于起始日期的增长量
            initial_count = df['follower_count'].iloc[0]
            df['growth_amount'] = df['follower_count'] - initial_count
            
            ax.plot(df['time'], df['growth_amount'], 
                   marker='o', linewidth=2.5, markersize=6, 
                   color=color, alpha=0.9, label=label,
                   markeredgewidth=0, markerfacecolor=color, markeredgecolor='white')
            
            # 添加渐变填充
            ax.fill_between(df['time'], df['growth_amount'], 
                          alpha=0.2, color=color)
        
        ax.set_title(f"Follower Growth Amount Comparison (From {start_date})", 
                    fontsize=18, fontweight='bold', pad=20, color='#2C3E50')
        ax.set_xlabel("Time", fontsize=12, fontweight='bold', color='#2C3E50')
        ax.set_ylabel("Growth Amount (Followers)", fontsize=12, fontweight='bold', color='#2C3E50')
        # 先添加统计信息，再添加图例，避免重叠
        # 计算统计信息
        final_growth_data = []
        for i, df in enumerate(all_data):
            if len(df) >= 2:
                final_growth = df['growth_amount'].iloc[-1]
                username = df['username'].iloc[0]
                platform = df['platform'].iloc[0]
                label = f"{username} ({platform})"
                
                final_growth_data.append({
                    'label': label,
                    'growth_amount': final_growth
                })
        
        # 按增长量排序
        final_growth_data.sort(key=lambda x: x['growth_amount'], reverse=True)
        
        # 添加统计信息到左上角
        stats_text = f"Comparison Period: {start_date} to Present\n"
        stats_text += f"Total Users: {len(final_growth_data)}\n"
        if final_growth_data:
            best = final_growth_data[0]
            worst = final_growth_data[-1]
            stats_text += f"Best: {best['label']} ({best['growth_amount']:+,})\n"
            stats_text += f"Worst: {worst['label']} ({worst['growth_amount']:+,})"
        
        ax.text(0.02, 0.98, stats_text,
               transform=ax.transAxes, fontsize=10,
               verticalalignment='top', horizontalalignment='left',
               bbox=dict(boxstyle='round,pad=0.5', facecolor='white', alpha=0.9, edgecolor='#BDC3C7'))
        
        # 图例放在统计信息下方，避免重叠
        ax.legend(loc='upper left', bbox_to_anchor=(0.02, 0.85), fontsize=10)
        ax.grid(True, alpha=0.3, linestyle='-', linewidth=0.5)
        
        # 设置Y轴格式（增长量可能为负数，需要特殊处理）
        def format_growth_axis(x, pos):
            if x == 0:
                return '0'
            elif x > 0:
                if x >= 1e6:
                    return f'+{x/1e6:.1f}M'
                elif x >= 1e3:
                    return f'+{x/1e3:.1f}K'
                else:
                    return f'+{int(x):,}'
            else:
                if abs(x) >= 1e6:
                    return f'{x/1e6:.1f}M'
                elif abs(x) >= 1e3:
                    return f'{x/1e3:.1f}K'
                else:
                    return f'{int(x):,}'
        
        ax.yaxis.set_major_formatter(plt.FuncFormatter(format_growth_axis))
        
        # 添加零线（基准线）
        ax.axhline(y=0, color='#95A5A6', linestyle='--', alpha=0.7, linewidth=1)
        
        # 添加生成时间
        generate_time = datetime.now().strftime('Generated: %Y-%m-%d %H:%M:%S')
        ax.text(0.02, 0.02, generate_time,
               fontsize=8, color='#7F8C8D',
               transform=ax.transAxes,
               verticalalignment='bottom')
        
        # 调整布局
        plt.tight_layout()
        
        # 保存到内存
        buffer = BytesIO()
        plt.savefig(buffer, format='png', dpi=150, bbox_inches='tight', 
                   pad_inches=0.2, facecolor='white', edgecolor='none')
        buffer.seek(0)
        plt.close()
        
        # 返回图片
        return Response(content=buffer.getvalue(), media_type="image/png")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating comparison chart: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error generating comparison chart: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port) 