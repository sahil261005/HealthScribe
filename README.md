# HealthScribe

A medical records app for prescriptions. Take a photo of a prescription, the AI reads it and turns it into
structured data (medicines, dosages, symptoms, vitals, allergies). You check it, save it, and then you can
ask a chatbot questions about your own medical history ("what was my last BP?", "which antibiotics have I taken?").

## What it does

- **Reads prescriptions** - English with Gemini vision, or Hindi / Marathi / other Indian scripts with a
  Sarvam OCR + Gemini hybrid. You review and edit the result before it is saved.
- **Chat with your records** - a RAG chatbot that only answers from your own records and says
  "I don't have that information" when something isn't there.
- **Safety checks** - warns when a new medicine clashes with a known allergy (including drug families,
  e.g. penicillin → amoxicillin) and checks for interactions with medicines you took before.
- **Dashboard** - timeline of visits, vitals over time, most prescribed medicines, and a comparison when
  two doctors treated the same thing.
- **Share with a doctor** - a private link + QR code to your health summary (expires after 7 days, can be turned off).

## How it works

```
                 ┌──────────────┐
  React app ───► │   Django     │  login (JWT), saving records, allergy checks, share links
  (Vite)         │  backend     │──────────┐
      │          └──────────────┘          │ internal calls (X-Internal-Key)
      │                                    ▼
      │          ┌──────────────────────────────────────────────┐
      └────────► │  FastAPI AI service                          │
   (same JWT)    │   /extract_data  Gemini  or  Sarvam → Gemini │
                 │   /chat          RAG over pgvector           │
                 └──────────────────────────────────────────────┘
                                    │
                         Supabase Postgres (records, embeddings, chat history)
```

**1. Extraction** - two engines, the user picks one in the upload screen:

| Engine | How | Use it for |
|---|---|---|
| Gemini | Gemini reads the image and fills a strict JSON schema | English prescriptions (faster) |
| Hybrid | Sarvam OCR reads the text first, then Gemini gets the image **and** that text, checks one against the other and fills the same JSON | Hindi, Marathi and other Indian scripts |

Dates are copied exactly as written and parsed in code, day-first (`12/08/2026` = 12 August), because
Indian prescriptions are written day-first. If Sarvam fails, the hybrid falls back to Gemini.

**2. Saving** - Django saves the reviewed record, checks it against the patient's allergies, asks the AI
service for drug interactions, and sends the record to be embedded for the chatbot.

**3. Chatbot (RAG)**
- Each record is embedded as **one chunk** (`gemini-embedding-001`) - a visit is short, and splitting it
  would separate symptoms from the medicines given for them.
- Retrieval uses **MMR with λ = 0.7**, which picks relevant records but skips near-duplicates (patients have
  many almost identical follow-up visits).
- For questions like "latest", "last time" or "current", the newest records are added as well, because
  embeddings have no idea which visit is the most recent. Records are given to the model newest first.
- Every search is filtered by the logged-in user's id, so one patient can never see another patient's records.

## Evaluation

There are two evaluation scripts. Both call the real app code (not a copy), save every raw output, and
can recompute the numbers from the saved results with `--rescore`.

**About the data:** both test sets are **synthetic**. Real medical records can't be used for privacy
reasons, and there is no public dataset of Indian patient histories or full prescriptions with labels.
The test data and saved results live in `ai_service/eval_data/` (`ocr/`, `rag/`, `results/`), which is kept out of git.

### RAG chatbot - similarity search vs. MMR (`evaluate_rag.py`)

