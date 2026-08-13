from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.db import Base, engine
from app.main import app


def setup_module():
    Path(".data").mkdir(parents=True, exist_ok=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    settings.storage_root.mkdir(parents=True, exist_ok=True)


def test_create_upload_and_reopen_project():
    with TestClient(app) as client:
        created = client.post("/api/v1/projects", json={"name": "柠檬宝宝"}).json()
        assert created["current_stage"] == "material"
        project_id = created["id"]

        upload = client.post(
            f"/api/v1/projects/{project_id}/assets",
            files=[("files", ("lemon.png", b"\x89PNG\r\nstage-zero", "image/png"))],
        )
        assert upload.status_code == 201
        assert upload.json()[0]["sha256"]

        reopened = client.get(f"/api/v1/projects/{project_id}")
        assert reopened.status_code == 200
        body = reopened.json()
        assert body["name"] == "柠檬宝宝"
        assert body["assets"][0]["original_name"] == "lemon.png"


def test_owner_boundary_is_enforced():
    with TestClient(app) as client:
        project = client.post(
            "/api/v1/projects",
            json={"name": "私有项目"},
            headers={"X-Owner-Id": "owner-a"},
        ).json()
        hidden = client.get(
            f"/api/v1/projects/{project['id']}",
            headers={"X-Owner-Id": "owner-b"},
        )
        assert hidden.status_code == 404


def test_list_preview_backup_and_restore():
    with TestClient(app) as client:
        created = client.post("/api/v1/projects", json={"name": "备份测试"}).json()
        project_id = created["id"]
        upload = client.post(
            f"/api/v1/projects/{project_id}/assets",
            files=[("files", ("sample.webp", b"RIFF-local-first", "image/webp"))],
        )
        asset_id = upload.json()[0]["id"]

        listing = client.get("/api/v1/projects").json()
        assert listing["total"] >= 1
        assert any(item["id"] == project_id for item in listing["items"])
        preview = client.get(
            f"/api/v1/projects/{project_id}/assets/{asset_id}/content"
        )
        assert preview.content == b"RIFF-local-first"

        backup = client.get(f"/api/v1/projects/{project_id}/backup")
        assert backup.status_code == 200
        restored = client.post(
            "/api/v1/project-backups/import",
            files=[("file", ("project.perler.zip", backup.content, "application/zip"))],
        )
        assert restored.status_code == 201
        restored_project = restored.json()["project"]
        assert restored_project["id"] != project_id
        assert restored_project["assets"][0]["sha256"] == upload.json()[0]["sha256"]


def test_rejects_invalid_backup():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/project-backups/import",
            files=[("file", ("broken.zip", b"not-a-zip", "application/zip"))],
        )
        assert response.status_code == 422
