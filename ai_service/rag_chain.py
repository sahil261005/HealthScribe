import re
import random
import os
import json
import time
import psycopg2
import threading
import concurrent.futures
from dotenv import load_dotenv

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.vectorstores import PGVector

load_dotenv()

GEMINI_API_KEY = (os.getenv("GENAI_API_KEY") or "").strip() or None
CHROMA_DIR = os.path.join(os.path.dirname(__file__), "chroma_db")
CONNECTION_STRING = os.getenv("DATABASE_URL")
# PGVector uses sqlalchemy, which only accepts postgresql:// and crashes on postgres://
# (django and psycopg2 accept both, so the same url can work there and fail here)
if CONNECTION_STRING and CONNECTION_STRING.startswith("postgres://"):
    CONNECTION_STRING = "postgresql://" + CONNECTION_STRING[len("postgres://"):]

# sqlalchemy 2.1 changed the default postgres driver to psycopg (v3), but we only install
# psycopg2, so PGVector crashed with "No module named 'psycopg'". tell it to use psycopg2.
# (psycopg2.connect for the chat history still needs the normal url, so keep both)
PGVECTOR_URL = None
if CONNECTION_STRING:
    PGVECTOR_URL = CONNECTION_STRING.replace("postgresql://", "postgresql+psycopg2://", 1)


_chat_table_initialized = False

def init_chat_table():
    global _chat_table_initialized
    if _chat_table_initialized or not CONNECTION_STRING:
        return
    try:
        conn = psycopg2.connect(CONNECTION_STRING, connect_timeout=5)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                sender VARCHAR(50) NOT NULL,
                message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
        _chat_table_initialized = True
        print("chat_history table ready")
    except Exception as e:
        print(f"couldnt create chat_history table: {e}")


# Embeddings and LLM lazy configuration
embeddings_model = None

FALLBACK_CHAT_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-3.6-flash",
]

# don't start trying another chat model after this many seconds,
# otherwise a message could wait through all 7 models and take minutes
CHAT_FALLBACK_TIME_LIMIT = 40


def is_quota_error(err):
    text = str(err).lower()
    return "429" in text or "quota" in text or "resource_exhausted" in text or "resource exhausted" in text


def friendly_error(err):
    # don't show raw errors in the chat, they can have internal details in them.
    # keep the word "quota" so the frontend can show its quota message
    print(f"chat error: {err}")
    if err is not None and is_quota_error(err):
        return "The AI quota is used up for now, please try again later."
    return "The assistant is not available right now, please try again in a minute."


def get_embeddings_model():
    global embeddings_model
    if embeddings_model is None and GEMINI_API_KEY:
        embeddings_model = GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-001",
            google_api_key=GEMINI_API_KEY
        )
    return embeddings_model

def get_chat_model(model_name="gemini-3.5-flash-lite", timeout=20):
    if GEMINI_API_KEY:
        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=GEMINI_API_KEY,
            temperature=0.3,
            max_retries=1,
            timeout=timeout,
        )
    return None

PROMPT_TEMPLATE = """You are a helpful medical assistant for the HealthScribe app.

IMPORTANT RULES:
1. You are NOT a doctor. Do not provide medical advice or diagnoses.
2. Only answer based on the patient's medical records provided in the context below.
3. If the information is not in the records, say "I don't have that information in your records."
4. Be concise, friendly, and accurate in your responses.
5. When mentioning medicines, always include the dosage if available.
6. If asked about dates, try to mention when the record was created.

PATIENT'S RELEVANT MEDICAL RECORDS:
{context}

PREVIOUS CONVERSATION:
{chat_history}

PATIENT'S QUESTION: {question}

YOUR RESPONSE:"""

MEDICAL_PROMPT = ChatPromptTemplate.from_template(PROMPT_TEMPLATE)

# Conversational greeting detection & fast-path prompt
CLINICAL_KEYWORDS = {
    "medicine", "medicines", "medication", "medications", "drug", "drugs",
    "prescription", "prescriptions", "prescribed", "diagnosis", "symptom", "symptoms",
    "disease", "condition", "fever", "cough", "pain", "headache", "pressure", "bp",
    "pulse", "heart", "vitals", "vital", "report", "reports", "record", "records",
    "lab", "test", "tests", "allergy", "allergies", "allergic", "dose", "dosage",
    "treatment", "hospital", "clinic", "mg", "tablet", "tablets", "syrup"
}

