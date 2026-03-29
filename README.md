# HealthScribe - Comprehensive Medical Intelligence System

HealthScribe is a complete medical records management ecosystem that leverages a **Hybrid AI Stack** (**Sarvam AI** + **Google Gemini 2.0 Flash**) for multimodal data extraction and **RAG (Retrieval-Augmented Generation)** to provide a chat interface for personal medical history.

---

## 🏛 Architecture & Data Flow

The system is split into three main components:
1.  **Frontend (React)**: User dashboard, record visualization, and interactive chat.
2.  **Backend (Django)**: Handles authentication, persistent storage (PostgreSQL), and business logic (like allergy detection).
3.  **AI Service (FastAPI)**: Manages interactions with LLMs, vector embeddings (ChromaDB), and extraction pipelines.

### Data Flow for New Records:
1.  **Upload**: User uploads a file (JPG, PNG, PDF).
2.  **Multimodal Extraction (Hybrid)**:
    -   **Step A**: The image is sent to **Sarvam AI Vision** (Document Intelligence) to extract high-fidelity text. This is optimized for Indian prescriptions and handwritten notes.
    -   **Step B**: The extracted text is processed by **Gemini 2.0 Flash** to convert it into a structured JSON schema (Medicines, Symptoms, Vitals, Allergies).
    -   *Fallback*: If Sarvam is unavailable, Gemini performs direct multimodal extraction.
3.  **Verification**: User reviews extracted data.
4.  **Persistence**: Data is saved to PostgreSQL and embedded into **ChromaDB**.
5.  **RAG**: User chats with the bot using Gemini 2.0 Flash and context retrieved from the vector store.

---

## 📁 Project Structure

```text
MEDIICAL APP/
├── ai_service/             # FastAPI Microservice (Python)
│   ├── chroma_db/          # Persistent Vector Store
│   ├── main.py             # Sarvam/Gemini Integration Logic
│   ├── rag_chain.py        # LangChain RAG pipeline
│   └── .env                # API Keys (Sarvam + Gemini)
├── backend/                # Django REST API (Python)
│   ├── api/                
│   │   ├── models.py       # Patient & Record Schemas
│   │   └── views.py        # Allergy Logic & Auth
├── frontend/               # React (Vite) SPA
│   ├── src/
│   │   ├── api.js          # Axios Wrapper
│   │   └── components/     # UI Pages
└── .gitignore
```

---

## � Tech Stack Highlights

-   **OCR Engine**: **Sarvam AI** (Best-in-class for regional Indic text & Indian document layouts).
-   **Structured Intelligence**: **Google Gemini 2.0 Flash** (Fastest JSON-mode model for extraction).
-   **RAG Pipeline**: **LangChain** + **ChromaDB**.
-   **Embeddings**: `models/embedding-001`.
-   **Database**: PostgreSQL (Relational) + ChromaDB (Vector).
-   **Frontend**: React + Tailwind CSS.

---

## 🤖 AI & RAG Logic

### Hybrid Extraction Strategy
By combining Sarvam and Gemini, we achieve the best of both worlds:
-   **Sarvam AI** handles the raw reading of complex, often handwritten, Indian prescriptions where global models might struggle.
-   **Gemini 2.0 Flash** handles the "reasoning" layer, identifying dosages, linking medicines to symptoms, and formatting output for the database.

---

## 🔌 API Reference

### AI Service (FastAPI - Port 8001)
-   `POST /extract_data`: 
    -   Triggers the Hybrid Sarvam/Gemini pipeline.
    -   Includes `ocr_engine` in response to track which model performed the extraction.
-   `POST /embed_record`: Syncs structured data into ChromaDB.
-   `POST /chat`: RAG conversation endpoint.

---

## 🛠 Setup & Requirements

### Environment Variables (.env)
-   `GENAI_API_KEY`: Google Gemini Key.
-   `SARVAM_API_KEY`: Sarvam AI Key (Get it from sarvam.ai).
-   `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`: Postgres credentials.

License: MIT
