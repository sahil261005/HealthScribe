# HealthScribe

A medical records app that uses AI to extract data from prescriptions. Upload a prescription photo, the AI reads it and pulls out medicines, symptoms, vitals etc. Then you can chat with your records using RAG.

## How it works

1. **Upload** a prescription image or PDF
2. **AI extraction** - Gemini 2.5 Flash reads the image and structures it into JSON using strict Pydantic schemas. Optionally, Sarvam AI can be used as a first-pass OCR for Indian prescriptions before Gemini structuring.
3. **Review** - you verify the extracted data before saving
4. **Chat** - ask questions about your medical history, the bot searches your records using ChromaDB

Sarvam AI can be enabled as a configurable OCR layer for Indian scripts. If enabled and it fails, Gemini handles the image directly as fallback.

## Project structure

```
HealthScribee/
├── ai_service/          # FastAPI - handles AI stuff
│   ├── main.py          # extraction, interactions, comparison endpoints
│   ├── rag_chain.py     # langchain RAG pipeline + embeddings
│   └── .env             # API keys
├── backend/             # Django - auth, records, sharing
│   ├── api/
│   │   ├── models.py
│   │   ├── views.py
│   │   ├── serializers.py
│   │   └── urls.py
│   └── backend/
├── frontend/            # React (Vite)
│   └── src/
│       ├── api.js
│       └── components/
└── .gitignore
```

## Tech stack

- **OCR**: Sarvam AI (good for Indian scripts and handwriting)
- **AI Model**: Google Gemini 2.5 Flash
- **Structured JSON Schema**: Pydantic models (with Gemini response_schema)
- **RAG Framework**: LangChain + ChromaDB
- **Embeddings**: gemini-embedding-001
- **Backend**: Django + DRF, SQLite
- **Frontend**: React, Vite, vanilla CSS

## Features

- prescription OCR with hybrid Sarvam + Gemini pipeline
- structured extraction (medicines, symptoms, vitals, allergies)
- user verification before saving
- RAG chatbot for asking questions about your records
- allergy detection (warns if a prescribed med matches known allergies)
- drug interaction checking between old and new medicines
- multi-doctor comparison (compares treatments from different doctors)
- shareable health profile with QR code
- PDF export
- vitals trending chart
- JWT authentication

## API endpoints

**Django (port 8000)**
- `POST /api/auth/register/` - signup
- `POST /api/auth/login/` - login, returns JWT
- `POST /api/auth/refresh/` - refresh token
- `GET /api/auth/profile/` - get user profile
- `GET /api/save_record/` - get all records
- `POST /api/save_record/` - save new record
- `POST /api/share/generate/` - generate share link
- `GET /api/share/<token>/` - view shared report

**FastAPI (port 8001)**
- `GET /` - health check
- `GET /stats` - vector store stats
- `POST /extract_data` - OCR + extraction
- `POST /embed_record` - embed into ChromaDB
- `POST /chat` - RAG chat
- `POST /chat/clear` - clear chat history
- `POST /check_interactions` - drug interaction check
- `POST /compare_doctors` - compare two doctors' treatments

## Setup

You need two `.env` files:

**ai_service/.env**
```
GENAI_API_KEY=your-gemini-key
SARVAM_API_KEY=your-sarvam-key
FRONTEND_URL=http://localhost:5173
```

**backend/.env**
```
SECRET_KEY=your-django-secret
DEBUG=True
FRONTEND_URL=http://localhost:5173
```

Then run each service:

```bash
# backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver

# ai service
cd ai_service
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --port 8001

# frontend
cd frontend
npm install
npm run dev
```

## Technical Deep Dive

