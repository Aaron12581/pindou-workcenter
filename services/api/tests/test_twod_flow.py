from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, PngImagePlugin

from app.main import app
import app.main as main_module
from app.twod_engine import inspect_candidate, prepare_model_source


def source_png() -> bytes:
    image = Image.new("RGB", (180, 220), "#f6f2e7")
    draw = ImageDraw.Draw(image)
    draw.ellipse((35, 20, 145, 130), fill="#ffd65a", outline="#694c32", width=6)
    draw.rectangle((62, 120, 118, 204), fill="#55a9d8")
    draw.ellipse((65, 60, 78, 74), fill="#242424")
    draw.ellipse((102, 60, 115, 74), fill="#242424")
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def test_model_reference_uses_the_selected_subject_box_not_the_full_scene():
    image = Image.new("RGBA", (600, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((50, 60, 230, 350), fill="#d04b42")
    draw.ellipse((370, 50, 570, 350), fill="#315fa6")
    raw = BytesIO()
    image.save(raw, "PNG")
    prepared = prepare_model_source(raw.getvalue(), {
        "subject_boxes": [{"x": 0.05, "y": 0.1, "width": 0.38, "height": 0.8}],
        "composition": "full",
    })
    with Image.open(BytesIO(prepared)) as output:
        red_pixels = sum(red > blue + 35 for red, _green, blue, _alpha in output.getdata())
        blue_pixels = sum(blue > red + 35 for red, _green, blue, _alpha in output.getdata())
        assert red_pixels > 10_000
        assert blue_pixels == 0


def test_model_reference_keeps_complex_unselected_source_pixels_intact():
    """No automatic colour-based cutout may erase dark costume details."""
    image = Image.new("RGBA", (640, 960), "#18202d")
    draw = ImageDraw.Draw(image)
    draw.polygon(((120, 110), (320, 24), (520, 110), (450, 270), (190, 270)), fill="#111827")  # dark hat
    draw.rectangle((180, 270, 460, 790), fill="#173f73")  # blue armour
    draw.rectangle((70, 600, 570, 650), fill="#c7ccd1")  # sword
    raw = BytesIO(); image.save(raw, "PNG")

    prepared = prepare_model_source(raw.getvalue(), {"composition": "full"})
    with Image.open(BytesIO(prepared)) as output:
        assert output.size == image.size
        assert output.getpixel((320, 90)) == (17, 24, 39, 255)
        assert output.getpixel((320, 400)) == (23, 63, 115, 255)
        assert output.getpixel((320, 625)) == (199, 204, 209, 255)


def test_original_to_three_candidates_confirm_and_pattern_gate():
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "原图转 2D"}).json()
        original = client.post(
            f"/api/v1/projects/{project['id']}/assets",
            files=[("files", ("character.png", source_png(), "image/png"))],
        ).json()[0]
        blocked = client.post(
            f"/api/v1/projects/{project['id']}/patterns/generate",
            json={"source_asset_id": original["id"], "board_layout": "single", "color_mode": "standard"},
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "FORMAL_2D_REQUIRED"

        generated = client.post(
            f"/api/v1/projects/{project['id']}/2d-candidates",
            json={"source_asset_id": original["id"]},
        )
        assert generated.status_code == 201
        candidates = generated.json()
        assert [item["variant"] for item in candidates] == ["simplified", "standard", "rich"]
        assert sum(item["recommended"] for item in candidates) == 1
        for item in candidates:
            content = client.get(
                f"/api/v1/projects/{project['id']}/assets/{item['asset']['id']}/content"
            )
            image = Image.open(BytesIO(content.content))
            assert image.mode == "RGBA"
            assert image.size == (768, 768)

        standard = next(item for item in candidates if item["variant"] == "standard")
        confirmed = client.post(
            f"/api/v1/projects/{project['id']}/2d-candidates/confirm",
            json={"candidate_asset_id": standard["asset"]["id"]},
        )
        assert confirmed.status_code == 409
        assert confirmed.json()["detail"]["code"] == "FINAL_2D_GENERATION_REQUIRED"


def test_model_candidates_are_confirmable_and_keep_three_real_variants(monkeypatch):
    def fake_model_candidates(_source: bytes, _settings: dict):
        outputs = {}
        for variant, color in (
            ("simplified", "#4d8cc9"),
            ("standard", "#f2b84b"),
            ("rich", "#d56b82"),
        ):
            image = Image.new("RGBA", (1024, 1536), (255, 255, 255, 0))
            ImageDraw.Draw(image).ellipse((180, 180, 844, 1370), fill=color)
            metadata = PngImagePlugin.PngInfo()
            metadata.add_text("perler_generation_mode", "model_generated")
            metadata.add_text("perler_model", "test-image-model")
            metadata.add_text("perler_variant", variant)
            output = BytesIO()
            image.save(output, "PNG", pnginfo=metadata)
            outputs[variant] = output.getvalue()
        return outputs, {
            "score": 90, "generationMode": "model_generated",
            "model": "test-image-model", "confirmable": True, "warnings": [],
        }

    monkeypatch.setattr(main_module, "generate_model_candidates", fake_model_candidates)
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "成品模型 2D"}).json()
        original = client.post(
            f"/api/v1/projects/{project['id']}/assets",
            files=[("files", ("character.png", source_png(), "image/png"))],
        ).json()[0]
        response = client.post(
            f"/api/v1/projects/{project['id']}/2d-candidates/model",
            json={"source_asset_id": original["id"], "composition": "full"},
        )
        assert response.status_code == 201
        candidates = response.json()
        assert [item["variant"] for item in candidates] == ["simplified", "standard", "rich"]
        listed = client.get(
            f"/api/v1/projects/{project['id']}/2d-candidates/{original['id']}"
        ).json()
        assert all(item["quality"]["generationMode"] == "model_generated" for item in listed)
        standard = next(item for item in listed if item["variant"] == "standard")
        confirmed = client.post(
            f"/api/v1/projects/{project['id']}/2d-candidates/confirm",
            json={"candidate_asset_id": standard["asset"]["id"]},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["role"] == "confirmed_2d"
        refreshed_project = client.get(f"/api/v1/projects/{project['id']}").json()
        assert refreshed_project["current_stage"] == "board"


def test_translucent_canvas_halo_is_not_reported_as_subject_touching_edge():
    """A low-alpha border remnant must not turn a well-margined subject red."""
    image = Image.new("RGBA", (1024, 1536), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1023, 1535), outline=(248, 250, 252, 20), width=2)
    draw.ellipse((250, 160, 774, 1370), fill=(58, 112, 184, 255))
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("perler_generation_mode", "model_generated")
    output = BytesIO(); image.save(output, "PNG", pnginfo=metadata)

    quality = inspect_candidate(output.getvalue())
    assert quality["touchesEdge"] is False
    assert quality["confirmable"] is True
    assert quality["subjectMargins"] == {"left": 250, "top": 160, "right": 249, "bottom": 165}


