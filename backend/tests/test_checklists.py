from fastapi.testclient import TestClient

from app.main import app


def login(client, email):
    response = client.post('/auth/login', data={'username': email, 'password': 'Aero@123'})
    assert response.status_code == 200
    return response.json()['access_token']


def test_admin_creates_and_publishes_checklist():
    with TestClient(app) as client:
        client.headers['Authorization'] = f'Bearer {login(client, "fiscal@aeroops.local")}'
        payload = {'name': 'Checklist de teste', 'inspection_type': 'PISTA', 'items': [{'item_key': 'item_1', 'label': 'Verificar pista'}]}
        assert client.post('/checklist-templates', json=payload).status_code == 403
        client.headers['Authorization'] = f'Bearer {login(client, "administrador@aeroops.local")}'
        created = client.post('/checklist-templates', json=payload)
        assert created.status_code == 201
        template_id = created.json()['id']
        published = client.patch(f'/checklist-templates/{template_id}/status', json={'status': 'PUBLICADO'})
        assert published.status_code == 200
        assert published.json()['status'] == 'PUBLICADO'
