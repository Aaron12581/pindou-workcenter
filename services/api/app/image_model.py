from __future__ import annotations

import base64
import json
import logging
import os
import re
import ssl
import threading
import time
import uuid
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import certifi
from openai import OpenAI
from PIL import Image, ImageFilter, ImageOps, PngImagePlugin

from .twod_engine import VARIANTS, analyze_material_complexity, repair_model_candidate_background
from .config import settings as app_settings


PROVIDER = app_settings.image_provider.strip().lower()
MODEL_NAME = app_settings.image_model
APP_VERSION = "0.20.23"
OPENAI_REQUEST_TIMEOUT_SECONDS = 600.0
OPENAI_MAX_RETRIES = 2
MAX_DASHSCOPE_INPUT_BYTES = 9_500_000
HTTPS_CONTEXT = ssl.create_default_context(cafile=certifi.where())
logger = logging.getLogger("perler.image_model")
_openai_client: OpenAI | None = None
_openai_client_key: tuple[str, int] | None = None
_openai_client_lock = threading.Lock()

STYLE_PROMPTS = {
    "simplified": (
        "Design this as a small-board fuse-bead character for a 52 by 52 grid, not as a finished illustration. "
        "Keep only the silhouette and the 4–6 identity-critical visual parts. Use broad, enclosed flat colour blocks "
        "with one base tone per part and at most one deliberately placed shadow tone in the whole character. "
        "Delete fabric folds, armour engraving, weave, reflected light, tiny highlights, texture, gradients and decorative lines. "
        "Thicken thin weapons and accessories into continuous readable shapes. Every retained mark must survive as at least "
        "a 2-by-2 bead region; do not use isolated specks."
    ),
    "standard": (
        "Create a clear 4-head-tall chibi character (head plus a naturally shortened but complete torso and two legs), "
        "not a normal-proportioned illustration with only the lower body shrunk. The head is intentionally about one "
        "quarter of the full character height; hands, feet, costume silhouette and pose must remain complete. Treat this "
        "as a standard 104 by 104 bead-design sheet: merge costume patterns into 6–9 stable functional colour regions. "
        "Each major part may have one base tone and one shadow OR highlight tone, never both. Preserve only the face, "
        "silhouette, one or two material cues, and identity colours; remove engraving, repeated armour plates, dense weave, "
        "specular fragments, tiny folds and micro-decoration. Thicken swords or narrow props while keeping them connected."
    ),
    "rich": (
        "Use this only as a large-board bead-design sheet, not a high-detail illustration. Keep the original body proportions, "
        "identity colors, costume structure, expression, hair and props, but limit every major part to base, shadow and highlight "
        "at most. Add only sparse, structurally meaningful material cues; never reproduce repeated armour plates, weave, fabric folds, "
        "photographic texture, glitter or scattered reflected-light fragments. Any extra detail must form a stable multi-bead region "
        "and must improve recognition at a distance."
    ),
}

PATTERN_DETAIL_BUDGETS = {
    "limited": "Use at most 16 functional colours; this is a ceiling, not a target. Use broad flat regions: one tone per major part, plus a dark adaptive outline and only the identity accents that improve recognition. Do not add colours merely to fill the allowance. No gradients, texture, dithering, isolated pixels or one-bead decorative marks.",
    "standard": "Use at most 30 functional colours; this is a ceiling, not a target. Major parts may use a base plus one deliberately chosen shadow OR highlight tone, and a few identity-defining face, material or prop colours where they form stable regions. Do not add incidental transition colours. No gradients, repeated texture, scattered shine, dense folds, dithering or isolated pixels.",
    "rich": "Use at most 42 functional colours, only when the physical board has at least one 104-bead dimension, and only when each added colour carries a readable structural purpose. This is a ceiling, not a target. A major part may use base, shadow and highlight, but extra tones must form stable regions. Keep selected material cues only; no continuous gradients, dense texture, scattered shine, dithering or one-bead noise.",
}


def model_status() -> dict:
    configured = (
        app_settings.dashscope_api_key is not None
        and bool(app_settings.dashscope_workspace_id)
        if PROVIDER == "dashscope"
        else app_settings.openai_api_key is not None
    )
    return {
        "provider": PROVIDER,
        "model": MODEL_NAME,
        "configured": configured,
        "generationMode": "model_generated",
        "candidateCount": 3,
        "candidateCountOptions": [1, 3],
        "variants": list(VARIANTS),
        "keyStorage": "environment_only",
    }


