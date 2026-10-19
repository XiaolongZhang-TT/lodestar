# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

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
