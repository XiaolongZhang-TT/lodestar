# Nav 个人导航页 —— Flask + waitress，构建时装依赖
FROM python:3.12-alpine

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .
COPY static ./static

ENV NAV_PORT=8091
EXPOSE 8091

# 书签数据与会话密钥都落在 /app/data，部署时挂载卷持久化
VOLUME /app/data

CMD ["python3", "-u", "server.py"]