def test_real_tight_crop_is_a_warning_but_does_not_block_model_confirmation(monkeypatch):
    image = Image.new("RGBA", (1024, 1536), (255, 255, 255, 0))
    ImageDraw.Draw(image).rectangle((0, 100, 700, 1430), fill=(50, 100, 160, 255))
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("perler_generation_mode", "model_generated")
    output = BytesIO(); image.save(output, "PNG", pnginfo=metadata)
    generated = output.getvalue()
    assert inspect_candidate(generated)["touchesEdge"] is True
    assert inspect_candidate(generated)["confirmable"] is True

    def fake_model_candidates(_source: bytes, _settings: dict):
        return {"standard": generated}, {"generationMode": "model_generated", "confirmable": True, "warnings": []}

    monkeypatch.setattr(main_module, "generate_model_candidates", fake_model_candidates)
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "贴边提醒不阻断"}).json()
        original = client.post(
            f"/api/v1/projects/{project['id']}/assets",
            files=[("files", ("source.png", source_png(), "image/png"))],
        ).json()[0]
        candidate = client.post(
            f"/api/v1/projects/{project['id']}/2d-candidates/model",
            json={"source_asset_id": original["id"], "candidate_mode": "single", "variant": "standard"},
        ).json()[0]
        confirmed = client.post(
            f"/api/v1/projects/{project['id']}/2d-candidates/confirm",
            json={"candidate_asset_id": candidate["asset"]["id"]},
        )
        assert confirmed.status_code == 200
        generated_from_legacy_original_id = client.post(
            f"/api/v1/projects/{project['id']}/patterns/generate",
            json={
                "source_asset_id": original["id"],
                "board_layout": "quad",
                "color_mode": "standard",
            },
        )
        assert generated_from_legacy_original_id.status_code == 201
        assert generated_from_legacy_original_id.json()["source_asset_id"] == confirmed.json()["id"]


