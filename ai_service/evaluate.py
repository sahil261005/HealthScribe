# Extraction evaluation for HealthScribe: Gemini-only vs. Sarvam OCR + Gemini (hybrid)
#
# Steps:
#   1. load the 50 synthetic prescriptions (eval_data/ocr/images) and the right answers for each
#      one (eval_data/ocr/ground_truth.json)
#   2. send every prescription through the real /extract_data endpoint (same code as the app,
#      called in-process) with both engines, and save the raw output + time taken
#   3. compare each output with the ground truth: medicines (exact name + close match), dosage, symptoms, doctor,
#      visit date, vitals, allergies, and count anything that was made up
#   4. print a summary per language (english / hindi / marathi / indic = hindi+marathi) and per image type
#      (printed / handwritten / photo), and save it to eval_data/results/ocr_results.json
#
# usage:
#   python evaluate.py              run both engines on all prescriptions
#   python evaluate.py --resume     continue a run that stopped (e.g. API limit)
#   python evaluate.py --rescore    recompute the numbers from the saved outputs, no API calls

import argparse
import json
import os
import re
import secrets
import statistics
import sys
import time
from datetime import datetime
from difflib import SequenceMatcher

# never touch the real database during the eval
os.environ["DATABASE_URL"] = ""
# throwaway login secret just for this process, so we can call the protected endpoint
os.environ["JWT_SECRET_KEY"] = secrets.token_urlsafe(32)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import jwt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402

OCR_DIR = os.path.join(BASE_DIR, "eval_data", "ocr")
RAW_PATH = os.path.join(BASE_DIR, "eval_data", "results", "ocr_raw.json")
RESULTS_PATH = os.path.join(BASE_DIR, "eval_data", "results", "ocr_results.json")

ENGINES = ["gemini", "hybrid"]
LANGUAGES = {"en": "english", "hi": "hindi", "mr": "marathi"}
SARVAM_LANGUAGE = {"en": "en-IN", "hi": "hi-IN", "mr": "mr-IN"}  # language code sarvam gets in the hybrid
IMAGE_TYPES = ["printed", "handwritten", "photo"]


# ---------- step 2: run the extraction ----------

def make_token():
    now = int(time.time())
    payload = {"token_type": "access", "user_id": 1, "iat": now, "exp": now + 6 * 3600, "jti": "eval"}
    return jwt.encode(payload, os.environ["JWT_SECRET_KEY"], algorithm="HS256")


def save_raw(raw):
    os.makedirs(os.path.dirname(RAW_PATH), exist_ok=True)
    with open(RAW_PATH, "w") as f:
        json.dump(raw, f, indent=1, ensure_ascii=False)


def run_extraction(prescriptions, resume):
    main.limiter.enabled = False  # the rate limit is for real users, the eval paces itself
    client = TestClient(main.app)
    headers = {"Authorization": f"Bearer {make_token()}"}

    raw = {}
    if resume and os.path.exists(RAW_PATH):
        with open(RAW_PATH) as f:
            raw = json.load(f)

    for engine in ENGINES:
        raw.setdefault(engine, {})
        print(f"\n{engine}")
        for n, rx in enumerate(prescriptions, 1):
            if raw[engine].get(rx["id"], {}).get("status") == 200:
                continue  # already done (when resuming)
            with open(os.path.join(OCR_DIR, "images", f"{rx['id']}.jpg"), "rb") as f:
                image = f.read()
            language = SARVAM_LANGUAGE[rx["language"]]

            for attempt in range(4):
                start = time.time()
                resp = client.post(f"/extract_data?engine={engine}&language={language}",
                                   files={"uploaded_file": (f"{rx['id']}.jpg", image, "image/jpeg")},
                                   headers=headers)
                result = {"status": resp.status_code, "latency_s": round(time.time() - start, 2),
                          "output": resp.json() if resp.status_code == 200 else None}
                if resp.status_code == 200:
                    break
                print(f"  {rx['id']} failed with {resp.status_code}, retrying...")
                time.sleep(30 * (attempt + 1))

            raw[engine][rx["id"]] = result
            save_raw(raw)  # save after every prescription so nothing is lost
            print(f"  [{n}/{len(prescriptions)}] {rx['id']} {result['latency_s']}s")
            time.sleep(5)  # stay under the gemini free tier per-minute limit
    return raw


