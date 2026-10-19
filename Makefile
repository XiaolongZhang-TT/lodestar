# Lodestar 常用开发命令：make help 查看全部
.PHONY: help install dev run test lint format docker-build docker-up docker-down clean

PYTHON ?= python3
COMPOSE ?= docker compose

help: ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## 安装运行依赖
	$(PYTHON) -m pip install -r requirements.txt

dev: ## 安装开发依赖（含 pytest / ruff）
	$(PYTHON) -m pip install -r requirements-dev.txt

run: ## 本机启动（http://127.0.0.1:8091）
	$(PYTHON) server.py

test: ## 运行测试
	$(PYTHON) -m pytest

lint: ## 代码检查
	$(PYTHON) -m ruff check .

format: ## 自动格式化代码
	$(PYTHON) -m ruff format .

docker-build: ## 构建 Docker 镜像
	$(COMPOSE) build

docker-up: ## 构建并后台启动容器
	$(COMPOSE) up -d --build

docker-down: ## 停止容器
	$(COMPOSE) down

clean: ## 清理本地缓存
	rm -rf .pytest_cache .ruff_cache __pycache__ tests/__pycache__
