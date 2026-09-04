from fastapi.testclient import TestClient

from app.main import app


def test_inspection_flow_enforces_evidence_and_submits():
    with TestClient(app) as client:
        login = client.post('/auth/login', data={'username': 'fiscal@aeroops.local', 'password': 'Aero@123'})
        assert login.status_code == 200
        client.headers['Authorization'] = f"Bearer {login.json()['access_token']}"
        invalid = {
            'inspection_type': 'PATIO', 'apron': 'Pátio 1', 'grid_cell': '9F',
            'shift': 'Tarde', 'weather': 'Seco',
            'answers': [{'item_key': 'organizacao', 'label': 'Organização', 'status': 'NAO_CONFORME'}],
        }
        assert client.post('/inspections', json=invalid).status_code == 422
        valid = {
            'inspection_type': 'PATIO', 'apron': 'Pátio 1', 'grid_cell': '9F',
            'shift': 'Tarde', 'weather': 'Seco',
            'answers': [
                {'item_key': 'organizacao', 'label': 'Organização', 'status': 'NAO_CONFORME', 'observation': 'Objeto solto', 'severity': 'MEDIA', 'evidence_url': '/uploads/foto.png', 'grid_cell': '9F'},
                {'item_key': 'pavimento', 'label': 'Pavimento', 'status': 'CONFORME'},
            ],
        }
        created = client.post('/inspections', json=valid)
        assert created.status_code == 201
        inspection_id = created.json()['id']
        submitted = client.post(f'/inspections/{inspection_id}/submit')
        assert submitted.status_code == 200
        occurrences = client.get('/occurrences').json()
        assert any(item['inspection_id'] == inspection_id and item['status'] == 'EM_VALIDACAO' for item in occurrences)
