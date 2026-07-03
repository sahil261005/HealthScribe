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

# Configure CORS origins
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
def health_check():
    return {"status": "healthy", "service": "ai_service"}


@app.get("/stats")
def get_stats():
    return get_vectorstore_stats()


@app.post("/extract_data")
@limiter.limit("5/minute")
async def extract_data(request: Request, uploaded_file: UploadFile = File(...), engine: str = "gemini"):
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
    You are a medical assistant. You will be provided with text extracted from a medical document.
    Extract this into pure JSON:
    {
        "doctor_name": "String",
        "medicines": [{"name": "String", "dosage": "String", "reason": "String"}],
        "symptoms": ["String"],
        "vitals": {"bp": "String", "pulse": "String", "temp": "String"},
        "allergies": ["String"]
    }
    Do not add markdown or extra text. If certain data is missing, leave it as an empty list or empty strings.
    """

    sarvam_text = None
    if engine != "gemini" and SARVAM_API_KEY:
        try:
            import requests
            import time
            import io
            import zipfile

            logger.info("Starting Sarvam OCR digitization...")
            
            # 1. Create the digitization job
            create_url = "https://api.sarvam.ai/doc-digitization/job/v1"
            headers = {
                "api-subscription-key": SARVAM_API_KEY,
                "Content-Type": "application/json"
            }
            create_payload = {
                "job_parameters": {
                    "language": "en-IN",
                    "output_format": "md"
                }
            }
            create_resp = requests.post(create_url, headers=headers, json=create_payload, timeout=20)
            if create_resp.status_code not in (200, 201, 202):
                raise Exception(f"Create job failed ({create_resp.status_code}): {create_resp.text}")
            
            job_id = create_resp.json()["job_id"]
            logger.info("Job created: %s", job_id)
            
            # 2. Request a presigned upload URL
            upload_init_url = "https://api.sarvam.ai/doc-digitization/job/v1/upload-files"
            upload_payload = {
                "job_id": job_id,
                "files": [uploaded_file.filename or "file.png"]
            }
            upload_init_resp = requests.post(upload_init_url, headers=headers, json=upload_payload, timeout=20)
            if upload_init_resp.status_code not in (200, 201, 202):
                raise Exception(f"Failed to get upload URL: {upload_init_resp.text}")
            
            upload_json = upload_init_resp.json()
            presigned_url = None
            if "upload_urls" in upload_json:
                upload_urls_dict = upload_json["upload_urls"]
                first_url_obj = list(upload_urls_dict.values())[0]
                if isinstance(first_url_obj, dict):
                    presigned_url = first_url_obj.get("url") or first_url_obj.get("file_url")
                else:
                    presigned_url = first_url_obj
            elif "urls" in upload_json and upload_json["urls"]:
                presigned_url = upload_json["urls"][0]
                
            if not presigned_url:
                raise Exception(f"No upload URL found in response: {upload_json}")
            
            # 3. PUT the file binary to the presigned url
            put_headers = {"Content-Type": file_type}
            if "blob.core.windows.net" in presigned_url:
                put_headers["x-ms-blob-type"] = "BlockBlob"
                
            put_resp = requests.put(presigned_url, data=file_content, headers=put_headers, timeout=30)
            if put_resp.status_code not in (200, 201, 202, 204):
                raise Exception(f"Upload to storage failed ({put_resp.status_code})")
            
            # 4. Trigger the job to start
            start_url = f"https://api.sarvam.ai/doc-digitization/job/v1/{job_id}/start"
            start_resp = requests.post(start_url, headers=headers, timeout=20)
            if start_resp.status_code not in (200, 201, 202):
                raise Exception(f"Failed to start job ({start_resp.status_code})")
            
            # 5. Poll the status until completed
            status_url = f"https://api.sarvam.ai/doc-digitization/job/v1/{job_id}/status"
            max_polls = 50
            completed = False
            for attempt in range(max_polls):
                time.sleep(3)
                status_resp = requests.get(status_url, headers=headers, timeout=15)
                if status_resp.status_code in (200, 201, 202):
                    resp_data = status_resp.json()
                    # Sarvam API returns "job_state" instead of "status"
                    job_state = resp_data.get("job_state", resp_data.get("status", ""))
                    if job_state:
                        job_state = job_state.lower()
                    logger.info("Job %s status check %d: %s", job_id, attempt + 1, job_state)
                    if job_state == "completed":
                        completed = True
                        break
                    elif job_state in ("failed", "cancelled"):
                        raise Exception(f"Job failed with status: {job_state}")
                else:
                    logger.warning("Failed to check status: %s", status_resp.text)
            
            if not completed:
                raise Exception("Job timed out")
            
            # 6. Retrieve the results zip URL
            download_url = f"https://api.sarvam.ai/doc-digitization/job/v1/{job_id}/download-files"
            download_resp = requests.post(download_url, headers=headers, timeout=20)
            if download_resp.status_code not in (200, 201, 202):
                raise Exception(f"Get download URL failed: {download_resp.text}")
            
            download_json = download_resp.json()
            zip_download_url = None
            if download_json.get("download_urls"):
                download_urls_dict = download_json.get("download_urls", {})
                first_val = list(download_urls_dict.values())[0]
                if isinstance(first_val, dict):
                    zip_download_url = first_val.get("url") or first_val.get("file_url")
                else:
                    zip_download_url = first_val
            
            if not zip_download_url:
                zip_download_url = download_json.get("url")
            if not zip_download_url and "urls" in download_json:
                zip_download_url = download_json["urls"][0]
                
            if not zip_download_url:
                raise Exception(f"No download URL found: {download_json}")
                
            zip_resp = requests.get(zip_download_url, timeout=30)
            if zip_resp.status_code != 200:
                raise Exception("Failed to download results zip")
            
            # 7. Unzip and parse the text content
            with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as z:
                text_content = ""
                for filename in z.namelist():
                    if filename.endswith(".md") or filename.endswith(".txt"):
                        with z.open(filename) as f:
                            text_content = f.read().decode("utf-8")
                            break
                
                # Check for json outputs if no md/txt exists
                if not text_content:
                    for filename in z.namelist():
                        if filename.endswith(".json"):
                            with z.open(filename) as f:
                                json_data = json.loads(f.read().decode("utf-8"))
                                text_content = json.dumps(json_data)
                                break
            
            if text_content:
                sarvam_text = text_content
                logger.info("Sarvam OCR finished successfully.")
            else:
                raise Exception("No text files found inside the results zip.")
        except Exception as e:
            logger.warning("Sarvam OCR failed. Falling back to Gemini direct vision: %s", e)

    # Use Gemini to parse the output text or image into structured JSON
    ai_response = None
    try:
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
                "symptoms": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "vitals": {
                    "type": "object",
                    "properties": {
                        "bp": {"type": "string"},
                        "pulse": {"type": "string"},
                        "temp": {"type": "string"}
                    },
                    "required": ["bp", "pulse", "temp"]
                },
                "allergies": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "required": ["doctor_name", "medicines", "symptoms", "vitals", "allergies"]
        }

        config = {
            "response_mime_type": "application/json",
            "response_schema": json_schema
        }

        if sarvam_text:
            ai_response = model.generate_content(
                f"{extraction_prompt}\n\nTEXT CONTENT:\n{sarvam_text}",
                generation_config=config
            )
        else:
            logger.info("Running Gemini vision direct upload...")
            ai_response = model.generate_content([
                {"mime_type": file_type, "data": file_content},
                extraction_prompt,
            ], generation_config=config)

        result = json.loads(ai_response.text)
        result["ocr_engine"] = "Sarvam AI" if sarvam_text else "Gemini"
        return result

    except json.JSONDecodeError:
        raw = ai_response.text if ai_response else "no response"
        logger.error("Gemini returned invalid JSON structure: %s", raw)
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
