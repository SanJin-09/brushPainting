# Gongbi Batch Repaint

<div align="center">

<h3>单机 GPU 工笔画批处理</h3>

<p>
  支持多图上传、批量初始生成、重生成、自然语言语义编辑、历史版本管理与 ZIP 导出。
</p>

<p>
  <img src="https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Database-SQLite-003B57?logo=sqlite&logoColor=white" alt="SQLite" />
  <img src="https://img.shields.io/badge/Queue-Redis%20%2B%20RQ-DC382D?logo=redis&logoColor=white" alt="Redis RQ" />
  <img src="https://img.shields.io/badge/Backend-DiffSynth--Studio-blue" alt="DiffSynth-Studio" />
  <img src="https://img.shields.io/badge/Model-Qwen--Image--Edit--2511-purple" alt="Qwen-Image-Edit-2511" />
</p>

</div>


## 项目概览

**Gongbi Batch Repaint** 是一个面向单机 GPU 推理场景的工笔画批处理后端。项目以 FastAPI 提供批处理接口，以 Redis + RQ 承接串行 GPU 推理任务，并通过 SQLite 与本地文件系统保存批次、图片、版本、缩略图和导出文件。

当前版本完成了后端能力与接口替换：

* 多图上传与批次管理
* 批量初始工笔画生成
* 单图重生成
* 基于自然语言的语义编辑
* 历史版本查询
* ZIP 结果导出
* Mock 推理环境下的本地开发与接口验证
* DiffSynth-Studio + Qwen-Image-Edit-2511 + 工笔 LoRA 的生产推理部署

## 目录

