# RAG evaluation for the HealthScribe chatbot
#
# Compares two ways of finding the records a question needs:
#   - similarity search (plain semantic search)
#   - MMR, lambda = 0.7 (what the app uses) - like similarity, but skips near-duplicate records
#
# Steps:
#   1. load the synthetic patient records (eval_data/rag/records.json) into a temporary
#      vector store with the real embed_medical_record() from rag_chain.py
#   2. retrieval check: for every question, did we fetch the right record? how many of the
#      fetched records were duplicates? did anything from another patient leak in?
#   3. answer check: ask every question through the real chat_with_rag() and check in code
#      that the answer has the expected facts (or says "I don't have that" when it should)
#   4. LLM-as-a-judge: a bigger gemini model checks that every fact in the answer comes from
#      the records (faithfulness)
#   5. print the summary and save everything to eval_data/results/rag_results.json
#
# The data is synthetic (eval_data/rag), nothing here touches the real database.
#
# usage:
#   python evaluate_rag.py                full run (retrieval + answers + judge)
#   python evaluate_rag.py --no-judge     skip the judge (it has a small free tier limit)
#   python evaluate_rag.py --judge-only   run the judge later on the saved answers
#   python evaluate_rag.py --rescore      recompute the numbers from the saved results, no API calls

import argparse
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime

# never touch the real database, even if DATABASE_URL is set in .env
os.environ["DATABASE_URL"] = ""

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import rag_chain  # noqa: E402
import google.generativeai as genai  # noqa: E402
from langchain_core.embeddings import Embeddings  # noqa: E402

DATA_DIR = os.path.join(BASE_DIR, "eval_data", "rag")
RESULTS_PATH = os.path.join(BASE_DIR, "eval_data", "results", "rag_results.json")
# embeddings are saved here so a second run doesn't call the API again (not committed)
EMBED_CACHE_PATH = os.path.join(BASE_DIR, "eval_data", "results", ".embedding_cache.json")

# retrieval-only check (no LLM calls): similarity vs MMR with a few lambda values
RETRIEVAL_SETUPS = {
    "similarity": {"search_type": "similarity", "lambda_mult": 0.7},
    "mmr λ=0.3": {"search_type": "mmr", "lambda_mult": 0.3},
    "mmr λ=0.5": {"search_type": "mmr", "lambda_mult": 0.5},
    "mmr λ=0.7": {"search_type": "mmr", "lambda_mult": 0.7},
}
# the two setups that go through the full chatbot ("mmr" = what the app uses)
ANSWER_SETUPS = {
    "similarity": {"search_type": "similarity", "lambda_mult": 0.7},
    "mmr": {"search_type": "mmr", "lambda_mult": 0.7},
}
TOP_K = 5

# a bigger model than the chat model (gemini-3.5-flash-lite) grades the answers
JUDGE_MODELS = ["gemini-3-flash-preview", "gemini-3.8-flash", "gemini-3.7-flash"]

REFUSAL_PHRASES = [
    "don't have", "do not have", "not in your records", "no record", "no information",
    "couldn't find", "could not find", "not able to find", "doesn't mention", "does not mention",
    "isn't in your records", "is not in your records", "no mention", "not available in your records",
    "there is no", "there are no", "i don't see", "i do not see",
]


# ---------- step 1: records -> vector store ----------

class CachedEmbeddings(Embeddings):
    # the same text always gives the same embedding, so keep them in a file
    # (saves a lot of free tier quota when the eval runs more than once)
    def __init__(self, inner):
        self.inner = inner
        self.cache = {}
        if os.path.exists(EMBED_CACHE_PATH):
            with open(EMBED_CACHE_PATH) as f:
                self.cache = json.load(f)

    def save(self):
        os.makedirs(os.path.dirname(EMBED_CACHE_PATH), exist_ok=True)
        with open(EMBED_CACHE_PATH, "w") as f:
            json.dump(self.cache, f)

    def embed_documents(self, texts):
        missing = [t for t in texts if "doc:" + t not in self.cache]
        if missing:
            for t, vector in zip(missing, self.inner.embed_documents(missing)):
                self.cache["doc:" + t] = vector
        return [self.cache["doc:" + t] for t in texts]

    def embed_query(self, text):
        if "query:" + text not in self.cache:
            self.cache["query:" + text] = self.inner.embed_query(text)
        return self.cache["query:" + text]


