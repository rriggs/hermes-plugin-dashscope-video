"""DashScope (Qwen Cloud) video generation backend.

Exposes Alibaba Cloud Model Studio's HappyHorse video models through
the native DashScope async task API as a VideoGenProvider.

Configuration (config.yaml):

    video_gen:
      provider: dashscope
      dashscope:
        api: https://token-plan.ap-southeast-1.maas.aliyuncs.com
        key_env: QWEN_API_KEY
        model_family: happyhorse-1.1      # auto-routes: appends -t2v/-i2v/-r2v
        # model_t2v: happyhorse-1.1-t2v   # optional per-mode override
        # model_i2v: happyhorse-1.1-i2v
        # model_r2v: happyhorse-1.1-r2v

All keys are optional. Defaults:
  - api:          https://token-plan.ap-southeast-1.maas.aliyuncs.com
  - key_env:      QWEN_API_KEY
  - model_family: happyhorse-1.1

Model resolution (first hit wins):
  1. Explicit model kwarg from the tool call (full model ID)
  2. Per-mode config override (model_t2v / model_i2v / model_r2v)
  3. model_family + mode suffix (-t2v / -i2v / -r2v)
  4. Default family (happyhorse-1.1) + mode suffix

For PAYG users:
  - api:     https://dashscope-intl.aliyuncs.com
  - key_env: DASHSCOPE_API_KEY

Models:
  - happyhorse-1.1-t2v:  Text-to-video
  - happyhorse-1.1-i2v:  Image-to-video
  - happyhorse-1.1-r2v:  Reference-to-video

API flow (async -- required for video on both token plan and PAYG):
  1. POST {api}/api/v1/services/aigc/video-generation/video-synthesis
     with X-DashScope-Async: enable  -->  returns task_id
  2. GET  {api}/api/v1/tasks/{task_id}  -->  poll until SUCCEEDED/FAILED
  3. Download video from output URL, cache locally.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

from agent.video_gen_provider import (
    DEFAULT_ASPECT_RATIO,
    DEFAULT_RESOLUTION,
    VideoGenProvider,
    error_response,
    save_url_video,
    success_response,
)

logger = logging.getLogger(__name__)

# Model families. Each family auto-routes to mode-specific model IDs
# by appending -t2v, -i2v, or -r2v based on the input modality.
_FAMILIES = [
    {
        "id": "happyhorse-1.1",
        "display": "HappyHorse 1.1",
        "speed": "~90s",
        "strengths": "Cinematic video: text-to-video, image-to-video, reference-to-video",
        "price": "Token plan included",
        "modalities": ["text", "image"],
    },
]

# Mode suffixes appended to the family ID.
_MODE_SUFFIX = {"t2v": "-t2v", "i2v": "-i2v", "r2v": "-r2v"}

# Polling config
_POLL_INTERVAL_S = 5.0
_POLL_DEADLINE_S = 600.0  # 10 minutes max

# Defaults when config keys are absent.
_DEFAULT_API = "https://token-plan.ap-southeast-1.maas.aliyuncs.com"
_DEFAULT_KEY_ENV = "QWEN_API_KEY"
_DEFAULT_FAMILY = "happyhorse-1.1"

# Aspect ratio mapping: Hermes uses "16:9" style, DashScope uses "1280*720"
_ASPECT_TO_SIZE = {
    "16:9": "1280*720",
    "9:16": "720*1280",
    "1:1": "960*960",
    "4:3": "1024*768",
    "3:4": "768*1024",
}


def _load_config() -> Dict[str, Any]:
    """Read ``video_gen.dashscope`` from config.yaml."""
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        section = cfg.get("video_gen") if isinstance(cfg, dict) else None
        ds = section.get("dashscope") if isinstance(section, dict) else None
        return ds if isinstance(ds, dict) else {}
    except Exception as exc:
        logger.debug("Could not load video_gen.dashscope config: %s", exc)
        return {}


def _resolve_api(cfg: Dict[str, Any]) -> str:
    """Resolve the API base URL: config > default."""
    api = cfg.get("api", "")
    if isinstance(api, str) and api.strip():
        return api.strip().rstrip("/")
    return _DEFAULT_API


def _resolve_key_env(cfg: Dict[str, Any]) -> str:
    """Resolve the env var name holding the API key: config > default."""
    key_env = cfg.get("key_env", "")
    if isinstance(key_env, str) and key_env.strip():
        return key_env.strip()
    return _DEFAULT_KEY_ENV


class DashScopeVideoGenProvider(VideoGenProvider):
    """Alibaba Cloud DashScope / Qwen Cloud video generation backend.

    Uses the native DashScope async task API. Both the token plan and
    PAYG endpoints require async mode (X-DashScope-Async: enable) for
    video models.
    """

    @property
    def name(self) -> str:
        return "dashscope"

    @property
    def display_name(self) -> str:
        return "DashScope (Qwen Cloud)"

    def is_available(self) -> bool:
        cfg = _load_config()
        key_env = _resolve_key_env(cfg)
        return bool(os.environ.get(key_env, "").strip())

    def list_models(self) -> List[Dict[str, Any]]:
        return list(_FAMILIES)

    def default_model(self) -> Optional[str]:
        return _DEFAULT_FAMILY

    def capabilities(self) -> Dict[str, Any]:
        return {
            "modalities": ["text", "image"],
            "aspect_ratios": list(_ASPECT_TO_SIZE.keys()),
            "resolutions": ["720p"],
            "max_duration": 10,
            "min_duration": 3,
            "supports_audio": False,
            "supports_negative_prompt": False,
            "max_reference_images": 1,
        }

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "DashScope (Qwen Cloud)",
            "badge": "token-plan",
            "tag": "HappyHorse 1.1 video models via Alibaba Cloud Model Studio",
            "env_vars": [
                {
                    "key": "QWEN_API_KEY",
                    "prompt": "Qwen Cloud API key (sk-sp-* for token plan, sk-ws-* for PAYG)",
                    "url": "https://modelstudio.console.alibabacloud.com/",
                },
            ],
        }

    def generate(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        image_url: Optional[str] = None,
        reference_image_urls: Optional[List[str]] = None,
        duration: Optional[int] = None,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        resolution: str = DEFAULT_RESOLUTION,
        negative_prompt: Optional[str] = None,
        audio: Optional[bool] = None,
        seed: Optional[int] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        prompt = (prompt or "").strip()
        if not prompt:
            return error_response(
                error="Prompt is required",
                error_type="invalid_request",
                provider=self.name,
            )

        cfg = _load_config()
        key_env = _resolve_key_env(cfg)
        api_key = os.environ.get(key_env, "").strip()
        if not api_key:
            return error_response(
                error=(
                    f"{key_env} not set. Configure video_gen.dashscope.key_env "
                    f"in config.yaml and set the env var, or run `hermes tools` "
                    f"-> Video Generation -> DashScope."
                ),
                error_type="missing_credentials",
                provider=self.name,
            )

        # Determine mode from inputs
        if image_url:
            mode = "i2v"
            modality = "image"
        elif reference_image_urls:
            mode = "r2v"
            modality = "image"
        else:
            mode = "t2v"
            modality = "text"

        # Model resolution:
        # 1. Explicit model kwarg (full model ID from tool call)
        # 2. Per-mode config override (model_t2v / model_i2v / model_r2v)
        # 3. model_family from config + mode suffix
        # 4. Default family + mode suffix
        family = cfg.get("model_family", "") or _DEFAULT_FAMILY
        if isinstance(family, str):
            family = family.strip() or _DEFAULT_FAMILY
        else:
            family = _DEFAULT_FAMILY

        model_id = (
            model
            or cfg.get(f"model_{mode}")
            or f"{family}{_MODE_SUFFIX[mode]}"
        )

        # Clamp duration
        dur = duration or 5
        dur = max(3, min(10, dur))

        # Build request payload
        size = _ASPECT_TO_SIZE.get(aspect_ratio, "1280*720")

        input_data: Dict[str, Any] = {"prompt": prompt}
        if mode == "i2v" and image_url:
            input_data["image_url"] = image_url
        elif mode == "r2v" and reference_image_urls:
            input_data["ref_image_url"] = reference_image_urls[0]

        payload = {
            "model": model_id,
            "input": input_data,
            "parameters": {
                "duration": dur,
                "size": size,
            },
        }

        base = _resolve_api(cfg)
        submit_url = f"{base}/api/v1/services/aigc/video-generation/video-synthesis"

        try:
            import requests

            # Step 1: Submit async task
            resp = requests.post(
                submit_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "X-DashScope-Async": "enable",
                },
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            submit_data = resp.json()
        except Exception as exc:
            logger.debug("DashScope video submit failed", exc_info=True)
            return error_response(
                error=f"DashScope video submit failed: {exc}",
                error_type="api_error",
                provider=self.name,
                model=model_id,
                prompt=prompt,
            )

        # Check for submit errors
        if submit_data.get("code"):
            return error_response(
                error=f"DashScope error: {submit_data['code']}: {submit_data.get('message', '')}",
                error_type="api_error",
                provider=self.name,
                model=model_id,
                prompt=prompt,
            )

        task_id = submit_data.get("output", {}).get("task_id")
        if not task_id:
            return error_response(
                error="DashScope did not return a task_id",
                error_type="empty_response",
                provider=self.name,
                model=model_id,
                prompt=prompt,
            )

        # Step 2: Poll until terminal
        poll_url = f"{base}/api/v1/tasks/{task_id}"
        deadline = time.monotonic() + _POLL_DEADLINE_S
        terminal_states = {"SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"}
        task_status = "PENDING"
        poll_data: Dict[str, Any] = {}

        try:
            while task_status not in terminal_states:
                if time.monotonic() >= deadline:
                    return error_response(
                        error=f"Video generation timed out after {int(_POLL_DEADLINE_S)}s (task {task_id})",
                        error_type="timeout",
                        provider=self.name,
                        model=model_id,
                        prompt=prompt,
                    )
                time.sleep(_POLL_INTERVAL_S)
                poll_resp = requests.get(
                    poll_url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=30,
                )
                poll_resp.raise_for_status()
                poll_data = poll_resp.json()
                task_status = poll_data.get("output", {}).get("task_status", "UNKNOWN")
        except Exception as exc:
            logger.debug("DashScope video poll failed", exc_info=True)
            return error_response(
                error=f"DashScope video polling failed: {exc}",
                error_type="api_error",
                provider=self.name,
                model=model_id,
                prompt=prompt,
            )

        if task_status != "SUCCEEDED":
            fail_msg = poll_data.get("output", {}).get("message", task_status)
            return error_response(
                error=f"Video generation {task_status}: {fail_msg}",
                error_type="generation_failed",
                provider=self.name,
                model=model_id,
                prompt=prompt,
            )

        # Step 3: Extract video URL from result
        video_url: Optional[str] = None
        output = poll_data.get("output", {})
        video_url = output.get("video_url")
        if not video_url:
            results = output.get("results") or []
            for r in results:
                if isinstance(r, dict) and r.get("url"):
                    video_url = r["url"]
                    break
        if not video_url:
            choices = output.get("choices") or []
            for c in choices:
                msg = c.get("message", {})
                for item in msg.get("content", []):
                    if isinstance(item, dict):
                        video_url = item.get("video") or item.get("url")
                        if video_url:
                            break
                if video_url:
                    break

        if not video_url:
            return error_response(
                error="DashScope video task succeeded but no video URL found in response",
                error_type="empty_response",
                provider=self.name,
                model=model_id,
                prompt=prompt,
            )

        # Step 4: Download and cache locally (URLs are ephemeral)
        short = model_id.replace(".", "_").replace("-", "_")
        try:
            saved_path = save_url_video(video_url, prefix=f"dashscope_{short}")
            video_ref = str(saved_path)
        except Exception as exc:
            logger.debug("DashScope: caching video URL failed (%s); returning URL", exc)
            video_ref = video_url

        return success_response(
            video=video_ref,
            model=model_id,
            prompt=prompt,
            modality=modality,
            aspect_ratio=aspect_ratio,
            duration=dur,
            provider=self.name,
            extra={"task_id": task_id, "size": size},
        )


def register(ctx) -> None:
    """Plugin entry point -- wire DashScopeVideoGenProvider into the registry."""
    ctx.register_video_gen_provider(DashScopeVideoGenProvider())
