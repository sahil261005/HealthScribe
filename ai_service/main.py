import logging
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai_service")

load_dotenv()

app = FastAPI()

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

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp", "application/pdf"]


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


@app.get("/")
def health_check():
    return {"status": "healthy", "service": "ai_service"}


@app.get("/stats")
def get_stats():
    return get_vectorstore_stats()


@app.post("/extract_data")
async def extract_data(uploaded_file: UploadFile = File(...), engine: str = "gemini"):
    """takes a prescription image and extracts structured medical data from it"""

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

    # prompt telling gemini what json format we want back
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

    # try sarvam ocr first (works better for indian prescriptions)
    sarvam_text = None
    if engine != "gemini" and SARVAM_API_KEY:
        try:
            import requests
            import time
            import io
            import zipfile

            logger.info("Trying Sarvam OCR (async digitization)...")
            
            # Step 1: Create digitization job
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
            logger.info("Created Sarvam job: %s", job_id)
            
            # Step 2: Get presigned upload URL
            upload_init_url = "https://api.sarvam.ai/doc-digitization/job/v1/upload-files"
            upload_payload = {
                "job_id": job_id,
                "files": [uploaded_file.filename or "file.png"]
            }
            upload_init_resp = requests.post(upload_init_url, headers=headers, json=upload_payload, timeout=20)
            if upload_init_resp.status_code not in (200, 201, 202):
                raise Exception(f"Get upload URL failed ({upload_init_resp.status_code}): {upload_init_resp.text}")
            
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
            
            # Step 3: PUT the file to the presigned URL
            put_headers = {"Content-Type": file_type}
            if "blob.core.windows.net" in presigned_url:
                put_headers["x-ms-blob-type"] = "BlockBlob"
                
            put_resp = requests.put(presigned_url, data=file_content, headers=put_headers, timeout=30)
            if put_resp.status_code not in (200, 201, 202, 204):
                raise Exception(f"Upload to storage failed ({put_resp.status_code}): {put_resp.text}")
            
            # Step 4: Start the job
            start_url = f"https://api.sarvam.ai/doc-digitization/job/v1/{job_id}/start"
            start_resp = requests.post(start_url, headers=headers, timeout=20)
            if start_resp.status_code not in (200, 201, 202):
                raise Exception(f"Start job failed ({start_resp.status_code}): {start_resp.text}")
            
            # Step 5: Poll for status
            status_url = f"https://api.sarvam.ai/doc-digitization/job/v1/{job_id}/status"
            max_polls = 50
            completed = False
            for attempt in range(max_polls):
                time.sleep(3)
                status_resp = requests.get(status_url, headers=headers, timeout=15)
                if status_resp.status_code in (200, 201, 202):
                    status = status_resp.json().get("status")
                    logger.info("Job %s status check %d: %s", job_id, attempt + 1, status)
                    if status == "completed":
                        completed = True
                        break
                    elif status in ("failed", "cancelled"):
                        raise Exception(f"Job failed with status: {status}")
                else:
                    logger.warning("Failed to check status: %s", status_resp.text)
            
            if not completed:
                raise Exception("Job timed out waiting for completion")
            
            # Step 6: Download the results zip
            download_url = f"https://api.sarvam.ai/doc-digitization/job/v1/{job_id}/download-files"
            download_resp = requests.post(download_url, headers=headers, timeout=20)
            if download_resp.status_code not in (200, 201, 202):
                raise Exception(f"Get download URL failed ({download_resp.status_code}): {download_resp.text}")
            
            download_json = download_resp.json()
            download_urls_dict = download_json.get("download_urls", {})
            
            zip_download_url = None
            if download_urls_dict:
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
                raise Exception(f"No download URL found in response: {download_json}")
                
            zip_resp = requests.get(zip_download_url, timeout=30)
            if zip_resp.status_code != 200:
                raise Exception(f"Failed to download results zip ({zip_resp.status_code})")
            
            # Step 7: Unzip and read the text
            with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as z:
                text_content = ""
                for filename in z.namelist():
                    if filename.endswith(".md") or filename.endswith(".txt"):
                        with z.open(filename) as f:
                            text_content = f.read().decode("utf-8")
                            break
                
                # If no md/txt, try to read json
                if not text_content:
                    for filename in z.namelist():
                        if filename.endswith(".json"):
                            with z.open(filename) as f:
                                json_data = json.loads(f.read().decode("utf-8"))
                                text_content = json.dumps(json_data)
                                break
            
            if text_content:
                sarvam_text = text_content
                logger.info("Sarvam OCR worked! Extracted text length: %d", len(sarvam_text))
            else:
                raise Exception("No readable text file found in the results zip")
        except Exception as e:
            logger.warning("Sarvam OCR failed, falling back to Gemini directly: %s", e)

    # now use gemini to structure the text into json
    ai_response = None
    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        
        # standard JSON schema representation to bypass SDK translation bugs
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

        # tell gemini to return structured json matching our schema
        config = {
            "response_mime_type": "application/json",
            "response_schema": json_schema
        }

        if sarvam_text:
            # if sarvam gave us text, feed that to gemini
            ai_response = model.generate_content(
                f"{extraction_prompt}\n\nTEXT CONTENT:\n{sarvam_text}",
                generation_config=config
            )
        else:
            # otherwise send the raw image to gemini directly
            logger.info("Using Gemini for image extraction directly.")
            ai_response = model.generate_content([
                {"mime_type": file_type, "data": file_content},
                extraction_prompt,
            ], generation_config=config)

        # parse the clean JSON response from Gemini
        result = json.loads(ai_response.text)
        result["ocr_engine"] = "Sarvam AI" if sarvam_text else "Gemini"

        return result

    except json.JSONDecodeError:
        raw = ai_response.text if ai_response else "no response"
        logger.error("Gemini gave bad JSON: %s", raw)
        raise HTTPException(status_code=422, detail="Could not parse AI response as JSON.")
    except Exception as e:
        logger.exception("Extraction failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/embed_record")
