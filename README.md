# Lodestar · 个人导航页

**简体中文** | [English](README.en.md)

[![CI](https://github.com/XiaolongZhang-TT/lodestar/actions/workflows/ci.yml/badge.svg)](https://github.com/XiaolongZhang-TT/lodestar/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/XiaolongZhang-TT/lodestar?sort=semver)](https://github.com/XiaolongZhang-TT/lodestar/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)

> 一个轻量、自托管的个人导航页：**Flask 单文件后端 + 原生前端**，带登录后台，数据落盘为 JSON。
> **Lodestar** 意为「北极星 / 指引之星」——每个书签都是浏览途中的一颗星。

![Lodestar 明色主题](docs/screenshot-light.png)

<details>
<summary>🌙 查看暗色主题截图</summary>

![Lodestar 暗色主题](docs/screenshot-dark.png)

</details>

## 功能

- 🕐 大时钟 + 按时段问候语
- 🧩 卡片式书签，自动解析网站图标（favicon / 页面声明的图标），失败回退彩色首字母方块，也可用 emoji 覆盖
- 🔍 本地书签筛选（按 `/` 聚焦，即时过滤，不是搜索引擎）
- 🔐 **后台管理**（`/admin`）：登录后可增删改分类和链接、设置页面标题，保存即生效；未保存有提醒，网址缺协议自动补全
- 🌙 明 / 暗双主题：默认跟随系统，手动切换后会记住
- 📱 响应式布局 + PWA（手机可「添加到主屏幕」全屏使用）
- 🗄️ 数据以 JSON 落盘：原子写入、自动滚动备份、损坏时回退 `.bak`
- 🐳 提供 Dockerfile / docker compose，可在 x86 与 ARM（群晖、树莓派等）上构建

## 快速开始

### 方式一：Docker Compose（推荐）

```bash
git clone https://github.com/XiaolongZhang-TT/lodestar.git
cd lodestar
cp .env.example .env
# 编辑 .env，至少把 NAV_PASS 改成强密码
docker compose up -d --build
```

- 主页：`http://服务器IP:8091`
- 后台：`http://服务器IP:8091/admin`

### 方式二：预构建镜像（GHCR）

发布 tag 后，GitHub Actions 会自动构建 `linux/amd64` + `linux/arm64` 镜像：

```bash
docker run -d --name lodestar \
  -p 8091:8091 \
  -e NAV_USER=admin \
  -e NAV_PASS='换成你的强密码' \
  -v "$PWD/data:/app/data" \
  --restart unless-stopped \
  ghcr.io/xiaolongzhang-tt/lodestar:latest
```

> 镜像地址：`ghcr.io/xiaolongzhang-tt/lodestar`（可用的 tag 见 [Releases](https://github.com/XiaolongZhang-TT/lodestar/releases)）。
> 如果无法拉取，请按方式一在目标机器上构建。

### 方式三：本机运行

需要 Python 3.9+。

```bash
git clone https://github.com/XiaolongZhang-TT/lodestar.git
cd lodestar
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 server.py
```

- 主页：<http://127.0.0.1:8091>
- 后台：<http://127.0.0.1:8091/admin>

默认账号 `admin` / `lodestar-admin`（启动日志会提醒修改）。**正式部署务必换掉**：

```bash
NAV_USER=你的用户名 NAV_PASS=你的强密码 python3 server.py
```

## 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `NAV_USER` | `admin` | 后台登录用户名 |
| `NAV_PASS` | `lodestar-admin` | 后台登录密码，正式部署必须修改 |
| `NAV_PORT` | `8091` | 服务监听端口 |

使用 docker compose 时，把变量写进同目录的 `.env`（参考 [`.env.example`](.env.example)），避免留在 shell 历史里。

## 数据与安全

| 路径 | 说明 |
|---|---|
| `data/bookmarks.json` | 书签数据，保存时自动滚动备份 |
| `data/backups/` | 历史备份（保留最近 10 份），误删可从这里找回 |
| `data/secret.key` | 登录会话的 HMAC 签名密钥，首次启动自动生成（权限 600） |
| `data/icons/` | 网站图标缓存：成功 7 天、失败 10 分钟后重试；删掉即可强制重取 |

- 仓库自带的 `data/bookmarks.json` 是**演示数据**；真实书签请只在本地维护
  （可存为 `data/bookmarks.private.json`，已被 `.gitignore` 忽略），不要提交
- 登录：`POST /api/login` 校验账号密码（常量时间比较 + 失败延迟 0.5s），
  颁发 HttpOnly 签名 Cookie，有效期一周
- 数据保存接口 `POST /api/data` 必须携带有效会话；主页读取 `GET /api/data` 无需登录
- 图标代理 `/api/icon` 只解析书签中出现的 host，防止被当公开代理滥用
- 会话密钥泄露的处置：删除 `data/secret.key` 并重启（所有人需重新登录）
- 这是**单用户**应用，没有权限隔离；请置于反向代理之后提供 HTTPS，
  或只在内网 / VPN 中访问。更多安全说明见 [SECURITY.md](SECURITY.md)

## 维护书签

全部在 `http://你的地址/admin` 完成：

- 分类：改名 / 换 emoji 图标 / 新增 / 删除（删除需确认）
- 链接：每行四个字段——图标 emoji（可空）、名称、网址、备注（可空），可增删
- 顶部可改页面标题和问候语中的名字；改完点「保存」即写入数据文件

## 开发

```bash
make dev    # 安装运行 + 开发依赖（pytest / ruff）
make test   # 运行测试
make lint   # 代码检查
make run    # 本机启动
```

不使用 Make 时等价于：

```bash
pip install -r requirements-dev.txt
python3 -m pytest
python3 -m ruff check .
```

修改 `static/` 下的资源后，请同步提升 `index.html` / `admin.html` 中的 `?v=N` 版本号。

## 项目结构

```
lodestar/
├── server.py            # Flask 后端：数据 / 会话 / 图标代理 / 路由
├── static/              # 原生前端与 PWA
│   ├── index.html + app.js     # 前台：时钟 / 渲染 / 筛选 / 图标重试
│   ├── admin.html + admin.js   # 后台：登录 / 增删改 / 未保存保护
│   ├── style.css               # 前后台共用样式（含明暗主题变量）
│   └── manifest.webmanifest + icon.svg
├── tests/               # pytest：纯函数 + API 测试
├── docs/                # README 截图
├── .github/             # CI、镜像发布、Dependabot、Issue / PR 模板
├── Dockerfile / docker-compose.yml
├── requirements.txt / requirements-dev.txt
├── pyproject.toml       # pytest / ruff 配置
├── Makefile
└── data/                # 运行时数据（仓库内为演示书签）
```

## 贡献

欢迎提交 Issue 和 PR！请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。
安全漏洞请按 [SECURITY.md](SECURITY.md) 私密报告，不要开公开 issue。

## 许可证

[MIT License](LICENSE) © 2026 Xiaolong Zhang
