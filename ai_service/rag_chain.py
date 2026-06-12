import os
import json
import psycopg2
from dotenv import load_dotenv

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.vectorstores import PGVector

load_dotenv()

GEMINI_API_KEY = os.getenv("GENAI_API_KEY")
CHROMA_DIR = os.path.join(os.path.dirname(__file__), "chroma_db")
CONNECTION_STRING = os.getenv("DATABASE_URL")


# create chat_history table in postgres if it doesnt exist yet
def init_chat_table():
    if not CONNECTION_STRING:
        return
    try:
        conn = psycopg2.connect(CONNECTION_STRING)
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
        print("chat_history table ready")
    except Exception as e:
        print(f"couldnt create chat_history table: {e}")

init_chat_table()


# embedding model - using gemini embedding
embeddings_model = None
if GEMINI_API_KEY:
    embeddings_model = GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=GEMINI_API_KEY
    )

# llm for chat
chat_model = None
if GEMINI_API_KEY:
    chat_model = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=GEMINI_API_KEY,
        temperature=0.3,
    )

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

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "chat_histories.json")


# chat history helpers - uses postgres if available, otherwise json file

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


def get_history(user_id):
    # try postgres first
    if CONNECTION_STRING:
        try:
            conn = psycopg2.connect(CONNECTION_STRING)
            cur = conn.cursor()
            # get last 20 msgs, ordered oldest first so the conversation reads properly
            cur.execute("""
                SELECT sender, message FROM (
                    SELECT sender, message, created_at FROM chat_history
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    LIMIT 20
                ) sub ORDER BY created_at ASC
            """, (str(user_id),))
            rows = cur.fetchall()
            cur.close()
            conn.close()

            result = []
            for sender, msg in rows:
                result.append(f"{sender}: {msg}")
            return result
        except Exception as e:
            print(f"postgres history error: {e}")

    # fallback to json file
    key = str(user_id)
    if key not in chat_histories:
        chat_histories[key] = []
    return chat_histories[key]


def add_message(user_id, question, answer):
    if CONNECTION_STRING:
        try:
            conn = psycopg2.connect(CONNECTION_STRING)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO chat_history (user_id, sender, message) VALUES (%s, %s, %s)",
                (str(user_id), "Human", question)
            )
            cur.execute(
                "INSERT INTO chat_history (user_id, sender, message) VALUES (%s, %s, %s)",
                (str(user_id), "Assistant", answer)
            )
            # cleanup old msgs so the table doesnt grow forever (keep last 20)
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

    # fallback to json
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


# vector store - pgvector for supabase, chroma for local dev

def get_vectorstore():
    if embeddings_model is None:
        return None

    if CONNECTION_STRING:
        try:
            store = PGVector(
                connection_string=CONNECTION_STRING,
                embedding_function=embeddings_model,
                collection_name="medical_records"
            )
            return store
        except Exception as e:
            print(f"pgvector error: {e}")
            return None

    # local chromadb fallback
    try:
        store = Chroma(
            persist_directory=CHROMA_DIR,
            embedding_function=embeddings_model,
            collection_name="medical_records"
        )
        return store
    except Exception as e:
        print(f"chroma error: {e}")
        return None


def embed_medical_record(record_id, user_id, category, upload_date,
                          symptoms, medicines, vitals, allergies):
    """saves a medical record into the vector store for RAG search"""

    store = get_vectorstore()
    if store is None:
        return False

    try:
        # build text from all the record fields
        parts = []
        parts.append(f"Medical Record from {upload_date}")
        parts.append(f"Category: {category}")

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

        # not splitting into chunks because medical records are short enough to fit in one doc.
        # splitting would break the link between symptoms and their medicines which is bad
        doc = Document(
            page_content=text,
            metadata={
                "record_id": record_id,
                "user_id": user_id,
                "category": category,
                "upload_date": upload_date
            }
        )

        # remove old embedding if exists so we dont get duplicates
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


def chat_with_rag(user_id, question, clear_history=False):
    """main function - retrieves relevant records and generates answer"""

    if chat_model is None or embeddings_model is None:
        return {"error": "AI models not configured"}

    try:
        if clear_history:
            clear_user_memory(user_id)

        store = get_vectorstore()
        if store is None:
            return {"error": "vector db not available"}

        # using mmr instead of similarity so we dont get 5 almost identical records
        # when a patient has repeat prescriptions. mmr picks more diverse results
        retriever = store.as_retriever(
            search_type="mmr",
            search_kwargs={
                "k": 5,
                "fetch_k": 10,
                "filter": {"user_id": user_id}
            }
        )

        docs = retriever.invoke(question)
        context = format_docs(docs)
        history = format_history(user_id)

        # run the chain: prompt -> model -> parse output
        chain = MEDICAL_PROMPT | chat_model | StrOutputParser()

        answer = chain.invoke({
            "context": context,
            "chat_history": history,
            "question": question
        })

        add_message(user_id, question, answer)
        return {"answer": answer}

    except Exception as e:
        return {"error": str(e)}


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
