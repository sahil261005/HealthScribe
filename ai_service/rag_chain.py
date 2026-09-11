import re
import os
import json
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

def is_conversational_query(question: str) -> bool:
    if not question:
        return False
    q = question.strip().lower()
    if len(q) > 100:
        return False
    words = set(re.findall(r"\b\w+\b", q))
    if any(w in CLINICAL_KEYWORDS for w in words):
        return False
    for pat in CONVERSATIONAL_PHRASES:
        if re.search(pat, q):
            return True
    return False

GREETING_PROMPT_TEMPLATE = """You are HealthScribe Assistant, a friendly, professional, and empathetic clinical companion.
The user sent a casual greeting or introductory question.
Respond warmly, politely, and concisely (1-2 sentences).
Welcome them to HealthScribe and let them know you can help answer questions about their uploaded medical records, prescriptions, symptoms, doctor notes, and vitals.
Do not provide medical diagnoses or medical advice.

USER MESSAGE: {question}

YOUR RESPONSE:"""

GREETING_PROMPT = ChatPromptTemplate.from_template(GREETING_PROMPT_TEMPLATE)


HISTORY_FILE = os.path.join(os.path.dirname(__file__), "chat_histories.json")


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
        for attempt in range(2):
            try:
                if _history_conn is None or _history_conn.closed:
                    _history_conn = psycopg2.connect(CONNECTION_STRING, connect_timeout=5)
                cur = _history_conn.cursor()
                cur.execute("""
                    SELECT sender, message FROM (
                        SELECT sender, message, created_at FROM chat_history
                        WHERE user_id = %s
                        ORDER BY created_at DESC
                        LIMIT 6
                    ) sub ORDER BY created_at ASC
                """, (str(user_id),))
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
                if attempt == 1:
                    break

    # Fallback to in-memory JSON file history
    key = str(user_id)
    if key not in chat_histories:
        chat_histories[key] = []
    return chat_histories[key]


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
            # Keep only the last 20 messages for this user to save space
            cur.execute("""
                DELETE FROM chat_history
                WHERE user_id = %s
                AND id NOT IN (
                    SELECT id FROM chat_history
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    LIMIT 20
                )
            """, (str(user_id), str(user_id)))
            conn.commit()
            cur.close()
            conn.close()
            return
        except Exception as e:
            print(f"postgres add_message error: {e}")

    # Fallback to local JSON save
    key = str(user_id)
    history = get_history(key)
    history.append(f"Human: {question}")
    history.append(f"Assistant: {answer}")

    if len(history) > 20:
        chat_histories[key] = history[-20:]
    else:
        chat_histories[key] = history

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
                connection_string=CONNECTION_STRING,
                embedding_function=emb,
                collection_name="medical_records"
            )
            _vectorstore_cache = store
            return store
        except Exception as e:
            print(f"pgvector error: {e}, falling back to local chroma")

    # Use Chroma locally
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
            vital_parts = []
            for name, value in vitals.items():
                if value:
                    vital_parts.append(f"{name}: {value}")
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
            last_err = None
            for model_name in FALLBACK_CHAT_MODELS:
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
                return {"error": f"All chat models unavailable. Last error: {last_err}"}

        emb = get_embeddings_model()
        if emb is None:
            return {"error": "AI embeddings not configured"}

        store = get_vectorstore()
        if store is None:
            return {"error": "vector db not available"}

        # Configure retriever search parameters
        search_kwargs = {"k": k, "fetch_k": 10, "filter": {"user_id": user_id}}
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

        for model_name in FALLBACK_CHAT_MODELS:
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
            return {"error": f"All chat models unavailable. Last error: {last_err}"}

        ans_text = str(answer)
        threading.Thread(target=add_message, args=(user_id, question, ans_text), daemon=True).start()
        return {"answer": ans_text, "model_used": used_model}

    except Exception as e:
        return {"error": str(e)}



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
            last_err = None
            for model_name in FALLBACK_CHAT_MODELS:
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
            yield f"Error generating response: {last_err}"
            return

        emb = get_embeddings_model()
        if emb is None:
            yield "Embeddings model not configured."
            return

        store = get_vectorstore()
        if store is None:
            yield "Vector database is currently unavailable."
            return

        # Configure retriever search parameters
        search_kwargs = {"k": k, "fetch_k": 10, "filter": {"user_id": user_id}}
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

        for model_name in FALLBACK_CHAT_MODELS:
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
                    yield f"\n\n[Connection interrupted: {e}]"
                    return
                continue

        yield f"All chat models are currently unavailable: {last_err}"

    except Exception as e:
        yield f"Chat error: {str(e)}"


def get_vectorstore_stats():
    store = get_vectorstore()
    if store is None:
        return {"error": "vector db not available"}

    try:
        collection = store._collection
        count = collection.count()
        return {
            "total_documents": count,
            "persist_directory": CHROMA_DIR
        }
    except Exception as e:
        return {"error": str(e)}
