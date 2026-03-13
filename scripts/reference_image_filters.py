from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class TextDensityFilter:
    enabled: bool
    max_score: float
    min_components: int

    @classmethod
    def load(cls, payload: dict[str, Any]) -> "TextDensityFilter":
        return cls(
            enabled=bool(payload.get("enabled", False)),
            max_score=float(payload.get("max_score", 0.58)),
            min_components=int(payload.get("min_components", 80)),
        )


@dataclass
class ClipFilter:
    enabled: bool
    model_name_or_path: str
    local_files_only: bool
    positive_prompts: list[str]
    negative_prompts: list[str]
    min_positive_score: float
    min_margin: float

    @classmethod
    def load(cls, payload: dict[str, Any]) -> "ClipFilter":
        return cls(
            enabled=bool(payload.get("enabled", False)),
            model_name_or_path=str(payload.get("model_name_or_path", "openai/clip-vit-base-patch32")),
            local_files_only=bool(payload.get("local_files_only", False)),
            positive_prompts=[str(x) for x in payload.get("positive_prompts", [])],
            negative_prompts=[str(x) for x in payload.get("negative_prompts", [])],
            min_positive_score=float(payload.get("min_positive_score", 0.30)),
            min_margin=float(payload.get("min_margin", 0.05)),
        )


@dataclass
class ImageFilterConfig:
    text_density: TextDensityFilter
    clip: ClipFilter

    @classmethod
    def load(cls, payload: dict[str, Any]) -> "ImageFilterConfig":
        return cls(
            text_density=TextDensityFilter.load(payload.get("text_density", {})),
            clip=ClipFilter.load(payload.get("clip", {})),
        )


def load_image_filter_config(path: Path) -> ImageFilterConfig:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    return ImageFilterConfig.load(payload.get("image_filter", {}))


class ImageFilterPipeline:
    def __init__(self, config: ImageFilterConfig, *, verbose: bool = False) -> None:
        self.config = config
        self.verbose = verbose
        self._clip_model = None
        self._clip_processor = None

    def assess(self, content: bytes) -> tuple[bool, dict[str, Any]]:
        diagnostics: dict[str, Any] = {}

        if self.config.text_density.enabled:
            passed, data = self._run_text_density(content)
            diagnostics["text_density"] = data
            if not passed:
                diagnostics["rejected_by"] = "text_density"
                return False, diagnostics

        if self.config.clip.enabled:
            passed, data = self._run_clip(content)
            diagnostics["clip"] = data
            if not passed:
                diagnostics["rejected_by"] = "clip"
                return False, diagnostics

        return True, diagnostics

    def _run_text_density(self, content: bytes) -> tuple[bool, dict[str, Any]]:
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "text_density filter requires opencv-python-headless and numpy in the executing environment"
            ) from exc

        data = np.frombuffer(content, dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if image is None:
            return False, {"error": "decode_failed"}

        height, width = image.shape[:2]
        long_edge = max(height, width)
        if long_edge > 1600:
            scale = 1600 / float(long_edge)
            image = cv2.resize(
                image,
                (max(1, int(width * scale)), max(1, int(height * scale))),
                interpolation=cv2.INTER_AREA,
            )

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        binary = cv2.morphologyEx(
            binary,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)),
        )

        num_labels, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        image_area = float(binary.shape[0] * binary.shape[1])
        small_component_count = 0
        small_component_area = 0.0
        for idx in range(1, num_labels):
            area = float(stats[idx, cv2.CC_STAT_AREA])
            width_i = float(stats[idx, cv2.CC_STAT_WIDTH])
            height_i = float(stats[idx, cv2.CC_STAT_HEIGHT])
            if area < 8 or area > image_area * 0.003:
                continue
            if width_i <= 1 or height_i <= 1:
                continue
            aspect = width_i / max(height_i, 1.0)
            if 0.08 <= aspect <= 12:
                small_component_count += 1
                small_component_area += area

        dark_pixel_ratio = float((binary > 0).sum()) / image_area
        row_activity = ((binary > 0).sum(axis=1) / binary.shape[1] > 0.03).mean()
        col_activity = ((binary > 0).sum(axis=0) / binary.shape[0] > 0.03).mean()
        monochrome_score = 1.0 - float(hsv[:, :, 1].mean()) / 255.0
        component_density = small_component_count / max(image_area / 1_000_000.0, 1e-6)
        component_area_ratio = small_component_area / image_area

        score = 0.0
        score += min(1.0, component_density / 140.0) * 0.40
        score += min(1.0, component_area_ratio / 0.12) * 0.20
        score += min(1.0, max(row_activity, col_activity) / 0.75) * 0.20
        score += min(1.0, monochrome_score / 0.85) * 0.10
        score += min(1.0, dark_pixel_ratio / 0.20) * 0.10

        diagnostics = {
            "score": round(float(score), 4),
            "small_component_count": int(small_component_count),
            "component_density": round(float(component_density), 4),
            "component_area_ratio": round(float(component_area_ratio), 4),
            "dark_pixel_ratio": round(float(dark_pixel_ratio), 4),
            "row_activity": round(float(row_activity), 4),
            "col_activity": round(float(col_activity), 4),
            "monochrome_score": round(float(monochrome_score), 4),
        }
        passed = not (
            small_component_count >= self.config.text_density.min_components
            and score >= self.config.text_density.max_score
        )
        return passed, diagnostics

    def _ensure_clip_loaded(self) -> None:
        if self._clip_model is not None and self._clip_processor is not None:
            return

        try:
            import torch  # type: ignore
            from PIL import Image  # type: ignore  # noqa: F401
            from transformers import CLIPModel, CLIPProcessor  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "clip filter requires torch, pillow and transformers in the executing environment"
            ) from exc

        self._clip_processor = CLIPProcessor.from_pretrained(
            self.config.clip.model_name_or_path,
            local_files_only=self.config.clip.local_files_only,
        )
        self._clip_model = CLIPModel.from_pretrained(
            self.config.clip.model_name_or_path,
            local_files_only=self.config.clip.local_files_only,
        )
        self._clip_model.eval()
        if torch.cuda.is_available():
            self._clip_model.to("cuda")

    def _run_clip(self, content: bytes) -> tuple[bool, dict[str, Any]]:
        self._ensure_clip_loaded()

        try:
            import torch  # type: ignore
            from PIL import Image  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "clip filter requires torch and pillow in the executing environment"
            ) from exc

        prompts = self.config.clip.positive_prompts + self.config.clip.negative_prompts
        if not prompts:
            return True, {"skipped": "no_prompts"}

        image = Image.open(io.BytesIO(content)).convert("RGB")
        inputs = self._clip_processor(text=prompts, images=image, return_tensors="pt", padding=True)
        if torch.cuda.is_available():
            inputs = {key: value.to("cuda") for key, value in inputs.items()}

        with torch.no_grad():
            outputs = self._clip_model(**inputs)
            logits = outputs.logits_per_image[0]
            scores = torch.softmax(logits, dim=0).detach().cpu().tolist()

        positive_count = len(self.config.clip.positive_prompts)
        positive_scores = scores[:positive_count] or [0.0]
        negative_scores = scores[positive_count:] or [0.0]
        positive_best = max(positive_scores)
        negative_best = max(negative_scores)
        margin = positive_best - negative_best
        passed = positive_best >= self.config.clip.min_positive_score and margin >= self.config.clip.min_margin
        diagnostics = {
            "positive_best": round(float(positive_best), 4),
            "negative_best": round(float(negative_best), 4),
            "margin": round(float(margin), 4),
            "top_prompt": prompts[scores.index(max(scores))],
        }
        return passed, diagnostics