# ---------- step 3: compare with the ground truth ----------

FORM_WORDS = {"tab", "tablet", "cap", "capsule", "syp", "syrup", "inj", "injection"}


def clean_med_name(name):
    # "Tab. Dolo 650mg" -> "dolo",  "Tab Zerodol-SP" -> "zerodol sp"
    text = name.lower().replace(".", " ").replace("-", " ")
    text = re.sub(r"\b\d+(\.\d+)?\s*(mg|mcg|ml|g|iu)\b", " ", text)
    return " ".join(w for w in text.split() if w not in FORM_WORDS and not w.isdigit())


def squash(text):
    return re.sub(r"\s+", "", (text or "").lower())


def match_medicines(true_meds, found_meds):
    # pair each real medicine with the closest extracted one (small spelling differences are ok)
    found_names = [clean_med_name(m.get("name", "")) for m in found_meds]
    used = set()
    pairs = []
    for med in true_meds:
        target = clean_med_name(med["name"])
        best, best_score = None, 0
        for i, name in enumerate(found_names):
            if i in used or not name:
                continue
            score = 1.0 if (name == target or target in name.split() or name.startswith(target)) \
                else SequenceMatcher(None, name, target).ratio()
            if score > best_score:
                best, best_score = i, score
        if best is not None and best_score >= 0.85:
            used.add(best)
            pairs.append((med, found_meds[best], best_score == 1.0))
    made_up = len(found_meds) - len(used)
    return pairs, made_up


def text_matches(a, b):
    a, b = a.lower().strip(), b.lower().strip()
    return a == b or a in b or b in a


def symptom_matches(true_symptom, found, synonyms):
    # hindi / marathi complaints come back translated, so accept the usual english words for them
    return any(text_matches(option, found) for option in synonyms.get(true_symptom, [true_symptom]))


def score_prescription(truth, output):
    output = output or {}
    found_meds = [m for m in (output.get("medicines") or []) if isinstance(m, dict)]
    found_symptoms = [x for x in (output.get("symptoms") or []) if isinstance(x, str) and x.strip()]
    found_allergies = [x for x in (output.get("allergies") or []) if isinstance(x, str) and x.strip()]
    vitals = output.get("vitals") or {}
    synonyms = truth.get("symptom_synonyms", {})

    pairs, made_up = match_medicines(truth["medicines"], found_meds)
    s = {
        "meds_true": len(truth["medicines"]), "meds_found": len(found_meds), "meds_matched": len(pairs),
        "meds_made_up": made_up,
        # name read exactly right (not just close enough)
        "meds_exact": sum(1 for _, _, exact in pairs if exact),
        "strength_total": 0, "strength_ok": 0, "frequency_ok": 0,
        "symptoms_true": len(truth["symptoms"]),
        "symptoms_matched": sum(1 for t in truth["symptoms"] if any(symptom_matches(t, f, synonyms) for f in found_symptoms)),
        # letterhead text like "Specialist in: Diabetes" taken as a patient symptom
        "letterhead_leaks": sum(1 for f in found_symptoms
                                if any(text_matches(sp, f) for sp in truth["letterhead_specialities"])
                                and not any(symptom_matches(t, f, synonyms) for t in truth["symptoms"])),
        "doctor_ok": truth["doctor_name"].split()[-1].lower() in (output.get("doctor_name") or "").lower(),
        "date_ok": (output.get("visit_date") or "") == truth["visit_date"],
        "vitals_total": len(truth["vitals"]),
        "vitals_ok": sum(1 for k, v in truth["vitals"].items() if v in str(vitals.get(k) or "").replace(" ", "")),
        "allergies_true": len(truth["allergies"]),
        "allergies_matched": sum(1 for a in truth["allergies"] if any(text_matches(a.split()[0], f) for f in found_allergies)),
    }
    for med, found, exact in pairs:
        text = squash(found.get("name", "") + " " + found.get("dosage", ""))
        if med["strength"]:
            s["strength_total"] += 1
            s["strength_ok"] += squash(med["strength"]) in text
        s["frequency_ok"] += squash(med["frequency"]) in text
    return s