def load_json(name):
    with open(os.path.join(DATA_DIR, name)) as f:
        return json.load(f)


def build_vector_store(records):
    # a fresh temporary chroma store, filled with the same function the app uses
    rag_chain.CHROMA_DIR = tempfile.mkdtemp(prefix="healthscribe_rag_eval_")
    rag_chain._vectorstore_cache = None
    rag_chain.embeddings_model = CachedEmbeddings(rag_chain.get_embeddings_model())
    # no chat history during the eval, every question is asked fresh
    rag_chain.add_message = lambda *args, **kwargs: None
    rag_chain.chat_histories = {}

    print(f"embedding {len(records)} records...")
    for r in records:
        for attempt in range(5):
            ok = rag_chain.embed_medical_record(
                record_id=r["record_id"], user_id=r["user_id"], category=r["category"],
                doctor_name=r["doctor_name"], upload_date=r["upload_date"], symptoms=r["symptoms"],
                medicines=r["medicines"], vitals=r["vitals"], allergies=r["allergies"],
            )
            if ok:
                break
            time.sleep(15 * (attempt + 1))  # probably rate limited, wait and try again
        else:
            raise RuntimeError(f"could not embed record {r['record_id']}")
    rag_chain.embeddings_model.save()
    return rag_chain.get_vectorstore()


# ---------- step 2: retrieval check ----------

def same_content(record):
    # two records "say the same thing" if they have the same symptoms and medicines
    return (tuple(sorted(record["symptoms"])), tuple(sorted(m["name"] for m in record["medicines"])))


def check_retrieval(question, retrieved_ids, records_by_id):
    relevant = set(question["relevant_record_ids"])
    contents = [same_content(records_by_id[i]) for i in retrieved_ids]
    row = {
        # a record from another patient = data leak
        "leaked": any(records_by_id[i]["user_id"] != question["user_id"] for i in retrieved_ids),
        # share of fetched records that repeat one already fetched
        "redundancy": (len(contents) - len(set(contents))) / len(contents) if contents else 0.0,
    }
    if relevant:
        row["hit"] = any(i in relevant for i in retrieved_ids)
    return row


# ---------- step 3: answer check ----------

def fact_found(fact, answer):
    # facts are a list of accepted spellings, a date, or a number (e.g. "3" or "three")
    a = answer.lower()
    if isinstance(fact, dict) and fact.get("type") == "number":
        return any(re.search(rf"\b{w}\b", a) for w in fact["words"])
    if isinstance(fact, dict) and fact.get("type") == "date":
        month_ok = fact["month"] in a or fact["month"][:3] in a
        day_ok = re.search(rf"\b0?{fact['day']}(st|nd|rd|th)?\b", a) is not None
        return month_ok and day_ok
    return any(option in a for option in fact)


def is_refusal(answer):
    a = answer.lower().replace("’", "'")
    return any(p in a for p in REFUSAL_PHRASES)


def ask_chatbot(question, setup):
    # the real chatbot function, retried if gemini is rate limiting us
    for attempt in range(4):
        start = time.time()
        result = rag_chain.chat_with_rag(
            user_id=question["user_id"], question=question["question"],
            search_type=setup["search_type"], k=TOP_K, lambda_mult=setup["lambda_mult"],
        )
        if "answer" in result:
            return result["answer"], round(time.time() - start, 2)
        print(f"    chat failed, retrying...")
        time.sleep(20 * (attempt + 1))
    return None, None


# ---------- step 4: LLM-as-a-judge ----------

def reference_answer(question):
    # what a correct answer has to contain, written out for the judge
    if not question["answerable"]:
        return "The information is NOT in the patient's records, so the answer must say it is not available."
    parts = []
    for fact in question["expected_facts"]:
        if isinstance(fact, dict) and fact.get("type") == "number":
            parts.append(f"the number {fact['value']}")
        elif isinstance(fact, dict):
            parts.append(f"the date {fact['month'].title()} {fact['day']}")
        else:
            parts.append(" / ".join(fact))
    return "The answer must mention: " + "; ".join(parts)


