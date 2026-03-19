from pathlib import Path

from model_runtime.qwen_image_backend import compose_qwen_edit_prompt, resolve_qwen_runtime_config
import model_runtime.qwen_image_backend as qwen_backend


def test_compose_qwen_edit_prompt_includes_detail_preservation_constraints():
    prompt = compose_qwen_edit_prompt("Traditional Chinese gongbi painting")

    assert "中国传统工笔画风格" in prompt
    assert "保留原始构图" in prompt
    assert "所有可见细节" in prompt
    assert "Traditional Chinese gongbi painting" in prompt


def test_resolve_qwen_runtime_config_prefers_yaml_render_values(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "style.yaml"
    config_path.write_text(
        "\n".join(
            [
                "style_id: gongbi_default",
                "prompt_profile:",
                "  positive: keep details",
                "  negative: blur",
                "render:",
                "  qwen_image_steps: 28",
                "  qwen_image_true_cfg_scale: 5.5",
                "  qwen_image_guidance_scale: 1.25",
            ]
        ),
        encoding="utf-8",
    )

    qwen_backend._style_payload.cache_clear()
    monkeypatch.setenv("STYLE_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("QWEN_IMAGE_STEPS", "99")
    monkeypatch.setenv("QWEN_IMAGE_TRUE_CFG_SCALE", "9.0")
    monkeypatch.setenv("QWEN_IMAGE_GUIDANCE_SCALE", "2.0")
    monkeypatch.setenv("QWEN_IMAGE_MODEL_PATH", str(tmp_path / "qwen-model"))

    runtime_config = resolve_qwen_runtime_config()

    assert runtime_config["steps"] == 28
    assert runtime_config["true_cfg_scale"] == 5.5
    assert runtime_config["guidance_scale"] == 1.25
    assert runtime_config["negative_prompt"] == "blur"
    qwen_backend._style_payload.cache_clear()
