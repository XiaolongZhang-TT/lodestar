# Lodestar 个人导航页 —— Flask + waitress，构建时装依赖
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

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python3 -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('NAV_PORT', '8091') + '/api/data', timeout=3)"

CMD ["python3", "-u", "server.py"]
