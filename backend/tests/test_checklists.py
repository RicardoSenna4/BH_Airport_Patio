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
        created_by_fiscal = client.post('/checklist-templates', json=payload)
        assert created_by_fiscal.status_code == 201
        fiscal_template_id = created_by_fiscal.json()['id']
        submitted = client.patch(f'/checklist-templates/{fiscal_template_id}/status', json={'status': 'EM_REVISAO'})
        assert submitted.status_code == 200
        client.headers['Authorization'] = f'Bearer {login(client, "administrador@aeroops.local")}'
        created = client.post('/checklist-templates', json={**payload, 'name': 'Checklist administrador'})
        assert created.status_code == 201
        template_id = created.json()['id']
        published = client.patch(f'/checklist-templates/{template_id}/status', json={'status': 'PUBLICADO'})
        assert published.status_code == 200
        assert published.json()['status'] == 'PUBLICADO'


def test_checklist_creation_accepts_attached_pdf():
    with TestClient(app) as client:
        client.headers['Authorization'] = f'Bearer {login(client, "fiscal@aeroops.local")}'
        payload = {'name': 'Checklist com anexo', 'inspection_type': 'PATIO', 'items': [{'item_key': 'item_1', 'label': 'Verificar área'}]}
        created = client.post('/checklist-templates', json=payload)
        assert created.status_code == 201
        uploaded = client.post(f"/attachments?checklist_id={created.json()['id']}", files={'file': ('procedimento.pdf', b'%PDF-1.4 demo', 'application/pdf')})
        assert uploaded.status_code == 201
        assert uploaded.json()['checklist_id'] == created.json()['id']