CONVERSATIONAL_PHRASES = [
    r"\b(hi|hello|hey|hola|namaste|greetings|yo|sup|hii|hiii|heya|howdy)\b",
    r"\bgood\s+(morning|afternoon|evening|day|night)\b",
    r"\bhow\s+(are\s+(you|u)|r\s+u|is\s+it\s+going|do\s+(you|u)\s+do)\b",
    r"\b(who|what)\s+(are|r)\s+(you|u)\b",
    r"\bwhat\s+(can|do)\s+(you|u)\s+do\b",
    r"\bwho\s+made\s+(you|u)\b",
    r"\b(what\s+is\s+healthscribe|tell\s+me\s+about\s+(yourself|urself|you|u))\b",
    r"\b(thank\s+(you|u)|thanks|bye|goodbye|see\s+(you|u)|thnx|ty|thx)\b",
    r"^(help|\?)$",
    r"\b(wassup|wazzup|whats\s+up|what\'?s\s+up)\b",
]

# words that can come with a greeting without changing its meaning ("thanks so much", "hi there")
FILLER_WORDS = {
    "there", "again", "so", "much", "a", "lot", "very", "bro", "buddy", "dear", "man", "all",
    "everyone", "assistant", "healthscribe", "and", "ok", "okay", "please", "great", "good",
    "nice", "cool", "oh", "hmm", "for", "the", "today", "tomorrow", "later", "soon", "now",
    "help", "your", "you", "u", "it", "is", "doing", "s",
}

def is_conversational_query(question: str) -> bool:
    if not question:
        return False
    q = question.strip().lower()
    if len(q) > 100:
        return False
    words = set(re.findall(r"\b\w+\b", q))
    if any(w in CLINICAL_KEYWORDS for w in words):
        return False

    # remove the greeting parts from the message
    leftover = q
    matched = False
    for pat in CONVERSATIONAL_PHRASES:
        if re.search(pat, leftover):
            matched = True
            leftover = re.sub(pat, " ", leftover)

    if not matched:
        return False

    # if there is still a real question left after the greeting
    # (like "thanks, what was my temperature?") it should go to the RAG search
    leftover_words = [w for w in re.findall(r"[a-z]+", leftover) if w not in FILLER_WORDS]
    return len(leftover_words) == 0

GREETING_PROMPT_TEMPLATE = """You are HealthScribe Assistant, a friendly, professional, and empathetic clinical companion.
The user sent a casual greeting or introductory question.
Respond warmly, politely, and concisely (1-2 sentences).
Welcome them to HealthScribe and let them know you can help answer questions about their uploaded medical records, prescriptions, symptoms, doctor notes, and vitals.
Do not provide medical diagnoses or medical advice.

USER MESSAGE: {question}

YOUR RESPONSE:"""

GREETING_PROMPT = ChatPromptTemplate.from_template(GREETING_PROMPT_TEMPLATE)

# Instant canned responses for common greetings — zero API calls, zero latency
INSTANT_RESPONSES = {
    "greeting": [
        "Hello! 👋 I'm your HealthScribe assistant. I can help you review your medical records, prescriptions, symptoms, doctor notes, and vitals. What would you like to know?",
        "Hi there! Welcome to HealthScribe. I can help you look up your prescriptions, symptoms, vitals, and doctor notes from your uploaded records. How can I help?",
        "Hey! I'm HealthScribe Assistant — here to help you navigate your medical records. Ask me about your medicines, symptoms, vitals, or doctor visits!",
    ],
    "identity": [
        "I'm HealthScribe Assistant! I help you understand your uploaded medical records — prescriptions, symptoms, vitals, doctor notes, and more. I'm not a doctor, but I can help you find info in your records. 😊",
        "I'm your HealthScribe AI companion! I can search through your medical records, look up prescribed medicines and dosages, review symptoms, and check your vitals. What would you like to explore?",
    ],
    "capability": [
        "I can help you with:\n• 📋 Review your medical records\n• 💊 Look up prescribed medicines & dosages\n• 🩺 Check your symptoms history\n• ❤️ View your vitals (BP, pulse, temperature)\n• 👨‍⚕️ See doctor notes\n\nJust ask me anything about your health records!",
        "Here's what I can do for you:\n• Search your uploaded prescriptions and medicines\n• Review symptoms from past visits\n• Check your vitals history\n• Look up doctor notes and diagnoses\n\nWhat would you like to know?",
    ],
    "thanks": [
        "You're welcome! 😊 Let me know if you need anything else about your records.",
        "Happy to help! Feel free to ask me anything about your medical records anytime.",
    ],
    "goodbye": [
        "Goodbye! Take care of yourself. I'll be here whenever you need to check your records! 👋",
        "See you! Remember, I'm always here to help with your health records. Stay healthy! 😊",
    ],
}

