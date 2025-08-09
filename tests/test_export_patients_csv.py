import pytest
import os, sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from app import app
from unittest.mock import patch
import werkzeug
werkzeug.__version__ = getattr(werkzeug, "__version__", "0")



class MockResponse:
    def __init__(self, data, status_code=200):
        self.data = data
        self.status_code = status_code

    def json(self):
        return self.data


def mock_requests_get(url, *args, **kwargs):
    if "Patient/" in url:
        return MockResponse({"name": [{"given": ["Max"], "family": "Mustermann"}]})
    if "Condition?patient=" in url:
        return MockResponse({"entry": [{"resource": {"code": {"coding": [{"display": "Unbekannt"}]}}}]})
    return MockResponse({}, 404)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@patch("app.requests.get", side_effect=mock_requests_get)
def test_export_patients_csv_success(mock_get, client):
    response = client.post("/export_patients_csv", data={"selected_patients": ["1"]})
    assert response.status_code == 200
    assert response.headers["Content-Disposition"] == "attachment;filename=patients.csv"
    assert "Vorname;Nachname;Todesursache" in response.data.decode("utf-8")


def test_export_patients_csv_no_selection(client):
    response = client.post("/export_patients_csv", data={})
    assert response.status_code == 302
    assert "/patient_list" in response.headers["Location"]
    with client.session_transaction() as sess:
        assert ("warning", "Keine Patienten ausgewählt") in sess.get("_flashes", [])
