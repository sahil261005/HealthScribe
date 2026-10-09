import logging
from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict
from datetime import datetime
import google.generativeai as genai
import jwt
import os
import json
import secrets
import time
import requests
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from rag_chain import (
    embed_medical_record,
    delete_medical_record,
    chat_with_rag,
    stream_chat_with_rag,
    clear_user_memory,
    get_vectorstore_stats,
    is_quota_error
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai_service")

load_dotenv()

GEMINI_API_KEY = (os.getenv("GENAI_API_KEY") or "").strip() or None
SARVAM_API_KEY = (os.getenv("SARVAM_API_KEY") or "").strip() or None

# same value as SECRET_KEY in the django backend - used to check the user's login token
JWT_SECRET_KEY = (os.getenv("JWT_SECRET_KEY") or "").strip() or None
# shared secret so only our django backend can call the internal endpoints
INTERNAL_API_KEY = (os.getenv("INTERNAL_API_KEY") or "").strip() or None

if not JWT_SECRET_KEY:
    logger.warning("JWT_SECRET_KEY not found - chat / extraction will reject every request.")
if not INTERNAL_API_KEY:
    logger.warning("INTERNAL_API_KEY not found - django won't be able to embed or delete records.")


def read_user_id_from_token(request: Request):
    # gets the user id out of the django JWT, or None if the token is missing / invalid / expired
    auth_header = request.headers.get("Authorization", "")
    if not JWT_SECRET_KEY or not auth_header.startswith("Bearer "):
        return None

    token = auth_header[len("Bearer "):].strip()
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return None

    # refresh tokens are signed with the same key, only accept access tokens
    if payload.get("token_type") != "access":
        return None

    try:
        return int(payload.get("user_id"))
    except (TypeError, ValueError):
        return None


def get_current_user_id(request: Request):
    # used with Depends() on every endpoint the frontend calls.
    # we take the user from the token, never from the request body,
    # otherwise anyone could read someone else's records by changing user_id
    if not JWT_SECRET_KEY:
        raise HTTPException(status_code=503, detail="AI service login check is not configured.")

    user_id = read_user_id_from_token(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Please log in again.")
    return user_id


def require_internal_key(request: Request):
    # used with Depends() on endpoints that only django should call
    key = request.headers.get("X-Internal-Key", "")
    if not INTERNAL_API_KEY or not secrets.compare_digest(key.encode(), INTERNAL_API_KEY.encode()):
        raise HTTPException(status_code=403, detail="Not allowed.")


def rate_limit_key(request: Request):
    # rate limit each logged in user separately. using the ip doesn't work well
    # on render because requests come through their proxy
    user_id = read_user_id_from_token(request)
    if user_id is not None:
        return f"user-{user_id}"
    return get_remote_address(request)


# Set up rate limiter
limiter = Limiter(key_func=rate_limit_key)
app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Configure CORS - any origin can call us, but no cookies.
# auth is done with the Authorization header so we don't need credentials
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    logger.warning("GENAI_API_KEY not found - AI features will not work.")

FALLBACK_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-3.6-flash",
]

# each model gets this many seconds before we give up on it
MODEL_TIMEOUT = 45
# don't start trying another model after this many seconds,
# otherwise one request could go through all 7 models and take minutes
FALLBACK_TIME_LIMIT = 60


def generate_content_with_fallback(contents, generation_config=None):
    """Executes Gemini generation with automatic multi-model fallback if quota/capacity is exceeded."""
    last_err = None
    started = time.time()
    for model_name in FALLBACK_MODELS:
        if time.time() - started > FALLBACK_TIME_LIMIT:
            logger.warning("Fallback time limit reached, not trying more models.")
            break
        try:
            logger.info("Attempting Gemini generation with model: %s", model_name)
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(
                contents,
                generation_config=generation_config,
                request_options={"timeout": MODEL_TIMEOUT}
            )
            return response, model_name
        except Exception as e:
            last_err = e
            err_str = str(e)
            logger.warning("Gemini model %s failed: %s. Trying next fallback...", model_name, err_str)
            continue
    raise last_err or Exception("All Gemini fallback models exhausted.")


def ai_error_response(e, message):
    # don't send the raw error to the frontend, it can have internal details in it.
    # quota errors still say "quota" so the frontend can show its quota message
    if is_quota_error(e):
        return HTTPException(status_code=429, detail="Gemini quota exceeded, please try again later.")
    return HTTPException(status_code=500, detail=message)


MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB limit
ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp", "application/pdf"]

# prescriptions write dates in lots of ways. indian ones are day first (12/08/2026 = 12 aug),
# so we ask the model to copy the date as written and parse it here ourselves -
# when gemini converted it, it read 12/08/2026 as december 8 (US style).
# month first is only tried last, for dates like 08/25/2026 that can't be day first
DATE_FORMATS = [
    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%y", "%d/%m/%y", "%d.%m.%y",
    "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%d-%b-%Y", "%d %b, %Y", "%d-%b-%y",
    "%m/%d/%Y",
]


def normalize_date(value):
    # convert whatever date we got to YYYY-MM-DD, or "" if we can't read it
    if not value:
        return ""
    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def clean_str(value):
    # sarvam gives null for fields it couldn't find, django can't save null
    if value is None:
        return ""
    return str(value).strip()


def clean_str_list(values):
    if not isinstance(values, list):
        return []
    cleaned = []
    for value in values:
        text = clean_str(value)
        if text:
            cleaned.append(text)
    return cleaned


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
    # user_id is not taken from here anymore, it comes from the login token
    query: str
    clear_history: bool = False
    search_type: str = "mmr"
    k: int = 5
    lambda_mult: float = 0.5


@app.api_route("/", methods=["GET", "HEAD"])
@app.api_route("/health", methods=["GET", "HEAD"])
@limiter.exempt
def health_check():
    return {
        "status": "ok",
        "service": "ai_service",
        "sarvam_configured": bool(SARVAM_API_KEY),
        "gemini_configured": bool(GEMINI_API_KEY),
        "fallback_models": FALLBACK_MODELS,
    }



@app.get("/stats")
def get_stats():
    return get_vectorstore_stats()


# NOTE: the endpoints below are plain "def" and not "async def" on purpose.
# they call blocking code (requests, gemini, time.sleep) and inside an async def
# that freezes the whole server for every other user. fastapi runs plain def
# endpoints in a thread pool so they don't block each other.

@app.post("/extract_data", dependencies=[Depends(get_current_user_id)])
@limiter.limit("5/minute")
def extract_data(request: Request, uploaded_file: UploadFile = File(...), engine: str = "gemini"):
    # Accepts a scanned prescription image and extracts structured fields
    file_type = uploaded_file.content_type or "image/jpeg"

    if file_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"File type '{file_type}' not supported.")

    file_content = uploaded_file.file.read()

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
        "visit_date": "String",
        "medicines": [{"name": "String", "dosage": "String", "reason": "String"}],
        "symptoms": ["String"],
        "vitals": {"bp": "String", "pulse": "String", "temp": "String"},
        "allergies": ["String"]
    }
    CRITICAL RULES:
    1. ONLY extract symptoms that are specifically written as the patient's actual complaints or diagnosis.
    2. DO NOT extract printed letterhead lists, doctor specialties, clinic services (e.g. "Tonsillitis, Throat Cancer, Deviated Nasal Septum, Broken Nose"), or sidebar checklists as patient symptoms.
    3. Do not add markdown or extra text. If certain data is missing, leave it as an empty list or empty strings.
    4. visit_date is the date written on the prescription. Copy it EXACTLY as it is written (e.g. "12/08/2026"), do not reformat it. Leave it empty if there is no date.
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
                "description": "The date the prescription was issued, exactly as written on it."
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

    # --- SARVAM OCR ENGINE: Regional & Handwritten Indian Scripts ---
    if engine in ("sarvam", "hybrid") and SARVAM_API_KEY:
        try:
            logger.info("ENGINE: SARVAM — Submitting to Sarvam Extract API (doc-ai/v1/job/extract)...")

            headers = {"api-subscription-key": SARVAM_API_KEY.strip()}

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
            if not isinstance(extracted, dict):
                extracted = {}

            # Map medicine objects safely (handle null values from Sarvam)
            parsed_medicines = []
            for item in extracted.get("medicines") or []:
                if isinstance(item, dict):
                    m_name = clean_str(item.get("medicine_name") or item.get("name"))
                    if not m_name:
                        continue
                    m_dosage = clean_str(item.get("dosage"))
                    m_freq = clean_str(item.get("frequency"))
                    full_dosage = f"{m_dosage} {m_freq}".strip()
                    parsed_medicines.append({
                        "name": m_name,
                        "dosage": full_dosage,
                        "reason": clean_str(item.get("reason"))
                    })

            vitals_raw = extracted.get("vitals")
            if not isinstance(vitals_raw, dict):
                vitals_raw = {}
            bp_val = vitals_raw.get("blood_pressure") or vitals_raw.get("bp")
            pulse_val = vitals_raw.get("pulse_rate") or vitals_raw.get("pulse")
            temp_val = vitals_raw.get("temperature") or vitals_raw.get("temp")

            # every field goes through clean_str / clean_str_list because sarvam
            # returns null for missing fields and that used to crash the save in django
            result = {
                "doctor_name": clean_str(extracted.get("doctor_name")),
                "visit_date": normalize_date(extracted.get("prescription_date")),
                "medicines": parsed_medicines,
                "symptoms": clean_str_list(extracted.get("diagnoses") or extracted.get("symptoms")),
                "vitals": {
                    "bp": clean_str(bp_val),
                    "pulse": clean_str(pulse_val),
                    "temp": clean_str(temp_val)
                },
                "allergies": clean_str_list(extracted.get("allergies")),
                "ocr_engine": "Sarvam AI"
            }
            return result

        except Exception as e:
            logger.error("Sarvam Extract API failed, falling back to Gemini: %s", e)

    # --- GEMINI DIRECT VISION: Fast Standard Scan ---
    try:
        logger.info("ENGINE: GEMINI — Running Direct Vision extraction with fallback models...")

        json_schema = {
            "type": "object",
            "properties": {
                "doctor_name": {"type": "string"},
                "visit_date": {"type": "string"},
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
            "required": ["doctor_name", "visit_date", "medicines", "symptoms", "vitals", "allergies"]
        }

        config = {
            "response_mime_type": "application/json",
            "response_schema": json_schema
        }

        ai_response, used_model = generate_content_with_fallback([
            {"mime_type": file_type, "data": file_content},
            extraction_prompt,
        ], generation_config=config)

        result = json.loads(ai_response.text)
        result["visit_date"] = normalize_date(result.get("visit_date"))
        result["ocr_engine"] = f"Gemini ({used_model})"
        return result

    except json.JSONDecodeError:
        raw = ai_response.text if 'ai_response' in locals() and ai_response else "no response"
        logger.error("Gemini returned invalid JSON: %s", raw)
        raise HTTPException(status_code=422, detail="Failed to parse structured JSON from model.")
    except Exception as e:
        logger.exception("AI Extraction failed: %s", e)
        raise ai_error_response(e, "Could not read this document. Please try again.")


@app.post("/embed_record", dependencies=[Depends(require_internal_key)])
def embed_record(body: EmbedRecordRequest):
    # Saves record schema fields into vector store (only called by django)
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

    if not ok:
        raise HTTPException(status_code=500, detail="Failed to save into vector database.")

    return {"message": "ok"}


@app.post("/delete_record", dependencies=[Depends(require_internal_key)])
def delete_record(body: DeleteRecordRequest):
    # only called by django after it deletes the record.
    # return an error if it fails so django knows to try again
    if not delete_medical_record(body.record_id):
        raise HTTPException(status_code=500, detail="Failed to delete from vector database.")
    return {"message": "ok"}


@app.post("/chat")
@limiter.limit("10/minute")
def chat(request: Request, body: ChatRequest, user_id: int = Depends(get_current_user_id)):
    if not body.query or not body.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    result = chat_with_rag(
        user_id=user_id,
        question=body.query.strip(),
        clear_history=body.clear_history,
        search_type=body.search_type,
        k=body.k,
        lambda_mult=body.lambda_mult,
    )

    if "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])

    return result



@app.post("/chat/stream")
@limiter.limit("20/minute")
def chat_stream(request: Request, body: ChatRequest, user_id: int = Depends(get_current_user_id)):
    if not body.query or not body.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    def event_stream():
        try:
            for chunk in stream_chat_with_rag(
                user_id=user_id,
                question=body.query.strip(),
                clear_history=body.clear_history,
                search_type=body.search_type,
                k=body.k,
                lambda_mult=body.lambda_mult,
            ):
                payload = json.dumps({"chunk": chunk})
                yield f"data: {payload}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"Stream error: {e}")
            err_payload = json.dumps({"error": "Something went wrong, please try again."})
            yield f"data: {err_payload}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )

@app.post("/chat/clear")
def clear_chat(user_id: int = Depends(get_current_user_id)):
    clear_user_memory(user_id)
    return {"message": "cleared"}


@app.post("/check_interactions", dependencies=[Depends(require_internal_key)])
def check_interactions(body: InteractionRequest):
    # only called by django when a new record is saved
    if not GEMINI_API_KEY:
        return {"warnings": []}

    try:
        current = ", ".join(body.current_medicines) if body.current_medicines else "None"
        new = ", ".join(body.new_medicines)

        prompt = f"""A patient is currently taking: {current}
They have been newly prescribed: {new}

Are there any known severe drug interactions between these?
If yes, list them as short warning strings.
If no interactions, return an empty JSON array: []

Return ONLY a JSON array of strings, nothing else."""

        response, _ = generate_content_with_fallback(prompt)
        text = response.text.replace("```json", "").replace("```", "").strip()
        warnings = json.loads(text)

        # the model sometimes returns an object or null instead of a list
        if not isinstance(warnings, list):
            warnings = []
        warnings = [str(w) for w in warnings if w]
        return {"warnings": warnings}
    except Exception as e:
        logger.warning("Interaction check failed: %s", e)
        return {"warnings": []}


@app.post("/compare_doctors", dependencies=[Depends(get_current_user_id)])
@limiter.limit("5/minute")
def compare_doctors(request: Request, body: CompareDoctorsRequest):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="AI not configured")

    try:
        doc1 = body.record1.get("doctor_name", "Doctor A")
        doc2 = body.record2.get("doctor_name", "Doctor B")

        prompt = f"""Compare these two medical records:

Doctor {doc1}: symptoms={body.record1.get('symptoms')}, medicines={body.record1.get('medicines')}
Doctor {doc2}: symptoms={body.record2.get('symptoms')}, medicines={body.record2.get('medicines')}

What are the differences in treatment? Explain in simple terms why they might differ.
Keep it short and remind the patient to consult a specialist if unsure."""

        response, _ = generate_content_with_fallback(prompt)
        return {"summary": response.text}
    except Exception as e:
        logger.error("Compare failed: %s", e)
        raise ai_error_response(e, "Could not compare these records. Please try again.")
