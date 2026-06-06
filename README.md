# Gongbi Batch Repaint

单机 GPU 工笔画批处理后端。支持多图上传、批量初始生成、重生成、自然语言语义编辑、历史版本和 ZIP 导出。

当前不提供 Mask、局部圈画、Mask Assist、bbox 裁剪或羽化合成功能。

当前提交完成后端与接口替换；`apps/web` 仍是旧 Session/Mask 前端，需在后续前端交付中改接本页列出的 Batch/Image/Version/Job API。

## 架构

- API：FastAPI
- 数据库：SQLite，默认 `runtime/db.sqlite`
- 队列：Redis + RQ，单 `SimpleWorker` 串行使用 GPU
- 开发推理：`MODEL_BACKEND=mock`
- 生产推理：DiffSynth-Studio + Qwen-Image-Edit-2511 + 工笔 LoRA
- 存储：`runtime/uploads`、`runtime/outputs`、`runtime/thumbs`、`runtime/exports`

## 快速启动

```bash
cp .env.example .env
docker compose -f infra/docker/docker-compose.yml up --build
```

本地开发默认使用 Mock，不需要 GPU 和模型：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r services/api/requirements.txt -r services/worker/requirements.txt
make api
make worker
```

## 公共接口

- `POST /api/images/upload`
- `GET /api/batches/{batch_id}`
- `POST /api/batches/{batch_id}/generate`
- `POST /api/images/{image_id}/regenerate`
- `POST /api/images/{image_id}/edit`
- `GET /api/jobs/{job_id}`
- `GET /api/images/{image_id}/versions`
- `POST /api/batches/{batch_id}/export`
- `GET /media/{path}`

语义编辑请求示例：

```json
{
  "version_id": "历史版本 ID",
  "user_prompt": "把人物衣服改成红色",
  "seed": 123
}
```

## 正式离线部署

在可联网机器安装 `hf` CLI 后准备模型：

```bash
bash scripts/prepare_offline_models.sh runtime/models
```

将 `runtime/models` 随部署包复制到正式服务器，并设置：

```text
MODEL_BACKEND=diffsynth_qwen
QWEN_EDIT_MODEL_PATH=/models/qwen_image_edit_2511
QWEN_IMAGE_COMPONENTS_PATH=/models/qwen_image
QWEN_EDIT_PROCESSOR_PATH=/models/qwen_image_edit/processor
GONGBI_LORA_PATH=/models/lora/qwen_image_edit_2511_gongbi_lora_v1.safetensors
GONGBI_LORA_SCALE=1.0
```

正式运行期间不访问 Hugging Face，不需要 `HF_TOKEN`。生产目标为 80GB 以上 NVIDIA GPU，模型和 LoRA 在 RQ Worker 启动时加载并常驻 GPU。

GPU 服务器使用基础 Compose 与 GPU override 启动：

```bash
docker compose \
  -f infra/docker/docker-compose.yml \
  -f infra/docker/docker-compose.gpu.yml \
  up -d
```

联网机器可进一步准备包含 Docker 镜像和项目文件的离线部署包：

```bash
bash scripts/prepare_offline_bundle.sh
```

离线服务器解压项目包、执行 `docker load -i docker-images.tar`，再使用上述 GPU Compose 命令启动。

## 验证

```bash
pytest -q
./scripts/e2e_mock.sh
```

GPU 环境需额外验证 LoRA 整图生成、自然语言语义编辑和多图串行排队效果。
