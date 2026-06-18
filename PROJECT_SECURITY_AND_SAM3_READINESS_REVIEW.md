# 项目漏洞、设计缺陷与 SAM3 接入准备度审查

审查日期：2026-06-18  
审查范围：FastAPI API、Redis/RQ Worker、本地存储与 SQLite、Docker 部署、Web 前端、模型运行时及仓库内置 SAM3 源码。

## 1. 结论

当前项目已经完成 SAM3 的开发级调用链：API、RQ 任务、模型加载、文本提示分割、Mask/透明子图保存和前端展示均已接通，调用方式也与官方接口一致。

但项目**尚不具备直接暴露到公网或作为无人值守生产服务运行的条件**。主要阻断项如下：

1. Redis 通过宿主机端口无鉴权暴露，而 RQ 默认使用不安全的 Pickle 反序列化，组合后存在 Worker 任意代码执行风险。
2. API 没有认证、授权、限流和资源配额，上传、推理、导出及媒体访问均可匿名调用。
3. 数据库没有迁移机制；模型字段变化仅依赖 `create_all()`，旧部署升级时可能直接出现缺列或索引不一致。
4. 数据库任务记录与 Redis 入队不是原子操作，且没有过期任务恢复机制，API/Worker 崩溃后图片可能永久卡在 `queued` 或 `running`。
5. SAM3 面向中文用户，但官方模型标注语言为英语；当前中文提示词未经翻译或规范化直接送入模型，质量风险尚未验证。
6. 真实权重、显存峰值、模型冷热切换、长时间稳定性和 API 全链路尚未通过 GPU 验收。
7. 仓库分发了完整 SAM3 源码，却没有同时保留官方 SAM License，存在许可证合规缺口。
8. 前后端锁定的依赖中存在已公开漏洞，尤其涉及图片解析和 multipart 上传的漏洞与本项目入口直接相关。

综合判断：**SAM3 接入准备“部分到位”，开发联调基本完成，生产安全、可运维性和模型质量验证未完成。**

## 2. 已经做对的部分

- `services/model_runtime/model_runtime/sam_engine.py:92-114` 使用独立的 `SAM3_BACKEND`、本地 checkpoint、设备和置信度配置，避免与生成模型后端混用。
- `sam_engine.py:165-181` 使用官方 `set_image()` + `set_text_prompt()` 状态接口，并校验 masks/scores 数量和维度。
- `services/worker/tasks.py:128-133` 在加载 SAM3 前释放生成模型；生成任务也会反向释放 SAM3，已经考虑单 GPU 显存竞争。
- checkpoint 通过 `torch.load(..., weights_only=True)` 加载，降低恶意 Pickle 权重执行风险，见 `services/model_runtime/sam3/model_builder.py:539-556`。
- 上传图片执行格式验证、Pillow `verify()`、EXIF 方向修正、文件大小和最大边限制，见 `services/api/app/services/storage.py:30-49`。
- 媒体路由限制目录和后缀，并阻止路径穿越，见 `storage.py:121-133`。
- 同一图片的活动任务通过应用检查和 SQLite 部分唯一索引双重约束，见 `services/api/app/models/entities.py:85-94`。
- SAM3 官方源码比对结果良好：仓库内 `services/model_runtime/sam3` 与官方仓库 2026-06-15 的 `5dd401d1c5c1d5c3eedff06d41b77af824517619` 提交内容一致，差异仅为本地 `__pycache__`。
- 当前测试结果为 `21 passed`，前端 `npm run build` 也通过。

## 3. 高优先级安全问题

### P0-1 Redis 暴露与 RQ Pickle 可组合成远程代码执行

证据：

- `infra/docker/docker-compose.yml:5-6` 将 Redis 映射到宿主机 `0.0.0.0:6380`。
- Redis URL 没有用户名或密码，见 `docker-compose.yml:16`。
- `services/api/app/services/job_service.py:49` 和 `services/worker/rq_worker.py:14` 均使用 RQ 默认序列化器。
- RQ 官方文档明确说明默认序列化器为 Pickle，恶意数据在反序列化时可以执行任意代码。
- Redis 官方 Docker 镜像为方便容器互联，默认关闭 protected mode；官方说明在使用 `-p` 暴露端口后会成为无密码开放实例。

影响：

只要攻击者能访问 6380 端口，就可能写入恶意 RQ 数据并在 GPU Worker 中触发反序列化。Worker 同时挂载项目目录、运行时目录和模型目录，后果包括代码执行、文件破坏、模型窃取及 GPU 资源滥用。