async def embed_record(request: EmbedRecordRequest):
    """saves a medical record into the vector db for RAG search later"""
    try:
        # convert pydantic medicine objects to plain dicts
        medicines = [med.model_dump() for med in request.medicines]

        ok = embed_medical_record(
            record_id=request.record_id,
            user_id=request.user_id,
            category=request.category,
            upload_date=request.upload_date,
            symptoms=request.symptoms,
            medicines=medicines,
            vitals=request.vitals,
            allergies=request.allergies,
        )

        if ok:
            logger.info("Embedded record %d for user %d", request.record_id, request.user_id)
            return {"message": "ok", "record_id": request.record_id}
        else:
            raise HTTPException(status_code=500, detail="Failed to embed record.")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("embed_record failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/delete_record")
async def delete_record(request: DeleteRecordRequest):
    """deletes a medical record from the vector db"""
    from rag_chain import delete_medical_record
    delete_medical_record(request.record_id)
    return {"message": "ok"}


@app.post("/chat")
async def chat(request: ChatRequest):
    """RAG chat - searches patient records and answers questions"""
    if not request.query or not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    result = chat_with_rag(
        user_id=request.user_id,
        question=request.query.strip(),
        clear_history=request.clear_history,
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
async def check_interactions(request: InteractionRequest):
    """checks if any of the new medicines have bad interactions with current ones"""
    if not GEMINI_API_KEY:
        return {"warnings": []}

    try:
        model = genai.GenerativeModel("gemini-2.5-flash")

        current = ", ".join(request.current_medicines) if request.current_medicines else "None"
        new = ", ".join(request.new_medicines)

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
async def compare_doctors(request: CompareDoctorsRequest):
    """compares two medical records from different doctors"""
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="AI not configured")

    try:
        model = genai.GenerativeModel("gemini-2.5-flash")

        doc1 = request.record1.get("doctor_name", "Doctor A")
        doc2 = request.record2.get("doctor_name", "Doctor B")

        prompt = f"""Compare these two medical records:

Doctor {doc1}: symptoms={request.record1.get('symptoms')}, medicines={request.record1.get('medicines')}
Doctor {doc2}: symptoms={request.record2.get('symptoms')}, medicines={request.record2.get('medicines')}

What are the differences in treatment? Explain in simple terms why they might differ.
Keep it short and remind the patient to consult a specialist if unsure."""

        response = model.generate_content(prompt)
        return {"summary": response.text}
    except Exception as e:
        logger.error("Compare failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


