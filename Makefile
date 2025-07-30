.PHONY: help build run stop logs clean dev prod

# 默认目标
help:
	@echo "Follower Tracker 管理命令"
	@echo ""
	@echo "开发环境:"
	@echo "  make dev      - 启动开发环境"
	@echo "  make build    - 构建镜像"
	@echo "  make run      - 运行容器"
	@echo "  make stop     - 停止服务"
	@echo "  make logs     - 查看日志"
	@echo ""
	@echo "生产环境:"
	@echo "  make prod     - 部署生产环境"
	@echo "  make clean    - 清理资源"
	@echo ""
	@echo "其他:"
	@echo "  make help     - 显示帮助信息"

# 构建镜像
build:
	@echo "构建 Docker 镜像..."
	docker build -t follower-tracker:latest .

# 开发环境
dev:
	@echo "启动开发环境..."
	@if [ ! -f .env ]; then \
		echo "创建 .env 文件..."; \
		cp env.example .env; \
		echo "请编辑 .env 文件配置环境变量"; \
	fi
	docker-compose up --build -d
	@echo "开发环境已启动，访问 http://localhost:8000"

# 生产环境
prod:
	@echo "部署生产环境..."
	@if [ ! -f .env ]; then \
		echo "创建 .env 文件..."; \
		cp env.example .env; \
		echo "请编辑 .env 文件配置环境变量"; \
	fi
	docker build -t follower-tracker:latest .
	docker-compose -f docker-compose.prod.yml up -d
	@echo "生产环境已部署，访问 http://localhost:8000"

# 运行容器
run:
	@echo "运行容器..."
	docker-compose up -d

# 停止服务
stop:
	@echo "停止服务..."
	docker-compose down
	docker-compose -f docker-compose.prod.yml down 2>/dev/null || true

# 查看日志
logs:
	@echo "查看服务日志..."
	docker-compose logs -f follower-tracker

# 清理资源
clean:
	@echo "清理资源..."
	docker-compose down --volumes --remove-orphans
	docker-compose -f docker-compose.prod.yml down --volumes --remove-orphans 2>/dev/null || true
	docker rmi follower-tracker:latest 2>/dev/null || true
	@echo "清理完成"

# 重启服务
restart:
	@echo "重启服务..."
	docker-compose restart follower-tracker

# 进入容器
shell:
	@echo "进入容器..."
	docker-compose exec follower-tracker bash

# 健康检查
health:
	@echo "检查服务健康状态..."
	@curl -f http://localhost:8000/health || echo "服务未运行" 