from fastapi.testclient import TestClient

from app.main import app


def bearer(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/auth/login",
        data={"username": "fiscal@aeroops.local", "password": "Aero@123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_directory_search_matches_partial_terms_across_fields_case_insensitively():
    with TestClient(app) as client:
        headers = bearer(client)
        bakery = client.post(
            "/directory/contacts",
            headers=headers,
            json={
                "business_name": "Casa do Pão de Queijo",
                "contact_name": "Marcos Silveira",
                "phone": "(31) 3222-4500",
                "location": "Piso 2, saguão de embarque",
                "tags": "entrega, retirada de mercadoria",
            },
        )
        center = client.post(
            "/directory/contacts",
            headers=headers,
            json={
                "business_name": "Centro de Referência de Repatriados",
                "contact_name": "Equipe de plantão",
                "phone": "4002-8922",
                "location": "Terminal, área pública",
                "tags": "apoio, atendimento público",
            },
        )
        assert bakery.status_code == 201
        assert center.status_code == 201

        cases = {
            "queijo": bakery.json()["id"],
            "SILVEIRA": bakery.json()["id"],
            "3222-45": bakery.json()["id"],
            "RETIRADA": bakery.json()["id"],
            "repatriados": center.json()["id"],
            "área pública": center.json()["id"],
        }
        for term, expected_id in cases.items():
            response = client.get("/directory/contacts", headers=headers, params={"q": term})
            assert response.status_code == 200
            assert [item["id"] for item in response.json()] == [expected_id]


def test_directory_contact_crud_and_validation():
    with TestClient(app) as client:
        headers = bearer(client)
        payload = {
            "business_name": "Kopenhagen",
            "contact_name": "Ana Lima",
            "phone": "Ramal 1234",
            "location": "Piso térreo",
            "tags": "chocolate, loja 12",
        }
        created = client.post("/directory/contacts", headers=headers, json=payload)
        assert created.status_code == 201
        contact_id = created.json()["id"]
        assert created.json()["business_name"] == "Kopenhagen"

        updated = client.patch(
            f"/directory/contacts/{contact_id}",
            headers=headers,
            json={"contact_name": "Ana Souza", "phone": "Ramal 4321"},
        )
        assert updated.status_code == 200
        assert updated.json()["contact_name"] == "Ana Souza"
        assert updated.json()["phone"] == "Ramal 4321"

        invalid = client.patch(
            f"/directory/contacts/{contact_id}",
            headers=headers,
            json={"business_name": "   "},
        )
        assert invalid.status_code == 422

        removed = client.delete(f"/directory/contacts/{contact_id}", headers=headers)
        assert removed.status_code == 204
        assert client.get(f"/directory/contacts?q=kopenhagen", headers=headers).json() == []
        assert client.delete(f"/directory/contacts/{contact_id}", headers=headers).status_code == 404


def test_directory_requires_authentication():
    with TestClient(app) as client:
        assert client.get("/directory/contacts").status_code == 401
        assert client.post(
            "/directory/contacts",
            json={"business_name": "Loja", "phone": "100"},
        ).status_code == 401
