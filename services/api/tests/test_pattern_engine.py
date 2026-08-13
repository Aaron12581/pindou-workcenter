import csv
import hashlib
import json
import zipfile
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.main import app
from app.image_model import ModelGenerationError
from app.mard_palette import MARD_STANDARD_PALETTE
from app.pattern_engine import _collapse_flat_source_variants, _collapse_low_contrast_blocks, _delta_e_2000, _enforce_mode_palette, _lab, _preserve_hand_contrast, generate_pattern, generate_pattern_from_model_grid, generate_pattern_from_model_image


def sample_png() -> bytes:
    image = Image.new("RGBA", (96, 72), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((12, 5, 84, 69), fill="#ffd83f", outline="#452719", width=5)
    draw.ellipse((30, 27, 40, 39), fill="#232323")
    draw.ellipse((56, 27, 66, 39), fill="#232323")
    draw.arc((37, 34, 59, 56), 10, 170, fill="#e54b4f", width=3)
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def confirmed_2d(client: TestClient, project_id: str, source_asset_id: str) -> dict:
    candidates = client.post(
        f"/api/v1/projects/{project_id}/2d-candidates",
        json={"source_asset_id": source_asset_id},
    )
    assert candidates.status_code == 201
    standard = next(item for item in candidates.json() if item["variant"] == "standard")
    # Downstream engine tests use an explicitly injected formal-asset fixture.
    # The public confirmation route correctly rejects offline preview renders.
    confirmed = client.patch(
        f"/api/v1/projects/{project_id}/assets/{standard['asset']['id']}/role",
        json={"role": "confirmed_2d"},
    )
    assert confirmed.status_code == 200
    return confirmed.json()


def test_standard_palette_and_quad_pattern_semantics():
    assert len(MARD_STANDARD_PALETTE) == 221
    pattern = generate_pattern(sample_png(), layout="quad", color_mode="standard")
    assert pattern["width"] == 104
    assert pattern["height"] == 104
    assert pattern["boardLayout"]["seamsX"] == [52]
    assert pattern["boardLayout"]["seamsY"] == [52]
    assert pattern["statistics"]["totalBeads"] == len(pattern["cells"])
    assert 1 <= pattern["statistics"]["colorCount"] <= len(MARD_STANDARD_PALETTE)
    assert {cell["boardId"] for cell in pattern["cells"]} <= {"A1", "A2", "B1", "B2"}
    assert all(cell["brand"] == "MARD" and cell["colorCode"] for cell in pattern["cells"])


def test_opaque_pale_canvas_is_removed_before_local_pattern_sampling():
    image = Image.new("RGBA", (120, 120), "#F8FAFC")
    draw = ImageDraw.Draw(image)
    draw.ellipse((32, 24, 88, 96), fill="#d59b7a")
    draw.ellipse((47, 49, 53, 55), fill="#2d2830")
    output = BytesIO()
    image.save(output, "PNG")

    pattern = generate_pattern(output.getvalue(), layout="single", color_mode="standard")

    removal = pattern["statistics"]["backgroundRemoval"]
    assert removal["applied"] is True
    assert removal["removedPixels"] > 9000
    # The white canvas must not turn into a nearly full 52×52 bead board.
    assert pattern["statistics"]["totalBeads"] < 2500


def test_flat_face_does_not_receive_invented_local_features():
    image = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((18, 10, 78, 88), fill="#e9ae8a")
    output = BytesIO()
    image.save(output, "PNG")

    pattern = generate_pattern(output.getvalue(), layout="single", color_mode="standard")

    # A uniformly coloured face should remain a single official bead colour;
    # the engine must not add generic eyes, brows or mouth beads.
    assert len({cell["colorCode"] for cell in pattern["cells"]}) == 1


def test_direct_model_image_is_sampled_mechanically_into_editable_mard_cells():
    pattern = generate_pattern_from_model_image(
        sample_png(), layout="single", color_mode="rich", model="qwen-image-2.0",
    )
    assert pattern["statistics"]["semanticPlanning"]["generationMode"] == "direct-model-image"
    assert pattern["statistics"]["semanticPlanning"]["model"] == "qwen-image-2.0"
    assert pattern["statistics"]["totalBeads"] == len(pattern["cells"])
    assert all(cell["brand"] == "MARD" and cell["boardId"] == "A1" for cell in pattern["cells"])


def test_detail_tier_palette_limits_are_maximums_not_fixed_counts():
    assignments = {
        (index, 0): (color, 0.0)
        for index, color in enumerate(MARD_STANDARD_PALETTE[:50])
    }
    for mode, maximum in (("limited", 16), ("standard", 30), ("rich", 42)):
        reduced, changed, before = _enforce_mode_palette(assignments, mode)
        assert before == 50
        assert len({color.code for color, _ in reduced.values()}) <= maximum
        assert changed > 0


def test_generate_endpoint_uses_model_image_path_without_text_grid(monkeypatch):
    monkeypatch.setattr("app.main.planner_status", lambda: {"enabled": True, "configured": True, "plannerVersion": "direct-pattern-image-v6"})
    monkeypatch.setattr("app.main.model_status", lambda: {"model": "qwen-image-2.0"})
    monkeypatch.setattr("app.main.generate_direct_pattern_image", lambda *_args, **_kwargs: sample_png())
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "模型像素成图"}).json()
        source = client.post(
            f"/api/v1/projects/{project['id']}/assets",
            files={"files": ("source.png", sample_png(), "image/png")},
        ).json()[0]
        formal = confirmed_2d(client, project["id"], source["id"])
        response = client.post(f"/api/v1/projects/{project['id']}/patterns/generate", json={
            "source_asset_id": formal["id"], "board_layout": "single", "color_mode": "standard", "generation_mode": "model_direct",
        })
        assert response.status_code == 201
        planning = response.json()["pattern"]["statistics"]["semanticPlanning"]
        assert planning["used"] is True
        assert planning["generationMode"] == "direct-model-image"
        assert planning["fallback"] is False


