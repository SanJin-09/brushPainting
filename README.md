# Gongbi Collage MVP

本项目实现以下闭环：

1. 上传原图，创建会话。
2. 随机分割对象子图。
3. 锁定统一工笔风格，批量生成子图效果。
4. 对不满意子图单独重生成。
5. 全部子图通过后执行 AI 衔接合成。
6. 导出最终图片与 manifest。

## 目录

- `apps/web`: React + Vite 管理台
- `services/api`: FastAPI REST API
- `services/worker`: Celery worker 与任务编排
- `services/model_runtime`: 分割/风格化/合成运行时封装
- `infra/docker`: Dockerfiles + docker compose
- `infra/sql`: 数据库初始化 SQL
- `configs/styles`: 统一风格模板
- `tests`: 单元/接口/集成测试

## 快速启动（Docker Compose）

```bash
cp .env.example .env
docker compose -f infra/docker/docker-compose.yml up --build
```

服务默认端口：

- API: `http://localhost:8000`
- Web: `http://localhost:5173`
- MinIO Console: `http://localhost:9001`

## 本地开发（不跑 GPU 推理）

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r services/api/requirements.txt -r services/worker/requirements.txt -r services/model_runtime/requirements.txt
uvicorn services.api.app.main:app --reload --port 8000
```

## 关键接口

- `POST /api/v1/sessions`
- `POST /api/v1/sessions/{id}/segment`
- `POST /api/v1/sessions/{id}/style/lock`
- `POST /api/v1/sessions/{id}/reset-generation`
- `POST /api/v1/sessions/{id}/crops/generate`
- `POST /api/v1/crops/{crop_id}/regenerate`
- `POST /api/v1/crops/{crop_id}/approve`
- `POST /api/v1/sessions/{id}/compose`
- `POST /api/v1/sessions/{id}/export`
- `GET /api/v1/sessions/{id}`
- `GET /api/v1/jobs/{job_id}`

## 说明

当前仓库中的模型运行时提供了可替换的默认实现（PIL/OpenCV 风格化与边界修复），并预留了 Diffusers + LoRA + ControlNet 接口。切换到真实 SDXL 推理只需在 `services/model_runtime/model_runtime/*.py` 中替换实现。

- 默认 `MODEL_BACKEND=mock`（可直接跑通流程）
- 若切换 `MODEL_BACKEND=diffusers`，请补齐 `torch/diffusers/transformers/accelerate/safetensors` 与模型权重，并完成 `diffusers_backend.py` 中的两个推理函数
