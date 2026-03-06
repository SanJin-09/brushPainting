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

若你之前已经跑过旧版本并保留了 postgres volume，建议先重建一次数据库：

```bash
docker compose -f infra/docker/docker-compose.yml down -v
docker compose -f infra/docker/docker-compose.yml up --build -d
```

Linux + NVIDIA GPU 推理节点可使用：

```bash
docker compose -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.gpu.yml up --build
```

默认会把宿主机模型目录挂载到容器 `/models`：

- 宿主机路径由 `MODEL_HOST_PATH` 控制（默认 `./runtime/models`）
- `.env` 中推理路径默认：
  - `SDXL_BASE_MODEL_PATH=/models/sdxl/base`
  - `SDXL_INPAINT_MODEL_PATH=/models/sdxl/inpaint`
  - `SDXL_CONTROLNET_CANNY_PATH=/models/controlnet/sdxl_canny`
  - `SDXL_LORA_PATH=/models/lora/gongbi_lora_v1.safetensors`

建议目录结构：

```text
runtime/models/
├── sdxl/
│   ├── base/
│   └── inpaint/
├── controlnet/
│   └── sdxl_canny/
└── lora/
    └── gongbi_lora_v1.safetensors
```

服务默认端口：

- API: `http://localhost:8000`
- Web: `http://localhost:5173`
- PostgreSQL (host): `localhost:5433`
- Redis (host): `localhost:6380`
- MinIO API: `http://localhost:9010`
- MinIO Console: `http://localhost:9011`

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

## Mock E2E 验收

```bash
./scripts/e2e_mock.sh
```

## 说明

当前仓库支持两套后端：

- `MODEL_BACKEND=mock`：PIL/OpenCV 的轻量模拟推理（便于开发联调）
- `MODEL_BACKEND=diffusers`：本地 SDXL + LoRA + ControlNet + Inpaint 推理（需挂载模型权重）
