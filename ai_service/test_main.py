"""
tests for the AI service endpoints.
uses FastAPI's TestClient so we dont need to actually start the server.
all external api calls are mocked so tests are fast and free
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app


client = TestClient(app)


# -- health check tests --

class TestHealthCheck:

    def test_health_check_returns_200(self):
        response = client.get("/")
        assert response.status_code == 200

    def test_health_check_response_body(self):
        response = client.get("/")
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "ai_service"


# -- extraction tests --

class TestExtractData:

    @patch("main.genai.GenerativeModel")
    @patch("main.GEMINI_API_KEY", "test-key-123")
    def test_extract_valid_image_returns_structured_data(self, mock_model_class):
        """upload a valid jpeg and check we get back structured medical json"""
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "medicines": [{"name": "Paracetamol", "dosage": "500mg", "reason": "Fever"}],
            "symptoms": ["Fever", "Headache"],
            "vitals": {"bp": "120/80", "pulse": "72", "temp": "99.1"},
            "allergies": ["Penicillin"]
        })
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model

        # fake jpeg file with magic bytes
        fake_file = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        response = client.post(
            "/extract_data",
            files={"uploaded_file": ("prescription.jpg", fake_file, "image/jpeg")}
        )

        assert response.status_code == 200
        data = response.json()
        assert "medicines" in data
        assert "symptoms" in data
        assert "vitals" in data
        assert "allergies" in data
        assert data["ocr_engine"] in ["Gemini", "Sarvam AI"]
        assert len(data["medicines"]) == 1
        assert data["medicines"][0]["name"] == "Paracetamol"

    def test_reject_unsupported_file_type(self):
        """text files should be rejected"""
        fake_file = b"this is a text file"
        response = client.post(
            "/extract_data",
            files={"uploaded_file": ("notes.txt", fake_file, "text/plain")}
        )

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["error"] == "unsupported_file_type"

    def test_reject_empty_file(self):
        response = client.post(
            "/extract_data",
            files={"uploaded_file": ("empty.jpg", b"", "image/jpeg")}
        )

        assert response.status_code == 400
        data = response.json()
        assert data["detail"]["error"] == "empty_file"

    def test_reject_oversized_file(self):
        """files bigger than 10mb should be rejected"""
        huge_file = b"\x00" * (11 * 1024 * 1024)
        response = client.post(
            "/extract_data",
            files={"uploaded_file": ("huge.jpg", huge_file, "image/jpeg")}
        )

        assert response.status_code == 413
        data = response.json()
        assert data["detail"]["error"] == "file_too_large"

    @patch("main.GEMINI_API_KEY", None)
    def test_reject_when_api_key_missing(self):
        """should return 503 if the api key isnt set"""
        fake_file = b"\xff\xd8" + b"\x00" * 50
        response = client.post(
            "/extract_data",
            files={"uploaded_file": ("test.jpg", fake_file, "image/jpeg")}
        )

        assert response.status_code == 503
        data = response.json()
        assert data["detail"]["error"] == "service_unavailable"

    @patch("main.genai.GenerativeModel")
    @patch("main.GEMINI_API_KEY", "test-key-123")
    def test_gemini_returns_unparseable_text(self, mock_model_class):
        """if gemini returns gibberish instead of json we should get 422"""
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Sorry, I cannot process this image."
        mock_model.generate_content.return_value = mock_response
        mock_model_class.return_value = mock_model

        fake_file = b"\xff\xd8" + b"\x00" * 50
        response = client.post(
            "/extract_data",
            files={"uploaded_file": ("bad.jpg", fake_file, "image/jpeg")}
        )

        assert response.status_code == 422
        data = response.json()
        assert data["detail"]["error"] == "extraction_parse_error"

    def test_accepts_png_file(self):
        with patch("main.genai.GenerativeModel") as mock_model_class, \
             patch("main.GEMINI_API_KEY", "test-key"):
            mock_model = MagicMock()
            mock_response = MagicMock()
            mock_response.text = json.dumps({
                "medicines": [], "symptoms": [], "vitals": {}, "allergies": []
            })
            mock_model.generate_content.return_value = mock_response
            mock_model_class.return_value = mock_model

            fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
            response = client.post(
                "/extract_data",
                files={"uploaded_file": ("scan.png", fake_png, "image/png")}
            )

            assert response.status_code == 200

    def test_accepts_pdf_file(self):
        with patch("main.genai.GenerativeModel") as mock_model_class, \
             patch("main.GEMINI_API_KEY", "test-key"):
            mock_model = MagicMock()
            mock_response = MagicMock()
            mock_response.text = json.dumps({
                "medicines": [], "symptoms": [], "vitals": {}, "allergies": []
            })
            mock_model.generate_content.return_value = mock_response
            mock_model_class.return_value = mock_model

            fake_pdf = b"%PDF-1.4" + b"\x00" * 50
            response = client.post(
                "/extract_data",
                files={"uploaded_file": ("report.pdf", fake_pdf, "application/pdf")}
            )

            assert response.status_code == 200


# -- embed record tests --

class TestEmbedRecord:

    @patch("main.embed_medical_record")
    def test_embed_record_success(self, mock_embed):
        mock_embed.return_value = True

        response = client.post("/embed_record", json={
            "record_id": 1,
            "user_id": 42,
            "category": "Consultation",
            "upload_date": "2026-03-20",
            "symptoms": ["Fever"],
            "medicines": [{"name": "Paracetamol", "dosage": "500mg", "reason": "Fever"}],
            "vitals": {"bp": "120/80"},
            "allergies": ["None"]
        })

        assert response.status_code == 200
        assert response.json()["message"] == "ok"

    @patch("main.embed_medical_record")
    def test_embed_record_failure_returns_500(self, mock_embed):
        mock_embed.return_value = False

        response = client.post("/embed_record", json={
            "record_id": 1,
            "user_id": 42,
        })

        assert response.status_code == 500

    def test_embed_record_missing_required_fields(self):
        """missing record_id or user_id should trigger pydantic validation error"""
        response = client.post("/embed_record", json={
            "category": "Test"
        })

        assert response.status_code == 422


# -- chat tests --

class TestChat:

    @patch("main.chat_with_rag")
    def test_chat_returns_answer(self, mock_chat):
        mock_chat.return_value = {"answer": "Based on your records, you were treated for fever on March 15."}

        response = client.post("/chat", json={
            "query": "When did I have fever?",
            "user_id": 1
        })

        assert response.status_code == 200
        assert "answer" in response.json()
        assert "fever" in response.json()["answer"].lower()

    def test_chat_rejects_empty_query(self):
        response = client.post("/chat", json={
            "query": "",
            "user_id": 1
        })

        assert response.status_code == 422

    def test_chat_rejects_whitespace_query(self):
        response = client.post("/chat", json={
            "query": "   ",
            "user_id": 1
        })

        assert response.status_code == 422

    @patch("main.chat_with_rag")
    def test_chat_error_surfaces_as_503(self, mock_chat):
        """if rag chain fails, should return 503"""
        mock_chat.return_value = {"error": "models not ready"}

        response = client.post("/chat", json={
            "query": "What medicines am I on?",
            "user_id": 1
        })

        assert response.status_code == 503


# -- clear chat tests --

class TestChatClear:

    @patch("main.clear_user_memory")
    def test_clear_chat_history(self, mock_clear):
        response = client.post("/chat/clear", json={"user_id": 42})

        assert response.status_code == 200
        assert response.json()["message"] == "cleared"
        mock_clear.assert_called_once_with(42)