def get_instant_response(question: str):
    """Returns an instant canned response for common greetings, or None if LLM should handle it."""
    q = question.strip().lower()
    cleaned = re.sub(r"[^\w\s]", "", q).strip()

    # Capability questions
    if re.search(r"\bwhat\s+(can|do)\s+(you|u)\s+do\b", q) or re.search(r"\bwhat\s+(can|do)\s+(you|u)\s+do\b", cleaned):
        return random.choice(INSTANT_RESPONSES["capability"])
    if cleaned == "help":
        return random.choice(INSTANT_RESPONSES["capability"])

    # Identity questions
    if re.search(r"\b(who|what)\s+(are|r)\s+(you|u)\b", q) or re.search(r"\b(who|what)\s+(are|r)\s+(you|u)\b", cleaned):
        return random.choice(INSTANT_RESPONSES["identity"])
    if re.search(r"\bwhat\s+is\s+healthscribe\b", q):
        return random.choice(INSTANT_RESPONSES["identity"])

    # Thanks
    if re.search(r"\b(thank\s+(you|u)|thanks|thnx|ty|thx)\b", q):
        return random.choice(INSTANT_RESPONSES["thanks"])

    # Goodbye
    if re.search(r"\b(bye|goodbye|see\s+(you|u))\b", q):
        return random.choice(INSTANT_RESPONSES["goodbye"])

    # Simple greetings
    if re.search(r"\b(hi|hello|hey|hola|namaste|greetings|yo|sup|hii|hiii|heya|howdy)\b", q):
        return random.choice(INSTANT_RESPONSES["greeting"])
    if re.search(r"\bgood\s+(morning|afternoon|evening|day|night)\b", q):
        return random.choice(INSTANT_RESPONSES["greeting"])
    if re.search(r"\b(wassup|wazzup|whats\s+up|what\'?s\s+up)\b", q):
        return random.choice(INSTANT_RESPONSES["greeting"])
    if re.search(r"\bhow\s+(are\s+(you|u)|r\s+u|is\s+it\s+going)\b", q):
        return random.choice(INSTANT_RESPONSES["greeting"])

    return None


HISTORY_FILE = os.path.join(os.path.dirname(__file__), "chat_histories.json")

# how many past messages go into the prompt
HISTORY_IN_PROMPT = 6
# how many messages we keep per user in total
HISTORY_TO_KEEP = 20

# requests run in parallel threads now, so only one thread
# should use the shared postgres connection / the json file at a time
_history_conn_lock = threading.Lock()
_history_file_lock = threading.Lock()


# Chat history utilities (postgres with local JSON file fallback)
def load_histories():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_histories(data):
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"couldnt save history file: {e}")


chat_histories = load_histories()


_history_conn = None

def get_history(user_id):
    global _history_conn
    # Try fetching history from Postgres with connection reuse and auto-reconnect
    if CONNECTION_STRING:
        with _history_conn_lock:
            for attempt in range(2):
                try:
                    if _history_conn is None or _history_conn.closed:
                        _history_conn = psycopg2.connect(CONNECTION_STRING, connect_timeout=5)
                    cur = _history_conn.cursor()
                    # order by id, not created_at - the question and answer are inserted
                    # together so they get the exact same created_at, and postgres
                    # could return them in any order (answer before question)
                    cur.execute("""
                        SELECT sender, message FROM (
                            SELECT id, sender, message FROM chat_history
                            WHERE user_id = %s
                            ORDER BY id DESC
                            LIMIT %s
                        ) sub ORDER BY id ASC
                    """, (str(user_id), HISTORY_IN_PROMPT))
                    rows = cur.fetchall()
                    cur.close()

                    result = []
                    for sender, msg in rows:
                        result.append(f"{sender}: {msg}")
                    return result
                except Exception as e:
                    print(f"postgres history error (attempt {attempt+1}): {e}")
                    try:
                        if _history_conn:
                            _history_conn.close()
                    except Exception:
                        pass
                    _history_conn = None

    # Fallback to the local JSON file history
    with _history_file_lock:
        history = chat_histories.get(str(user_id), [])
        return list(history[-HISTORY_IN_PROMPT:])