# ---------- step 4: summary ----------

def pct(part, total):
    return round(100 * part / total, 1) if total else None


def summarize(scores, latencies):
    t = {k: sum(s[k] for s in scores) for k in scores[0]}
    precision = pct(t["meds_matched"], t["meds_found"])
    recall = pct(t["meds_matched"], t["meds_true"])
    return {
        "prescriptions": len(scores),
        "medicine_f1": round(2 * precision * recall / (precision + recall), 1) if precision and recall else 0.0,
        "medicine_exact_match": pct(t["meds_exact"], t["meds_true"]),
        "made_up_medicines": t["meds_made_up"],
        "strength_accuracy": pct(t["strength_ok"], t["strength_total"]),
        "frequency_accuracy": pct(t["frequency_ok"], t["meds_matched"]),
        "symptom_accuracy": pct(t["symptoms_matched"], t["symptoms_true"]),
        "letterhead_leaks": t["letterhead_leaks"],
        "doctor_accuracy": pct(t["doctor_ok"], len(scores)),
        "date_accuracy": pct(t["date_ok"], len(scores)),
        "vitals_accuracy": pct(t["vitals_ok"], t["vitals_total"]),
        "allergy_accuracy": pct(t["allergies_matched"], t["allergies_true"]),
        "latency_p50_s": round(statistics.median(latencies), 2) if latencies else None,
    }


def score_all(raw, prescriptions):
    results = {}
    for engine in ENGINES:
        groups = {}
        failed = fell_back = 0
        for rx in prescriptions:
            result = raw[engine][rx["id"]]
            if result["status"] != 200:
                failed += 1
            elif engine == "hybrid" and not result["output"].get("ocr_engine", "").startswith("Sarvam"):
                fell_back += 1  # sarvam failed and the app quietly used gemini instead
            s = score_prescription(rx, result["output"])
            language = LANGUAGES[rx["language"]]
            names = [language, "overall"] + ([rx["tier"]] if language == "english" else ["indic"])
            for name in names:
                groups.setdefault(name, ([], []))
                groups[name][0].append(s)
                if result["status"] == 200:
                    groups[name][1].append(result["latency_s"])
        order = IMAGE_TYPES + list(LANGUAGES.values()) + ["indic", "overall"]
        results[engine] = {
            "failed_requests": failed,
            "hybrid_fell_back_to_gemini": fell_back,
            "groups": {name: summarize(*groups[name]) for name in order if name in groups},
        }
    return results


def print_summary(results):
    metrics = ["medicine_exact_match", "medicine_f1", "made_up_medicines", "strength_accuracy", "frequency_accuracy", "symptom_accuracy",
               "letterhead_leaks", "doctor_accuracy", "date_accuracy", "vitals_accuracy", "allergy_accuracy", "latency_p50_s"]
    for engine, data in results.items():
        groups = data["groups"]
        print(f"\n=== {engine} (failed requests: {data['failed_requests']}, fell back to gemini: {data['hybrid_fell_back_to_gemini']}) ===")
        print(f"{'':22}" + "".join(f"{name[:11]:>12}" for name in groups))
        for m in metrics:
            print(f"{m:22}" + "".join(f"{str(groups[name][m]):>12}" for name in groups))


def main_cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", action="store_true", help="continue a run that stopped")
    parser.add_argument("--rescore", action="store_true", help="recompute the numbers from the saved outputs")
    args = parser.parse_args()

    # step 1
    with open(os.path.join(OCR_DIR, "ground_truth.json")) as f:
        prescriptions = json.load(f)

    # step 2
    if args.rescore:
        with open(RAW_PATH) as f:
            raw = json.load(f)
    else:
        raw = run_extraction(prescriptions, args.resume)

    # steps 3 + 4
    results = {
        "scored_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": {"prescriptions": len(prescriptions),
                    "per_language": {name: sum(1 for p in prescriptions if p["language"] == code) for code, name in LANGUAGES.items()},
                    "medicines": sum(len(p["medicines"]) for p in prescriptions), "synthetic": True},
        "engines": score_all(raw, prescriptions),
    }
    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=1)
    print_summary(results["engines"])
    print(f"\nsaved to {RESULTS_PATH}")


if __name__ == "__main__":
    main_cli()
