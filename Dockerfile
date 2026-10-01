# Nav 个人导航页 —— 仅用 Python 标准库，镜像里不需要安装任何依赖
FROM python:3.12-alpine

WORKDIR /app
COPY . .

ENV NAV_PORT=8091
EXPOSE 8091

# 书签数据与会话密钥都落在 /app/data，部署时挂载卷持久化
VOLUME /app/data

CMD ["python3", "-u", "server.py"]
