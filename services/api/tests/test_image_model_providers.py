import base64
import json
from io import BytesIO
from urllib.error import HTTPError

from PIL import Image, ImageDraw
from pydantic import SecretStr

import app.image_model as image_model
from app.twod_engine import analyze_material_complexity


class FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size: int = -1) -> bytes:
        return self.content


def png_bytes(size=(1024, 1536)) -> bytes:
    image = Image.new("RGB", size, "#4f86bd")
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def test_dashscope_generates_only_selected_variant_and_marks_provider(monkeypatch):
    calls = []
    api_response = json.dumps({
        "output": {"choices": [{
            "finish_reason": "stop",
            "message": {"content": [{"image": "https://example.aliyuncs.com/result.png"}]},
        }]},
        "usage": {"image_count": 1, "width": 1024, "height": 1536},
    }).encode()

    def fake_urlopen(request, timeout, context=None):
        calls.append((request, timeout))
        if getattr(request, "method", None) == "POST":
            return FakeResponse(api_response)
        return FakeResponse(png_bytes())

    monkeypatch.setattr(image_model, "PROVIDER", "dashscope")
    monkeypatch.setattr(image_model, "MODEL_NAME", "qwen-image-2.0")
    monkeypatch.setattr(image_model.app_settings, "dashscope_api_key", SecretStr("test-key"))
    monkeypatch.setattr(image_model.app_settings, "dashscope_workspace_id", "ws-test")
    monkeypatch.setattr(image_model, "urlopen", fake_urlopen)

    source = png_bytes((720, 1280))
    outputs, quality = image_model.generate_model_candidates(source, {
        "candidate_mode": "single",
        "variant": "rich",
        "composition": "full",
    })

    assert list(outputs) == ["rich"]
    assert quality["provider"] == "dashscope"
    assert quality["model"] == "qwen-image-2.0"
    assert len(calls) == 2
    with Image.open(BytesIO(outputs["rich"])) as output:
        assert output.info["perler_generation_mode"] == "model_generated"
        assert output.info["perler_provider"] == "dashscope"
        assert output.info["perler_model"] == "qwen-image-2.0"
        assert output.info["perler_variant"] == "rich"


def test_dashscope_resizes_and_compresses_large_source(monkeypatch):
    seen_payload = {}
    api_response = json.dumps({
        "output": {"choices": [{
            "finish_reason": "stop",
            "message": {"content": [{"image": "https://example.aliyuncs.com/result.png"}]},
        }]},
    }).encode()

    def fake_urlopen(request, timeout, context=None):
        if getattr(request, "method", None) == "POST":
            seen_payload.update(json.loads(request.data.decode("utf-8")))
            return FakeResponse(api_response)
        return FakeResponse(png_bytes())

    monkeypatch.setattr(image_model, "PROVIDER", "dashscope")
    monkeypatch.setattr(image_model.app_settings, "dashscope_api_key", SecretStr("test-key"))
    monkeypatch.setattr(image_model.app_settings, "dashscope_workspace_id", "ws-test")
    monkeypatch.setattr(image_model, "urlopen", fake_urlopen)

    image_model.generate_model_candidates(png_bytes((3600, 5400)), {
        "candidate_mode": "single", "variant": "standard",
    })
    data_url = seen_payload["input"]["messages"][0]["content"][0]["image"]
    assert data_url.startswith("data:image/jpeg;base64,")
    assert len(base64.b64decode(data_url.split(",", 1)[1])) < 10_000_000


def test_dashscope_preserves_provider_error_details(monkeypatch):
    body = BytesIO(json.dumps({
        "request_id": "req-test",
        "code": "InvalidApiKey",
        "message": "Invalid API-key provided.",
    }).encode())

    def fake_urlopen(_request, timeout, context=None):
        raise HTTPError("https://example", 401, "Unauthorized", {}, body)

    monkeypatch.setattr(image_model, "PROVIDER", "dashscope")
    monkeypatch.setattr(image_model.app_settings, "dashscope_api_key", SecretStr("bad-key"))
    monkeypatch.setattr(image_model.app_settings, "dashscope_workspace_id", "ws-test")
    monkeypatch.setattr(image_model, "urlopen", fake_urlopen)

    try:
        image_model.generate_model_candidates(png_bytes(), {
            "candidate_mode": "single", "variant": "standard",
        })
    except image_model.ModelGenerationError as exc:
        assert exc.code == "MODEL_AUTH_FAILED"
        assert exc.provider_code == "InvalidApiKey"
        assert exc.request_id == "req-test"
    else:
        raise AssertionError("expected ModelGenerationError")