def test_configured_model_failure_does_not_save_a_local_fallback(monkeypatch):
    monkeypatch.setattr("app.main.planner_status", lambda: {"enabled": True, "configured": True, "plannerVersion": "direct-pattern-image-v6"})
    def fail(*_args, **_kwargs):
        raise ModelGenerationError("MODEL_TIMEOUT", provider_message="simulated provider timeout")
    monkeypatch.setattr("app.main.generate_direct_pattern_image", fail)
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "模型失败不回退"}).json()
        source = client.post(
            f"/api/v1/projects/{project['id']}/assets",
            files={"files": ("source.png", sample_png(), "image/png")},
        ).json()[0]
        formal = confirmed_2d(client, project["id"], source["id"])
        response = client.post(f"/api/v1/projects/{project['id']}/patterns/generate", json={
            "source_asset_id": formal["id"], "board_layout": "single", "color_mode": "standard", "generation_mode": "model_direct",
        })
        assert response.status_code == 502
        assert response.json()["detail"]["code"] == "MODEL_TIMEOUT"
        assert client.get(f"/api/v1/projects/{project['id']}/patterns:latest").status_code == 404


def test_explicit_local_mode_never_calls_the_image_model(monkeypatch):
    def should_not_run(*_args, **_kwargs):
        raise AssertionError("local generation must not call the image model")

    monkeypatch.setattr("app.main.generate_direct_pattern_image", should_not_run)
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "本地语义简化"}).json()
        source = client.post(
            f"/api/v1/projects/{project['id']}/assets",
            files={"files": ("source.png", sample_png(), "image/png")},
        ).json()[0]
        formal = confirmed_2d(client, project["id"], source["id"])
        response = client.post(f"/api/v1/projects/{project['id']}/patterns/generate", json={
            "source_asset_id": formal["id"], "board_layout": "single", "color_mode": "standard",
            "generation_mode": "local",
        })
        assert response.status_code == 201
        pattern = response.json()["pattern"]
        assert pattern["statistics"]["semanticPlanning"]["requestedMode"] == "local"
        assert pattern["statistics"]["semanticPlanning"]["generationMode"] == "local-deterministic"


def test_single_standard_board_is_52_and_custom_layout_is_real():
    single = generate_pattern(sample_png(), layout="single", color_mode="standard")
    custom = generate_pattern(sample_png(), layout="custom_3x1", color_mode="rich")
    assert (single["width"], single["height"]) == (52, 52)
    assert single["boardLayout"]["boardWidth"] == 52
    assert (custom["width"], custom["height"]) == (156, 52)
    assert custom["boardLayout"]["columns"] == 3
    assert custom["boardLayout"]["seamsX"] == [52, 104]


