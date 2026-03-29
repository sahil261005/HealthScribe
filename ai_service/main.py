import logging
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from typing import List, Dict, Union
import google.generativeai as genai
import os
import json
from dotenv import load_dotenv

from rag_chain import (
    embed_medical_record,
    chat_with_rag,
    clear_user_memory,
    get_vectorstore_stats
)

# set up logging so we can see whats happening in the terminal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ai_service")

load_dotenv()

app = FastAPI(
    title="HealthScribe AI Service",
    description="Handles AI extraction, embeddings, and RAG chat for medical records.",
    version="1.0.0",
)

# cors setup - only allow requests from our frontend
frontend_urls = os.getenv("FRONTEND_URL", "http://localhost:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[url.strip() for url in frontend_urls],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_API_KEY = os.getenv("GENAI_API_KEY")
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    logger.warning("GENAI_API_KEY not found - AI features will not work.")

# max file size is 10mb, should be enough for most prescriptions
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_MIME_TYPES = [
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
]


# pydantic models for request validation
class MedicineItem(BaseModel):
    name: str
    dosage: str = ""
    reason: str = ""


class EmbedRecordRequest(BaseModel):
    record_id: int
    user_id: int
    category: str = ""
    upload_date: str = ""
    symptoms: List[str] = []
    medicines: List[MedicineItem] = []
    vitals: Dict[str, str] = {}
    allergies: List[str] = []


class ChatRequest(BaseModel):
    # validates that the query isnt empty before it even reaches the handler
    query: str
    user_id: Union[int, str] = 1
    clear_history: bool = False

    @field_validator("query")
    @classmethod
    def query_must_not_be_empty(cls, value):
        if not value or value.strip() == "":
            raise ValueError("Query cannot be empty.")
        return value.strip()


# -- endpoints --

@app.get("/")
def health_check():
    return {"status": "healthy", "service": "ai_service"}


@app.get("/stats")
def get_stats():
    return get_vectorstore_stats()


@app.post("/extract_data")
async def extract_data_from_file(uploaded_file: UploadFile = File(...)):
    """this is the main extraction endpoint. it works like this:
    1. try sarvam ai first for OCR (its better for indian prescriptions)
    2. send the text to gemini to structure it into json
    3. if sarvam fails, gemini reads the image directly as fallback"""

    # check file type first
    file_mime_type = uploaded_file.content_type or "image/jpeg"

    if file_mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unsupported_file_type",
                "message": f"File type '{file_mime_type}' is not supported. "
                           f"Allowed types: {', '.join(ALLOWED_MIME_TYPES)}",
            },
        )

    file_content = await uploaded_file.read()

    if len(file_content) == 0:
        raise HTTPException(
            status_code=400,
            detail={"error": "empty_file", "message": "Uploaded file is empty."},
        )

    if len(file_content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "error": "file_too_large",
                "message": f"File exceeds {MAX_FILE_SIZE_BYTES // (1024*1024)} MB limit.",
            },
        )

    # make sure we actually have an api key
    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail={"error": "service_unavailable", "message": "AI service is not configured."},
        )

    # the prompt that tells gemini what format we want the data in
    extraction_prompt = """
    You are a medical assistant. You will be provided with text extracted from a medical document.
    Extract this into pure JSON:
    {
        "medicines": [{"name": "String", "dosage": "String", "reason": "String"}],
        "symptoms": ["String"],
        "vitals": {"bp": "String", "pulse": "String", "temp": "String"},
        "allergies": ["String"]
    }
    Do not add markdown or extra text. If certain data is missing, leave it as an empty list or empty strings.
    """

    # step 1: try sarvam ai for OCR (works better for handwritten stuff)
    sarvam_text_content = None
    if SARVAM_API_KEY and "paste-your-sarvam" not in SARVAM_API_KEY:
        try:
            import requests

            logger.info("Attempting Sarvam AI extraction...")
            sarvam_url = "https://api.sarvam.ai/v1/vision/extract"
            headers = {"api-key": SARVAM_API_KEY}
            files = {"file": (uploaded_file.filename, file_content, file_mime_type)}

            response = requests.post(sarvam_url, headers=headers, files=files, timeout=30)

            if response.status_code == 200:
                sarvam_data = response.json()
                sarvam_text_content = sarvam_data.get("text", "")
                logger.info("Sarvam OCR extraction successful.")
            else:
                logger.warning("Sarvam API returned %d: %s", response.status_code, response.text)
        except Exception as sarvam_error:
            logger.warning("Sarvam process failed, falling back to Gemini: %s", sarvam_error)

    # step 2: use gemini to process the text (or do multimodal if sarvam failed)
    try:
        gemini_model = genai.GenerativeModel("gemini-2.5-flash")

        if sarvam_text_content:
            # sarvam worked, so send the ocr text to gemini for structuring
            ai_response = gemini_model.generate_content(
                f"{extraction_prompt}\n\nTEXT CONTENT:\n{sarvam_text_content}"
            )
        else:
            # sarvam didnt work, let gemini read the image directly
            logger.info("Using Gemini multimodal extraction (Sarvam unavailable).")
            ai_response = gemini_model.generate_content([
                {"mime_type": file_mime_type, "data": file_content},
                extraction_prompt,
            ])

        response_text = ai_response.text
        # clean up the response - gemini sometimes wraps json in markdown code blocks
        response_text = response_text.replace("```json", "").replace("```", "").strip()

        extracted_data = json.loads(response_text)
        extracted_data["ocr_engine"] = "Sarvam AI" if sarvam_text_content else "Gemini"

        return extracted_data

    except json.JSONDecodeError:
        logger.error("Gemini returned unparseable JSON: %s", ai_response.text if "ai_response" in dir() else "N/A")
        raise HTTPException(
            status_code=422,
            detail={
                "error": "extraction_parse_error",
                "message": "AI returned data that could not be parsed as JSON.",
                "raw": ai_response.text if "ai_response" in dir() else None,
            },
        )
    except Exception as general_error:
        logger.exception("Extraction failed: %s", general_error)
        raise HTTPException(
            status_code=500,
            detail={"error": "extraction_failed", "message": str(general_error)},
        )


