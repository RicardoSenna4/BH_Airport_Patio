from datetime import date

from fastapi.testclient import TestClient

from app.main import app


def bearer(client: TestClient, role: str) -> dict[str, str]:
    login = client.post("/auth/login", data={"username": f"{role}@aeroops.local", "password": "Aero@123"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def inspection_payload(status: str = "CONFORME", severity: str | None = None) -> dict:
    answer = {"item_key": "fod", "label": "FOD", "status": status}
    if status == "NAO_CONFORME":
        answer.update({"observation": "Objeto na área operacional", "severity": severity, "evidence_url": "/evidence/test", "grid_cell": "A7"})
    return {"inspection_type": "PATIO", "apron": "Pátio 1", "grid_cell": "A7", "shift": "Manhã", "weather": "Seco", "answers": [answer]}


def test_uat_draft_can_be_resumed_and_submitted():
    with TestClient(app) as client:
        headers = bearer(client, "fiscal")
        created = client.post("/inspections", headers=headers, json=inspection_payload())
        assert created.status_code == 201
        inspection_id = created.json()["id"]
        updated_payload = inspection_payload()
        updated_payload["notes"] = "Inspeção retomada"
        updated = client.patch(f"/inspections/{inspection_id}", headers=headers, json=updated_payload)
        assert updated.status_code == 200
        assert updated.json()["notes"] == "Inspeção retomada"
        assert client.post(f"/inspections/{inspection_id}/submit", headers=headers).json()["status"] == "CONCLUIDA"


def test_uat_critical_alert_expiry_dashboard_and_report_are_consistent():
    with TestClient(app) as client:
        fiscal = bearer(client, "fiscal")
        created = client.post("/inspections", headers=fiscal, json=inspection_payload("NAO_CONFORME", "CRITICA"))
        assert client.post(f"/inspections/{created.json()['id']}/submit", headers=fiscal).status_code == 200

        analyst = bearer(client, "analista")
        equipment = client.post("/equipment", headers=analyst, json={"code": "UAT-01", "name": "GPU", "company": "Teste", "next_inspection": date.today().isoformat()})
        assert equipment.status_code == 201
        dashboard = client.get("/dashboard/summary", headers=fiscal).json()
        assert dashboard["critical_open"] == 1
        assert dashboard["equipment_expiring_30_days"] == 1
        report = client.get("/reports/summary", headers=fiscal).json()
        assert sum(report["inspections_by_day"].values()) == 1
        assert report["occurrences_by_area"]["Pátio 1"] == 1
