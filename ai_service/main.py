import logging
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict
import google.generativeai as genai
import os
import json
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from rag_chain import (
    embed_medical_record,
    chat_with_rag,
    clear_user_memory,
    get_vectorstore_stats
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai_service")

load_dotenv()

# Set up rate limiter
limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Configure CORS origins - allow all origins for modern decoupled frontends
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r".*",
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

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB limit
ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp", "application/pdf"]


# Request and response models
class MedicineItem(BaseModel):
    name: str
    dosage: str = ""
    reason: str = ""


class VitalsSchema(BaseModel):
    bp: str = ""
    pulse: str = ""
    temp: str = ""


class ExtractionResult(BaseModel):
    doctor_name: str = ""
    medicines: List[MedicineItem] = []
    symptoms: List[str] = []
    vitals: VitalsSchema = VitalsSchema()
    allergies: List[str] = []


class EmbedRecordRequest(BaseModel):
    record_id: int
    user_id: int
    category: str = ""
    doctor_name: str = ""
    upload_date: str = ""
    symptoms: List[str] = []
    medicines: List[MedicineItem] = []
    vitals: Dict[str, str] = {}
    allergies: List[str] = []


class DeleteRecordRequest(BaseModel):
    record_id: int


class InteractionRequest(BaseModel):
    current_medicines: List[str]
    new_medicines: List[str]


class CompareDoctorsRequest(BaseModel):
    record1: dict
    record2: dict


class ChatRequest(BaseModel):
    query: str
    user_id: int = 1
    clear_history: bool = False
    search_type: str = "mmr"
    k: int = 5
    lambda_mult: float = 0.5


@app.get("/")
@app.get("/health")
@limiter.exempt
def health_check():
    return {"status": "ok", "service": "ai_service"}



@app.get("/stats")
def get_stats():
    return get_vectorstore_stats()


@app.post("/extract_data")
@limiter.limit("5/minute")
async def extract_data(request: Request, uploaded_file: UploadFile = File(...), engine: str = "hybrid"):
    # Accepts a scanned prescription image and extracts structured fields
    file_type = uploaded_file.content_type or "image/jpeg"

    if file_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"File type '{file_type}' not supported.")

    file_content = await uploaded_file.read()

    if len(file_content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if len(file_content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large. Max 10 MB.")

    if not GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="AI service is not configured.")

    # Instructions for structured output parsing
    extraction_prompt = """
    You are a medical assistant extracting clinical information from a prescription or medical document.
    Extract this into pure JSON:
    {
        "doctor_name": "String",
        "medicines": [{"name": "String", "dosage": "String", "reason": "String"}],
        "symptoms": ["String"],
        "vitals": {"bp": "String", "pulse": "String", "temp": "String"},
        "allergies": ["String"]
    }
    CRITICAL RULES:
    1. ONLY extract symptoms that are specifically written as the patient's actual complaints or diagnosis.
    2. DO NOT extract printed letterhead lists, doctor specialties, clinic services (e.g. "Tonsillitis, Throat Cancer, Deviated Nasal Septum, Broken Nose"), or sidebar checklists as patient symptoms.
    3. Do not add markdown or extra text. If certain data is missing, leave it as an empty list or empty strings.
    """

    # Define the extraction schema for Sarvam Extract API (generated via Sarvam Playground)
    sarvam_schema = json.dumps({
        "type": "object",
        "properties": {
            "doctor_name": {
                "type": "string",
                "description": "The full name of the medical practitioner issuing the prescription."
            },
            "patient_info": {
                "type": "object",
                "description": "Patient demographic information from the prescription.",
                "properties": {
                    "name": {"type": "string", "description": "The name of the patient as written on the prescription."},
                    "age": {"type": "string", "description": "The age of the patient as written on the prescription."}
                }
            },
            "prescription_date": {
                "type": "string",
                "description": "The date the prescription was issued."
            },
            "medicines": {
                "type": "array",
                "description": "A list of all medications prescribed to the patient.",
                "items": {
                    "type": "object",
                    "description": "A single prescribed medication entry.",
                    "properties": {
                        "medicine_name": {"type": "string", "description": "The name of the prescribed medication."},
                        "dosage": {"type": "string", "description": "The strength or dosage of the medication."},
                        "frequency": {"type": "string", "description": "The timing and frequency of the medication intake."}
                    }
                }
            },
            "diagnoses": {
                "type": "array",
                "description": "Medical conditions or diagnoses noted by the doctor.",
                "items": {"type": "string", "description": "A single diagnosis or medical condition."}
            },
            "vitals": {
                "type": "object",
                "description": "Patient vital signs recorded on the document.",
                "properties": {
                    "blood_pressure": {"type": "string", "description": "Recorded blood pressure reading."},
                    "pulse_rate": {"type": "string", "description": "Recorded pulse rate."},
                    "temperature": {"type": "string", "description": "Recorded body temperature."}
                }
            },
            "allergies": {
                "type": "array",
                "description": "List of patient allergies noted on the prescription.",
                "items": {"type": "string", "description": "A single allergy noted on the prescription."}
            },
            "additional_instructions": {
                "type": "string",
                "description": "Any additional notes or instructions provided by the doctor."
            }
        }
    })

    # --- HYBRID ENGINE: Sarvam Extract API ---
    if engine != "gemini" and SARVAM_API_KEY:
        try:
            import requests
            import time

            logger.info("ENGINE: HYBRID — Submitting to Sarvam Extract API (doc-ai/v1/job/extract)...")

            headers = {"api-subscription-key": SARVAM_API_KEY}

            # Step 1: Submit the extraction job with file + schema in one multipart POST
            submit_resp = requests.post(
                "https://api.sarvam.ai/doc-ai/v1/job/extract",
                headers=headers,
                files={"file": (uploaded_file.filename or "prescription.jpg", file_content, file_type)},
                data={
                    "schema": sarvam_schema,
                    "language": "en-IN",
                    "output_format": "json",
                    "model": "sarvam-vision-v1"
                },
                timeout=20
            )

            if submit_resp.status_code not in (200, 201, 202):
                raise Exception(f"Sarvam Extract job submit failed ({submit_resp.status_code}): {submit_resp.text}")

            job_id = submit_resp.json().get("job_id")
            if not job_id:
                raise Exception(f"No job_id in Sarvam response: {submit_resp.json()}")

            logger.info("Sarvam Extract job created: %s", job_id)

            # Step 2: Poll status until completed
            status_url = f"https://api.sarvam.ai/doc-ai/v1/job/{job_id}/status"
            completed = False
            for attempt in range(20):
                time.sleep(1.5)
                status_resp = requests.get(status_url, headers=headers, timeout=10)
                if status_resp.status_code == 200:
                    job_state = (status_resp.json().get("job_state") or status_resp.json().get("status") or "").lower()
                    logger.info("Sarvam job %s poll %d: %s", job_id, attempt + 1, job_state)
                    if job_state == "completed":
                        completed = True
                        break
                    elif job_state in ("failed", "cancelled"):
                        raise Exception(f"Sarvam job failed with state: {job_state}")

            if not completed:
                raise Exception("Sarvam Extract API timed out after polling")

            # Step 3: Fetch structured JSON results directly
            results_resp = requests.get(
                f"https://api.sarvam.ai/doc-ai/v1/job/{job_id}/results",
                headers=headers,
                timeout=15
            )

            if results_resp.status_code != 200:
                raise Exception(f"Sarvam results fetch failed ({results_resp.status_code}): {results_resp.text}")

            raw = results_resp.json()
            logger.info("Sarvam Extract returned structured JSON successfully.")

            # Sarvam wraps extracted fields inside "result" key
            result_data = raw.get("result", raw) if isinstance(raw, dict) else raw
            extracted = result_data if isinstance(result_data, dict) else (result_data[0] if isinstance(result_data, list) and result_data else {})
            
            # Map medicine objects safely (handle null values from Sarvam)
            parsed_medicines = []
            for item in extracted.get("medicines", []):
                if isinstance(item, dict):
                    m_name = item.get("medicine_name") or item.get("name") or ""
                    m_dosage = item.get("dosage") or ""
                    m_freq = item.get("frequency") or ""
                    full_dosage = f"{m_dosage} {m_freq}".strip() if (m_dosage or m_freq) else ""
                    parsed_medicines.append({
                        "name": m_name,
                        "dosage": full_dosage,
                        "reason": item.get("reason") or ""
                    })

            vitals_raw = extracted.get("vitals") or {}
            bp_val = vitals_raw.get("blood_pressure") or vitals_raw.get("bp", "")
            pulse_val = vitals_raw.get("pulse_rate") or vitals_raw.get("pulse", "")
            temp_val = vitals_raw.get("temperature") or vitals_raw.get("temp", "")

            result = {
                "doctor_name": extracted.get("doctor_name", ""),
                "medicines": parsed_medicines,
                "symptoms": extracted.get("diagnoses") or extracted.get("symptoms", []),
                "vitals": {
                    "bp": bp_val,
                    "pulse": pulse_val,
                    "temp": temp_val
                },
                "allergies": extracted.get("allergies", []),
                "ocr_engine": "Sarvam AI"
            }
            return result

        except Exception as e:
            logger.error("Sarvam Extract API failed, falling back to Gemini: %s", e)

    # --- GEMINI ENGINE (Fast Vision or Sarvam fallback) ---
    try:
        logger.info("ENGINE: GEMINI — Running Direct Vision extraction...")
        model = genai.GenerativeModel("gemini-2.5-flash")

        json_schema = {
            "type": "object",
            "properties": {
                "doctor_name": {"type": "string"},
                "medicines": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "dosage": {"type": "string"},
                            "reason": {"type": "string"}
                        },
                        "required": ["name", "dosage", "reason"]
                    }
                },
                "symptoms": {"type": "array", "items": {"type": "string"}},
                "vitals": {
                    "type": "object",
                    "properties": {
                        "bp": {"type": "string"},
                        "pulse": {"type": "string"},
                        "temp": {"type": "string"}
                    },
                    "required": ["bp", "pulse", "temp"]
                },
                "allergies": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["doctor_name", "medicines", "symptoms", "vitals", "allergies"]
        }

        config = {
            "response_mime_type": "application/json",
            "response_schema": json_schema
        }

        ai_response = model.generate_content([
            {"mime_type": file_type, "data": file_content},
            extraction_prompt,
        ], generation_config=config)

        result = json.loads(ai_response.text)
        result["ocr_engine"] = "Gemini"
        return result

    except json.JSONDecodeError:
        raw = ai_response.text if ai_response else "no response"
        logger.error("Gemini returned invalid JSON: %s", raw)
        raise HTTPException(status_code=422, detail="Failed to parse structured JSON from model.")
    except Exception as e:
        logger.exception("AI Extraction failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/embed_record")