def add_message(user_id, question, answer):
    # Save to Postgres
    if CONNECTION_STRING:
        try:
            conn = psycopg2.connect(CONNECTION_STRING, connect_timeout=5)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO chat_history (user_id, sender, message) VALUES (%s, %s, %s), (%s, %s, %s)",
                (str(user_id), "Human", question, str(user_id), "Assistant", answer)
            )
            # Keep only the last few messages for this user to save space
            # (by id again, so we never delete half of a question/answer pair)
            cur.execute("""
                DELETE FROM chat_history
                WHERE user_id = %s
                AND id NOT IN (
                    SELECT id FROM chat_history
                    WHERE user_id = %s
                    ORDER BY id DESC
                    LIMIT %s
                )
            """, (str(user_id), str(user_id), HISTORY_TO_KEEP))
            conn.commit()
            cur.close()
            conn.close()
            return
        except Exception as e:
            print(f"postgres add_message error: {e}")

    # Fallback to local JSON save
    key = str(user_id)
    with _history_file_lock:
        history = chat_histories.get(key, [])
        history.append(f"Human: {question}")
        history.append(f"Assistant: {answer}")
        chat_histories[key] = history[-HISTORY_TO_KEEP:]
        save_histories(chat_histories)


def clear_user_memory(user_id):
    if CONNECTION_STRING:
        try:
            conn = psycopg2.connect(CONNECTION_STRING)
            cur = conn.cursor()
            cur.execute("DELETE FROM chat_history WHERE user_id = %s", (str(user_id),))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"postgres clear error: {e}")

    key = str(user_id)
    with _history_file_lock:
        if key in chat_histories:
            del chat_histories[key]
            save_histories(chat_histories)


def format_history(user_id):
    history = get_history(user_id)
    if not history:
        return "No previous conversation."
    return "\n".join(history)


# Vector database initialization (Postgres PGVector / Local Chroma fallback)
# Cache the store so we don't open a new DB connection on every request
_vectorstore_cache = None

def get_vectorstore():
    global _vectorstore_cache
    if _vectorstore_cache is not None:
        return _vectorstore_cache

    emb = get_embeddings_model()
    if emb is None:
        return None

    if CONNECTION_STRING:
        try:
            store = PGVector(
                connection_string=PGVECTOR_URL,
                embedding_function=emb,
                collection_name="medical_records"
            )
            _vectorstore_cache = store
            return store
        except Exception as e:
            # don't fall back to local chroma here. on render the disk is wiped on every
            # restart, so records saved there would just disappear later.
            # returning None means we try postgres again on the next request
            # flush so it actually shows up in the render logs straight away
            print(f"pgvector error: {type(e).__name__}: {e}", flush=True)
            return None

    # Use Chroma locally (only when there is no DATABASE_URL, e.g. local dev)
    try:
        store = Chroma(
            persist_directory=CHROMA_DIR,
            embedding_function=emb,
            collection_name="medical_records"
        )
        _vectorstore_cache = store
        return store
    except Exception as e:
        print(f"chroma error: {e}")
        return None


def embed_medical_record(record_id, user_id, category, doctor_name, upload_date,
                          symptoms, medicines, vitals, allergies):
    # Formats a clinical record and embeds it into the vector database
    store = get_vectorstore()
    if store is None:
        return False

    try:
        parts = []
        parts.append(f"Medical Record from {upload_date}")
        parts.append(f"Category: {category}")
        if doctor_name:
            parts.append(f"Doctor: {doctor_name}")

        if symptoms:
            parts.append(f"Symptoms: {', '.join(symptoms)}")

        if medicines:
            med_lines = []
            for med in medicines:
                line = med.get("name", "Unknown")
                if med.get("dosage"):
                    line += f" ({med['dosage']})"
                if med.get("reason"):
                    line += f" for {med['reason']}"
                med_lines.append(line)
            parts.append(f"Medicines: {'; '.join(med_lines)}")

        if vitals:
            # Expand shorthand labels so vector search matches natural language queries
            # e.g. "temp" → "Temperature" so "what was my temperature" retrieves this record
            vital_label_map = {
                "temp": "Temperature (temp)",
                "bp": "Blood Pressure (BP)",
                "pulse": "Pulse / Heart Rate",
            }
            vital_parts = []
            for name, value in vitals.items():
                if value:
                    expanded = vital_label_map.get(name.lower(), name)
                    vital_parts.append(f"{expanded}: {value}")
            if vital_parts:
                parts.append(f"Vitals: {', '.join(vital_parts)}")

        if allergies:
            parts.append(f"Allergies: {', '.join(allergies)}")

        text = "\n".join(parts)

        # We keep the record in a single chunk so the LLM doesn't lose the
        # semantic link between symptoms and their prescribed drugs.
        doc = Document(
            page_content=text,
            metadata={
                "record_id": record_id,
                "user_id": user_id,
                "category": category,
                "upload_date": upload_date
            }
        )

        # Clear out previous records to avoid duplicate issues
        try:
            store.delete(ids=[f"record_{record_id}"])
        except:
            pass

        store.add_documents([doc], ids=[f"record_{record_id}"])
        return True

    except Exception as e:
        print(f"embedding error: {e}")
        return False


