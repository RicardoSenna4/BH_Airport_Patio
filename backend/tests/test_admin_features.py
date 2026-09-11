from fastapi.testclient import TestClient

from app.main import app


def token(client, email):
    response = client.post('/auth/login', data={'username': email, 'password': 'Aero@123'})
    assert response.status_code == 200
    return response.json()['access_token']


def test_map_and_reports_are_available():
    with TestClient(app) as client:
        client.headers['Authorization'] = f'Bearer {token(client, "coordenacao@aeroops.local")}'
        grid = client.get('/grid')
        assert grid.status_code == 200
        assert len(grid.json()) == 24
        report = client.get('/reports/summary')
        assert report.status_code == 200
        assert 'inspections_by_day' in report.json()


def test_users_are_restricted_and_admin_can_list():
    with TestClient(app) as client:
        client.headers['Authorization'] = f'Bearer {token(client, "fiscal@aeroops.local")}'
        assert client.get('/users').status_code == 403
        client.headers['Authorization'] = f'Bearer {token(client, "administrador@aeroops.local")}'
        assert client.get('/users').status_code == 200