def judge(question, context, answer):
    # faithful = every fact in the answer is in the records the chatbot was given
    # correct  = the answer matches the reference (checked without the records)
    prompt = f"""You are grading a medical records chatbot. Be strict and answer two separate questions.

QUESTION ASKED: {question['question']}
CHATBOT ANSWER: {answer}

CHECK 1 - FAITHFULNESS. These are the records the chatbot was given:
{context}
"faithful" is true if every fact in the answer (values, dates, medicines, doctors) appears in these records.
Saying the information is not available counts as faithful. Greetings and polite phrases don't count as facts.

CHECK 2 - CORRECTNESS. Ignore the records above for this check. Reference:
{reference_answer(question)}
"correct" is true only if the answer contains everything in the reference (numbers and dates must match exactly).
Extra correct details are fine.

Return JSON: {{"faithful": true/false, "correct": true/false, "reason": "one short sentence"}}"""

    # try the judge models in order, moving on when one is rate limited
    for attempt in range(6):
        model_name = JUDGE_MODELS[attempt % len(JUDGE_MODELS)]
        try:
            response = genai.GenerativeModel(model_name).generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json", "temperature": 0},
                request_options={"timeout": 90},
            )
            data = json.loads(response.text)
            time.sleep(4)  # free tier only allows a few requests a minute
            return {"faithful": bool(data.get("faithful")), "correct": bool(data.get("correct")),
                    "reason": data.get("reason", ""), "judge_model": model_name}
        except Exception as e:
            print(f"    judge {model_name} failed: {str(e)[:80]}")
            time.sleep(10)
    return None


def record_context(record_ids, records_by_id):
    # the exact text the chatbot saw for these records
    texts = []
    for i in record_ids:
        r = records_by_id[i]
        texts.append(rag_chain.build_record_text(r["category"], r["doctor_name"], r["upload_date"], r["symptoms"],
                                                 r["medicines"], r["vitals"], r["allergies"]))
    return "\n\n---\n\n".join(texts)


def judge_saved_answers(results, records_by_id):
    # grades the "mmr" answers (what the app uses) that don't have a grade yet
    todo = [q for q in results["questions"] if q["answers"].get("mmr", {}).get("answer") and not q["answers"]["mmr"].get("judge")]
    print(f"judging {len(todo)} answers...")
    for n, q in enumerate(todo, 1):
        row = q["answers"]["mmr"]
        row["judge"] = judge(q, record_context(row["retrieved"], records_by_id), row["answer"])
        print(f"  [{n}/{len(todo)}] {q['id']} -> {row['judge'] and (row['judge']['faithful'], row['judge']['correct'])}")
        save(results)  # save after every answer, so nothing is lost if the quota runs out


# ---------- step 5: summary ----------

def pct(values):
    values = [v for v in values if v is not None]
    return round(100 * sum(values) / len(values), 1) if values else None