def test_thin_weapon_detail_survives_pattern_generation():
    image = Image.new("RGBA", (600, 800), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((360, 210, 540, 650), fill="#c83d32")
    draw.line((400, 440, 25, 700), fill="#c8cbd1", width=9)
    output = BytesIO()
    image.save(output, "PNG")
    pattern = generate_pattern(output.getvalue(), layout="single", color_mode="rich")
    leftmost = min(cell["x"] for cell in pattern["cells"])
    rightmost = max(cell["x"] for cell in pattern["cells"])
    assert leftmost < 8
    assert rightmost > 38
    occupied = {(cell["x"], cell["y"]) for cell in pattern["cells"]}
    sword_band = {(x, y) for x, y in occupied if x < 38 and y > 25}
    components = []
    while sword_band:
        pending = [sword_band.pop()]
        component = set(pending)
        while pending:
            x, y = pending.pop()
            for point in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if point in sword_band:
                    sword_band.remove(point)
                    component.add(point)
                    pending.append(point)
        components.append(component)
    assert max(map(len, components)) >= 20
    assert pattern["engineVersion"] == "direct-model-grid-v12"


def test_source_backed_hair_and_garment_outlines_survive_grid_reduction():
    """Continuous dark silhouette lines must not dissolve into their fills."""
    image = Image.new("RGBA", (620, 820), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    outline = "#2b2230"
    # Head/hair silhouette and coat edge are intentionally only 10px wide:
    # after fitting to a 52×52 board, ordinary BOX sampling would otherwise
    # turn much of each line into the adjoining fill colour.
    draw.ellipse((165, 70, 455, 365), fill="#76546D", outline=outline, width=10)
    draw.rounded_rectangle((130, 325, 490, 720), radius=76, fill="#D58F49", outline=outline, width=10)
    output = BytesIO()
    image.save(output, "PNG")

    pattern = generate_pattern(output.getvalue(), layout="single", color_mode="standard")

    def luma(value: str) -> float:
        red, green, blue = (int(value[index:index + 2], 16) for index in (1, 3, 5))
        return .2126 * red + .7152 * green + .0722 * blue

    dark_outline_cells = [
        cell for cell in pattern["cells"]
        if luma(cell["colorValue"]) < 78
    ]
    # Both closed silhouettes remain readable as a continuous structural edge,
    # rather than being collapsed into a mostly flat hair/coat mass.
    assert len(dark_outline_cells) >= 55
    assert pattern["statistics"]["regionCounts"].get("outline", 0) >= 55


def test_flat_face_and_clothing_variants_do_not_become_extra_bead_shades():
    image = Image.new("RGBA", (8, 3), (0, 0, 0, 0))
    pixels = image.load()
    assignments = {}
    regions = {}
    for x in range(8):
        # These low-contrast source differences emulate resampling artefacts,
        # not an intentional cheek, chin or garment seam.
        pixels[x, 0] = (232 + (x % 2), 174, 140, 255)
        assignments[(x, 0)] = (MARD_STANDARD_PALETTE[x % 2], 0.0)
        regions[(x, 0)] = "face"
        pixels[x, 1] = (96 + (x % 2), 74, 68, 255)
        assignments[(x, 1)] = (MARD_STANDARD_PALETTE[x % 2], 0.0)
        regions[(x, 1)] = "clothing"
        pixels[x, 2] = (232 + (x % 2), 174, 140, 255)
        assignments[(x, 2)] = (MARD_STANDARD_PALETTE[x % 2], 0.0)
        regions[(x, 2)] = "hand"

    simplified, changed = _collapse_flat_source_variants(assignments, pixels, regions)

    assert changed > 0
    assert len({simplified[(x, 0)][0].code for x in range(8)}) == 1
    assert len({simplified[(x, 1)][0].code for x in range(8)}) == 1
    # Hand detail is protected and is never flattened by this broad-region pass.
    assert len({simplified[(x, 2)][0].code for x in range(8)}) == 2


def test_low_contrast_face_and_clothing_blocks_are_not_kept_as_shadows():
    image = Image.new("RGBA", (5, 6), (0, 0, 0, 0))
    pixels = image.load()
    assignments = {}
    regions = {}
    edges = {}
    base, shade = MARD_STANDARD_PALETTE[0], MARD_STANDARD_PALETTE[1]
    for row, region in enumerate(("face", "face", "face", "clothing", "clothing", "clothing")):
        for x in range(5):
            point = (x, row)
            is_shade = x == 2
            assignments[point] = (shade if is_shade else base, 0.0)
            # The second colour is a soft sampling variation, not a seam.
            pixels[x, row] = (236, 178, 143, 255) if is_shade else (232, 174, 140, 255)
            regions[point] = region
            edges[point] = 0

    simplified, changed = _collapse_low_contrast_blocks(assignments, pixels, edges, regions)

    assert changed == 6
    assert {item[0].code for item in simplified.values()} == {base.code}


def test_hand_mapping_preserves_a_source_backed_boundary_against_clothing():
    image = Image.new("RGBA", (2, 1), (0, 0, 0, 0))
    pixels = image.load()
    # The source has a clear skin/garment boundary, but the first catalogue
    # mapping has collapsed both cells to one pale bead.
    pixels[0, 0] = (225, 179, 131, 255)
    pixels[1, 0] = (233, 156, 23, 255)
    same = MARD_STANDARD_PALETTE[0]
    hand_colour = next(item for item in MARD_STANDARD_PALETTE if item.code == "G4")
    palette = tuple((item, _lab(item.rgb)) for item in (same, hand_colour))
    preserved, changed = _preserve_hand_contrast(
        {(0, 0): (same, 0.0), (1, 0): (same, 0.0)},
        pixels,
        {(0, 0): "hand", (1, 0): "clothing"},
        palette,
    )

    assert changed == 1
    assert preserved[(0, 0)][0].code == hand_colour.code
    assert preserved[(1, 0)][0].code == same.code


def test_direct_model_grid_is_saved_without_local_redraw():
    pattern = generate_pattern_from_model_grid({
        "targetGrid": {"width": 52, "height": 52},
        "runs": [
            {"x": 1, "y": 2, "length": 3, "colorCode": "A1"},
            {"x": 4, "y": 2, "length": 2, "colorCode": "H7"},
        ],
        "plannerVersion": "direct-pattern-generator-v2", "model": "test-model",
    }, layout="single", color_mode="standard")
    assert [(cell["x"], cell["y"], cell["colorCode"]) for cell in pattern["cells"]] == [
        (1, 2, "A1"), (2, 2, "A1"), (3, 2, "A1"), (4, 2, "H7"), (5, 2, "H7"),
    ]
    assert pattern["statistics"]["semanticPlanning"]["generationMode"] == "direct-model-grid"


def test_model_semantic_plan_is_applied_and_auditable():
    plan = {
        "plannerVersion": "semantic-pattern-planner-v1",
        "model": "qwen3-vl-flash",
        "faceBox": [.28, .14, .72, .56],
        "garmentBoxes": [[.2, .5, .8, .95]],
        "facialKeypoints": [
            {"name": "left_eye", "x": .42, "y": .38, "radius": 1},
            {"name": "right_eye", "x": .58, "y": .38, "radius": 1},
        ],
        "thinFeaturePaths": [
            {"name": "sword", "points": [[.1, .85], [.75, .3]], "thickness": 2},
        ],
        "identityPriorities": ["双眼", "剑身连续"],
        "assessment": "初稿弱化了眼睛和剑身。",
        "recommendedAction": "strengthen_thin_features",
    }
    pattern = generate_pattern(
        sample_png(),
        layout="single",
        color_mode="standard",
        semantic_plan=plan,
    )
    local_pattern = generate_pattern(
        sample_png(),
        layout="single",
        color_mode="standard",
    )
    planning = pattern["statistics"]["semanticPlanning"]
    assert planning["used"] is True
    assert planning["appliedCellChanges"] > 0
    assert planning["model"] == "qwen3-vl-flash"
    assert planning["identityPriorities"] == ["双眼", "剑身连续"]
    assert pattern["statistics"]["regionPolicy"] == "model-planned-face-weapon-clothing"
    assert pattern["statistics"]["regionCounts"]["facial_detail"] >= 2
    local_cells = {(cell["x"], cell["y"]): cell["colorCode"] for cell in local_pattern["cells"]}
    model_cells = {(cell["x"], cell["y"]): cell["colorCode"] for cell in pattern["cells"]}
    assert model_cells != local_cells


def test_face_features_and_clothing_keep_independent_colour_budget():
    image = Image.new("RGBA", (420, 720), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((145, 80, 275, 235), fill="#edba94", outline="#3b2828", width=10)
    draw.ellipse((178, 135, 192, 151), fill="#202027")
    draw.ellipse((228, 135, 242, 151), fill="#202027")
    draw.line((202, 178, 222, 178), fill="#a33f43", width=7)
    draw.polygon(((105, 220), (315, 220), (355, 650), (65, 650)), fill="#9c2038")
    draw.line((105, 300, 315, 570), fill="#edc84c", width=22)
    output = BytesIO()
    image.save(output, "PNG")

    pattern = generate_pattern(output.getvalue(), layout="quad", color_mode="standard")
    regions = pattern["statistics"]["regionCounts"]
    assert regions["face"] > 0
    assert regions["facial_detail"] >= 2
    assert regions["clothing"] > regions["face"]
    face_cells = [
        cell for cell in pattern["cells"]
        if 40 <= cell["x"] <= 75 and 12 <= cell["y"] <= 42
    ]
    assert len({cell["colorCode"] for cell in face_cells}) >= 3
    assert pattern["statistics"]["regionPolicy"] == "stable-palette-symbolic-face-weapon-clothing"


def test_larger_board_keeps_identity_colours_while_allowing_extra_detail_colours():
    image = Image.new("RGBA", (480, 760), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((155, 70, 305, 245), fill="#e7ad83", outline="#302426", width=12)
    draw.line((185, 135, 215, 132), fill="#2b2022", width=8)
    draw.line((245, 132, 275, 135), fill="#2b2022", width=8)
    draw.ellipse((196, 145, 209, 159), fill="#17171b")
    draw.ellipse((251, 145, 264, 159), fill="#17171b")
    draw.line((218, 198, 244, 198), fill="#963d45", width=7)
    draw.polygon(((95, 235), (365, 235), (420, 700), (55, 700)), fill="#a61f35")
    draw.polygon(((120, 270), (230, 245), (350, 620), (300, 690)), fill="#5f242b")
    draw.line((125, 330, 340, 590), fill="#d5ae48", width=24)
    output = BytesIO()
    image.save(output, "PNG")

    quad = generate_pattern(output.getvalue(), layout="quad", color_mode="rich")
    nine = generate_pattern(output.getvalue(), layout="custom_3x3", color_mode="rich")
    quad_codes = {item["code"] for item in quad["palette"]}
    nine_codes = {item["code"] for item in nine["palette"]}
    # The 104×104 and 156×156 renderings must retain the same identity colours;
    # richer boards may legitimately expose an additional detail shade.
    assert len(quad_codes & nine_codes) >= min(len(quad_codes), len(nine_codes)) - 1

    def facial_detail_count(pattern):
        width, height = pattern["width"], pattern["height"]
        return sum(
            1 for cell in pattern["cells"]
            if width * .36 <= cell["x"] <= width * .64
            and height * .08 <= cell["y"] <= height * .34
            and cell["colorValue"].lower() in {
                item["value"].lower()
                for item in pattern["palette"]
                if int(item["value"][1:3], 16) < 100
            }
        )

    assert facial_detail_count(quad) >= 4
    assert facial_detail_count(nine) >= facial_detail_count(quad)


def test_ciede2000_matches_reference_pair():
    # Sharma et al. supplementary test pair 1.
    assert abs(
        _delta_e_2000((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485))
        - 2.0425
    ) < .0001


def test_palette_uses_official_colors_without_a_fixed_count_cap():
    pattern = generate_pattern(sample_png(), layout="quad", color_mode="limited")
    assert pattern["statistics"]["colorCount"] <= len(MARD_STANDARD_PALETTE)
    assert pattern["statistics"]["referenceColorPolicy"] == "disabled-global-bias"


def test_pattern_quality_is_evidence_based_and_exposes_warnings():
    pattern = generate_pattern(sample_png(), layout="single", color_mode="standard")
    stats = pattern["statistics"]
    assert 0 <= stats["qualityScore"] <= 100
    assert stats["qualityLevel"] in {"good", "review", "insufficient"}
    assert stats["qualityPolicy"] == "structure-color-makeability-v1"
    assert isinstance(stats["qualityWarnings"], list)


def test_generate_and_reopen_persisted_pattern():
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "真实图纸"}).json()
        upload = client.post(
            f"/api/v1/projects/{project['id']}/assets",
            files=[("files", ("2d.png", sample_png(), "image/png"))],
        ).json()[0]
        upload = confirmed_2d(client, project["id"], upload["id"])
        generated = client.post(
            f"/api/v1/projects/{project['id']}/patterns/generate",
            json={
                "source_asset_id": upload["id"],
                "board_layout": "quad",
                "color_mode": "standard",
            },
        )
        assert generated.status_code == 201
        body = generated.json()
        assert body["pattern"]["statistics"]["totalBeads"] > 0
        reopened = client.get(f"/api/v1/projects/{project['id']}/patterns/{body['id']}")
        assert reopened.status_code == 200
        assert reopened.json()["pattern"] == body["pattern"]


def test_edit_autosave_revision_and_latest_pattern():
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "网格编辑"}).json()
        upload = client.post(
            f"/api/v1/projects/{project['id']}/assets",
            files=[("files", ("2d.png", sample_png(), "image/png"))],
        ).json()[0]
        upload = confirmed_2d(client, project["id"], upload["id"])
        generated = client.post(
            f"/api/v1/projects/{project['id']}/patterns/generate",
            json={"source_asset_id": upload["id"], "board_layout": "single", "color_mode": "limited"},
        ).json()
        initial_total = generated["pattern"]["statistics"]["totalBeads"]
        edited = generated["pattern"]
        edited["cells"] = edited["cells"][1:]
        edited["statistics"]["totalBeads"] -= 1
        saved = client.put(
            f"/api/v1/projects/{project['id']}/patterns/{generated['id']}",
            json={"pattern": edited, "expected_revision": 0},
        )
        assert saved.status_code == 200
        assert saved.json()["pattern"]["revision"] == 1
        conflict = client.put(
            f"/api/v1/projects/{project['id']}/patterns/{generated['id']}",
            json={"pattern": edited, "expected_revision": 0},
        )
        assert conflict.status_code == 409
        latest = client.get(f"/api/v1/projects/{project['id']}/patterns:latest")
        assert latest.status_code == 200
        assert latest.json()["pattern"]["statistics"]["totalBeads"] == edited["statistics"]["totalBeads"]


