import os
import json
from dotenv import load_dotenv

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import Chroma

load_dotenv()

GEMINI_API_KEY = os.getenv("GENAI_API_KEY")
 
# set up the embedding model (this is what converts text into vectors)
embeddings_model = None
if GEMINI_API_KEY:
    embeddings_model = GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=GEMINI_API_KEY
    )

# the chat model for generating responses
chat_model = None
if GEMINI_API_KEY:
    chat_model = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=GEMINI_API_KEY,
        temperature=0.3,
    )

# this is the prompt template that tells gemini how to behave
# tried a bunch of different ones, this one works best for medical stuff
MEDICAL_ASSISTANT_TEMPLATE = """You are a helpful medical assistant for the HealthScribe app.

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

MEDICAL_PROMPT = ChatPromptTemplate.from_template(MEDICAL_ASSISTANT_TEMPLATE)

# path where we save chat history so it doesnt get lost when server restarts
CHAT_HISTORY_FILE = os.path.join(os.path.dirname(__file__), "chat_histories.json")


def load_chat_histories():
    """load saved chat histories from disk"""
    if os.path.exists(CHAT_HISTORY_FILE):
        try:
            with open(CHAT_HISTORY_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_chat_histories(histories):
    """save chat histories to disk so they persist between restarts"""
    try:
        with open(CHAT_HISTORY_FILE, "w") as f:
            json.dump(histories, f)
    except Exception as e:
        print(f"Failed to save history: {e}")


# load any existing chat histories when the module starts
user_chat_histories = load_chat_histories()


def get_user_chat_history(user_id):
    """get the chat history for a specific user, create empty list if new user"""
    user_id_str = str(user_id)
    if user_id_str not in user_chat_histories:
        user_chat_histories[user_id_str] = []
    return user_chat_histories[user_id_str]


def add_to_chat_history(user_id, question, answer):
    """add a new question/answer pair to the users chat history
    we only keep the last 20 messages so it doesnt get too long"""
    user_id_str = str(user_id)
    history = get_user_chat_history(user_id_str)
    history.append(f"Human: {question}")
    history.append(f"Assistant: {answer}")

    # only keep last 20 messages otherwise context gets too big
    if len(history) > 20:
        user_chat_histories[user_id_str] = history[-20:]
    else:
        user_chat_histories[user_id_str] = history

    save_chat_histories(user_chat_histories)


def clear_user_memory(user_id):
    """clear chat history for a user (when they click the clear button)"""
    user_id_str = str(user_id)
    if user_id_str in user_chat_histories:
        del user_chat_histories[user_id_str]
        save_chat_histories(user_chat_histories)


def format_chat_history(user_id):
    """turn the chat history list into a string for the prompt"""
    history = get_user_chat_history(user_id)
    if not history:
        return "No previous conversation."
    return "\n".join(history)


def get_or_create_vectorstore():
    """get the chroma vector store, or create it if it doesnt exist yet"""
    if embeddings_model is None:
        return None

    try:
        vectorstore = Chroma(
            persist_directory=CHROMA_PERSIST_DIRECTORY,
            embedding_function=embeddings_model,
            collection_name="medical_records"
        )
        return vectorstore
    except Exception as error:
        print(f"Error creating vector store: {error}")
        return None


def embed_medical_record(record_id, user_id, category, upload_date,
                         symptoms, medicines, vitals, allergies):
    """takes a medical record and embeds it into chromadb so the chatbot can search it later.
    we build a text representation of the record and store it with metadata"""
    vectorstore = get_or_create_vectorstore()

    if vectorstore is None:
        return False

    try:
        # build a text version of the record that makes sense for searching
        text_parts = []
        text_parts.append(f"Medical Record from {upload_date}")
        text_parts.append(f"Category: {category}")

        if symptoms and len(symptoms) > 0:
            symptoms_text = ", ".join(symptoms)
            text_parts.append(f"Symptoms: {symptoms_text}")

        if medicines and len(medicines) > 0:
            medicine_lines = []
            for med in medicines:
                med_name = med.get("name", "Unknown")
                med_dosage = med.get("dosage", "")
                med_reason = med.get("reason", "")

                med_text = f"{med_name}"
                if med_dosage:
                    med_text += f" ({med_dosage})"
                if med_reason:
                    med_text += f" for {med_reason}"

                medicine_lines.append(med_text)

            text_parts.append(f"Medicines: {'; '.join(medicine_lines)}")

        # only add vitals that actually have values
        if vitals and len(vitals) > 0:
            vital_lines = []
            for name, value in vitals.items():
                if value:
                    vital_lines.append(f"{name}: {value}")
            if vital_lines:
                text_parts.append(f"Vitals: {', '.join(vital_lines)}")

        if allergies and len(allergies) > 0:
            text_parts.append(f"Allergies mentioned: {', '.join(allergies)}")

        document_text = "\n".join(text_parts)

        # create the document with metadata for filtering
        document = Document(
            page_content=document_text,
            metadata={
                "record_id": record_id,
                "user_id": user_id,
                "category": category,
                "upload_date": upload_date
            }
        )

        vectorstore.add_documents([document])
        return True

    except Exception as error:
        print(f"error: {error}")
        return False


def format_docs(docs):
    """format retrieved documents into a string for the prompt context"""
    if not docs:
        return "none found."
    result = ""
    for i, doc in enumerate(docs):
        if i > 0:
            result += "\n\n---\n\n"
        result += doc.page_content
    return result


def chat_with_rag(user_id, question, clear_history=False):
    """main chat function - retrieves relevent records from chromadb
    and uses gemini to generate a response based on them"""
    if chat_model is None or embeddings_model is None:
        return {"error": "models not ready"}

    try:
        if clear_history:
            clear_user_memory(user_id)

        vectorstore = get_or_create_vectorstore()

        if vectorstore is None:
            return {"error": "no db"}

        # search for records that match the users question
        # we filter by user_id so users only see their own records
        retriever = vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={
                "k": 5,
                "filter": {"user_id": user_id}
            }
        )

        retrieved_docs = retriever.invoke(question)
        context = format_docs(retrieved_docs)

        chat_history = format_chat_history(user_id)

        # chain the prompt, model, and output parser together
        # this is the langchain way of doing things
        rag_chain = (
            MEDICAL_PROMPT
            | chat_model
            | StrOutputParser()
        )

        answer = rag_chain.invoke({
            "context": context,
            "chat_history": chat_history,
            "question": question
        })

        add_to_chat_history(user_id, question, answer)

        return {"answer": answer}

    except Exception as error:
        return {"error": str(error)}


def get_vectorstore_stats():
    """get some basic stats about whats in the vector database"""
    vectorstore = get_or_create_vectorstore()

    if vectorstore is None:
        return {"error": "no vector db"}

    try:
        collection = vectorstore._collection
        count = collection.count()
        return {
            "total_documents": count,
            "persist_directory": CHROMA_PERSIST_DIRECTORY
        }
    except Exception as error:
        return {"error": str(error)}