* [项目概览](#项目概览)
* [架构](#架构)
* [目录与运行时存储](#目录与运行时存储)
* [快速启动](#快速启动)
* [公共接口](#公共接口)
* [语义编辑请求示例](#语义编辑请求示例)
* [正式离线部署](#正式离线部署)
* [验证](#验证)
* [功能边界](#功能边界)
* [前端对接说明](#前端对接说明)

## 架构

### 技术栈

| 模块   | 技术选型                                              | 说明                                                                        |
| ---- | ------------------------------------------------- | ------------------------------------------------------------------------- |
| API  | FastAPI                                           | 提供图片、批次、任务、版本与导出接口                                                        |
| 数据库  | SQLite                                            | 默认数据库路径为 `runtime/db.sqlite`                                              |
| 队列   | Redis + RQ                                        | 通过单个 `SimpleWorker` 串行使用 GPU                                              |
| 开发推理 | `MODEL_BACKEND=mock`                              | 本地开发默认模式，不需要 GPU 和模型                                                      |
| 生产推理 | DiffSynth-Studio + Qwen-Image-Edit-2511 + 工笔 LoRA | 面向正式 GPU 推理环境                                                             |
| 存储   | 本地文件系统                                            | 使用 `runtime/uploads`、`runtime/outputs`、`runtime/thumbs`、`runtime/exports` |

### 后端流程

```mermaid
flowchart LR
    A[Client / Web Frontend] --> B[FastAPI Service]

    B --> C[(SQLite)]
    B --> D[Redis Queue]

    D --> E[RQ SimpleWorker]
    E --> F{MODEL_BACKEND}

    F -->|mock| G[Mock Backend]
    F -->|diffsynth_qwen| H[DiffSynth-Studio<br/>Qwen-Image-Edit-2511<br/>Gongbi LoRA]

    G --> I[Generated Outputs]
    H --> I

    I --> J[runtime/outputs]
    I --> K[runtime/thumbs]
    B --> L[runtime/uploads]
    B --> M[runtime/exports]
```

### 任务执行模型

```mermaid
sequenceDiagram
    participant U as Client
    participant A as FastAPI
    participant R as Redis / RQ
    participant W as SimpleWorker
    participant M as Model Backend
    participant S as Runtime Storage

    U->>A: Upload images
    A->>S: Save uploads
    A->>A: Create batch and image records

    U->>A: Generate / Regenerate / Edit
    A->>R: Enqueue job
    R->>W: Dispatch job
    W->>M: Run inference
    M->>S: Save output and thumbnail
    W->>A: Update job / version metadata

    U->>A: Query job / versions / export
    A->>S: Read generated files
    A-->>U: Return metadata or media path
```


## 目录与运行时存储

默认运行时文件位于 `runtime/` 下：

| 路径                  | 用途               |
| ------------------- | ---------------- |
| `runtime/db.sqlite` | SQLite 数据库       |
| `runtime/uploads`   | 用户上传的原始图片        |
| `runtime/outputs`   | 生成、重生成、语义编辑后的结果图 |
| `runtime/thumbs`    | 缩略图              |
| `runtime/exports`   | ZIP 导出文件         |
| `runtime/models`    | 离线部署时使用的模型文件目录   |


## 快速启动

### Docker Compose 启动

```bash
cp .env.example .env
docker compose -f infra/docker/docker-compose.yml up --build
```

### 本地开发启动

本地开发默认使用 Mock 后端，不需要 GPU 和模型。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r services/api/requirements.txt -r services/worker/requirements.txt
make api
make worker
```

> [!TIP]
> Mock 模式适合验证接口、任务流、数据库写入、版本记录和 ZIP 导出流程；正式图像质量验证需要切换到 `diffsynth_qwen` 后端。

## 公共接口

| Method | Path                                | 说明               |
| ------ | ----------------------------------- | ---------------- |
| `POST` | `/api/images/upload`                | 上传图片并创建批次 / 图片记录 |
| `GET`  | `/api/batches/{batch_id}`           | 查询批次详情           |
| `POST` | `/api/batches/{batch_id}/generate`  | 对批次执行初始生成        |
| `POST` | `/api/images/{image_id}/regenerate` | 对单张图片执行重生成       |
| `POST` | `/api/images/{image_id}/edit`       | 对单张图片执行自然语言语义编辑  |
| `GET`  | `/api/jobs/{job_id}`                | 查询任务状态           |
| `GET`  | `/api/images/{image_id}/versions`   | 查询图片历史版本         |
| `POST` | `/api/batches/{batch_id}/export`    | 导出批次结果 ZIP       |
| `GET`  | `/media/{path}`                     | 访问上传、输出、缩略图或导出文件 |


## 语义编辑请求示例

```json
{
  "version_id": "历史版本 ID",
  "user_prompt": "把人物衣服改成红色",
  "seed": 123
}
```

字段说明：

| 字段            | 类型     | 说明            |
| ------------- | ------ | ------------- |
| `version_id`  | string | 要基于哪个历史版本继续编辑 |
| `user_prompt` | string | 用户自然语言编辑指令    |
| `seed`        | number | 随机种子，用于结果复现   |

## 正式离线部署

### 1. 在联网机器准备模型

在可联网机器安装 `hf` CLI 后执行：

```bash
bash scripts/prepare_offline_models.sh runtime/models
```

然后将 `runtime/models` 随部署包复制到正式服务器。

### 2. 配置生产推理环境变量

在正式服务器设置：

```text
MODEL_BACKEND=diffsynth_qwen
QWEN_EDIT_MODEL_PATH=/models/qwen_image_edit_2511
QWEN_IMAGE_COMPONENTS_PATH=/models/qwen_image
QWEN_EDIT_PROCESSOR_PATH=/models/qwen_image_edit/processor
GONGBI_LORA_PATH=/models/lora/qwen_image_edit_2511_gongbi_lora_v1.safetensors
GONGBI_LORA_SCALE=1.0
```

### 3. 使用 GPU Compose 启动

```bash
docker compose \
  -f infra/docker/docker-compose.yml \
  -f infra/docker/docker-compose.gpu.yml \
  up -d
```

### 4. 准备完整离线部署包

联网机器可进一步准备包含 Docker 镜像和项目文件的离线部署包：

```bash
bash scripts/prepare_offline_bundle.sh
```

离线服务器解压项目包后执行：

```bash
docker load -i docker-images.tar
```

然后继续使用 GPU Compose 启动：

```bash
docker compose \
  -f infra/docker/docker-compose.yml \
  -f infra/docker/docker-compose.gpu.yml \
  up -d
```

## 验证

### 单元测试与 Mock E2E

```bash
pytest -q
./scripts/e2e_mock.sh
```

### GPU 环境额外验证项

GPU 环境需额外验证以下内容：

* LoRA 整图生成效果
* 自然语言语义编辑效果
* 多图任务串行排队效果
* Worker 启动后模型与 LoRA 是否正确常驻 GPU
* 批次导出 ZIP 是否包含预期输出文件
* 历史版本链路是否完整

## 功能边界

当前版本支持：

* 多图上传
* 批量初始生成
* 单图重生成
* 自然语言语义编辑
* 历史版本记录
* ZIP 导出
* Mock 开发推理
* DiffSynth-Studio + Qwen-Image-Edit-2511 + 工笔 LoRA 生产推理


## 前端对接说明

`apps/web` 当前仍是旧 Session / Mask 前端。后续前端交付时，应改接以下 API 族：

| API 族       | 主要用途                |
| ----------- | ------------------- |
| Batch API   | 批次创建、批次查询、批量生成、批次导出 |
| Image API   | 图片上传、单图重生成、单图语义编辑   |
| Version API | 图片历史版本查询            |
| Job API     | 异步任务状态查询            |
| Media API   | 上传图、输出图、缩略图、导出文件访问  |

建议前端围绕以下核心页面重构：

* 批次上传页
* 批次生成进度页
* 图片版本查看页
* 单图重生成 / 语义编辑页
* 批次 ZIP 导出页


## 开发状态

| 模块               | 状态            |
| ---------------- | ------------- |
| 后端 API           | 已完成当前版本接口替换   |
| Mock 推理          | 已支持           |
| RQ Worker 串行推理   | 已支持           |
| SQLite 元数据管理     | 已支持           |
| 本地运行时存储          | 已支持           |
| ZIP 导出           | 已支持           |
| GPU 生产推理         | 需在正式 GPU 环境验证 |
| `apps/web` 新接口适配 | 待后续前端交付       |