def _prompt(variant: str, settings: dict) -> str:
    composition = {
        "full": "Show the complete subject, including clothing, weapons, accessories, hands, feet, and pose.",
        "half": "Use a waist-up composition while preserving all important visible props and gestures.",
        "head": "Use a head-and-shoulders chibi composition with a highly recognizable face and hairstyle.",
    }.get(settings.get("composition"), "Show the complete subject and preserve the pose.")
    style = settings.get("style") or "clean polished 2D character illustration"
    outline = settings.get("outline") or "use a darker color derived from the subject for outlines, never fixed black"
    subject_mode = settings.get("subject_mode", "single")
    subject = (
        "The supplied reference is the visual ground truth for one selected primary subject. Faithfully redraw that exact "
        "subject only: do not substitute a generic character or change its apparent identity, gender presentation, face, "
        "hairstyle, hat, costume silhouette, colour blocks, materials, props, weapons, gesture or action. Do not invent, "
        "retain, repeat, or place additional people, character fragments, background figures, scenery, animals, objects, "
        "or decorative elements."
        if subject_mode != "multiple" else
        "Keep the selected depicted people only, preserving their relative position, expression, hairstyle, clothing, props, "
        "weapons, gesture, and action. Do not add people, background figures, scenery, or extra objects."
    )
    return (
        f"Transform the supplied reference image into a finished {style}, suitable as the approved intermediate "
        "artwork for conversion into a fuse-bead pattern. This must be a genuine redraw, not a posterize filter. "
        f"{subject} {composition} {STYLE_PROMPTS[variant]} Use ideal illustration colors; do not quantize to bead "
        f"brand colors yet. {outline}. Use one perfectly flat, solid #F8FAFC studio backdrop with no texture, gradient, "
        "shadow, floor, scenery, pattern, or objects; the application will remove this exact backdrop after generation. "
        "Leave generous safe margins. No text, logo, watermark, frame, grid, bead texture, extra objects, or cropped body parts."
    )


def _normalize_png(content: bytes, variant: str, provider: str = PROVIDER, analysis: dict | None = None) -> bytes:
    image = Image.open(BytesIO(content))
    image.load()
    image = ImageOps.exif_transpose(image).convert("RGBA")
    if image.width < 512 or image.height < 512:
        raise ValueError("MODEL_IMAGE_TOO_SMALL")
    # GPT Image 2 does not support transparent output. It is prompted for one
    # solid studio backdrop, then the border-connected backdrop is removed
    # locally.  A pure near-white threshold is insufficient for opaque model
    # outputs with slight compression/lighting variation.
    image.putalpha(Image.new("L", image.size, 255))
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("perler_generation_mode", "model_generated")
    metadata.add_text("perler_provider", provider)
    metadata.add_text("perler_model", MODEL_NAME)
    metadata.add_text("perler_variant", variant)
    if analysis:
        metadata.add_text("perler_complexity_score", str(analysis["complexityScore"]))
        metadata.add_text("perler_complexity_level", analysis["complexityLevel"])
        metadata.add_text("perler_recommended_variant", analysis["recommendedVariant"])
        metadata.add_text("perler_recommended_board", analysis["recommendedBoard"])
        metadata.add_text("perler_route", analysis["route"])
    output = BytesIO()
    image.save(output, "PNG", optimize=True, pnginfo=metadata)
    return repair_model_candidate_background(output.getvalue())


def _requested_variants(settings: dict) -> list[str]:
    requested_variant = settings.get("variant", "standard")
    if requested_variant not in VARIANTS:
        raise ValueError("INVALID_2D_VARIANT")
    return [requested_variant] if settings.get("candidate_mode", "all") == "single" else list(VARIANTS)


def _pattern_grid_description(layout: str) -> str:
    known = {
        "single": "52 by 52 beads",
        "double_horizontal": "104 by 52 beads",
        "double_vertical": "52 by 104 beads",
        "quad": "104 by 104 beads",
        "six_horizontal": "156 by 104 beads",
    }
    if layout in known:
        return known[layout]
    if layout.startswith("custom_"):
        return layout.removeprefix("custom_").replace("x", " by ") + " 58-bead boards"
    return "the selected physical bead-board layout"