def test_manual_versions_restore_and_inspection():
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "版本与检查"}).json()
        upload = client.post(
            f"/api/v1/projects/{project['id']}/assets",
            files=[("files", ("2d.png", sample_png(), "image/png"))],
        ).json()[0]
        upload = confirmed_2d(client, project["id"], upload["id"])
        generated = client.post(
            f"/api/v1/projects/{project['id']}/patterns/generate",
            json={"source_asset_id": upload["id"], "board_layout": "quad", "color_mode": "standard"},
        ).json()
        base = f"/api/v1/projects/{project['id']}/patterns/{generated['id']}"
        snapshot = client.post(
            f"{base}/versions",
            headers={"Idempotency-Key": "test-version-001"},
            json={"name": "初始关键版本", "note": "生成后保存", "expected_revision": 0},
        )
        assert snapshot.status_code == 201
        assert snapshot.json()["version_no"] == 1
        initial_total = generated["pattern"]["statistics"]["totalBeads"]
        edited = generated["pattern"]
        edited["cells"] = edited["cells"][1:]
        edited["statistics"]["totalBeads"] -= 1
        saved = client.put(base, json={"pattern": edited, "expected_revision": 0}).json()
        restored = client.post(
            f"{base}/versions/{snapshot.json()['id']}/restore",
            headers={"Idempotency-Key": "test-restore-001"},
            json={"expected_revision": 1},
        )
        assert restored.status_code == 200
        assert restored.json()["pattern"]["revision"] == 2
        assert restored.json()["pattern"]["statistics"]["totalBeads"] == initial_total
        versions = client.get(f"{base}/versions").json()
        assert versions["total"] == 1 and versions["items"][0]["pattern"] is None
        inspection = client.post(f"{base}/inspect")
        assert inspection.status_code == 200
        report = inspection.json()
        assert report["inspected_revision"] == 2
        assert report["summary"]["total"] == len(report["issues"])
        assert report["summary"]["blocking"] == 0