def delete_medical_record(record_id):
    store = get_vectorstore()
    if store is None:
        return False
    try:
        store.delete(ids=[f"record_{record_id}"])
        return True
    except Exception as e:
        print(f"delete embedding error: {e}")
        return False


def format_docs(docs):
    if not docs:
        return "no records found."
    pieces = []
    for doc in docs:
        pieces.append(doc.page_content)
    return "\n\n---\n\n".join(pieces)


def chat_with_rag(user_id, question, clear_history=False, search_type="mmr", k=5, lambda_mult=0.5):
    # Main search and answer logic using LangChain and RAG
    if not GEMINI_API_KEY:
        return {"error": "AI models not configured"}

    try:
        if clear_history:
            clear_user_memory(user_id)

        # ⚡ Conversational Shortcut: Skip vector database search for simple greetings!
        if is_conversational_query(question):
            instant = get_instant_response(question)
            if instant:
                threading.Thread(target=add_message, args=(user_id, question, instant), daemon=True).start()
                return {"answer": instant, "model_used": "instant", "fast_path": True}
            # Fallback to LLM for edge-case conversational queries
            last_err = None
            start_time = time.time()
            for model_name in FALLBACK_CHAT_MODELS:
                if time.time() - start_time > CHAT_FALLBACK_TIME_LIMIT:
                    break
                try:
                    candidate_model = get_chat_model(model_name, timeout=15)
                    if candidate_model is None:
                        continue
                    chain = GREETING_PROMPT | candidate_model | StrOutputParser()
                    answer = chain.invoke({"question": question})
                    ans_text = str(answer)
                    threading.Thread(target=add_message, args=(user_id, question, ans_text), daemon=True).start()
                    return {"answer": ans_text, "model_used": model_name, "fast_path": True}
                except Exception as e:
                    last_err = e
                    continue
            if last_err:
                return {"error": friendly_error(last_err)}

        emb = get_embeddings_model()
        if emb is None:
            return {"error": "AI embeddings not configured"}

        store = get_vectorstore()
        if store is None:
            return {"error": "The records database is not available right now, please try again in a minute."}

        # Configure retriever search parameters
        # fetch_k=20 gives MMR a wider candidate pool so it doesn't discard
        # vitals-containing records when multiple similar visits exist on the same date
        search_kwargs = {"k": k, "fetch_k": 20, "filter": {"user_id": user_id}}
        if search_type == "mmr":
            search_kwargs["lambda_mult"] = lambda_mult

        retriever = store.as_retriever(
            search_type=search_type,
            search_kwargs=search_kwargs
        )

        # Fetch relevant documents and conversation history concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future_docs = executor.submit(retriever.invoke, question)
            future_history = executor.submit(format_history, user_id)
            docs = future_docs.result()
            history = future_history.result()

        context = format_docs(docs)

        # Multi-model fallback cascade
        last_err = None
        answer = None
        used_model = None
        start_time = time.time()

        for model_name in FALLBACK_CHAT_MODELS:
            if time.time() - start_time > CHAT_FALLBACK_TIME_LIMIT:
                print("chat fallback time limit reached, not trying more models")
                break
            try:
                candidate_model = get_chat_model(model_name)
                if candidate_model is None:
                    continue
                chain = MEDICAL_PROMPT | candidate_model | StrOutputParser()
                answer = chain.invoke({
                    "context": context,
                    "chat_history": history,
                    "question": question
                })
                used_model = model_name
                break
            except Exception as e:
                last_err = e
                err_str = str(e)
                print(f"Chat model {model_name} failed: {err_str}. Trying next fallback...")
                continue

        if answer is None:
            return {"error": friendly_error(last_err)}

        ans_text = str(answer)
        threading.Thread(target=add_message, args=(user_id, question, ans_text), daemon=True).start()
        return {"answer": ans_text, "model_used": used_model}

    except Exception as e:
        return {"error": friendly_error(e)}



