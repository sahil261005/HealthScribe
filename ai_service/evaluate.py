import os
import json
import requests
import time
from difflib import SequenceMatcher

# Base directory path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Correct ground-truth answers from the prescription images (manually typed out).
# We score medicines/symptoms individually to get detailed percentages.
ground_truths = [
    {
        "id": 1,
        "doctor_name": "Dr. Akshara",
        "symptoms": ["fever", "headache"],
        "medicines": [
            {"name": "ABCIXIMAB", "dosage": "morning"},
            {"name": "VOMILAST", "dosage": "morning"},
            {"name": "ZOCLAR", "dosage": "morning"},
            {"name": "GESTAKIND", "dosage": "night"},
        ],
    },
    {
        "id": 2,
        "doctor_name": "Dr. Darshan Singh Bhakuni",
        "symptoms": ["tightness of skin", "ulcers"],
        "medicines": [
            {"name": "Linezolid", "dosage": "twice a day"},
            {"name": "Clopidogrel", "dosage": "once a day"},
            {"name": "Amlodipine", "dosage": "once a day"},
            {"name": "Domperidone", "dosage": "twice a day"},
            {"name": "Omeprazole", "dosage": "twice a day"},
            {"name": "Bosentan", "dosage": "twice a day"},
            {"name": "Sildinafil", "dosage": "twice a day"},
            {"name": "Prednisolone", "dosage": "once a day"},
            {"name": "Mycophenolate", "dosage": "twice a day"},
            {"name": "ciprofloxacin", "dosage": "twice a day"},
        ],
    },
]


def fuzzy_match(a, b, threshold=0.7):
    # Matches words even if they have minor typos (e.g. ABCXIMAB vs ABCIXIMAB)
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() >= threshold


def check_medicine_in_pred(gt_name, pred_meds):
    # Helper to check if a medicine is present in the predicted list
    exact_match = False
    fuzzy_matched = False
    dosage = ""
    
    for pm in pred_meds:
        pm_name = pm.get("name", "").lower()
        pm_dose = pm.get("dosage", "").lower()

        # Clean off prefixes like tab, cap, syp
        words = pm_name.replace(".", " ").split()
        prefixes = {"tab", "cap", "tablet", "tablets", "capsule", "capsules", "syp", "inj"}
        clean_words = [w for w in words if w not in prefixes]

        # Match single words
        for w in clean_words:
            if gt_name.lower() == w.lower():
                exact_match = True
                fuzzy_matched = True
                dosage = pm_dose
                return exact_match, fuzzy_matched, dosage
            elif fuzzy_match(gt_name, w):
                fuzzy_matched = True
                dosage = pm_dose

        # Match full cleaned string for multi-word drug names
        full_clean = " ".join(clean_words)
        if gt_name.lower() == full_clean.lower():
            exact_match = True
            fuzzy_matched = True
            dosage = pm_dose
            return exact_match, fuzzy_matched, dosage
        elif fuzzy_match(gt_name, full_clean):
            fuzzy_matched = True
            dosage = pm_dose

    return exact_match, fuzzy_matched, dosage