def test_dashscope_accepts_documented_workspace_id_with_underscore(monkeypatch):
    monkeypatch.setattr(image_model.app_settings, "dashscope_workspace_id", "ws_test123")
    assert image_model._dashscope_endpoint() == (
        "https://ws_test123.cn-beijing.maas.aliyuncs.com"
        "/api/v1/services/aigc/multimodal-generation/generation"
    )


def test_dashscope_direct_pattern_requests_one_image_and_returns_png(monkeypatch):
    calls = []
    api_response = json.dumps({
        "output": {"choices": [{
            "finish_reason": "stop",
            "message": {"content": [{"image": "https://example.aliyuncs.com/pattern.png"}]},
        }]},
    }).encode()

    def fake_urlopen(request, timeout, context=None):
        calls.append((request, timeout))
        if getattr(request, "method", None) == "POST":
            return FakeResponse(api_response)
        return FakeResponse(png_bytes((1024, 1024)))

    monkeypatch.setattr(image_model, "PROVIDER", "dashscope")
    monkeypatch.setattr(image_model, "MODEL_NAME", "qwen-image-2.0")
    monkeypatch.setattr(image_model.app_settings, "dashscope_api_key", SecretStr("test-key"))
    monkeypatch.setattr(image_model.app_settings, "dashscope_workspace_id", "ws-test")
    monkeypatch.setattr(image_model, "urlopen", fake_urlopen)

    result = image_model.generate_direct_pattern_image(png_bytes((720, 1280)), layout="quad", color_mode="standard")
    assert len(calls) == 2
    request_payload = json.loads(calls[0][0].data.decode("utf-8"))
    assert request_payload["model"] == "qwen-image-2.0"
    assert request_payload["parameters"]["size"] == "1024*1024"
    assert "not returning a text grid" in request_payload["input"]["messages"][0]["content"][1]["text"]
    assert "at most 30 functional colours" in request_payload["input"]["messages"][0]["content"][1]["text"]
    assert "104 by 104 beads" in request_payload["input"]["messages"][0]["content"][1]["text"]
    with Image.open(BytesIO(result)) as output:
        assert output.format == "PNG"


def test_dashscope_vision_model_is_rejected_before_network_request(monkeypatch):
    monkeypatch.setattr(image_model, "PROVIDER", "dashscope")
    monkeypatch.setattr(image_model, "MODEL_NAME", "qwen3-vl-flash")
    monkeypatch.setattr(image_model.app_settings, "dashscope_api_key", SecretStr("test-key"))
    try:
        image_model.generate_direct_pattern_image(png_bytes(), layout="single", color_mode="standard")
    except image_model.ModelGenerationError as exc:
        assert exc.code == "MODEL_NOT_IMAGE_GENERATION"
        assert "qwen-image-2.0" in (exc.provider_message or "")
    else:
        raise AssertionError("expected a local image-model validation error")


def test_openai_pattern_edit_omits_unsupported_input_fidelity(monkeypatch):
    calls = []

    class FakeImages:
        def edit(self, **kwargs):
            calls.append(kwargs)
            return type("Result", (), {
                "data": [type("ImageData", (), {"b64_json": base64.b64encode(png_bytes((1024, 1024))).decode()})()]
            })()

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.images = FakeImages()

    monkeypatch.setattr(image_model, "PROVIDER", "openai")
    monkeypatch.setattr(image_model, "MODEL_NAME", "gpt-image-2")
    monkeypatch.setattr(image_model.app_settings, "openai_api_key", SecretStr("test-key"))
    monkeypatch.setattr(image_model, "OpenAI", FakeOpenAI)

    result = image_model._openai_pattern_image(Image.open(BytesIO(png_bytes())), "quad", "rich")
    assert result
    assert calls[0]["model"] == "gpt-image-2"
    assert "input_fidelity" not in calls[0]


