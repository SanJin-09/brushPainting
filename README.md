# Gongbi Repaint Workflow

本项目实现以下闭环：

1. 上传原图，创建会话。
2. 锁定统一工笔风格。
3. 生成整图工笔版本。
4. 在当前成图上手绘粗选区。
5. 使用 mask assist 精修选区。
6. 对局部区域做 masked inpaint，生成候选版本。
7. 手动采纳候选版本为当前版本。
8. 导出当前版本与 manifest。

## 目录

- `apps/web`: React + Vite 工作台
- `services/api`: FastAPI REST API
- `services/worker`: Celery worker 与任务编排
- `services/model_runtime`: 风格化、局部重绘、mask assist 运行时
- `infra/docker`: Dockerfiles + docker compose
- `infra/sql`: 数据库初始化 SQL
- `configs/styles`: 统一风格模板
- `tests`: 单元/接口测试

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

## 模型目录

默认会把宿主机模型目录挂载到容器 `/models`：

- `SDXL_BASE_MODEL_PATH=/models/sdxl/base`
- `SDXL_INPAINT_MODEL_PATH=/models/sdxl/inpaint`
- `SDXL_CONTROLNET_CANNY_PATH=/models/controlnet/sdxl_canny`
- `SDXL_LORA_PATH=/models/lora/gongbi_lora_v1.safetensors`
- `SAM_MODEL_PATH=/models/sam/sam_vit_b.pth`

建议目录结构：

```text
runtime/models/
├── sdxl/
│   ├── base/
│   └── inpaint/
├── controlnet/
│   └── sdxl_canny/
├── lora/
│   └── gongbi_lora_v1.safetensors
└── sam/
    └── sam_vit_b.pth
```

## 本地开发（不跑 GPU 推理）

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r services/api/requirements.txt -r services/worker/requirements.txt -r services/model_runtime/requirements.txt
uvicorn services.api.app.main:app --reload --port 8000
```

默认开发模式建议：

- `MODEL_BACKEND=mock`
- `MASK_ASSIST_BACKEND=mock`

生产或本地完整推理时可切换：

- `MODEL_BACKEND=diffusers`
- `MASK_ASSIST_BACKEND=sam`

## 关键接口

- `POST /api/v1/sessions`
- `POST /api/v1/sessions/{id}/style/lock`
- `POST /api/v1/sessions/{id}/render`
- `POST /api/v1/sessions/{id}/mask-assist`
- `POST /api/v1/sessions/{id}/edits`
- `POST /api/v1/sessions/{id}/versions/{version_id}/adopt`
- `POST /api/v1/sessions/{id}/export`
- `GET /api/v1/sessions/{id}`
- `GET /api/v1/jobs/{job_id}`

## Mock E2E 验收

```bash
./scripts/e2e_mock.sh
```

## 参考图抓取脚本

当你需要先批量收集工笔参考图，再人工审核时，可以使用：

```bash
python3 scripts/scrape_reference_images.py \
  --config scripts/scrape_reference_images.example.json \
  --verbose
```

如果环境里还没装 `httpx`，先执行：

```bash
pip install httpx
```

如果启用了图像级筛选：

- `text_density` 需要 `opencv-python-headless` 和 `numpy`
- `clip` 还需要 `torch`、`transformers` 和 `Pillow`

仓库内置了几组可直接跑的站点配置：

- `scripts/reference_scrape_configs/wikimedia_qiu_ying.json`
- `scripts/reference_scrape_configs/met_qiu_ying_api.json`
- `scripts/reference_scrape_configs/cleveland_qiu_ying_api.json`
- `scripts/reference_scrape_configs/npm_open_data_pages.json`

例如先抓一轮 Wikimedia Commons：

```bash
python3 scripts/scrape_reference_images.py \
  --config scripts/reference_scrape_configs/wikimedia_qiu_ying.json \
  --verbose
```

如果图片已经抓到本地，想补做一轮离线筛选，可以使用：

```bash
python3 scripts/filter_downloaded_reference_images.py \
  --config scripts/reference_scrape_configs/met_qiu_ying_api.json \
  --input-dir runtime/reference_scrape/filtered_met_run \
  --move-rejected-to runtime/reference_scrape/filtered_met_run_rejected \
  --verbose
```

未显式传 `--report-dir` 时，离线筛选报告会默认写到输入目录下的 `_offline_filter_reports/`。

脚本特点：

- 读取 JSON 配置，限制允许抓取的域名
- 同时支持 HTML 页面递归抓取和官方 JSON API 种子源
- 支持对 API 记录按标题、分类、媒材、标签等元数据做自动筛选
- 支持图像级第二层筛选：默认可用的文字密度启发式，可选 CLIP 零样本打分
- 默认遵守 `robots.txt`
- 支持页面链接递归抓取、图片直链下载、按 URL 规则过滤
- 自动去重，并输出 `manifest.jsonl` 与 `rejected_manifest.jsonl` 供后续人工审核
- 离线后处理脚本会输出 `offline_kept_manifest.jsonl` 与 `offline_rejected_manifest.jsonl`
- 不处理登录、验证码、反爬绕过；使用前请确认站点条款与图片授权

## 说明

当前仓库支持两套后端：

- `MODEL_BACKEND=mock`：PIL/OpenCV 的轻量模拟推理，适合开发联调和测试
- `MODEL_BACKEND=diffusers`：本地 SDXL + LoRA + ControlNet + Inpaint 推理

Mask assist 也支持两套后端：

- `MASK_ASSIST_BACKEND=mock`：形态学平滑与 bbox 回算
- `MASK_ASSIST_BACKEND=sam`：本地 SAM 模型做精确选区吸附
