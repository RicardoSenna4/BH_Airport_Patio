from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app


def authenticated_inspection(client: TestClient) -> int:
    login = client.post('/auth/login', data={'username': 'administrador@aeroops.local', 'password': 'Aero@123'})
    client.headers['Authorization'] = f"Bearer {login.json()['access_token']}"
    inspection = client.post('/inspections', json={
        'apron': 'Pátio 1', 'shift': 'Dia',
        'answers': [{'item_key': 'piso', 'label': 'Piso', 'status': 'CONFORME'}],
    })
    assert inspection.status_code == 201
    return inspection.json()['id']


def test_attachment_accepts_validates_and_resizes_image():
    with TestClient(app) as client:
        inspection_id = authenticated_inspection(client)
        image = Image.new('RGB', (3000, 3000), 'blue')
        source = BytesIO()
        image.save(source, format='PNG')
        response = client.post(f'/attachments?inspection_id={inspection_id}', files={'file': ('evidencia.png', source.getvalue(), 'image/png')})
        assert response.status_code == 201
        assert response.json()['content_type'] == 'image/png'
        downloaded = client.get(response.json()['storage_path'])
        resized = Image.open(BytesIO(downloaded.content))
        assert max(resized.size) == 2048


def test_attachment_rejects_unsupported_format():
    with TestClient(app) as client:
        inspection_id = authenticated_inspection(client)
        response = client.post(f'/attachments?inspection_id={inspection_id}', files={'file': ('evidencia.txt', b'texto', 'text/plain')})
        assert response.status_code == 415