def test_openai_pattern_input_is_flattened_bounded_and_diagnosable():
    source = Image.new("RGBA", (1536, 1024), (12, 24, 48, 0))
    for x in range(400, 1120):
        for y in range(120, 960):
            source.putpixel((x, y), (36, 72, 124, 255))
    prepared, profile = image_model._prepare_openai_pattern_source(source)
    with Image.open(prepared) as output:
        assert output.mode == "RGB"
        assert output.size == (1024, 1024)
        assert output.getpixel((0, 0)) == (248, 250, 252)
    assert profile["original_size"] == "1536x1024"
    assert profile["prepared_size"] == "1024x1024"
    assert profile["transparent_pixel_ratio"] > 0
    assert profile["bytes"] > 0
    assert profile["sdk_attempts_max"] == 3


def test_openai_pattern_error_preserves_code_message_and_request_id(monkeypatch):
    class FakeOpenAIError(Exception):
        code = "unsupported_parameter"
        request_id = "req_openai_pattern_123"

        def __init__(self):
            super().__init__("Unsupported parameter: input_fidelity")

    class FakeImages:
        def edit(self, **_kwargs):
            raise FakeOpenAIError()

    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.images = FakeImages()

    monkeypatch.setattr(image_model, "PROVIDER", "openai")
    monkeypatch.setattr(image_model, "MODEL_NAME", "gpt-image-2")
    monkeypatch.setattr(image_model.app_settings, "openai_api_key", SecretStr("test-key"))
    monkeypatch.setattr(image_model, "OpenAI", FakeOpenAI)

    try:
        image_model._openai_pattern_image(Image.open(BytesIO(png_bytes())), "single", "standard")
    except image_model.ModelGenerationError as exc:
        assert exc.provider_code == "unsupported_parameter"
        assert exc.request_id == "req_openai_pattern_123"
        assert "input_fidelity" in (exc.provider_message or "")
    else:
        raise AssertionError("expected ModelGenerationError")


def test_openai_connection_error_is_not_reported_as_generation_timeout():
    class APIConnectionError(Exception):
        def __init__(self):
            super().__init__("Connection error")

    error = image_model._openai_error(APIConnectionError())
    assert error.code == "MODEL_CONNECTION_FAILED"
    assert error.provider_message == "Connection error"


def test_openai_calls_reuse_one_shared_client_with_ten_minute_timeout_and_two_retries(monkeypatch):
    created = []

    class FakeImages:
        def edit(self, **_kwargs):
            encoded = base64.b64encode(png_bytes()).decode()
            return type("Result", (), {"data": [type("ImageData", (), {"b64_json": encoded})()]})()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            created.append(kwargs)
            self.images = FakeImages()

    monkeypatch.setattr(image_model, "PROVIDER", "openai")
    monkeypatch.setattr(image_model, "MODEL_NAME", "gpt-image-2")
    monkeypatch.setattr(image_model.app_settings, "openai_api_key", SecretStr("test-key"))
    monkeypatch.setattr(image_model, "OpenAI", FakeOpenAI)
    source = Image.open(BytesIO(png_bytes()))

    image_model._openai_candidates(source, {"variant": "standard"}, ["standard"])
    image_model._openai_pattern_image(source, "single", "standard")

    assert len(created) == 1
    assert all(item["timeout"] == 600.0 for item in created)
    assert all(item["max_retries"] == 2 for item in created)


def test_openai_connection_error_includes_safe_request_diagnostics():
    class TLSFailure(Exception):
        pass

    class APIConnectionError(Exception):
        def __init__(self):
            super().__init__("Connection error")
            self.__cause__ = TLSFailure("certificate verify failed")

    error = image_model._openai_error(
        APIConnectionError(), operation="direct_pattern", started_at=0.0, trace_id="trace-test",
    )
    assert error.code == "MODEL_CONNECTION_FAILED"
    assert error.diagnostics["trace_id"] == "trace-test"
    assert error.diagnostics["operation"] == "direct_pattern"
    assert error.diagnostics["client"] == "process_shared"
    assert error.diagnostics["exception_chain"][1]["type"] == "TLSFailure"