def test_formal_export_contains_pdf_png_csv_json_and_manifest():
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "正式导出"}).json()
        upload = client.post(
            f"/api/v1/projects/{project['id']}/assets",
            files=[("files", ("2d.png", sample_png(), "image/png"))],
        ).json()[0]
        upload = confirmed_2d(client, project["id"], upload["id"])
        generated = client.post(
            f"/api/v1/projects/{project['id']}/patterns/generate",
            json={"source_asset_id": upload["id"], "board_layout": "quad", "color_mode": "standard"},
        ).json()
        base = f"/api/v1/projects/{project['id']}/patterns/{generated['id']}"
        created = client.post(f"{base}/exports", json={"expected_revision": 0})
        assert created.status_code == 201
        export = created.json()
        assert export["board_count"] == 4
        assert export["total_beads"] == generated["pattern"]["statistics"]["totalBeads"]
        download = client.get(export["download_url"])
        assert download.status_code == 200
        archive = zipfile.ZipFile(BytesIO(download.content))
        names = set(archive.namelist())
        assert "拼豆图纸包.pdf" in names
        assert "完整图纸/完整图纸_带色号.png" in names
        assert "色号用量/MARD_色号用量.csv" in names
        assert "数据/pattern.json" in names
        assert {f"分板图/{item}.png" for item in ("A1", "A2", "B1", "B2")} <= names
        manifest = json.loads(archive.read("manifest.json"))
        for item in manifest["files"]:
            assert hashlib.sha256(archive.read(item["path"])).hexdigest() == item["sha256"]
        rows = list(csv.reader(
            archive.read("色号用量/MARD_色号用量.csv").decode("utf-8-sig").splitlines()
        ))
        assert int(rows[-1][-1]) == generated["pattern"]["statistics"]["totalBeads"]
        assert archive.read("拼豆图纸包.pdf").startswith(b"%PDF")
        conflict = client.post(f"{base}/exports", json={"expected_revision": 99})
        assert conflict.status_code == 409


