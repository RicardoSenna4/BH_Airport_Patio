from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app


def valid_png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (8, 8), "blue").save(output, format="PNG")
    return output.getvalue()


def auth(client: TestClient) -> dict[str, str]:
    response = client.post("/auth/login", data={"username": "fiscal@aeroops.local", "password": "Aero@123"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_upload_validates_signature_sanitizes_name_and_protects_download():
    with TestClient(app) as client:
        headers = auth(client)
        inspection = client.post("/inspections", headers=headers, json={
            "apron": "Pátio 1", "shift": "Dia",
            "answers": [{"item_key": "piso", "label": "Piso", "status": "CONFORME"}],
        })
        assert inspection.status_code == 201
        inspection_id = inspection.json()["id"]
        params = {"inspection_id": inspection_id}

        fake = client.post("/attachments", params=params, headers=headers, files={"file": ("fake.png", BytesIO(b"not a png"), "image/png")})
        assert fake.status_code == 415

        uploaded = client.post("/attachments", params=params, headers=headers, files={"file": ("../../evidence.png", BytesIO(valid_png()), "image/png")})
        assert uploaded.status_code == 201
        body = uploaded.json()
        assert body["filename"] == "evidence.png"
        assert body["storage_path"].startswith("/attachments/")
        with TestClient(app) as anonymous:
            assert anonymous.get(body["storage_path"]).status_code == 401
        downloaded = client.get(body["storage_path"], headers=headers)
        assert downloaded.status_code == 200
        assert downloaded.content.startswith(b"\x89PNG\r\n\x1a\n")
        Image.open(BytesIO(downloaded.content)).verify()
