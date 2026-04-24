# GetVideoAnywhere

前后端分离的万能视频下载站 MVP。

## 技术栈
- 前端：Vue 3 + Vite
- 后端：FastAPI + yt-dlp
- 部署：Docker Compose + Nginx

## 本地开发

### 1) 启动后端
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### 2) 启动前端
```bash
cd frontend
npm install
npm run dev
```

默认前端请求 `http://127.0.0.1:8000`，如需修改请设置 `VITE_API_BASE_URL`。

## API 简表
- `POST /parse`：解析视频信息与格式
- `POST /download`：创建单任务下载
- `POST /download/batch`：创建批量下载任务
- `GET /tasks`：查看任务列表
- `GET /tasks/{task_id}`：查看任务详情
- `GET /file/{task_id}`：下载产物
- `POST /ai/summarize`：视频文本总结
- `POST /ai/translate`：字幕文本翻译

## Docker 一键启动
```bash
docker compose up --build
```