def _pattern_image_prompt(layout: str, color_mode: str, source_variant: str | None = None) -> str:
    budget = PATTERN_DETAIL_BUDGETS[color_mode]
    source_instruction = (
        f"The approved 2D was already prepared as the {source_variant} detail tier; do not restore details that it intentionally omitted. "
        if source_variant in STYLE_PROMPTS else ""
    )
    return (
        "Convert the supplied approved 2D artwork into one clean, makeable fuse-bead pixel-art design. "
        "You are creating the final visual design, not explaining it and not returning a text grid. "
        "First preserve the subject's complete silhouette and identity-critical face, hairstyle, clothing blocks, hands, weapons, hats and pose; then deliberately discard nonessential illustration detail. "
        "Use hard-edged, square pixel regions only: no blur, anti-aliasing, gradients, bead texture, grid lines, text, logo, watermark, frame or background objects. "
        "Use one perfectly flat solid #F8FAFC background with generous margins; do not draw scenery or background objects. "
        f"Compose specifically for {_pattern_grid_description(layout)}. {budget} {source_instruction}"
        "The result must be a single finished image, not JSON, a table, coordinate list, palette list or written instructions."
    )


def _require_image_generation_model() -> None:
    """Fail before calling a vision-only model on the image-generation API.

    The direct-pattern path needs a model that returns an image.  In particular,
    `qwen3-vl-flash` can analyse an image but cannot produce the model-authored
    pixel image this path consumes.  A clear local error is preferable to a
    provider-side request failure that looks like a transient timeout.
    """
    if PROVIDER == "dashscope" and not MODEL_NAME.lower().startswith("qwen-image"):
        raise ModelGenerationError(
            "MODEL_NOT_IMAGE_GENERATION",
            provider_message=(
                f"当前图像模型“{MODEL_NAME}”是视觉理解模型，不能直接生成图纸成图。"
                "请将 PERLER_IMAGE_MODEL 设置为已开通的 qwen-image-2.0。"
            ),
        )


class ModelGenerationError(ValueError):
    def __init__(
        self,
        code: str,
        *,
        provider_code: str | None = None,
        provider_message: str | None = None,
        request_id: str | None = None,
        diagnostics: dict | None = None,
    ):
        super().__init__(code)
        self.code = code
        self.provider_code = provider_code
        self.provider_message = provider_message
        self.request_id = request_id
        self.diagnostics = diagnostics or None

    def detail(self) -> dict:
        return {
            "code": self.code,
            "provider_code": self.provider_code,
            "provider_message": self.provider_message,
            "request_id": self.request_id,
            "diagnostics": self.diagnostics,
        }


def _error_code(exc: Exception, provider_code: str = "", provider_message: str = "") -> str:
    name = type(exc).__name__.upper()
    message = " ".join((str(exc), provider_code, provider_message)).upper()
    if "DATAINSPECTIONFAILED" in message or "GREEN NET CHECK" in message or "CONTENT" in message and "SAFETY" in message:
        return "MODEL_INPUT_SAFETY_REJECTED"
    if "429" in message or "RATE" in name or "THROTTL" in message:
        return "MODEL_RATE_LIMITED"
    # The OpenAI SDK uses APIConnectionError for failures before an API request
    # reaches the service (DNS, proxy/VPN, TLS or firewall).  Keep that distinct
    # from a completed request that genuinely exceeded its generation timeout.
    if "CONNECTION" in name or "CONNECTION ERROR" in message or "NETWORK" in name:
        return "MODEL_CONNECTION_FAILED"
    if "TIMEOUT" in name or "TIMED OUT" in message:
        return "MODEL_TIMEOUT"
    if (
        "401" in message or "403" in message or "AUTH" in name
        or "APIKEY" in message or "API-KEY" in message or "PERMISSION" in message
    ):
        return "MODEL_AUTH_FAILED"
    if "QUOTA" in message or "BALANCE" in message or "ARREAR" in message:
        return "MODEL_QUOTA_EXHAUSTED"
    if "MODEL" in message and ("NOT FOUND" in message or "NOT EXIST" in message or "ACCESS" in message):
        return "MODEL_NOT_AVAILABLE"
    if "IMAGE" in message and ("SIZE" in message or "RESOLUTION" in message or "LARGE" in message):
        return "MODEL_INPUT_INVALID"
    return "MODEL_GENERATION_FAILED"