@limiter.limit("10/minute")
async def embed_record(request: Request, body: EmbedRecordRequest):
    # Saves record schema fields into vector store
    try:
        medicines = [med.model_dump() for med in body.medicines]

        ok = embed_medical_record(
            record_id=body.record_id,
            user_id=body.user_id,
            category=body.category,
            doctor_name=body.doctor_name,
            upload_date=body.upload_date,
            symptoms=body.symptoms,
            medicines=medicines,
            vitals=body.vitals,
            allergies=body.allergies,
        )

        if ok:
            logger.info("Embedded record %d for user %d", body.record_id, body.user_id)
            return {"message": "ok", "record_id": body.record_id}
        else:
            raise HTTPException(status_code=500, detail="Failed to embed record.")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("embed_record failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/delete_record")
async def delete_record(request: DeleteRecordRequest):
    from rag_chain import delete_medical_record
    delete_medical_record(request.record_id)
    return {"message": "ok"}


@app.post("/chat")
@limiter.limit("10/minute")
async def chat(request: Request, body: ChatRequest):
    if not body.query or not body.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    result = chat_with_rag(
        user_id=body.user_id,
        question=body.query.strip(),
        clear_history=body.clear_history,
        search_type=body.search_type,
        k=body.k,
        lambda_mult=body.lambda_mult,
    )

    if "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])

    return result


