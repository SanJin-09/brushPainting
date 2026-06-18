from __future__ import annotations

import uuid
from datetime import datetime, timezone

from PIL import Image

from model_runtime.generator import generate_image
from model_runtime.sam_engine import segment_image
from services.api.app.db.database import SessionLocal
from services.api.app.models.entities import ImageAsset, Job, SegmentationResult, Version
from services.api.app.models.enums import ImageStatus, JobStatus, JobType, VersionKind
from services.api.app.services.storage import LocalStorage

storage = LocalStorage()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _progress(db, job: Job, percent: int, message: str) -> None:
    job.progress = max(0, min(100, percent))
    job.progress_message = message
    db.commit()


def run_generation(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if not job or not job.image_id:
            return
        image = db.get(ImageAsset, job.image_id)
        if not image:
            return

        try:
            job.status = JobStatus.RUNNING.value
            job.started_at = _now()
            image.status = ImageStatus.RUNNING.value
            _progress(db, job, 10, "正在准备推理任务")

            payload = job.input_payload or {}
            seed = int(payload["seed"])
            user_prompt: str | None = None
            parent_version_id: str | None = None
            if job.type == JobType.SEMANTIC_EDIT.value:
                parent_version_id = str(payload["version_id"])
                parent = db.get(Version, parent_version_id)
                if not parent or parent.image_id != image.id:
                    raise RuntimeError("语义编辑指定版本不存在")
                source_url = parent.output_url
                user_prompt = str(payload["user_prompt"])
                kind = VersionKind.SEMANTIC_EDIT.value
            elif job.type == JobType.REGENERATE.value:
                source_url = image.original_url
                kind = VersionKind.REGENERATE.value
            else:
                source_url = image.original_url
                kind = VersionKind.INITIAL.value

            _progress(db, job, 25, "正在读取输入图片")
            with Image.open(storage.url_to_path(source_url)) as source:
                _progress(db, job, 35, "正在生成工笔图片")
                output, params = generate_image(source.convert("RGB"), seed=seed, user_prompt=user_prompt)

            _progress(db, job, 90, "正在保存生成结果")
            version_id = str(uuid.uuid4())
            output_url = storage.save_output(image.id, version_id, output)
            version = Version(
                id=version_id,
                image_id=image.id,
                parent_version_id=parent_version_id,
                kind=kind,
                output_url=output_url,
                user_prompt=user_prompt,
                seed=seed,
                params_json=params,
            )
            db.add(version)
            db.flush()
            image.active_version_id = version.id
            image.status = ImageStatus.SUCCEEDED.value
            job.status = JobStatus.SUCCEEDED.value
            job.progress = 100
            job.progress_message = "生成完成"
            job.result_version_id = version.id
            job.finished_at = _now()
            db.commit()
        except Exception as exc:
            job.status = JobStatus.FAILED.value
            job.error = str(exc)
            job.progress_message = "生成失败"
            job.finished_at = _now()
            image.status = ImageStatus.FAILED.value
            db.commit()
            raise


def run_segmentation(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if not job or not job.image_id:
            return
        image = db.get(ImageAsset, job.image_id)
        if not image:
            return

        payload = job.input_payload or {}
        user_prompt = str(payload.get("user_prompt", ""))

        try:
            job.status = JobStatus.RUNNING.value
            job.started_at = _now()
            image.status = ImageStatus.RUNNING.value
            _progress(db, job, 10, "正在加载 SAM 3 模型")

            with Image.open(storage.url_to_path(image.original_url)) as source:
                _progress(db, job, 20, f"正在按提示词「{user_prompt}」分割目标...")
                segments = segment_image(source.convert("RGB"), user_prompt=user_prompt)

            if not segments:
                job.status = JobStatus.FAILED.value
                job.error = f"未检测到与「{user_prompt}」匹配的目标"
                job.progress_message = "分割失败：无匹配目标"
                job.finished_at = _now()
                image.status = ImageStatus.FAILED.value
                db.commit()
                return

            _progress(db, job, 70, f"检测到 {len(segments)} 个目标，正在保存...")
            for i, seg in enumerate(segments):
                seg_id = str(uuid.uuid4())
                crop_url = storage.save_segment(image.id, seg_id, seg.crop)
                db.add(SegmentationResult(
                    id=seg_id,
                    source_image_id=image.id,
                    user_prompt=user_prompt,
                    region_index=i,
                    confidence=seg.confidence,
                    crop_url=crop_url,
                    bbox_x=seg.bbox[0], bbox_y=seg.bbox[1],
                    bbox_w=seg.bbox[2], bbox_h=seg.bbox[3],
                    area_ratio=seg.area_ratio,
                ))

            image.status = ImageStatus.SEGMENTED.value
            job.status = JobStatus.SUCCEEDED.value
            job.progress = 100
            job.progress_message = f"按「{user_prompt}」分割完成，共 {len(segments)} 个子图"
            job.finished_at = _now()
            db.commit()
        except Exception as exc:
            job.status = JobStatus.FAILED.value
            job.error = str(exc)
            job.progress_message = "分割失败"
            job.finished_at = _now()
            image.status = ImageStatus.FAILED.value
            db.commit()
            raise