def summarize(results):
    summary = {"retrieval": {}, "answers": {}}

    for name, rows in results["retrieval_rows"].items():
        summary["retrieval"][name] = {
            "hit_rate": pct([r["hit"] for r in rows if "hit" in r]),
            "redundancy": pct([r["redundancy"] for r in rows]),
            "leaks": sum(1 for r in rows if r["leaked"]),
            "queries": len(rows),
        }

    for name in ANSWER_SETUPS:
        rows = [(q, q["answers"][name]) for q in results["questions"] if q["answers"].get(name, {}).get("answer")]
        answerable = [(q, a) for q, a in rows if q["answerable"]]
        should_refuse = [(q, a) for q, a in rows if not q["answerable"]]
        judged = [(q, a) for q, a in rows if a.get("judge")]
        by_difficulty = {}
        for q, a in answerable:
            by_difficulty.setdefault(q["difficulty"], []).append(a["all_facts_found"])
        latencies = sorted(a["latency_s"] for q, a in rows)

        summary["answers"][name] = {
            "accuracy": pct([a["all_facts_found"] for q, a in answerable]),
            "accuracy_by_difficulty": {d: pct(v) for d, v in sorted(by_difficulty.items())},
            "correct_refusals": pct([a["refused"] for q, a in should_refuse]),
            "wrong_refusals": sum(1 for q, a in answerable if a["refused"]),
            "judged": len(judged),
            "faithfulness": pct([a["judge"]["faithful"] for q, a in judged]),
            # how often the judge agrees with the plain code checks (tells us if the judge can be trusted)
            "judge_agrees_with_code": pct([
                a["judge"]["correct"] == (a["all_facts_found"] if q["answerable"] else a["refused"]) for q, a in judged
            ]),
            "latency_p50_s": latencies[len(latencies) // 2] if latencies else None,
        }
    results["summary"] = summary


def print_summary(results):
    s = results["summary"]
    print("\n=== Retrieval (top 5 records) ===")
    for name, r in s["retrieval"].items():
        print(f"  {name:12} hit rate {r['hit_rate']}%   redundancy {r['redundancy']}%   leaks {r['leaks']}/{r['queries']}")
    print("\n=== Answers ===")
    for name, a in s["answers"].items():
        print(f"  {name:12} accuracy {a['accuracy']}%   by difficulty {a['accuracy_by_difficulty']}")
        print(f"  {'':12} correct refusals {a['correct_refusals']}%   wrong refusals {a['wrong_refusals']}   p50 {a['latency_p50_s']}s")
        if a["judged"]:
            print(f"  {'':12} faithfulness {a['faithfulness']}% (LLM judge, {a['judged']} answers)   "
                  f"judge agrees with code checks {a['judge_agrees_with_code']}%")


def save(results):
    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=1, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-judge", action="store_true", help="skip the LLM judge")
    parser.add_argument("--judge-only", action="store_true", help="only run the judge on the saved answers")
    parser.add_argument("--rescore", action="store_true", help="recompute the numbers from the saved results")
    args = parser.parse_args()

    records = load_json("records.json")
    records_by_id = {r["record_id"]: r for r in records}

    if args.rescore or args.judge_only:
        with open(RESULTS_PATH) as f:
            results = json.load(f)
        if args.judge_only:
            genai.configure(api_key=rag_chain.GEMINI_API_KEY)
            judge_saved_answers(results, records_by_id)
        summarize(results)
        save(results)
        print_summary(results)
        return

    genai.configure(api_key=rag_chain.GEMINI_API_KEY)
    questions = load_json("questions.json")

    # step 1
    store = build_vector_store(records)

    # step 2: retrieval only, no LLM calls
    print("checking retrieval...")
    retrieval_rows = {name: [] for name in RETRIEVAL_SETUPS}
    for q in questions:
        for name, setup in RETRIEVAL_SETUPS.items():
            docs = rag_chain.retrieve_records(store, q["question"], q["user_id"],
                                              setup["search_type"], TOP_K, setup["lambda_mult"])
            ids = [d.metadata["record_id"] for d in docs]
            retrieval_rows[name].append(check_retrieval(q, ids, records_by_id) | {"id": q["id"], "retrieved": ids})
    rag_chain.embeddings_model.save()

    # step 3: full answers through the real chatbot
    results = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": {"records": len(records), "patients": len({r["user_id"] for r in records}), "questions": len(questions)},
        "chat_model": rag_chain.FALLBACK_CHAT_MODELS[0],
        "retrieval_rows": retrieval_rows,
        "questions": [],
    }
    for n, q in enumerate(questions, 1):
        print(f"[{n}/{len(questions)}] {q['question']}")
        entry = {k: q[k] for k in ("id", "user_id", "type", "difficulty", "question", "answerable", "expected_facts")}
        entry["answers"] = {}
        for name, setup in ANSWER_SETUPS.items():
            docs = rag_chain.retrieve_records(store, q["question"], q["user_id"],
                                              setup["search_type"], TOP_K, setup["lambda_mult"])
            answer, latency = ask_chatbot(q, setup)
            row = {"retrieved": [d.metadata["record_id"] for d in docs], "answer": answer, "latency_s": latency}
            if answer is not None:
                row["all_facts_found"] = all(fact_found(f, answer) for f in q["expected_facts"])
                row["refused"] = is_refusal(answer)
            entry["answers"][name] = row
            time.sleep(2)
        results["questions"].append(entry)
    save(results)

    # step 4
    if not args.no_judge:
        judge_saved_answers(results, records_by_id)

    # step 5
    summarize(results)
    save(results)
    print_summary(results)


if __name__ == "__main__":
    main()