@app.post("/chat/clear")
async def clear_chat(request: dict):
    user_id = request.get("user_id", 1)
    clear_user_memory(user_id)
    return {"message": "cleared"}


@app.post("/check_interactions")
@limiter.limit("10/minute")
async def check_interactions(request: Request, body: InteractionRequest):
    if not GEMINI_API_KEY:
        return {"warnings": []}

    try:
        model = genai.GenerativeModel("gemini-2.5-flash")

        current = ", ".join(body.current_medicines) if body.current_medicines else "None"
        new = ", ".join(body.new_medicines)

        prompt = f"""A patient is currently taking: {current}
They have been newly prescribed: {new}

Are there any known severe drug interactions between these?
If yes, list them as short warning strings.
If no interactions, return an empty JSON array: []

Return ONLY a JSON array of strings, nothing else."""

        response = model.generate_content(prompt)
        text = response.text.replace("```json", "").replace("```", "").strip()
        warnings = json.loads(text)
        return {"warnings": warnings}
    except Exception as e:
        logger.warning("Interaction check failed: %s", e)
        return {"warnings": []}


@app.post("/compare_doctors")
@limiter.limit("5/minute")
async def compare_doctors(request: Request, body: CompareDoctorsRequest):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="AI not configured")

    try:
        model = genai.GenerativeModel("gemini-2.5-flash")

        doc1 = body.record1.get("doctor_name", "Doctor A")
        doc2 = body.record2.get("doctor_name", "Doctor B")

        prompt = f"""Compare these two medical records:

Doctor {doc1}: symptoms={body.record1.get('symptoms')}, medicines={body.record1.get('medicines')}
Doctor {doc2}: symptoms={body.record2.get('symptoms')}, medicines={body.record2.get('medicines')}

What are the differences in treatment? Explain in simple terms why they might differ.
Keep it short and remind the patient to consult a specialist if unsure."""

        response = model.generate_content(prompt)
        return {"summary": response.text}
    except Exception as e:
        logger.error("Compare failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
