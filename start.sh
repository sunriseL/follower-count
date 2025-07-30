#!/bin/bash

# 设置环境变量
export PYTHONPATH=/app
export PYTHONUNBUFFERED=1

# 确保数据目录存在
mkdir -p /app/data

# 初始化数据库
python -c "import asyncio; from main import init_database; asyncio.run(init_database())"

# 启动应用
exec uvicorn main:app --host 0.0.0.0 --port 8000 