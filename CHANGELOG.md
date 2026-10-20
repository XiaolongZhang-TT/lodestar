# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added

- 可选的 Docker Hub 发布工作流（配置 `DOCKERHUB_ENABLED` 与相关 Secrets 后启用）

### Fixed

- 修复 SPA 页面把 HTML 里的内联 `<svg` 误判为图标、从而缓存整页 HTML 的问题
- 图标解析改用 HTMLParser：支持多行 `<link>`、单双引号与 data: URI（含 base64）
- 支持 apple-touch-icon、mask-icon 与 Web App Manifest 图标（按尺寸选大图）
- 自动丢弃旧版误缓存的非图片数据；前端图标 URL 升级到 `v=3` 强制刷新
- 图标候选地址只允许 http(s) / data:，拒绝 `file:` 等 scheme
- 解析图标时使用重定向后的最终 URL 作为相对路径基准，修复 `/` → `/app/` 这类站点（如 Navidrome）取不到图标

### Changed

- 保存书签时只预热本次新增（或 URL 改为新 host）的图标，不再全量重复入队
- 首页图标改为先显示首字母、加载成功后淡入替换；加载失败保留首字母，不再出现约 6 秒空白块

## [1.0.0] - 2026-10-19

首个开源版本。

### Added

- 大时钟、按时段问候语与本地书签即时筛选（`/` 聚焦）
- 卡片式书签，自动解析 favicon / 页面声明的图标，失败回退彩色首字母，支持 emoji 覆盖
- 登录后台 `/admin`：分类与链接增删改、页面标题与问候名设置、未保存提醒、网址自动补全协议
- 明 / 暗双主题，默认跟随系统并记忆手动选择
- 响应式布局与 PWA，可添加到手机主屏幕全屏使用
- 数据落盘 JSON：原子写入、自动滚动备份（保留最近 10 份）、损坏时回退 `.bak`
- 图标缓存：成功 7 天、失败 10 分钟负缓存；SVG 自动补 `viewBox`
- Docker / docker compose 部署，支持 x86 与 ARM 构建
- pytest 测试与 GitHub Actions CI、多架构 GHCR 镜像发布
- MIT License、贡献指南、行为准则、安全策略、Issue / PR 模板

### Changed

- 最低 Python 版本为 3.11（Python 3.9 / 3.10 已 EOL），Docker 基础镜像为 `python:3.14-alpine`
- 依赖版本：click 8.5.0、MarkupSafe 3.0.4、pytest 9.1.1
- CI 测试矩阵覆盖 Python 3.11 / 3.14，并为 Docker 镜像增加启动冒烟测试

### Security

- 会话使用 HMAC 签名 Cookie，密钥权限 600；登录失败延迟以缓解暴力破解
- 图标代理仅允许书签中出现过的 host，避免被滥用为公开代理
- 仓库仅包含演示书签数据，真实数据通过 `.gitignore` 排除

[Unreleased]: https://github.com/XiaolongZhang-TT/lodestar/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/XiaolongZhang-TT/lodestar/releases/tag/v1.0.0