def test_switching_formal_2d_marks_old_downstream_pattern_stale(monkeypatch):
    def fake_model_candidates(_source: bytes, _settings: dict):
        outputs = {}
        for variant, color in (("standard", "#f2b84b"), ("rich", "#d56b82")):
            image = Image.new("RGBA", (1024, 1536), (255, 255, 255, 0))
            ImageDraw.Draw(image).ellipse((180, 180, 844, 1370), fill=color)
            metadata = PngImagePlugin.PngInfo()
            metadata.add_text("perler_generation_mode", "model_generated")
            metadata.add_text("perler_model", "test-image-model")
            metadata.add_text("perler_variant", variant)
            output = BytesIO()
            image.save(output, "PNG", pnginfo=metadata)
            outputs[variant] = output.getvalue()
        return outputs, {
            "score": 90, "generationMode": "model_generated",
            "model": "test-image-model", "confirmable": True, "warnings": [],
        }

    monkeypatch.setattr(main_module, "generate_model_candidates", fake_model_candidates)
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "切换正式 2D"}).json()
        original = client.post(
            f"/api/v1/projects/{project['id']}/assets",
            files=[("files", ("character.png", source_png(), "image/png"))],
        ).json()[0]
        candidates = client.post(
            f"/api/v1/projects/{project['id']}/2d-candidates/model",
            json={"source_asset_id": original["id"], "candidate_mode": "all"},
        ).json()
        standard = next(item for item in candidates if item["variant"] == "standard")
        rich = next(item for item in candidates if item["variant"] == "rich")
        client.post(
            f"/api/v1/projects/{project['id']}/2d-candidates/confirm",
            json={"candidate_asset_id": standard["asset"]["id"]},
        )
        pattern = client.post(
            f"/api/v1/projects/{project['id']}/patterns/generate",
            json={"source_asset_id": standard["asset"]["id"], "board_layout": "single", "color_mode": "standard"},
        ).json()
        switched = client.post(
            f"/api/v1/projects/{project['id']}/2d-candidates/confirm",
            json={"candidate_asset_id": rich["asset"]["id"]},
        )
        assert switched.status_code == 200
        stale = client.get(
            f"/api/v1/projects/{project['id']}/patterns/{pattern['id']}"
        ).json()
        assert stale["pattern"]["stale"] is True
        assert stale["pattern"]["staleReason"] == "FORMAL_2D_CHANGED"


