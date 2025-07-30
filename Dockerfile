# 多阶段构建 - 构建阶段
FROM python:3.11-slim AS builder

# 设置工作目录
WORKDIR /app

# 安装构建依赖
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libffi-dev \
    libssl-dev \
    libjpeg-dev \
    libpng-dev \
    libfreetype6-dev \
    libblas-dev \
    liblapack-dev \
    libatlas-base-dev \
    gfortran \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖到虚拟环境
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 生产阶段
FROM python:3.11-slim

# 创建非root用户
RUN groupadd -r appuser && useradd -r -g appuser appuser

# 设置工作目录
WORKDIR /app

# 安装运行时依赖
RUN apt-get update && apt-get install -y \
    libjpeg62-turbo \
    libpng16-16 \
    libfreetype6 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# 从构建阶段复制虚拟环境
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 复制应用代码
COPY main.py .
COPY config.py .
COPY start.sh .
COPY twitter_api_python/ ./twitter_api_python/

# 设置启动脚本权限
RUN chmod +x start.sh

# 创建数据目录并设置权限
RUN mkdir -p /app/data && \
    chown -R appuser:appuser /app

# 切换到非root用户
USER appuser

# 暴露端口
EXPOSE 8000

# 设置环境变量
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV MPLCONFIGDIR=/tmp/matplotlib

# 设置默认环境变量（可通过.env文件或docker run覆盖）
ENV APP_NAME="Follower Tracker"
ENV APP_VERSION="1.0.0"
ENV DEBUG="false"
ENV HOST="0.0.0.0"
ENV PORT="8000"
ENV DATA_DIR="/app/data"
ENV DB_PATH="/app/data/data.db"
ENV FETCH_INTERVAL="10"
ENV LOG_LEVEL="INFO"
ENV DEFAULT_INSTAGRAM_USER="kohinata_mika"
ENV DEFAULT_TWITTER_USER="kohinatamika"

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 启动命令
CMD ["./start.sh"] 