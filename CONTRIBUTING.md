# 贡献指南 / Contributing to Lodestar

感谢你愿意参与 Lodestar！本文档说明如何报告问题、搭建开发环境以及提交 Pull Request。

## 行为准则

参与本项目即表示你同意遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## 报告问题

- **Bug / 功能建议**：使用 [Issue 模板](https://github.com/XiaolongZhang-TT/lodestar/issues/new/choose)
- **安全漏洞**：**不要**开公开 issue，请按 [SECURITY.md](SECURITY.md) 私密报告
- 提交前请先搜索已有 issue，并确认使用的是最新版本
- 粘贴日志、截图前请遮挡真实域名、账号、书签等隐私信息

## 开发环境

需要 Python 3.9+（与 CI 一致的最低版本）。

```bash
git clone https://github.com/XiaolongZhang-TT/lodestar.git
cd lodestar

# 方式一：使用 venv
python3 -m venv .venv && source .venv/bin/activate
make dev          # 安装运行 + 开发依赖
make run          # http://127.0.0.1:8091

# 方式二：直接 pip 安装
pip install -r requirements-dev.txt
python3 server.py
```

> 本地开发时后台默认账号为 `admin / lodestar-admin`，可用 `NAV_USER` / `NAV_PASS` 环境变量覆盖。

常用命令：

| 命令 | 说明 |
|---|---|
| `make test` | 运行 pytest |
| `make lint` | ruff 静态检查 |
| `make format` | ruff 自动格式化 |
| `make docker-build` / `make docker-up` | 构建 / 启动 Docker 镜像 |

## 项目结构

```
server.py              # Flask 后端（单文件：数据、会话、图标代理、路由）
static/                # 原生前端：index / admin / style / PWA
tests/                 # pytest：纯函数 + API 测试
.github/workflows/     # CI 与镜像发布
```

修改前端静态资源后，记得同步提升 `index.html` / `admin.html` 中的 `?v=N` 版本号，
以便浏览器缓存正确失效。

## 提交 Pull Request

1. Fork 仓库并从 `main` 切出分支：`git switch -c fix/xxx` 或 `feat/xxx`
2. 保持改动聚焦，一个 PR 只做一件事
3. 补充或更新测试；涉及界面改动请附上前后截图
4. 在本地通过 `make test` 和 `make lint`
5. 提交 PR，并在描述中关联相关 issue（如 `Closes #12`）

Commit message 中英文均可，建议写清「做了什么、为什么」：

```
fix: 图标缓存过期后不再重复入队
feat: 支持按 URL 参数指定主题
docs: 补充 GHCR 镜像部署说明
```

## 不要提交的内容

- 真实书签、内网域名 / IP、账号密码
- `data/` 目录（书签数据、`secret.key`、图标与备份）
- `.env`、任何密钥或 token
- 与本 PR 无关的格式化噪音

仓库内的 `data/bookmarks.json` 是演示数据，请勿用真实数据覆盖后提交。

## 许可证

提交贡献即表示你同意以 [MIT License](LICENSE) 授权你的贡献。
