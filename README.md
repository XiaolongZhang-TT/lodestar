# Nav · 个人导航页

一个轻量的个人导航页（Flare 替代品）：**Flask 单文件后端 + 原生前端**，
带登录后台管理，数据落盘为 JSON。书签已从原 Flare 实例全部迁移。

## 功能

- 🕐 大时钟 + 按时段问候语
- 🧩 卡片式书签，自动解析网站图标（favicon / 页面声明的图标），失败回退彩色首字母方块，也可用 emoji 覆盖
- 🔍 本地书签筛选（按 `/` 聚焦，即时过滤，不是搜索引擎）
- 🔐 **后台管理**（`/admin`）：登录后可增删改分类和链接、设置页面标题，保存即生效；未保存有提醒，网址缺协议自动补全
- 🌙 明 / 暗双主题：默认跟随系统，手动切换后会记住
- 📱 响应式布局 + PWA（手机可「添加到主屏幕」全屏使用）

## 快速开始（本机）

```bash
cd nav_me
pip install -r requirements.txt
python3 server.py
# 主页  http://127.0.0.1:8091
# 后台  http://127.0.0.1:8091/admin
```

默认账号 `admin` / `nav-admin`（启动日志会提醒修改）。**正式部署务必换掉**：

```bash
NAV_USER=你的用户名 NAV_PASS=你的密码 python3 server.py
```

## Docker 部署（推荐，NAS / 服务器）

项目自带 [Dockerfile](Dockerfile) 和 [docker-compose.yml](docker-compose.yml)：

```bash
# 1. 先改 docker-compose.yml 里的 NAV_USER / NAV_PASS
# 2. 把整个项目目录拷到服务器（git clone 或 scp），然后在目录里执行：
docker compose up -d --build

# 主页  http://服务器IP:8091
# 后台  http://服务器IP:8091/admin
```

- **在目标机器上构建**：基础镜像 `python:3.12-alpine` 支持 x86 和 ARM，
  Mac 上构建出的镜像架构与 NAS 不同，直接在 NAS 上 `--build`，不要导出镜像搬运
- 构建需访问 Docker Hub 和 PyPI；若网络受限，可为 Docker 配置镜像加速，
  并把 Dockerfile 中的 pip 源换成国内镜像（如清华源）
- **数据持久化**：书签、会话密钥、图标缓存都在 `./data`（compose 已挂载），
  备份这个目录即可；`data/` 不会被打进镜像
- 更新版本：代码更新后再执行一次 `docker compose up -d --build`

建议置于反向代理之后提供 HTTPS（沿用你现有的 example.com 域名即可）。

## 数据与安全

| 文件 | 说明 |
|---|---|
| `data/bookmarks.json` | 全部书签数据，保存时自动滚动备份 |
| `data/backups/` | 历史备份（保留最近 10 份），误删可从这里找回 |
| `data/secret.key` | 登录会话的 HMAC 签名密钥，首次启动自动生成（权限 600，框架不会把它当静态文件暴露） |
| `data/icons/` | 网站图标缓存：成功 7 天、失败 1 小时后自动重试；删掉即可强制重取 |

- 登录：`POST /api/login` 校验账号密码（常量时间比较 + 失败延迟 0.5s），
  颁发 HttpOnly 签名 Cookie，有效期一周
- 数据保存接口 `POST /api/data` 必须携带有效会话；主页读取 `GET /api/data` 无需登录
- 图标代理 `/api/icon` 只解析书签中出现的 host，防止被当公开代理滥用
- 会话密钥泄露的处置：删除 `data/secret.key` 并重启（所有人需重新登录）

## 书签怎么维护

全部在 `http://你的地址/admin` 完成：

- 分类：改名 / 换 emoji 图标 / 新增 / 删除（删除需确认）
- 链接：每行四个字段——图标 emoji（可空）、名称、网址、备注（可空），可增删
- 顶部可改页面标题和问候语中的名字；改完点「保存」即写入数据文件

## 定制外观

设计变量集中在 [static/style.css](static/style.css) 顶部的 `:root`：

- `--accent` / `--accent-2`：主题色渐变（默认靛蓝 → 紫）
- `--radius`：卡片圆角
- `body::before`：背景光斑的三个渐变，可改成任何颜色或删掉

## 文件结构

```
nav_me/
├── server.py            # Flask 后端：路由按「方法 + 路径」逐个拆分
├── requirements.txt     # Python 依赖（已锁版本）
├── tests/               # 纯函数单元测试（pytest）
├── static/              # 前端（Flask 静态目录）
│   ├── index.html + app.js    # 前台：时钟 / 渲染 / 筛选 / 图标重试
│   ├── admin.html + admin.js  # 后台：登录 / 增删改 / 未保存保护
│   ├── style.css              # 前后台共用样式（含明暗主题变量）
│   └── manifest.webmanifest + icon.svg   # PWA
├── Dockerfile / docker-compose.yml
└── data/                # 运行时数据（书签 / 备份 / 密钥 / 图标缓存）
```