def run_eval(engine_name):
    doc_total = 0
    doc_matches = 0

    med_total = 0
    med_exact_matches = 0
    med_fuzzy_matches = 0

    dose_total = 0
    dose_matches = 0

    sym_total = 0
    sym_matches = 0

    total_time = 0.0

    for gt in ground_truths:
        tc_id = gt["id"]
        image_path = f"eval_data/images/prescription_{tc_id}.png"

        max_retries = 3
        delay = 10

        for attempt in range(max_retries):
            try:
                # Sleep to avoid hitting local/global API rate limits (5 requests per min max)
                time.sleep(15)

                with open(image_path, "rb") as img:
                    files = {"uploaded_file": (f"prescription_{tc_id}.png", img, "image/png")}
                    start_t = time.time()
                    r = requests.post(
                        f"http://localhost:8001/extract_data?engine={engine_name}",
                        files=files,
                        timeout=180,
                    )
                    end_t = time.time()

                if r.status_code == 200:
                    pred = r.json()
                    print(f"\n[{engine_name}] Extracted JSON for prescription_{tc_id}:")
                    print(json.dumps(pred, indent=2))

                    pred_meds = pred.get("medicines", [])
                    pred_syms = [s.lower() for s in pred.get("symptoms", [])]
                    pred_doc = pred.get("doctor_name", "").lower()

                    # 1. Check doctor name
                    doc_total += 1
                    gt_doc = gt["doctor_name"].lower()
                    if gt_doc in pred_doc or pred_doc in gt_doc or fuzzy_match(gt_doc, pred_doc):
                        doc_matches += 1

                    # 2. Check symptoms
                    for gt_sym in gt["symptoms"]:
                        sym_total += 1
                        for ps in pred_syms:
                            if gt_sym.lower() in ps or fuzzy_match(gt_sym, ps):
                                sym_matches += 1
                                break

                    # 3. Check medicines & dosages
                    for gt_med in gt["medicines"]:
                        med_total += 1
                        dose_total += 1

                        exact_match, fuzzy_match_found, matched_dose = check_medicine_in_pred(
                            gt_med["name"], pred_meds
                        )

                        if exact_match:
                            med_exact_matches += 1
                        if fuzzy_match_found:
                            med_fuzzy_matches += 1
                            # Dosage check: ground truth keyword appears in predicted dosage
                            gt_dose_kw = gt_med["dosage"].lower()
                            if gt_dose_kw in matched_dose or fuzzy_match(gt_dose_kw, matched_dose):
                                dose_matches += 1

                    total_time += (end_t - start_t)
                    break

                else:
                    print(f"Error status code {r.status_code} for prescription {tc_id}")
                    # Parse error details for rate limits
                    try:
                        err_detail = r.json().get("detail", "")
                    except Exception:
                        err_detail = r.text

                    if "429" in err_detail or "quota" in err_detail.lower() or "limit" in err_detail.lower():
                        sleep_time = delay
                        if "retry in" in err_detail:
                            try:
                                part = err_detail.split("retry in")[1].strip()
                                seconds_str = part.split("s")[0].strip()
                                sleep_time = int(float(seconds_str)) + 2
                            except Exception:
                                pass
                        print(f"Rate limit hit. Sleeping {sleep_time}s before retrying...")
                        time.sleep(sleep_time)
                        delay *= 2
                    else:
                        break

            except Exception as e:
                print(f"Error on prescription_{tc_id}: {e}")
                time.sleep(delay)
                delay *= 2

    # Calculate final percentages
    num_prescriptions = len(ground_truths)

    def pct(matches, total):
        if total == 0:
            return "N/A"
        return f"{round((matches / total) * 100)}%"

    return {
        "doctor": pct(doc_matches, doc_total),
        "med_exact": pct(med_exact_matches, med_total),
        "med_fuzzy": pct(med_fuzzy_matches, med_total),
        "dosages": pct(dose_matches, dose_total),
        "symptoms": pct(sym_matches, sym_total),
        "latency": f"{round(total_time / num_prescriptions, 1)}s",
    }


print("\nRunning evaluation on hybrid pipeline...")
hybrid_scores = run_eval("hybrid")

print("Running evaluation on Gemini-only pipeline...")
gemini_scores = run_eval("gemini")

# Print results to console
print("\nEvaluation completed!")
print(f"Doctor Name Accuracy | Hybrid: {hybrid_scores['doctor']:>4} | Gemini: {gemini_scores['doctor']:>4}")
print(f"Medicines (Exact)    | Hybrid: {hybrid_scores['med_exact']:>4} | Gemini: {gemini_scores['med_exact']:>4}")
print(f"Medicines (Fuzzy)    | Hybrid: {hybrid_scores['med_fuzzy']:>4} | Gemini: {gemini_scores['med_fuzzy']:>4}")
print(f"Dosages Accuracy     | Hybrid: {hybrid_scores['dosages']:>4} | Gemini: {gemini_scores['dosages']:>4}")
print(f"Symptoms Accuracy    | Hybrid: {hybrid_scores['symptoms']:>4} | Gemini: {gemini_scores['symptoms']:>4}")
print(f"Average Latency      | Hybrid: {hybrid_scores['latency']:>4} | Gemini: {gemini_scores['latency']:>4}\n")

# Format markdown table
markdown_table = f"""| Field | Sarvam+Gemini | Gemini Only |
| :--- | :---: | :---: |
| **Doctor Name Accuracy** | {hybrid_scores['doctor']} | {gemini_scores['doctor']} |
| **Medicines Accuracy (Exact Match)** | {hybrid_scores['med_exact']} | {gemini_scores['med_exact']} |
| **Medicines Accuracy (Fuzzy Match)** | {hybrid_scores['med_fuzzy']} | {gemini_scores['med_fuzzy']} |
| **Dosages Accuracy** | {hybrid_scores['dosages']} | {gemini_scores['dosages']} |
| **Symptoms Accuracy** | {hybrid_scores['symptoms']} | {gemini_scores['symptoms']} |
| **Average Latency** | {hybrid_scores['latency']} | {gemini_scores['latency']} |"""

# Write table to README.md
README_PATH = "../README.md"
if os.path.exists(README_PATH):
    print("Updating README.md with scores...")
    with open(README_PATH, "r") as f:
        
        content = f.read()

    import re
    # Replace the table block even if column headers changed
    table_pattern = r"\| Field \|.*?(?=\n\n|\Z)"

    if re.search(table_pattern, content, re.DOTALL):
        updated = re.sub(table_pattern, markdown_table, content, flags=re.DOTALL)
        with open(README_PATH, "w") as f:
            f.write(updated)
        print("README.md successfully updated!")
    else:
        print("Placeholder table not found in README.md.")
else:
    print("README.md not found.")