def test_confirm_repairs_qwen_textured_background_without_regeneration(monkeypatch):
    calls = 0

    def fake_model_candidates(_source: bytes, _settings: dict):
        nonlocal calls
        calls += 1
        image = Image.new("RGBA", (768, 1024), (246, 241, 226, 255))
        draw = ImageDraw.Draw(image)
        for y in range(0, image.height, 7):
            shade = 238 + (y % 19)
            draw.line((0, y, image.width - 1, y), fill=(shade, shade - 3, shade - 8, 255))
        draw.ellipse((190, 120, 580, 900), fill=(188, 52, 42, 255))
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("perler_generation_mode", "model_generated")
        metadata.add_text("perler_model", "qwen-image-2.0")
        metadata.add_text("perler_variant", "standard")
        output = BytesIO()
        image.save(output, "PNG", pnginfo=metadata)
        return {"standard": output.getvalue()}, {
            "score": 90, "generationMode": "model_generated",
            "model": "qwen-image-2.0", "confirmable": True, "warnings": [],
        }

    monkeypatch.setattr(main_module, "generate_model_candidates", fake_model_candidates)
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "纸纹背景确认"}).json()
        original = client.post(
            f"/api/v1/projects/{project['id']}/assets",
            files=[("files", ("source.png", source_png(), "image/png"))],
        ).json()[0]
        candidate = client.post(
            f"/api/v1/projects/{project['id']}/2d-candidates/model",
            json={
                "source_asset_id": original["id"],
                "candidate_mode": "single",
                "variant": "standard",
            },
        ).json()[0]
        confirmed = client.post(
            f"/api/v1/projects/{project['id']}/2d-candidates/confirm",
            json={"candidate_asset_id": candidate["asset"]["id"]},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["role"] == "confirmed_2d"
        assert calls == 1
        restored = client.get(f"/api/v1/projects/{project['id']}").json()
        assert restored["current_stage"] == "board"


def test_model_candidates_can_generate_one_selected_variant(monkeypatch):
    captured = {}

    def fake_model_candidates(_source: bytes, model_settings: dict):
        captured.update(model_settings)
        variant = model_settings["variant"]
        image = Image.new("RGBA", (1024, 1536), (65, 140, 205, 255))
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("perler_generation_mode", "model_generated")
        metadata.add_text("perler_model", "test-image-model")
        metadata.add_text("perler_variant", variant)
        output = BytesIO()
        image.save(output, "PNG", pnginfo=metadata)
        return {variant: output.getvalue()}, {
            "score": 90, "generationMode": "model_generated",
            "model": "test-image-model", "confirmable": True, "warnings": [],
        }

    monkeypatch.setattr(main_module, "generate_model_candidates", fake_model_candidates)
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "单张成品 2D"}).json()
        original = client.post(
            f"/api/v1/projects/{project['id']}/assets",
            files=[("files", ("character.png", source_png(), "image/png"))],
        ).json()[0]
        response = client.post(
            f"/api/v1/projects/{project['id']}/2d-candidates/model",
            json={"source_asset_id": original["id"], "composition": "full",
                  "candidate_mode": "single", "variant": "rich"},
        )
        assert response.status_code == 201
        assert [item["variant"] for item in response.json()] == ["rich"]
        assert captured["candidate_mode"] == "single"
        assert captured["variant"] == "rich"


def test_portrait_is_never_collapsed_to_a_horizontal_strip():
    image = Image.new("RGB", (360, 900), "#b8aa98")
    draw = ImageDraw.Draw(image)
    # Deliberately create a narrow high-contrast band that fooled the old
    # corner-difference mask into cropping away most of the portrait.
    draw.rectangle((55, 390, 305, 505), fill="#172638")
    output = BytesIO()
    image.save(output, "PNG")
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "纵向比例回归"}).json()
        original = client.post(
            f"/api/v1/projects/{project['id']}/assets",
            files=[("files", ("portrait.png", output.getvalue(), "image/png"))],
        ).json()[0]
        candidates = client.post(
            f"/api/v1/projects/{project['id']}/2d-candidates",
            json={"source_asset_id": original["id"]},
        ).json()
        assert candidates[0]["quality"]["geometryFallback"] is True
        assert candidates[0]["quality"]["confirmable"] is False
        content = client.get(
            f"/api/v1/projects/{project['id']}/assets/{candidates[1]['asset']['id']}/content"
        ).content
        candidate = Image.open(BytesIO(content)).convert("RGBA")
        alpha_bbox = candidate.getchannel("A").getbbox()
        assert alpha_bbox is not None
        width = alpha_bbox[2] - alpha_bbox[0]
        height = alpha_bbox[3] - alpha_bbox[1]
        assert height > width * 2


def test_regeneration_preserves_paid_candidate_history():
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "候选再生成"}).json()
        original = client.post(
            f"/api/v1/projects/{project['id']}/assets",
            files=[("files", ("source.png", source_png(), "image/png"))],
        ).json()[0]
        first = client.post(
            f"/api/v1/projects/{project['id']}/2d-candidates",
            json={"source_asset_id": original["id"]},
        ).json()
        second = client.post(
            f"/api/v1/projects/{project['id']}/2d-candidates",
            json={"source_asset_id": original["id"]},
        ).json()
        assert len(second) == 3
        assert {item["asset"]["id"] for item in first}.isdisjoint(
            {item["asset"]["id"] for item in second}
        )
        history = client.get(
            f"/api/v1/projects/{project['id']}/2d-candidates/{original['id']}"
        ).json()
        assert len(history) == 6