def test_batch_generation_confirmation_and_export():
    with TestClient(app) as client:
        project = client.post("/api/v1/projects", json={"name": "批量生产"}).json()
        uploads = client.post(
            f"/api/v1/projects/{project['id']}/assets",
            files=[
                ("files", ("one.png", sample_png(), "image/png")),
                ("files", ("two.png", sample_png(), "image/png")),
            ],
        ).json()
        payload = {
            "source_asset_ids": [item["id"] for item in uploads],
            "board_layout": "single",
            "color_mode": "limited",
        }
        assert client.post(f"/api/v1/projects/{project['id']}/batches", json=payload).status_code == 409
        for item in uploads:
            assert client.patch(
                f"/api/v1/projects/{project['id']}/assets/{item['id']}/role",
                json={"role": "confirmed_2d"},
            ).status_code == 200
        created = client.post(f"/api/v1/projects/{project['id']}/batches", json=payload)
        assert created.status_code == 201
        job = created.json()
        assert job["status"] == "succeeded"
        assert job["summary"]["succeeded"] == 2
        item_ids = [item["id"] for item in job["items"]]
        confirmed = client.post(
            f"/api/v1/projects/{project['id']}/batches/{job['id']}/confirm",
            json={"item_ids": item_ids},
        )
        assert confirmed.status_code == 200
        exported = client.post(f"/api/v1/projects/{project['id']}/batches/{job['id']}/export")
        assert exported.status_code == 200
        assert exported.json()["item_count"] == 2
        download = client.get(exported.json()["download_url"])
        assert download.status_code == 200
        archive = zipfile.ZipFile(BytesIO(download.content))
        assert "batch-manifest.json" in archive.namelist()
        assert len([name for name in archive.namelist() if name.endswith("/图纸包.zip")]) == 2
        assert client.post(f"/api/v1/projects/{project['id']}/batches/{job['id']}/retry").status_code == 409
        backup = client.get(f"/api/v1/projects/{project['id']}/backup")
        restored = client.post(
            "/api/v1/project-backups/import",
            files=[("file", ("batch.perler.zip", backup.content, "application/zip"))],
        ).json()["project"]
        restored_jobs = client.get(f"/api/v1/projects/{restored['id']}/batches").json()
        assert restored_jobs["total"] == 1
        assert restored_jobs["items"][0]["summary"]["succeeded"] == 2
        assert all(item["confirmed"] for item in restored_jobs["items"][0]["items"])
