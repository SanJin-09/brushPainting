# Gongbi Repaint Workflow

本项目实现以下闭环：

1. 上传原图，创建会话。
2. 锁定统一工笔风格。
3. 生成整图工笔版本。
4. 在支持局部编辑的后端上，可继续手绘粗选区。
5. 在支持局部编辑的后端上，可使用 mask assist 精修选区。
6. 在支持局部编辑的后端上，可对局部区域做 masked edit，生成候选版本。
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

- `QWEN_IMAGE_MODEL_PATH=/models/qwen_image_edit_2511`
- `SAM_MODEL_PATH=/models/sam/sam_vit_b.pth`

建议目录结构：

```text
runtime/models/
├── qwen_image_edit_2511/
├── z_image/
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

- `MODEL_BACKEND=qwen_image`
- `MASK_ASSIST_BACKEND=sam`
- `WORKER_CONCURRENCY=1`
- `WORKER_POOL=solo`

当前 Qwen 部署仅支持整图重绘；局部蒙版编辑在 `MODEL_BACKEND=qwen_image` 下会被显式禁用。
Qwen-Image-Edit-2511 运行时还需要 `torchvision`，当前仓库按 PyTorch 2.6.0 / CUDA 12.4 对应 `torchvision==0.21.0`。

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

## 合规参考图采集脚本

当你需要先批量收集工笔参考图，再人工审核时，默认使用“合规白名单开放源批处理”：

默认用途限定为：`仅内部训练与研究`。仓库内置批处理不会对授权不明站点自动下载原图，也不面向原图或数据集对外分发。

```bash
python3 scripts/run_reference_scrape_batch.py \
  --batch scripts/reference_scrape_batches/official_zero_auth_all.json \
  --output-root runtime/reference_scrape/official_zero_auth_all \
  --verbose
```

如果你只想优先跑彩色工笔倾向更强的一组站点：

```bash
python3 scripts/run_reference_scrape_batch.py \
  --batch scripts/reference_scrape_batches/official_zero_auth_colored_priority.json \
  --output-root runtime/reference_scrape/official_colored_priority \
  --verbose
```

如果环境里还没装 `httpx`，先执行：

```bash
pip install httpx
```

如果启用了图像级筛选：

- `text_density` 需要 `opencv-python-headless` 和 `numpy`
- `clip` 还需要 `torch`、`transformers` 和 `Pillow`

仓库内置的合规站点配置分两类：

- 自动下载明确开放授权图片：`met_open_access_download.json`、`cleveland_open_access_download.json`、`npm_open_license_download.json`
- 仅采集元数据，不自动下载原图：`dpm_digicol_metadata.json`、`dpm_minghuaji_metadata.json`、`smithsonian_nmaa_metadata.json`、`lacma_collections_metadata.json`、`british_museum_collection_metadata.json`

单站运行示例：

```bash
python3 scripts/scrape_reference_images.py \
  --config scripts/reference_scrape_configs/met_open_access_download.json \
  --output-dir runtime/reference_scrape/met_open_access_run_01 \
  --verbose
```

如果图片已经抓到本地，想补做一轮离线筛选，可以使用：

```bash
python3 scripts/filter_downloaded_reference_images.py \
  --config scripts/reference_scrape_configs/met_open_access_download.json \
  --input-dir runtime/reference_scrape/met_open_access_run_01 \
  --move-rejected-to runtime/reference_scrape/met_open_access_run_01_rejected \
  --verbose
```

未显式传 `--report-dir` 时，离线筛选报告会默认写到输入目录下的 `_offline_filter_reports/`。

如果你发现抓到了瓷器、玉器、青铜器等非绘画文物，可以直接在对应站点配置里补 `content_allow_patterns` / `content_deny_patterns`。离线筛选脚本会复用这组规则，不需要重新实现一套单独的过滤逻辑。

脚本特点：

- 读取 JSON 配置，按站点声明 `access_mode`、授权规则和访问节流
- 仅对白名单开放源下载图片，其余官方站点只做元数据发现
- 只走官方 API / Open Data / IIIF / 官方对象页，不做全站递归抓取
- 默认遵守 `robots.txt`，不处理登录、验证码或反爬绕过
- 下载记录强制写入 `site_id`、`object_url`、`rights`、`rights_url`、`license_check_status`
- 自动去重，并输出 `manifest.jsonl`、`rejected_manifest.jsonl` 与 `summary.json`
- 批处理入口会生成 `batch_summary.json`，便于人工版权复核
- 离线后处理脚本会输出 `offline_kept_manifest.jsonl` 与 `offline_rejected_manifest.jsonl`

## 说明

当前仓库支持两套后端：

- `MODEL_BACKEND=mock`：PIL/OpenCV 的轻量模拟推理，适合开发联调和测试
- `MODEL_BACKEND=qwen_image`：本地 `Qwen-Image-Edit-2511` 整图重绘
- `MODEL_BACKEND=zimage`：保留的回滚后端，支持整图图生图与局部重绘

默认完整推理目录示例：

```bash
hf download Qwen/Qwen-Image-Edit-2511 \
  --local-dir /home/featurize/work/brushPainting/runtime/models/qwen_image_edit_2511
```

模型运行时参数：

- `QWEN_IMAGE_MODEL_PATH`
- `QWEN_IMAGE_STEPS`
- `QWEN_IMAGE_TRUE_CFG_SCALE`
- `QWEN_IMAGE_GUIDANCE_SCALE`
- `WORKER_CONCURRENCY`
- `WORKER_POOL`
- `Z_IMAGE_MODEL_PATH`
- `Z_IMAGE_STEPS`
- `Z_IMAGE_SIZE`
- `Z_IMAGE_CFG`
- `Z_IMAGE_IMG2IMG_STRENGTH`
- `Z_IMAGE_INPAINT_STRENGTH`

模型运行时依赖需要安装兼容的 `torch`、`torchvision`、`diffusers`、`transformers`、`accelerate`、`sentencepiece`、`protobuf`。其中 PyTorch 官方旧版本页给出的 `torch==2.6.0` 对应 `torchvision==0.21.0`；当前 Qwen 编辑链路使用 `diffusers==0.36.0`。Qwen 编辑任务在本仓库内使用本地固定模板拼接 prompt，不依赖云端 prompt enhancement。

Mask assist 也支持两套后端：

- `MASK_ASSIST_BACKEND=mock`：形态学平滑与 bbox 回算
- `MASK_ASSIST_BACKEND=sam`：本地 SAM 模型做精确选区吸附