def test_openai_connection_diagnostics_identify_response_closed_before_http_response(monkeypatch):
    class RemoteProtocolError(Exception):
        pass

    class APIConnectionError(Exception):
        def __init__(self):
            super().__init__("Connection error")
            self.__cause__ = RemoteProtocolError("Server disconnected without sending a response.")

    monkeypatch.setenv("HTTPS_PROXY", "http://person:secret@127.0.0.1:7890")
    error = image_model._openai_error(APIConnectionError(), operation="direct_pattern")
    assert error.diagnostics["connection_stage"] == "response_not_received_connection_closed"
    assert error.diagnostics["transport"]["proxy_configured"] is True
    assert "127.0.0.1:7890" in error.diagnostics["transport"]["proxy_entries"]
    assert "secret" not in error.diagnostics["transport"]["proxy_entries"]


def test_variants_have_materially_different_board_ready_prompts():
    simplified = image_model._prompt("simplified", {"composition": "full"})
    standard = image_model._prompt("standard", {"composition": "full"})
    rich = image_model._prompt("rich", {"composition": "full"})
    assert "52 by 52" in simplified
    assert "104 by 104" in standard
    assert "original body proportions" in rich
    assert len({simplified, standard, rich}) == 3


def test_standard_prompt_requires_a_true_four_head_chibi_and_single_subject():
    prompt = image_model._prompt("standard", {"composition": "full", "subject_mode": "single"})
    assert "4-head-tall chibi" in prompt
    assert "not a normal-proportioned illustration with only the lower body shrunk" in prompt
    assert "primary subject" in prompt
    assert "background figures" in prompt
    assert "solid #F8FAFC studio backdrop" in prompt


def test_normalize_removes_a_textured_border_connected_model_backdrop():
    image = Image.new("RGBA", (768, 1024), (248, 250, 252, 255))
    draw = ImageDraw.Draw(image)
    for y in range(0, image.height, 11):
        draw.line((0, y, image.width - 1, y), fill=(238, 241, 246, 255))
    draw.ellipse((210, 170, 570, 900), fill=(44, 81, 140, 255))
    raw = BytesIO()
    image.save(raw, "PNG")
    normalized = image_model._normalize_png(raw.getvalue(), "standard", "openai")
    with Image.open(BytesIO(normalized)) as output:
        assert output.mode == "RGBA"
        assert output.getpixel((0, 0))[3] == 0
        assert output.getpixel((384, 500))[3] == 255


def test_complexity_router_recommends_larger_board_for_dense_material():
    simple = Image.new("RGB", (300, 300), "white")
    dense = Image.new("RGB", (300, 300), "white")
    pixels = dense.load()
    for y in range(300):
        for x in range(300):
            pixels[x, y] = ((x * 17 + y * 31) % 256, (x * 41) % 256, (y * 53) % 256)
    simple_bytes, dense_bytes = BytesIO(), BytesIO()
    simple.save(simple_bytes, "PNG")
    dense.save(dense_bytes, "PNG")
    simple_result = analyze_material_complexity(simple_bytes.getvalue())
    dense_result = analyze_material_complexity(dense_bytes.getvalue())
    assert dense_result["complexityScore"] > simple_result["complexityScore"]
    assert dense_result["route"] == "model-semantic-2d"


def test_flat_cartoon_is_not_misclassified_because_background_is_opaque():
    image = Image.new("RGB", (300, 300), "white")
    from PIL import ImageDraw
    draw = ImageDraw.Draw(image)
    draw.ellipse((60, 60, 240, 240), fill="#efc53b", outline="#333333", width=12)
    output = BytesIO()
    image.save(output, "PNG")
    result = analyze_material_complexity(output.getvalue())
    assert result["complexityLevel"] == "simple"
    assert result["recommendedBoard"] == "52×52"