### 1. Hybrid OCR & Extraction Pipeline
Medical prescriptions often contain handwritten text, specialized formatting, or regional dialects that generic OCR packages cannot parse well. HealthScribe solves this using a two-stage hybrid pipeline:
*   **Sarvam AI OCR**: Specifically trained on regional handwritings and Indian scripts, used to get the raw text representation.
*   **Gemini 2.5 Flash Fallback**: If Sarvam AI fails or is not configured, the raw image/PDF is sent directly to Gemini as a multimodal input.
*   **Pydantic Schema Extraction**: Instead of fragile string replacements or regex parsing on LLM markdown blocks, structured extraction leverages Gemini's native `response_schema` generation configuration. By passing our Python Pydantic model (`ExtractionResult`) directly to the API, Gemini is forced to return valid JSON that perfectly matches the model's type schema every time.

### 2. RAG Chatbot & Embedding Strategy
To allow users to search and converse with their consolidated medical history, we implement a Retrieval-Augmented Generation (RAG) loop:
*   **Single-Chunk Embeddings**: Medical records are compiled into structured text blocks and embedded using the `gemini-embedding-001` model as a single document/chunk. Since medical records are short and represent a complete, self-contained clinical event (like a specific prescription or doctor visit), splitting them into smaller chunks would lose the critical context linking symptoms, vitals, and prescribed medicines.
*   **Vector Store**: Embeddings are stored and queried locally in a ChromaDB database (or in Supabase PGVector if connection string is configured).
*   **MMR Retrieval**: We switch retrieval search type from simple similarity to Maximum Marginal Relevance (MMR). MMR ensures we retrieve a diverse set of medical documents rather than multiple almost-identical ones, preventing redundant information from dominating the prompt context if a patient has multiple similar records.
*   **Security & User Isolation**: When retrieving context for a RAG chat session, queries are strictly filtered using user metadata parameters (`"filter": {"user_id": user_id}`). This guarantees that a patient can never retrieve or see document records belonging to another user.
*   **Memory Management & Concurrency**: Active chat conversation histories are stored inside a PostgreSQL table (`chat_history`), querying only the last 20 messages for RAG prompt construction. Under local/offline development where `DATABASE_URL` is omitted, the system falls back to storing histories locally in `chat_histories.json` to prevent concurrency race conditions while keeping setup frictionless.

### 3. Rate Limiting
To prevent abuse of the external AI service endpoints (Gemini / Sarvam AI) and avoid excessive costs, the FastAPI service incorporates an in-memory rate limiter using **SlowAPI**:
*   **OCR & Extraction (`/extract_data`)**: 5 requests per minute
*   **RAG Chat (`/chat`)**: 10 requests per minute
*   **Vector Insertion (`/embed_record`)**: 10 requests per minute
*   **Drug Interactions (`/check_interactions`)**: 10 requests per minute
*   **Doctor Comparison (`/compare_doctors`)**: 5 requests per minute

This rate limiter tracks request counts in-memory based on the client's IP address, avoiding the need for an external Redis dependency for a single-server deployment. Rate limit breaches return standard HTTP `429 Too Many Requests` responses.

## Evaluation Metrics

Includes an evaluation script (`evaluate.py`) that runs both pipelines against 2 real prescription images and measures accuracy at the **individual field level** — each medicine name, dosage, and symptom is scored as a separate test case (14 medicines + 4 symptoms + 2 doctors = 20 field checks total). This produces realistic, granular accuracy percentages rather than a binary pass/fail per image.

| Field | Sarvam+Gemini | Gemini Only |
| :--- | :---: | :---: |
| **Doctor Name Accuracy** | 100% | 100% |
| **Medicines Accuracy (Exact Match)** | 100% | 93% |
| **Medicines Accuracy (Fuzzy Match)** | 100% | 100% |
| **Dosages Accuracy** | 100% | 100% |
| **Symptoms Accuracy** | 100% | 100% |
| **Average Latency** | 29.2s | 20.0s |

*Note: Native Gemini vision introduces minor OCR-induced typos on handwritten/unusual drug names (e.g. extracting `ABCXIMAB` instead of `ABCIXIMAB`), resulting in lower exact-match precision. Using Sarvam OCR + Gemini structures the raw text perfectly, achieving 100% exact-match accuracy.*

To run the evaluation:
1. Ensure the FastAPI AI service is running (`uvicorn main:app --port 8001`)
2. Run: `python evaluate.py`

License: MIT