def _safe_exception_chain(exc: Exception) -> list[dict]:
    """Return compact, key-safe connection evidence for the UI and terminal."""
    chain, seen, current = [], set(), exc
    while current is not None and id(current) not in seen and len(chain) < 5:
        seen.add(id(current))
        message = re.sub(r"sk-[A-Za-z0-9_-]+", "[redacted-api-key]", str(current) or type(current).__name__)
        chain.append({"type": type(current).__name__, "message": message[:420]})
        current = current.__cause__ or current.__context__
    return chain


def _safe_transport_environment() -> dict:
    """Expose only whether a process proxy is active, never its credentials."""
    proxy_names = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")
    configured = []
    for name in proxy_names:
        value = os.getenv(name)
        if not value:
            continue
        parsed = urlparse(value if "://" in value else f"http://{value}")
        target = parsed.hostname or "configured"
        try:
            port = parsed.port
        except ValueError:
            port = None
        if port:
            target = f"{target}:{port}"
        configured.append(f"{name}={target}")
    no_proxy = bool(os.getenv("NO_PROXY") or os.getenv("no_proxy"))
    return {"proxy_configured": bool(configured), "proxy_entries": configured, "no_proxy_configured": no_proxy}


def _connection_stage(exc: Exception) -> str | None:
    chain = _safe_exception_chain(exc)
    message = " ".join(item["message"].lower() for item in chain)
    if "disconnected without sending a response" in message:
        return "response_not_received_connection_closed"
    if "certificate" in message or "tls" in message or "ssl" in message:
        return "tls_handshake_failed"
    if "name or service not known" in message or "dns" in message:
        return "dns_resolution_failed"
    return None


def _openai_error(
    exc: Exception,
    *,
    operation: str = "image_edit",
    started_at: float | None = None,
    trace_id: str | None = None,
    input_profile: dict | None = None,
) -> ModelGenerationError:
    """Preserve actionable OpenAI fields for the UI rather than collapsing them."""
    provider_code = str(getattr(exc, "code", "") or "") or None
    provider_message = str(getattr(exc, "message", "") or str(exc) or "") or None
    request_id = str(getattr(exc, "request_id", "") or "") or None
    diagnostics = {
        "trace_id": trace_id or uuid.uuid4().hex[:12],
        "operation": operation,
        "provider": "openai",
        "model": MODEL_NAME,
        "elapsed_ms": round((time.perf_counter() - started_at) * 1000) if started_at is not None else None,
        "client": "process_shared",
        "timeout_seconds": OPENAI_REQUEST_TIMEOUT_SECONDS,
        "max_retries": OPENAI_MAX_RETRIES,
        "exception_chain": _safe_exception_chain(exc),
        "connection_stage": _connection_stage(exc),
        "transport": _safe_transport_environment(),
    }
    if input_profile:
        diagnostics["input"] = input_profile
    logger.warning("OpenAI image request failed: %s", json.dumps(diagnostics, ensure_ascii=False))
    return ModelGenerationError(
        _error_code(exc, provider_code or "", provider_message or ""),
        provider_code=provider_code,
        provider_message=provider_message,
        request_id=request_id,
        diagnostics=diagnostics,
    )


def _get_openai_client() -> OpenAI:
    """Reuse one SDK client so consecutive 2D/pattern requests reuse HTTP connections."""
    global _openai_client, _openai_client_key
    if app_settings.openai_api_key is None:
        raise ValueError("OPENAI_API_KEY_REQUIRED")
    api_key = app_settings.openai_api_key.get_secret_value()
    client_key = (api_key, id(OpenAI))
    with _openai_client_lock:
        if _openai_client is None or _openai_client_key != client_key:
            _openai_client = OpenAI(
                api_key=api_key,
                timeout=OPENAI_REQUEST_TIMEOUT_SECONDS,
                max_retries=OPENAI_MAX_RETRIES,
            )
            _openai_client_key = client_key
        return _openai_client