@app.post("/embed_record")
async def embed_record(request: EmbedRecordRequest):
    """saves a verified record into chromadb so the chatbot can find it later"""
    try:
        # convert pydantic models to regular dicts for the embed function
        medicines_as_dicts = []
        for med in request.medicines:
            medicines_as_dicts.append(med.model_dump())

        success = embed_medical_record(
            record_id=request.record_id,
            user_id=request.user_id,
            category=request.category,
            upload_date=request.upload_date,
            symptoms=request.symptoms,
            medicines=medicines_as_dicts,
            vitals=request.vitals,
            allergies=request.allergies,
        )

        if success:
            logger.info("Embedded record %d for user %d.", request.record_id, request.user_id)
            return {"message": "ok", "record_id": request.record_id}
        else:
            raise HTTPException(
                status_code=500,
                detail={"error": "embedding_failed", "message": "Vector store did not accept the record."},
            )

    except HTTPException:
        raise  # dont wrap http exceptions
    except Exception as error:
        logger.exception("embed_record failed: %s", error)
        raise HTTPException(
            status_code=500,
            detail={"error": "embedding_error", "message": str(error)},
        )


@app.post("/chat")
async def chat_with_langchain(request: ChatRequest):
    """rag chat endpoint - finds relevent medical records and generates a response"""
    result = chat_with_rag(
        user_id=request.user_id,
        question=request.query,
        clear_history=request.clear_history,
    )

    # if something went wrong in the rag chain, return a proper error
    if "error" in result:
        raise HTTPException(
            status_code=503,
            detail={"error": "chat_failed", "message": result["error"]},
        )

    return result


@app.post("/chat/clear")
async def clear_chat_history(request: dict):
    user_id = request.get("user_id", 1)
    clear_user_memory(user_id)
    return {"message": "cleared"}


@app.post("/chat_legacy")
async def chat_legacy(request_body: dict):
    """old chat endpoint that queries the database directly instead of using the vector store.
    keeping this around just in case we need it for debugging"""
    user_question = request_body.get("query")
    user_id = request_body.get("user_id", 1)

    if not user_question or str(user_question).strip() == "":
        raise HTTPException(
            status_code=400,
            detail={"error": "empty_query", "message": "Query cannot be empty."},
        )

    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail={"error": "service_unavailable", "message": "AI service is not configured."},
        )

    try:
        import psycopg2

        db = psycopg2.connect(
            dbname=os.getenv("DB_NAME", "healthscribe"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", "password"),
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
        )
        cursor = db.cursor()

        cursor.execute("""
            SELECT record.upload_date, record.category, entity.name, entity.value, entity.type
            FROM api_healthentity entity
            JOIN api_medicalrecord record ON entity.record_id = record.id
            WHERE record.user_id = %s
            ORDER BY record.upload_date DESC
        """, (user_id,))

        rows = cursor.fetchall()
        history_text = "Medical History:\n"

        if len(rows) == 0:
            history_text += "none.\n"
        else:
            for row in rows:
                history_text += f"- {row[0]} ({row[1]}) {row[4]}: {row[2]} = {row[3]}\n"

        cursor.close()
        db.close()

        system_instructions = "You are a medical assistant looking at history. Don't guess."
        full_prompt = f"{system_instructions}\n\n{history_text}\n\nQuestion: {user_question}"

        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(full_prompt)

        return {"answer": response.text}

    except Exception as e:
        logger.exception("chat_legacy failed: %s", e)
        raise HTTPException(
            status_code=500,
            detail={"error": "chat_legacy_failed", "message": str(e)},
        )