建议：

- 生产环境删除 Redis 的 `ports`，只保留 Docker 内部网络；确需宿主机访问时至少绑定 `127.0.0.1`。
- 启用 Redis ACL/密码，并限制防火墙来源。
- Queue 和 Worker 同时切换为 RQ `JSONSerializer`，当前任务参数只有字符串，适合 JSON。
- Redis 与 API/Worker 使用独立私有网络，不允许 Web 容器访问 Redis。

参考：

- [RQ Jobs：默认 Pickle 安全警告](https://python-rq.org/docs/jobs/)
- [Redis 官方镜像安全说明](https://hub.docker.com/_/redis)

### P0-2 API 无认证且默认监听所有网卡

证据：

- `infra/docker/api.Dockerfile:31` 和 `start_host.sh:18` 使用 `--host 0.0.0.0`。
- 所有上传、生成、编辑、分割、导出、任务和媒体接口均没有用户身份依赖。
- `services/api/app/main.py:25-31` 配置了通配 CORS，并允许 credentials。

影响：

任何可访问 8000 端口的人都能读取上传图片和结果、提交 GPU 任务、制造大量导出文件并持续消耗磁盘、内存和 GPU。

建议：

- 至少增加 API Key；多用户环境应增加用户/租户模型和对象级授权。
- CORS 改为明确的前端域名列表，未使用 Cookie 时关闭 `allow_credentials`。
- 在反向代理和应用层同时设置请求体限制、速率限制、并发任务限额和租户磁盘配额。
- 媒体文件改为鉴权下载或短时签名 URL。

### P1-1 图片上传与导出存在可利用的资源耗尽面

证据：

- `services/api/app/services/image_service.py:32-36` 会将一个批次内所有图片完整读取、解码，并保留在 `prepared` 列表中。
- 允许 5 张、每张最大边 8192 的 RGB 图片；理论解码数据仅像素就约为 `5 × 8192 × 8192 × 3 ≈ 960 MiB`，尚未计算 Pillow 对象、缩略图和编码缓冲。
- 每次调用导出都会生成新 ZIP，见 `storage.py:93-106`。
- 不同分割提示词的结果会一直保留，没有总量上限或清理策略。

影响：

匿名请求可以造成 API 内存峰值、CPU 解码压力和磁盘持续增长。

建议：

- 降低像素总量限制，并增加“单批总像素数”而非只检查单图最大边。
- 图片逐个校验、落盘和释放，不要同时保存全部解码对象。
- 为上传、输出、分割结果和导出增加保留期限及后台清理任务。
- 对同一批次导出结果做复用，或生成后设置短期 TTL。

### P1-2 依赖存在已知漏洞

2026-06-18 执行审计：

- `pip-audit --vulnerability-service osv`：当前 Python 环境报告 7 个包包含已知漏洞。
- `npm audit --omit=dev`：报告 5 个生产依赖包受影响，其中 4 个为 high。

与本项目直接相关的 Python 运行时问题：

| 包 | 当前版本 | 风险 | 建议最低修复版本 |
| --- | --- | --- | --- |
| Pillow | 11.1.0 | PSD/FITS/字体解析越界、整数溢出或 DoS | 12.2.0 |
| python-multipart | 0.0.20 | multipart 头部/前后缀 DoS、参数混淆等 | 0.0.31 |
| Starlette | 0.41.3 | multipart、Range、Host/path 处理相关漏洞 | 升级 FastAPI 后使用其兼容的已修复 Starlette |
| python-dotenv | 1.0.1 | `set_key` 符号链接文件覆盖 | 1.2.2 |

前端审计涉及：

- `axios@1.13.6`
- `follow-redirects@1.15.11`
- `form-data@4.0.5`
- `react-router@7.13.1`
- `react-router-dom@7.13.1`

其中部分公告针对 Node Adapter、RSC 或当前项目未使用的功能，实际可达性需要进一步确认，但仍应升级锁文件并重新审计。

建议：

1. 优先升级 `Pillow`、`python-multipart`、FastAPI/Starlette。
2. 更新前端直接依赖，重新生成 `apps/web/package-lock.json`。
3. CI 增加 `pip-audit`、`npm audit` 和镜像扫描。
4. 不要只写宽泛下限；生产环境应生成完整 lock/constraints 文件。

### P1-3 仓库跟踪了环境备份和凭据样式字段

`.env.host` 与 `.env.bak.20260319-125438` 均被 Git 跟踪，后者包含 MinIO access/secret 字段。即使当前值只是默认值，也会培养把真实凭据提交到仓库的习惯。

建议：

- 从版本控制移除 `.env.host`、`.env.bak*`，只保留无秘密的 `.env.example`。
- `.gitignore` 增加 `.env.*`，再对白名单 `.env.example` 取反。
- 若这些值曾用于真实环境，应轮换相关凭据。

## 4. 数据一致性与任务系统缺陷

### P1-4 没有数据库迁移，旧实例不能可靠升级

`services/api/app/main.py:17-20` 仅在启动时调用 `Base.metadata.create_all()`。该操作会创建缺失表，但不会把新列、约束和索引可靠地迁移到现有表。

当前 SAM3 相关开发已经涉及 `segments` 表字段、关系和索引变化，因此旧的 `runtime/db.sqlite` 可能与代码不一致。

建议：

- 引入 Alembic。
- 为 `segments.mask_url`、索引、状态值兼容等变化编写显式 migration。
- 启动时校验 schema revision，不匹配时拒绝提供服务。

参考：[SQLAlchemy 关于使用迁移工具修改既有数据库对象的说明](https://docs.sqlalchemy.org/en/latest/faq/metadata_schema.html)

### P1-5 创建任务与入队不是原子流程

`services/api/app/services/job_service.py:19-44` 先提交数据库任务，`routes.py:129-139` 再调用 Redis 入队。

异常窗口包括：

- 数据库提交成功后 API 进程崩溃：任务永久停留在 `queued`，实际并未进入 Redis。
- Redis 入队成功后 API 在刷新或响应前崩溃：客户端重试可能得到冲突，但不知道原任务状态。
- Worker 取走任务后进程崩溃：数据库可能停留在 `running`。

活动任务唯一索引会让这些僵尸任务永久阻止该图片提交新任务。

建议：

- 实现 transactional outbox，由独立 dispatcher 将待投递记录可靠写入 Redis。
- 或至少增加周期性 reconciliation：比对 DB、RQ Queue、Started/Failed Registry，修复超时任务。
- 设置 RQ `ttl`，为排队任务增加最大等待时间。
- 增加取消、重试和管理员解锁接口。
- Worker 启动时扫描并修复上一次异常退出遗留的 `running` 任务。

### P1-6 Worker 任务不具备严格幂等性

`run_generation()` 和 `run_segmentation()` 没有先验证 Job 是否仍为 `queued`，重复执行同一 job 可能重复创建版本或覆盖分割结果。任务重试、重复投递或运维手工重跑时会出现副作用。

建议：

- 通过条件更新实现状态机：仅允许 `queued -> running -> succeeded/failed`。
- 在数据库中记录 attempt，并对结果使用 job ID 作为幂等键。
- 对版本创建和任务完成状态使用同一数据库事务。

### P1-7 数据库与文件系统提交不一致

生成和分割流程会先写文件再提交数据库。如果文件写入中途或数据库提交失败，会留下孤儿文件；反之，数据库已有 URL 但文件删除/损坏时也没有修复机制。

建议：

- 先写临时文件，数据库提交成功后原子 rename。
- 异常路径显式删除本次新建文件。
- 定期扫描数据库引用与磁盘文件，清理孤儿并报告缺失文件。

### P2-1 图片状态模型不一致

- 分割失败会通过 `_restored_image_status()` 恢复为已有版本对应的状态。
- 生成、重生成或语义编辑失败时，`services/worker/tasks.py:101-107` 总是把图片标记为 `failed`，即使旧的 active version 仍然有效。
- 任务入队失败时 `routes.py:134-138` 也会把已有成功版本的图片标为失败。

建议：图片“是否有可用版本”和“最近一次任务是否失败”应拆成两个维度，避免复用一个 `status` 字段表达不同含义。

### P2-2 前后端超时策略冲突

- 后端 RQ 任务超时为 4 小时，见 `job_service.py:60`。
- 前端轮询 20 分钟后停止，见 `apps/web/src/pages/ImageDetailPage.tsx:16-17`。

前端显示超时后，任务仍可能继续占用 GPU 且锁住图片。建议由后端返回预计超时/截止时间，并提供取消接口；前端超时不应被描述为任务已经终止。

## 5. SAM3 接入准备度专项评估

### 5.1 准备度矩阵

| 项目 | 状态 | 结论 |
| --- | --- | --- |
| 官方图像分割 API 接线 | 已完成 | 调用链正确 |
| Mask、bbox、透明子图落盘 | 已完成 | Mock 流程有测试 |
| Python/PyTorch/CUDA 基础版本 | 基本完成 | 满足官方最低要求 |
| 官方源码完整性 | 已确认 | 与 2026-06-15 官方 main 一致 |
| 权重下载 | 部分完成 | gated 流程存在，但 revision 默认未锁定 |
| 许可证合规 | 未完成 | vendored 源码缺少 SAM License |
| 中文提示词适配 | 未完成 | 无翻译、词表或质量基准 |
| 真实 GPU 推理 | 未验证 | 本地无 `sam3.pt`，测试均为 Mock/Fake |
| 显存与模型切换稳定性 | 未验证 | 无峰值、碎片和交替任务测试 |
| 健康检查与可观测性 | 未完成 | `/healthz` 不能反映 Worker、GPU 或模型状态 |
| 灰度、回滚与版本兼容 | 未完成 | 无模型/code revision 元数据和兼容校验 |

### 5.2 中文产品界面与英语模型存在质量错配

Hugging Face 官方模型页将 `facebook/sam3` 标注为英语模型，官方示例也使用英语名词。当前前端却提示用户输入“人物、花、鸟”，后端在 `sam_engine.py:165-169` 原样发送中文。

这不一定导致程序错误，但可能造成漏检、误检或不同中文表达之间结果不稳定，是当前最重要的模型质量风险。

建议：

- 第一阶段在后端增加可审计的中译英步骤，并同时保存原始提示词与模型提示词。
- 对常用工笔画对象建立受控词表和同义词映射。
- 使用真实业务图片构建最小回归集，至少覆盖人物、服饰、花卉、鸟兽、器物、建筑及属性短语。
- 指标至少包含：有目标召回率、无目标误检率、实例完整率、Mask IoU、平均延迟和峰值显存。
- 不要在没有基准结果前宣称中文“开放词汇”已经可用。

参考：[Hugging Face `facebook/sam3` 模型页](https://huggingface.co/facebook/sam3)

### 5.3 权重和源码版本没有形成可复现绑定

`scripts/prepare_offline_models.sh:5` 默认 `SAM3_REVISION=main`。这意味着不同日期构建的离线包可能下载到不同权重，而 vendored 源码也没有记录其上游提交。

虽然本次比对确认源码当前等同于官方 `5dd401d...`，但仓库本身没有可供 CI 验证的 provenance 文件。

建议：

- 将 `SAM3_REVISION` 默认值固定为经过验收的 Hugging Face commit SHA。
- 增加 `THIRD_PARTY_SAM3.md` 或 manifest，记录官方仓库 URL、Git commit、HF revision、checkpoint SHA-256、许可证和同步日期。
- Worker 启动时计算 checkpoint hash，并与允许列表比较。
- 将 code revision、checkpoint hash、阈值、设备、耗时和峰值显存写入任务结果元数据。

### 5.4 缺少 SAM License

官方 `LICENSE` 要求分发 SAM Materials 或其衍生物时同时提供协议副本。本项目跟踪了 193 个 SAM3 文件、约 67,243 行 Python 源码，但没有跟踪官方 `LICENSE`、README 或 provenance。

建议：在继续分发或部署前补充官方 SAM License，并保留第三方版权声明。该问题不应仅靠每个源码文件头部的 Copyright 代替。

参考：[SAM3 官方仓库 License 章节](https://github.com/facebookresearch/sam3#license)

### 5.5 真实 GPU 验证脚本不够生产化

`scripts/verify_sam3.sh` 能检查依赖、CUDA、模型加载和单图推理，这是有价值的起点，但存在以下缺口：

- 每次执行都运行 `pip install`，会修改当前环境，且离线服务器上无法可靠执行。
- 没有检查 checkpoint SHA、源码 revision 和依赖 lock。
- 只验证一次推理结果数量，不验证 Mask 质量。
- 不记录冷启动时间、热启动时间、峰值显存和推理后残留显存。
- 不验证 `Qwen -> SAM3 -> Qwen -> SAM3` 多轮切换。
- 不通过 API、Redis、Worker、数据库和文件系统完成全链路测试。
- 输入图片路径被直接插入 `python -c` 字符串，路径包含引号时会失败。

建议把验证拆为：

1. 只读环境自检，不安装任何包。
2. 模型直接推理 smoke test。
3. Compose API 全链路测试。
4. 显存切换压力测试。
5. 固定回归集质量测试。

### 5.6 健康检查不能反映模型服务真实状态

`services/api/app/main.py:43-45` 的 `/healthz` 永远只返回 `ok`。当 Redis 不可用、Worker 已退出、GPU 不可见、权重缺失或 SAM3 首次加载必然失败时，API 仍显示健康。

建议至少拆分：

- `/livez`：API 进程是否存活。
- `/readyz`：数据库、Redis、至少一个 Worker 心跳是否可用。
- 模型能力状态：SAM3/Qwen 是否启用、checkpoint 是否存在、最近一次加载错误。
- Worker 指标：队列长度、任务年龄、GPU 显存、模型当前驻留状态、加载/推理耗时。

`SAM3_PRELOAD=false` 可以避免 SAM3 故障阻塞 Qwen，但必须由能力状态接口明确告诉调用方“分割暂不可用”，不能仅在首个用户任务中暴露错误。

### 5.7 设备和参数配置缺少约束

`sam_engine.py` 直接使用 `os.getenv()`，没有复用 `Settings` 中已经定义的字段，也没有范围校验：

- `SAM3_DEVICE=cuda:0` 会通过 CUDA 可用性检查，但官方 `_setup_device_and_mode()` 只在设备字符串严格等于 `"cuda"` 时执行 `model.cuda()`，可能造成模型和输入不在同一设备。
- score threshold 未限制在 `[0, 1]`。
- max results 可配置为负数或极大值。
- min area ratio 未限制在 `[0, 1]`。

建议：

- 使用唯一的强类型配置对象，并在 Worker 启动时校验。
- 当前实现先把设备限制为 `cpu` 或 `cuda`；如需多卡，显式修正模型 `.to(device)`。
- 为阈值、数量和路径增加范围/存在性校验。

### 5.8 当前显存切换只有“释放缓存”，没有容量治理

`release_runtime()` 的 `cache_clear()`、`gc.collect()` 和 `torch.cuda.empty_cache()` 是合理的基础措施，但不能保证：

- 所有张量引用均已释放。
- CUDA allocator 碎片不会累积。
- 22 GiB 级 GPU 能稳定完成两种大模型交替加载。
- 模型加载失败后 Worker 能继续服务另一种任务。

建议：

- 记录每个阶段的 `memory_allocated`、`memory_reserved` 和 peak memory。
- 进行至少 50 轮生成/分割交替压力测试。
- 对 CUDA OOM 分类处理：清理缓存后有限重试，仍失败则重启 Worker。
- 如果模型切换耗时或碎片不可接受，拆成两个 GPU Worker/队列，或使用独立推理进程管理生命周期。

## 6. 设计冗余与可维护性问题

### P2-3 vendored SAM3 范围远超当前需求

项目仅直接使用 `model_builder.py` 和 `model/sam3_image_processor.py`，但仓库纳入了训练、评估、Agent、视频、多 GPU 和大量可视化代码。部分 model/perflib 文件是图像模型依赖，但 `train`、`eval`、`agent` 等大部分目录不在当前调用链。

影响：

- 增加依赖、许可证、漏洞和同步审查成本。
- 上游升级时难以识别本项目真正受影响的代码。
- 容易让“代码已存在”被误认为“相关能力已支持”。

建议优先选择以下一种方式：

1. 将官方 SAM3 作为固定 commit 的 Python 包/子模块安装，不复制源码。
2. 若必须 vendoring，保留明确的上游同步脚本、commit manifest 和最小必要文件清单。

### P2-4 两套模型运行时存在重复生命周期代码

`generator.py` 与 `sam_engine.py` 重复实现 `_require_path()`、LRU cache、preload、release、GC 和 CUDA cache 清理；配置又同时存在于 `Settings` 和 `os.environ` 读取中。

建议抽象 `ModelRuntimeManager`，统一：

- 配置校验。
- 当前驻留模型。
- 加载/释放锁。
- 显存指标。
- OOM 恢复。
- 健康状态。
- 模型 revision 元数据。

### P2-5 Compose 同时承担开发和生产角色

`docker-compose.yml` 中存在以下开发特征：

- `APP_ENV=development`。
- 将整个 `services` 目录以可写 bind mount 覆盖镜像内容。
- Web 使用 Vite dev server，而非静态构建产物。
- API 和媒体地址硬编码为 `localhost`，远程客户端访问时会指向客户端自己的机器。
- Redis、API、Web 均发布宿主机端口。

建议拆成 `compose.dev.yml` 与加固后的 `compose.prod.yml`。生产镜像应不可变、非 root、只读根文件系统、最小挂载，并通过反向代理统一域名和 TLS。

## 7. 其他中低优先级问题

- `JobRead.error` 会原样返回 `str(exc)`，可能泄露本地路径、模型文件名和内部实现。对外返回错误码，详细堆栈只写服务端日志。
- `services/model_runtime/requirements.txt` 同时包含 SAM3 与 Qwen/DiffSynth 依赖，升级任一模型都会扰动另一套环境。可拆分 requirements/镜像。
- 多个依赖只写 `>=`，无法保证离线包可复现。
- `Job` 的活动任务部分唯一索引只声明了 `sqlite_where`。如果未来切换 PostgreSQL，应增加对应的 `postgresql_where`，否则数据库语义可能变化。
- 缺少结构化日志、request ID、job ID 上下文、推理耗时分布和告警。
- 没有数据删除 API、隐私保留策略或备份恢复说明。

## 8. 推荐整改顺序

### 第一阶段：上线阻断项

1. 关闭 Redis 宿主机暴露，启用 ACL，并把 RQ 改为 JSON serializer。
2. 增加 API 鉴权、CORS 白名单、限流、请求体和磁盘配额。
3. 升级 Pillow、python-multipart、FastAPI/Starlette 及前端受影响依赖。
4. 引入 Alembic 并生成当前 schema 的基线迁移。
5. 增加僵尸任务恢复、队列 TTL、取消/重试和状态机条件更新。
6. 补充 SAM License、源码 commit、权重 revision 和 checkpoint SHA。

### 第二阶段：SAM3 生产验收

1. 固定 SAM3 code + weight 版本组合。
2. 增加中文到英文提示词适配和业务词表。
3. 建立真实图片回归集及质量指标。
4. 完成冷/热启动、峰值显存、50 轮模型切换、OOM 恢复测试。
5. 完成 API -> Redis -> Worker -> SAM3 -> DB -> 文件输出的真实 GPU E2E。
6. 增加 readiness、Worker 心跳和 GPU/模型指标。

### 第三阶段：架构收敛

1. 拆分开发与生产 Compose。
2. 统一模型生命周期管理和强类型配置。
3. 缩减或规范化 vendored SAM3。
4. 增加文件/数据库一致性修复和数据生命周期管理。

## 9. 建议的 SAM3 上线验收门槛

以下条件全部满足后，才建议将 `SAM3_BACKEND=sam3` 作为生产默认值：

- [ ] checkpoint revision 和 SHA-256 已固定。
- [ ] SAM License 与第三方声明已随项目分发。
- [ ] 中文提示词策略和回归集已确定。
- [ ] 真实 GPU E2E 连续运行通过。
- [ ] 生成/SAM3 交替 50 轮无 OOM、无显存持续增长。
- [ ] Worker 异常退出后任务可自动恢复或明确失败。
- [ ] Redis 不对外暴露且启用认证/ACL。
- [ ] API 已鉴权、限流并有磁盘配额。
- [ ] 数据库 migration 可在旧库上演练成功。
- [ ] `/readyz` 能识别 Redis、Worker、GPU、模型权重故障。
- [ ] 依赖审计没有未接受的高危项。
- [ ] 模型输出质量达到预先定义的召回率、误检率和 Mask 指标。

## 10. 本次验证记录与限制

已执行：

- `.venv/bin/python -m pytest -q`：21 项通过。
- `npm run build`：通过。
- `npm audit --omit=dev --registry=https://registry.npmjs.org`：发现 5 个受影响生产依赖包。
- `pip-audit --vulnerability-service osv`：发现 7 个包含已知漏洞的包。
- Docker Compose 合并配置解析：通过。
- SAM3 vendored 源码与官方 2026-06-15 `main` 对比：源码一致。

未执行：

- 真实 SAM3 checkpoint 加载与推理：工作区没有 `runtime/models/sam3/sam3.pt`。
- Qwen 与 SAM3 的真实 GPU 交替测试。
- 高并发、故障注入、Worker 崩溃恢复和磁盘耗尽测试。
- 模型中文提示词质量评估。

因此，本报告对代码路径和部署风险的判断置信度较高；对实际分割质量、延迟和显存容量只作“尚未验证”的判断。
