from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app


def test_attachment_accepts_and_compresses_jpeg():
    with TestClient(app) as client:
        login = client.post('/auth/login', data={'username': 'administrador@aeroops.local', 'password': 'Aero@123'})
        client.headers['Authorization'] = f"Bearer {login.json()['access_token']}"
        image = Image.new('RGB', (3000, 3000), 'blue')
        source = BytesIO()
        image.save(source, format='PNG')
        response = client.post('/attachments', files={'file': ('evidencia.png', source.getvalue(), 'image/png')})
        assert response.status_code == 201
        assert response.json()['content_type'] == 'image/jpeg'


def test_attachment_rejects_unsupported_format():
    with TestClient(app) as client:
        login = client.post('/auth/login', data={'username': 'administrador@aeroops.local', 'password': 'Aero@123'})
        client.headers['Authorization'] = f"Bearer {login.json()['access_token']}"
        response = client.post('/attachments', files={'file': ('evidencia.txt', b'texto', 'text/plain')})
        assert response.status_code == 415