**Test set:** 49 records across 4 synthetic patients (blood pressure, diabetes, thyroid, asthma),
70 questions - easy lookups, medium ("latest", "current dose") and multi-step questions (counting visits,
"the last time my BP was above 140", "when did I first start...", comparing two dates, typos and Hinglish),
plus 9 questions the bot should refuse (not in the records / another patient's doctor).

| | Similarity search | MMR (λ = 0.7) |
|---|---|---|
| Answer accuracy (61 answerable questions) | 90.2% | **91.8%** |
| Accuracy on multi-step questions (29) | 79.3% | **86.2%** |
| Duplicate records in the retrieved context | 14.3% | **8.0%** |
| Right record retrieved (top 5) | 98.4% | 98.4% |
| Correctly refused out-of-scope questions | 9 / 9 | 9 / 9 |
| Records leaked from other patients | 0 | 0 |
| Median answer time | 1.06s | 1.07s |
| **Faithfulness (LLM-as-a-judge)** | - | **100%** (60 judged answers) |

Other MMR settings (retrieval only): λ = 0.3 → 83.6% right record, λ = 0.5 → 88.5%, λ = 0.7 → 98.4%.
Lower λ removes more duplicates but starts dropping the records that answer the question.

**How the numbers are measured**
- **Answer accuracy** - each question has the facts a correct answer must contain (a BP value, a date, a
  medicine name...). The script checks the chatbot's answer for them in code.
- **Duplicate records** - share of the 5 retrieved records that repeat one already retrieved
  (same symptoms and medicines).
- **Faithfulness** - a stronger Gemini Flash model than the chat model (Gemini 3 / 3.7 / 3.8 Flash, rotated
  when one hit the free tier limit) is shown the records the chatbot saw and its answer, and decides if every
  fact in the answer comes from those records. To check the judge itself, its verdicts were compared with the
  code checks: they agreed 98.3% of the time.

### Extraction - Gemini vs. hybrid (`evaluate.py`)

**Test set:** 50 synthetic prescriptions with 97 medicines.
- **20 English:** 7 printed, 7 handwriting-style, 6 phone-photo style (tilt, blur, shadow, noise).
- **30 Indic (15 Hindi + 15 Marathi):** 5 printed, 5 handwritten and 5 phone-photo style
  per language. Complaints, labels, allergies and advice are in Devanagari, and on 13 of them the
  medicine names are written in Devanagari too (e.g. "डोलो 650").
- Each one has a printed "Specialist in: ..." list on the letterhead that must **not** be extracted as
  symptoms.

**Results on the 30 Indic prescriptions (56 medicines):**

| | Gemini only | Hybrid (Sarvam OCR + Gemini) |
|---|---|---|
| **Medicine exact-match accuracy** | 89.3% (50 / 56) | **91.1%** (51 / 56) |
| Medicine F1 (close spelling counts) | 89.3% | **92.9%** |
| Made-up medicines | 6 | **4** |
| Symptoms found | **100%** | 96.7% |
| Medicine strength / frequency | 100% / 100% | 100% / 100% |
| Visit date, vitals, doctor name, allergies | 100% | 100% |

**Speed (all 50 prescriptions):** Gemini only **2.3s** median, hybrid **3.8s** (1.6x slower, it makes two calls).
On the 20 English prescriptions both engines scored 100%, and neither took letterhead text for symptoms.

Every miss was a medicine name written in Devanagari and read with one wrong letter, for example
"Sital" for "Cital" or "Bicozules" for "Becosules". The hybrid's lead is 1 medicine out of 56, and LLM
output varies a little between runs, so read it as "slightly better on Indic scripts in this run",
not as a large gap. The images use clean fonts, so these numbers are an upper bound - real doctor
handwriting is harder.

**How the numbers are measured**
- **Exact-match accuracy** - the share of the real medicines whose name was read exactly right (small
  differences like "Tab." or the strength are ignored, a changed letter is not).
- **F1** - also counts a close spelling as a match, and counts medicines that were made up.
- **Median time** - measured for every request when it ran, not estimated.

### Running the evaluations

```bash
cd ai_service

python evaluate_rag.py                 # RAG: retrieval + answers + LLM judge
python evaluate.py                     # extraction: both engines on all 50 prescriptions

python evaluate_rag.py --rescore       # recompute numbers from saved results, no API calls
python evaluate.py --rescore
```

The scripts read the test data from `ai_service/eval_data/ocr` and `eval_data/rag` and save results in `ai_service/eval_data/results/` (none of these are in git). On the Gemini free tier the judge can hit its daily
limit; run `python evaluate_rag.py --judge-only` later to grade the answers that are left.

## Project structure

```
MF_Health/
├── ai_service/                  # FastAPI - extraction, RAG chat, drug interactions
│   ├── main.py                  # endpoints, Gemini / hybrid extraction, auth
│   ├── rag_chain.py             # embeddings, retrieval (MMR + date-aware), chat
│   ├── evaluate.py              # extraction evaluation
│   ├── evaluate_rag.py          # RAG evaluation
│   └── eval_data/
│       ├── ocr/  rag/           # the test sets (not in git)
│       └── results/             # saved evaluation results (not in git)
├── backend/                     # Django - auth, records, allergy checks, share links
│   └── api/                     # models, views, urls, tests, reembed_records command
└── frontend/                    # React (Vite + Tailwind)
    └── src/components/          # dashboard, upload, chat, shared report
```

## Tech stack

- **AI:** Gemini (`gemini-3.5-flash-lite` with fallback models), `gemini-embedding-001`, Sarvam AI OCR
- **RAG:** LangChain, pgvector on Supabase (Chroma locally when there is no database)
- **Backend:** Django + DRF (JWT auth), FastAPI
- **Frontend:** React, Vite, Tailwind, Recharts
- **Hosting:** Render (backends), Vercel (frontend), Supabase (Postgres)

## Security

- The AI service takes the user from the Django JWT, never from the request body.
- Django → AI service calls (embedding, deleting, interaction checks) need a shared `X-Internal-Key`.
- Rate limits are per logged-in user: extraction 5/min, chat 10/min, streaming chat 20/min, doctor comparison 5/min.
- Share links expire after 7 days and can be turned off; the QR code is generated in the browser.

## Setup

You need two `.env` files.

**ai_service/.env**
```
GENAI_API_KEY=your-gemini-key
SARVAM_API_KEY=your-sarvam-key
JWT_SECRET_KEY=same-value-as-django-SECRET_KEY
INTERNAL_API_KEY=any-long-random-string
DATABASE_URL=                     # leave empty to use local Chroma + a JSON file for chat history
```

**backend/.env**
```
SECRET_KEY=your-django-secret
DEBUG=True
INTERNAL_API_KEY=same-value-as-in-ai_service
DATABASE_URL=                     # leave empty to use SQLite
```

`DEBUG` is off unless set to `True`, and with `DEBUG` off Django won't start without a `SECRET_KEY`.

Run each service:

```bash
# backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver

# ai service
cd ai_service
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --port 8001

# frontend
cd frontend
npm install
npm run dev
```

If some records are missing from the chatbot (for example the AI service was asleep when they were saved),
run `python manage.py reembed_records` in `backend/`.

## API

**Django (port 8000)**
- `POST /api/auth/register/`, `POST /api/auth/login/`, `POST /api/auth/refresh/`, `GET /api/auth/profile/`
- `GET / POST /api/save_record/` - list / save records, `DELETE /api/save_record/?id=<id>` - delete
- `POST /api/share/generate/` - create share link, `DELETE /api/share/generate/` - turn it off
- `GET /api/share/<token>/` - view a shared report

**FastAPI (port 8001)** - need the Django JWT (`Authorization: Bearer <token>`)
- `POST /extract_data?engine=gemini|hybrid&language=hi-IN` - read a prescription
- `POST /chat`, `POST /chat/stream`, `POST /chat/clear` - chatbot
- `POST /compare_doctors` - compare two doctors' treatments
- `GET /health`, `GET /stats`

Internal (Django only, `X-Internal-Key`): `POST /embed_record`, `POST /delete_record`, `POST /check_interactions`

License: MIT

---

## Summary

**HealthScribe | Django, FastAPI, React, LangChain, pgvector, Gemini, Sarvam AI, Supabase | Demo**

- Built a full-stack medical records platform that digitizes handwritten prescriptions through a hybrid OCR pipeline (Gemini vision for English, Sarvam OCR + Gemini for Indic scripts), plus a LangChain RAG assistant with intent routing, date-aware retrieval and grounded refusals over each patient's records.
- Benchmarked Gemini-only extraction against a Sarvam OCR + Gemini hybrid on 50 English, Hindi and Marathi prescriptions across 6 clinical fields: 89.3% vs. 91.1% exact-match accuracy on Indic-script medicines, with the hybrid 1.6x slower (3.8s vs. 2.3s).
- Benchmarked MMR retrieval (λ = 0.7) against semantic similarity search on 70 queries: 92% vs. 90% accuracy (86% vs. 79% on multi-step queries), 44% less redundant context; 100% faithfulness (LLM-as-a-judge).
- Implemented allergy-drug conflict alerts, LLM-based drug-interaction checks, multi-doctor treatment comparison, and a shareable QR-based health profile.