def stream_chat_with_rag(user_id, question, clear_history=False, search_type="mmr", k=5, lambda_mult=0.5):
    """
    Generator yielding string token chunks in real-time.
    Supports conversational greeting fast-path and multi-model fallback.
    """
    if not GEMINI_API_KEY:
        yield "AI models are not configured on the server."
        return

    try:
        if clear_history:
            clear_user_memory(user_id)

        # ⚡ Conversational Shortcut: Greetings bypass vector search completely for instant streaming
        if is_conversational_query(question):
            instant = get_instant_response(question)
            if instant:
                threading.Thread(target=add_message, args=(user_id, question, instant), daemon=True).start()
                yield instant
                return
            # Fallback to LLM for edge-case conversational queries
            last_err = None
            start_time = time.time()
            for model_name in FALLBACK_CHAT_MODELS:
                if time.time() - start_time > CHAT_FALLBACK_TIME_LIMIT:
                    break
                try:
                    candidate_model = get_chat_model(model_name, timeout=15)
                    if candidate_model is None:
                        continue
                    chain = GREETING_PROMPT | candidate_model | StrOutputParser()
                    full_answer = []
                    for chunk in chain.stream({"question": question}):
                        full_answer.append(chunk)
                        yield chunk
                    ans_text = "".join(full_answer)
                    threading.Thread(target=add_message, args=(user_id, question, ans_text), daemon=True).start()
                    return
                except Exception as e:
                    last_err = e
                    print(f"Greeting stream model {model_name} failed: {e}. Trying fallback...")
                    continue
            yield friendly_error(last_err)
            return

        emb = get_embeddings_model()
        if emb is None:
            yield "Embeddings model not configured."
            return

        store = get_vectorstore()
        if store is None:
            yield "The records database is not available right now, please try again in a minute."
            return

        # Configure retriever search parameters
        # fetch_k=20 gives MMR a wider candidate pool so it doesn't discard
        # vitals-containing records when multiple similar visits exist on the same date
        search_kwargs = {"k": k, "fetch_k": 20, "filter": {"user_id": user_id}}
        if search_type == "mmr":
            search_kwargs["lambda_mult"] = lambda_mult

        retriever = store.as_retriever(
            search_type=search_type,
            search_kwargs=search_kwargs
        )

        # Fetch relevant documents and conversation history concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future_docs = executor.submit(retriever.invoke, question)
            future_history = executor.submit(format_history, user_id)
            docs = future_docs.result()
            history = future_history.result()

        context = format_docs(docs)

        # Multi-model fallback cascade for streaming
        last_err = None
        started = False
        start_time = time.time()

        for model_name in FALLBACK_CHAT_MODELS:
            if time.time() - start_time > CHAT_FALLBACK_TIME_LIMIT:
                print("chat fallback time limit reached, not trying more models")
                break
            try:
                candidate_model = get_chat_model(model_name)
                if candidate_model is None:
                    continue
                chain = MEDICAL_PROMPT | candidate_model | StrOutputParser()
                full_answer = []
                for chunk in chain.stream({
                    "context": context,
                    "chat_history": history,
                    "question": question
                }):
                    started = True
                    full_answer.append(chunk)
                    yield chunk

                ans_text = "".join(full_answer)
                threading.Thread(target=add_message, args=(user_id, question, ans_text), daemon=True).start()
                return
            except Exception as e:
                last_err = e
                print(f"Streaming model {model_name} failed: {e}. Trying next fallback...")
                if started:
                    yield "\n\n[Connection interrupted, please try again]"
                    return
                continue

        yield friendly_error(last_err)

    except Exception as e:
        yield friendly_error(e)


def get_vectorstore_stats():
    store = get_vectorstore()
    if store is None:
        return {"error": "vector db not available"}

    try:
        if isinstance(store, PGVector):
            # pgvector doesn't have _collection like chroma, so count the rows ourselves
            conn = psycopg2.connect(CONNECTION_STRING, connect_timeout=5)
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*) FROM langchain_pg_embedding e
                JOIN langchain_pg_collection c ON e.collection_id = c.uuid
                WHERE c.name = %s
            """, ("medical_records",))
            count = cur.fetchone()[0]
            cur.close()
            conn.close()
            return {"total_documents": count, "store": "pgvector"}

        count = store._collection.count()
        return {
            "total_documents": count,
            "store": "chroma",
            "persist_directory": CHROMA_DIR
        }
    except Exception as e:
        print(f"stats error: {e}")
        return {"error": "could not read vector db stats"}