def test_regeneration_keeps_confirmed_2d_and_downstream_pattern_until_new_confirmation():
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "预处理回退"}).json()
        original = client.post(
            f"/api/v1/projects/{project['id']}/assets",
            files=[("files", ("source.png", source_png(), "image/png"))],
        ).json()[0]
        candidates = client.post(
            f"/api/v1/projects/{project['id']}/2d-candidates",
            json={"source_asset_id": original["id"]},
        ).json()
        formal = client.patch(
            f"/api/v1/projects/{project['id']}/assets/{candidates[1]['asset']['id']}/role",
            json={"role": "confirmed_2d"},
        ).json()
        pattern = client.post(
            f"/api/v1/projects/{project['id']}/patterns/generate",
            json={"source_asset_id": formal["id"], "board_layout": "single", "color_mode": "standard"},
        ).json()
        regenerated = client.post(
            f"/api/v1/projects/{project['id']}/2d-candidates",
            json={"source_asset_id": original["id"], "crop": {"x": .05, "y": .05, "width": .9, "height": .9}},
        )
        assert regenerated.status_code == 201
        stale = client.get(
            f"/api/v1/projects/{project['id']}/patterns/{pattern['id']}"
        ).json()
        assert stale["pattern"].get("stale") is not True
        loaded = client.get(f"/api/v1/projects/{project['id']}").json()
        assert any(asset["id"] == formal["id"] and asset["role"] == "confirmed_2d" for asset in loaded["assets"])


def test_manual_mask_multi_subject_crop_and_quality_report():
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "复杂背景修正"}).json()
        original = client.post(
            f"/api/v1/projects/{project['id']}/assets",
            files=[("files", ("complex.png", source_png(), "image/png"))],
        ).json()[0]
        response = client.post(
            f"/api/v1/projects/{project['id']}/2d-candidates",
            json={
                "source_asset_id": original["id"],
                "composition": "half",
                "crop": {"x": 0.05, "y": 0.05, "width": 0.9, "height": 0.9},
                "subject_boxes": [{"x": 0.1, "y": 0.05, "width": 0.8, "height": 0.9}],
                "mask_strokes": [
                    {"x": 0.5, "y": 0.2, "radius": 0.05, "mode": "keep"},
                    {"x": 0.05, "y": 0.05, "radius": 0.04, "mode": "remove"},
                ],
            },
        )
        assert response.status_code == 201
        assert len(response.json()) == 3
        quality = response.json()[0]["quality"]
        assert quality["manuallyAdjusted"] is True
        assert 0 <= quality["score"] <= 100
        listed = client.get(
            f"/api/v1/projects/{project['id']}/2d-candidates/{original['id']}"
        ).json()
        assert listed[0]["quality"]["coverage"] > 0


def test_backup_restores_candidate_relationship_without_false_confirmation():
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "2D 备份"}).json()
        original = client.post(
            f"/api/v1/projects/{project['id']}/assets",
            files=[("files", ("source.png", source_png(), "image/png"))],
        ).json()[0]
        candidates = client.post(
            f"/api/v1/projects/{project['id']}/2d-candidates",
            json={"source_asset_id": original["id"]},
        ).json()
        backup = client.get(f"/api/v1/projects/{project['id']}/backup")
        restored = client.post(
            "/api/v1/project-backups/import",
            files=[("file", ("2d.perler.zip", backup.content, "application/zip"))],
        ).json()["project"]
        restored_original = next(item for item in restored["assets"] if item["role"] == "original")
        restored_candidates = client.get(
            f"/api/v1/projects/{restored['id']}/2d-candidates/{restored_original['id']}"
        )
        assert restored_candidates.status_code == 200
        assert len(restored_candidates.json()) == 3
        assert sum(
            item["asset"]["role"] == "confirmed_2d"
            for item in restored_candidates.json()
        ) == 0