def _openai_candidates(source: Image.Image, settings: dict, variants: list[str]) -> dict[str, bytes]:
    if app_settings.openai_api_key is None:
        raise ValueError("OPENAI_API_KEY_REQUIRED")
    source_file = BytesIO()
    source.save(source_file, "PNG")
    source_file.name = "reference.png"
    client = _get_openai_client()
    outputs: dict[str, bytes] = {}
    for variant in variants:
        source_file.seek(0)
        started_at, trace_id = time.perf_counter(), uuid.uuid4().hex[:12]
        try:
            result = client.images.edit(
                model=MODEL_NAME,
                image=source_file,
                prompt=_prompt(variant, settings),
                size="1024x1536" if source.height >= source.width else "1536x1024",
                quality="medium",
                output_format="png",
            )
        except Exception as exc:
            raise _openai_error(exc, operation="2d_candidate", started_at=started_at, trace_id=trace_id) from exc
        encoded = result.data[0].b64_json if result.data else None
        if not encoded:
            raise ValueError("MODEL_EMPTY_RESULT")
        outputs[variant] = _normalize_png(base64.b64decode(encoded), variant, "openai", settings.get("_analysis"))
    return outputs


def _prepare_openai_pattern_source(source: Image.Image) -> tuple[BytesIO, dict]:
    """Make the direct-pattern image edit input transport-safe and deterministic."""
    original = ImageOps.exif_transpose(source).convert("RGBA")
    alpha = original.getchannel("A")
    alpha_extrema = alpha.getextrema()
    transparent_pixels = sum(1 for value in alpha.getdata() if value < 255)
    prepared = original.copy()
    prepared.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (1024, 1024), "#F8FAFC")
    offset = ((1024 - prepared.width) // 2, (1024 - prepared.height) // 2)
    canvas.paste(prepared, offset, prepared)
    output = BytesIO()
    canvas.save(output, "PNG", optimize=True)
    output.name = "approved-2d-flattened.png"
    profile = {
        "original_size": f"{original.width}x{original.height}",
        "prepared_size": "1024x1024",
        "format": "png-rgb",
        "bytes": output.tell(),
        "alpha_min": alpha_extrema[0],
        "transparent_pixel_ratio": round(transparent_pixels / (original.width * original.height), 4),
        "background": "#F8FAFC",
        "sdk_attempts_max": OPENAI_MAX_RETRIES + 1,
    }
    output.seek(0)
    return output, profile


def _openai_pattern_image(source: Image.Image, layout: str, color_mode: str, source_variant: str | None = None) -> bytes:
    _require_image_generation_model()
    if app_settings.openai_api_key is None:
        raise ValueError("OPENAI_API_KEY_REQUIRED")
    source_file, input_profile = _prepare_openai_pattern_source(source)
    client = _get_openai_client()
    started_at, trace_id = time.perf_counter(), uuid.uuid4().hex[:12]
    try:
        result = client.images.edit(
            model=MODEL_NAME, image=source_file, prompt=_pattern_image_prompt(layout, color_mode, source_variant),
            size="1024x1024", quality="medium", output_format="png",
        )
    except Exception as exc:
        raise _openai_error(exc, operation="direct_pattern", started_at=started_at, trace_id=trace_id, input_profile=input_profile) from exc
    encoded = result.data[0].b64_json if result.data else None
    if not encoded:
        raise ValueError("MODEL_EMPTY_RESULT")
    return _normalize_png(base64.b64decode(encoded), color_mode, "openai")


def _dashscope_endpoint() -> str:
    workspace = (app_settings.dashscope_workspace_id or "").strip()
    # Bailian workspace IDs commonly use the documented `ws_...` form.
    # Keep this strict enough to prevent a configured value becoming a URL.
    if not workspace or not re.fullmatch(r"[A-Za-z0-9_-]+", workspace):
        raise ValueError("DASHSCOPE_WORKSPACE_ID_REQUIRED")
    return (
        f"https://{workspace}.cn-beijing.maas.aliyuncs.com"
        "/api/v1/services/aigc/multimodal-generation/generation"
    )


def _encode_dashscope_source(source: Image.Image) -> str:
    """Create a provider-safe data URL while preserving the source aspect ratio."""
    image = source.convert("RGB")
    if max(image.size) > 3072:
        scale = 3072 / max(image.size)
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
    if min(image.size) < 384:
        scale = 384 / min(image.size)
        if max(image.size) * scale <= 3072:
            image = image.resize(
                (round(image.width * scale), round(image.height * scale)),
                Image.Resampling.LANCZOS,
            )
    for quality in (92, 86, 80, 72):
        encoded = BytesIO()
        image.save(encoded, "JPEG", quality=quality, optimize=True)
        if encoded.tell() <= MAX_DASHSCOPE_INPUT_BYTES:
            return "data:image/jpeg;base64," + base64.b64encode(encoded.getvalue()).decode("ascii")
    raise ModelGenerationError(
        "MODEL_INPUT_INVALID",
        provider_message="参考图压缩后仍超过百炼 10 MB 输入限制。",
    )


def _dashscope_error(exc: HTTPError) -> ModelGenerationError:
    provider_code = ""
    provider_message = ""
    request_id = exc.headers.get("x-request-id") if exc.headers else None
    try:
        payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        provider_code = str(payload.get("code") or "")
        provider_message = str(payload.get("message") or "")
        request_id = str(payload.get("request_id") or request_id or "") or None
    except Exception:
        provider_message = str(exc)
    return ModelGenerationError(
        _error_code(exc, provider_code, provider_message),
        provider_code=provider_code or None,
        provider_message=provider_message or None,
        request_id=request_id,
    )


def _download_dashscope_image(image_url: str) -> bytes:
    parsed = urlparse(image_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("MODEL_INVALID_RESULT_URL")
    request = Request(image_url, headers={"User-Agent": f"PerlerWorkbench/{APP_VERSION}"})
    with urlopen(request, timeout=180, context=HTTPS_CONTEXT) as response:
        content = response.read(30 * 1024 * 1024 + 1)
    if len(content) > 30 * 1024 * 1024:
        raise ValueError("MODEL_IMAGE_TOO_LARGE")
    return content


def _dashscope_candidates(source: Image.Image, settings: dict, variants: list[str]) -> dict[str, bytes]:
    if app_settings.dashscope_api_key is None:
        raise ValueError("DASHSCOPE_API_KEY_REQUIRED")
    data_url = _encode_dashscope_source(source)
    size = "1024*1536" if source.height >= source.width else "1536*1024"
    outputs: dict[str, bytes] = {}
    for variant in variants:
        payload = {
            "model": MODEL_NAME,
            "input": {"messages": [{"role": "user", "content": [
                {"image": data_url},
                {"text": _prompt(variant, settings)},
            ]}]},
            "parameters": {
                "n": 1,
                "negative_prompt": "文字，水印，标志，边框，网格，拼豆纹理，裁切身体，缺失手脚，多余人物",
                "prompt_extend": True,
                "watermark": False,
                "size": size,
            },
        }
        request = Request(
            _dashscope_endpoint(),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {app_settings.dashscope_api_key.get_secret_value()}",
                "Content-Type": "application/json",
                "User-Agent": f"PerlerWorkbench/{APP_VERSION}",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=240, context=HTTPS_CONTEXT) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise _dashscope_error(exc) from exc
        except (URLError, TimeoutError, OSError, ssl.SSLError) as exc:
            reason = getattr(exc, "reason", None)
            provider_message = str(reason or exc)
            raise ModelGenerationError(
                _error_code(exc, provider_message=provider_message),
                provider_message=provider_message,
            ) from exc
        if result.get("code"):
            provider_code = str(result.get("code") or "")
            provider_message = str(result.get("message") or "")
            raise ModelGenerationError(
                _error_code(ValueError(provider_message), provider_code, provider_message),
                provider_code=provider_code,
                provider_message=provider_message,
                request_id=str(result.get("request_id") or "") or None,
            )
        choices = result.get("output", {}).get("choices", [])
        content = choices[0].get("message", {}).get("content", []) if choices else []
        image_url = next((item.get("image") for item in content if item.get("image")), None)
        if not image_url:
            raise ValueError("MODEL_EMPTY_RESULT")
        try:
            downloaded = _download_dashscope_image(image_url)
        except (HTTPError, URLError, TimeoutError, OSError, ssl.SSLError) as exc:
            reason = getattr(exc, "reason", None)
            provider_message = f"生成成功，但下载候选图失败：{reason or exc}"
            raise ModelGenerationError(
                _error_code(exc, provider_message=provider_message),
                provider_message=provider_message,
            ) from exc
        outputs[variant] = _normalize_png(downloaded, variant, "dashscope", settings.get("_analysis"))
    return outputs


def _dashscope_pattern_image(source: Image.Image, layout: str, color_mode: str, source_variant: str | None = None) -> bytes:
    _require_image_generation_model()
    if app_settings.dashscope_api_key is None:
        raise ValueError("DASHSCOPE_API_KEY_REQUIRED")
    payload = {
        "model": MODEL_NAME,
        "input": {"messages": [{"role": "user", "content": [
            {"image": _encode_dashscope_source(source)},
            {"text": _pattern_image_prompt(layout, color_mode, source_variant)},
        ]}]},
        "parameters": {"n": 1, "negative_prompt": "文字，水印，标志，边框，网格线，拼豆纹理，模糊，渐变，裁切身体，多余人物",
            "prompt_extend": True, "watermark": False, "size": "1024*1024"},
    }
    request = Request(_dashscope_endpoint(), data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers={
        "Authorization": f"Bearer {app_settings.dashscope_api_key.get_secret_value()}",
        "Content-Type": "application/json", "User-Agent": f"PerlerWorkbench/{APP_VERSION}",
    }, method="POST")
    try:
        with urlopen(request, timeout=240, context=HTTPS_CONTEXT) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise _dashscope_error(exc) from exc
    except (URLError, TimeoutError, OSError, ssl.SSLError) as exc:
        raise ModelGenerationError(_error_code(exc, provider_message=str(getattr(exc, "reason", None) or exc)), provider_message=str(getattr(exc, "reason", None) or exc)) from exc
    if result.get("code"):
        raise ModelGenerationError(_error_code(ValueError(str(result.get("message") or "")), str(result.get("code") or ""), str(result.get("message") or "")), provider_code=str(result.get("code") or "") or None, provider_message=str(result.get("message") or "") or None, request_id=str(result.get("request_id") or "") or None)
    choices = result.get("output", {}).get("choices", [])
    content = choices[0].get("message", {}).get("content", []) if choices else []
    image_url = next((item.get("image") for item in content if item.get("image")), None)
    if not image_url:
        raise ValueError("MODEL_EMPTY_RESULT")
    return _normalize_png(_download_dashscope_image(image_url), color_mode, "dashscope")


def generate_direct_pattern_image(image_bytes: bytes, *, layout: str, color_mode: str, source_variant: str | None = None) -> bytes:
    """Ask the configured image model for the pattern image; it never emits a text grid."""
    try:
        source = ImageOps.exif_transpose(Image.open(BytesIO(image_bytes))).convert("RGBA")
        if PROVIDER == "dashscope":
            return _dashscope_pattern_image(source, layout, color_mode, source_variant)
        if PROVIDER == "openai":
            return _openai_pattern_image(source, layout, color_mode, source_variant)
        raise ValueError("UNSUPPORTED_IMAGE_PROVIDER")
    except ModelGenerationError:
        raise
    except ValueError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError, ssl.SSLError, json.JSONDecodeError) as exc:
        raise ModelGenerationError(_error_code(exc), provider_message=str(exc)) from exc


def generate_model_candidates(image_bytes: bytes, settings: dict | None = None) -> tuple[dict[str, bytes], dict]:
    settings = settings or {}
    try:
        source = Image.open(BytesIO(image_bytes))
        source.load()
    except Exception as exc:
        raise ValueError("INVALID_IMAGE") from exc
    source = ImageOps.exif_transpose(source).convert("RGBA")
    analysis = analyze_material_complexity(image_bytes)
    settings = {**settings, "_analysis": analysis}
    requested_variants = _requested_variants(settings)
    try:
        if PROVIDER == "dashscope":
            outputs = _dashscope_candidates(source, settings, requested_variants)
        elif PROVIDER == "openai":
            outputs = _openai_candidates(source, settings, requested_variants)
        else:
            raise ValueError("UNSUPPORTED_IMAGE_PROVIDER")
    except ModelGenerationError:
        raise
    except ValueError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise ValueError(_error_code(exc)) from exc
    except Exception as exc:
        raise ValueError(_error_code(exc)) from exc
    requested = requested_variants[0] if len(requested_variants) == 1 else analysis["recommendedVariant"]
    strategy_fit = 92 if requested == analysis["recommendedVariant"] else 82
    return outputs, {
        "score": strategy_fit,
        "generationMode": "model_generated",
        "provider": PROVIDER,
        "model": MODEL_NAME,
        "confirmable": True,
        **analysis,
        "selectedStrategy": requested,
        "targetBoard": VARIANTS[requested]["targetBoard"],
        "warnings": [],
    }
