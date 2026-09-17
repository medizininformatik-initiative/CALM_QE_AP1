import requests
import csv
from urllib.parse import urljoin, urlsplit, parse_qsl
import os
import sys
import time
import logging
import json
from utils import setup_logging, load_config, setup_auth, save_csv

def reauth():
    """Re-run authentication (e.g. after the SHIP session token expired) and
    refresh the module-level AUTH/HEADERS used by all requests."""
    global AUTH, HEADERS
    AUTH, HEADERS = setup_auth(config)
    logging.info("Re-authenticated (refreshed session).")

# Setup Logging
setup_logging("download.log")

# Load Configuration
config = load_config()
FHIR_BASE_URL = config["fhir"]["base_url"]
OUTPUT_DIR = config["analysis"]["output_dir"]
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Setup Authentication
AUTH, HEADERS = setup_auth(config)

def load_icd_codes(filepath, fallback):
    """Load ICD codes from a JSON file (supporting Erlangen format or flat list)."""
    if filepath and os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "codes" in data:
                return [item["code"] for item in data["codes"] if "code" in item]
            elif isinstance(data, dict):
                codes = []
                for k in ["asthma", "copd", "exacerbation"]:
                    if k in data:
                        codes.extend(data[k])
                if codes:
                    return codes
            elif isinstance(data, list):
                return data
            logging.warning(f"Could not parse structure of {filepath}. Using fallback.")
        except Exception as e:
            logging.error(f"Error reading {filepath}: {e}. Using fallback.")
    return fallback

def load_loinc_codes(filepath, fallback):
    """Load LOINC codes from a JSON file."""
    if filepath and os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "codes" in data:
                return [item["code"] for item in data["codes"] if "code" in item]
            elif isinstance(data, list):
                return data
            logging.warning(f"Could not parse structure of {filepath}. Using fallback.")
        except Exception as e:
            logging.error(f"Error reading {filepath}: {e}. Using fallback.")
    return fallback

# Load codes
asthma_copd_file = config["analysis"].get("asthma_copd_codes_file")
loinc_file = config["analysis"].get("loinc_codes_file")

condition_codes = load_icd_codes(asthma_copd_file, config["analysis"].get("condition_codes", []))
observation_codes = load_loinc_codes(loinc_file, config["analysis"].get("observation_codes", []))

# Resources to download for the analysis
RESOURCES = {
    "Condition":         condition_codes,
    "Observation":       observation_codes,
    "MedicationRequest": None,
    "Medication":        None,
}

# =============================================================================

def fetch_all_pages(url, form_data=None):
    """Follow FHIR pagination and collect all resources.

    If form_data is given, the first request is sent as POST _search (avoids
    HTTP 414 'URI Too Long' with large patient/code lists, e.g. on SHIP).
    Pagination links are always followed via GET."""
    resources = []
    page = 1
    post_mode = form_data is not None
    while url:
        logging.info(f"    Page {page}...")
        try:
            if post_mode:
                resp = requests.post(url, data=form_data, auth=AUTH, headers=HEADERS, timeout=60)
            else:
                resp = requests.get(url, auth=AUTH, headers=HEADERS, timeout=60)
            if resp.status_code in (401, 403):
                # SHIP session token expired mid-run -> re-authenticate and retry.
                logging.info(f"Auth expired (HTTP {resp.status_code}); re-authenticating...")
                reauth()
                continue
            resp.raise_for_status()
            bundle = resp.json()
        except requests.exceptions.RequestException as e:
            logging.error(f"Network error: {e}")
            logging.info(f"Waiting 10 seconds and retrying page {page}...")
            time.sleep(10)
            continue

        for entry in bundle.get("entry", []):
            resources.append(entry.get("resource", {}))

        url = next((link.get("url") for link in bundle.get("link", []) if link.get("relation") == "next"), None)
        if url:
            # Some servers (e.g. SHIP) return relative pagination links
            url = urljoin(FHIR_BASE_URL + "/", url)
            if post_mode:
                # In POST mode the next link's query (incl. pagination token) can
                # exceed URL length limits -> re-POST its parameters instead.
                parts = urlsplit(url)
                form_data = dict(parse_qsl(parts.query))
                url = f"{parts.scheme}://{parts.netloc}{parts.path}"
                if not url.endswith("/_search"):
                    url = url.rstrip("/") + "/_search"
            page += 1

    return resources

# Some servers (e.g. SHIP) stop paginating after this many results per search.
SERVER_RESULT_CAP = 20000

def count_resources(resource_type, params):
    """Return the server-side total for a search (or None if counting fails)."""
    try:
        resp = requests.post(f"{FHIR_BASE_URL}/{resource_type}/_search",
                             data={**params, "_summary": "count"},
                             auth=AUTH, headers=HEADERS, timeout=60)
        resp.raise_for_status()
        return resp.json().get("total")
    except requests.exceptions.RequestException as e:
        logging.warning(f"Count query failed ({e}); skipping split check.")
        return None

def fetch_capped(resource_type, codes, date_param, lo=None, hi=None):
    """Fetch all resources for a code list, splitting the query by code and by
    date range whenever the server would cap the result set."""
    params = {"code": ",".join(codes)}
    if lo is not None:
        params[date_param] = [f"ge{lo}-01-01", f"le{hi}-12-31"]

    total = count_resources(resource_type, params)
    if total is not None:
        logging.info(f"    {resource_type} slice ({len(codes)} codes, dates {lo}-{hi}): {total} hits")
    if total is None or total <= SERVER_RESULT_CAP:
        return fetch_all_pages(f"{FHIR_BASE_URL}/{resource_type}/_search",
                               form_data={**params, "_count": "200"})

    if len(codes) > 1:
        mid = len(codes) // 2
        return (fetch_capped(resource_type, codes[:mid], date_param, lo, hi)
                + fetch_capped(resource_type, codes[mid:], date_param, lo, hi))

    if lo is None:
        # Single code over the cap: fetch undated resources, then split by year.
        missing = fetch_all_pages(f"{FHIR_BASE_URL}/{resource_type}/_search",
                                  form_data={"code": codes[0], f"{date_param}:missing": "true", "_count": "200"})
        logging.info(f"    {resource_type} {codes[0]} without {date_param}: {len(missing)} resources")
        return missing + fetch_capped(resource_type, codes, date_param, 1900, 2035)

    if lo >= hi:
        logging.warning(f"    Cannot split {resource_type} {codes[0]} year {lo} further; results may be capped.")
        return fetch_all_pages(f"{FHIR_BASE_URL}/{resource_type}/_search",
                               form_data={**params, "_count": "200"})
    mid = (lo + hi) // 2
    return (fetch_capped(resource_type, codes, date_param, lo, mid)
            + fetch_capped(resource_type, codes, date_param, mid + 1, hi))

def extract_patient_ids_from_conditions():
    """Extract unique Patient IDs from condition.csv."""
    condition_csv = os.path.join(OUTPUT_DIR, "condition.csv")
    if not os.path.exists(condition_csv):
        return []

    patient_ids = set()
    with open(condition_csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ref = row.get("(1) subject.reference", "")
            if ref:
                pid = ref.replace("Patient/", "").strip()
                if pid:
                    patient_ids.add(pid)

    patient_ids = sorted(list(patient_ids))
    logging.info(f"Extracted {len(patient_ids)} unique cohort patient IDs from condition.csv")
    return patient_ids

def fetch_resources(resource_type, code_list=None, patient_ids=None):
    """Fetch resources, batching by code list and/or patient IDs to keep queries targeted and fast."""
    
    # If patient_ids are provided, filter queries by cohort patients
    if patient_ids:
        PATIENT_BATCH_SIZE = 50
        patient_chunks = [patient_ids[i:i + PATIENT_BATCH_SIZE] for i in range(0, len(patient_ids), PATIENT_BATCH_SIZE)]
        all_resources = []

        # Resumable checkpointing: each patient batch is written to its own file
        # so an interrupted run can be restarted and skip completed batches.
        chunk_dir = os.path.join(OUTPUT_DIR, "_chunks", resource_type)
        os.makedirs(chunk_dir, exist_ok=True)

        logging.info(f"Fetching {resource_type} for {len(patient_ids)} cohort patient(s) in {len(patient_chunks)} patient batch(es)...")

        for p_idx, p_chunk in enumerate(patient_chunks, 1):
            chunk_path = os.path.join(chunk_dir, f"batch_{p_idx:05d}.json")
            if os.path.exists(chunk_path):
                with open(chunk_path, encoding="utf-8") as f:
                    batch_res = json.load(f)
                logging.info(f"  Patient Batch {p_idx}/{len(patient_chunks)} (cached, {len(batch_res)} resources)")
                all_resources.extend(batch_res)
                continue

            patient_str = ",".join(p_chunk)
            batch_res = []
            if code_list:
                # Batch codes if more than 50
                CODE_BATCH_SIZE = 50
                code_chunks = [code_list[i:i + CODE_BATCH_SIZE] for i in range(0, len(code_list), CODE_BATCH_SIZE)]
                for c_idx, c_chunk in enumerate(code_chunks, 1):
                    code_str = ",".join(c_chunk)
                    url = f"{FHIR_BASE_URL}/{resource_type}/_search"
                    logging.info(f"  Patient Batch {p_idx}/{len(patient_chunks)} | Code Batch {c_idx}/{len(code_chunks)} ...")
                    batch_res.extend(fetch_all_pages(url, form_data={"patient": patient_str, "code": code_str, "_count": "200"}))
            else:
                url = f"{FHIR_BASE_URL}/{resource_type}/_search"
                logging.info(f"  Patient Batch {p_idx}/{len(patient_chunks)} ...")
                batch_res.extend(fetch_all_pages(url, form_data={"patient": patient_str, "_count": "200"}))

            with open(chunk_path, "w", encoding="utf-8") as f:
                json.dump(batch_res, f)
            all_resources.extend(batch_res)

        logging.info(f"Loaded {len(all_resources)} {resource_type} entries total for cohort patients")
        return all_resources

    # Fallback if no patient_ids provided
    if not code_list:
        url = f"{FHIR_BASE_URL}/{resource_type}?_count=200"
        logging.info(f"Fetching {resource_type} (no code/patient filter) ...")
        return fetch_all_pages(url)

    BATCH_SIZE = 50
    all_resources = []
    chunks = [code_list[i:i + BATCH_SIZE] for i in range(0, len(code_list), BATCH_SIZE)]

    date_param = "recorded-date" if resource_type == "Condition" else "date"
    # Optional cohort date window (e.g. CALMQE_YEAR_FROM=2023 CALMQE_YEAR_TO=2025)
    year_from = os.getenv("CALMQE_YEAR_FROM")
    year_to = os.getenv("CALMQE_YEAR_TO")
    lo = int(year_from) if year_from else None
    # Open-ended window ("2019 to now") -> default upper bound to current year
    hi = int(year_to) if year_to else (__import__("datetime").date.today().year if lo is not None else None)
    if lo is not None:
        logging.info(f"Restricting {resource_type} to {date_param} {lo}-{hi}")
    logging.info(f"Fetching {resource_type} in {len(chunks)} batch(es) of max {BATCH_SIZE} codes...")
    for idx, chunk in enumerate(chunks, 1):
        logging.info(f"  Batch {idx}/{len(chunks)} ...")
        all_resources.extend(fetch_capped(resource_type, chunk, date_param, lo, hi))

    # Date-slice boundaries can produce duplicates -> dedupe by resource id
    seen, unique = set(), []
    for r in all_resources:
        rid = r.get("id")
        if rid and rid in seen:
            continue
        seen.add(rid)
        unique.append(r)
    all_resources = unique

    logging.info(f"Loaded {len(all_resources)} {resource_type} entries total")
    return all_resources

def fetch_encounters_from_condition_csv():
    """Extract Encounter IDs from condition.csv and download them in batches."""
    encounter_csv = os.path.join(OUTPUT_DIR, "encounter.csv")
    condition_csv = os.path.join(OUTPUT_DIR, "condition.csv")

    if os.path.exists(encounter_csv):
        logging.info(f"Skipping Encounter (File already exists: {encounter_csv})")
        return

    if not os.path.exists(condition_csv):
        logging.warning("condition.csv not found – Encounter download skipped.")
        return

    logging.info("Loading Encounters (via IDs from condition.csv)...")

    encounter_ids = set()
    with open(condition_csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ref = row.get("(1) encounter.reference", "")
            if ref and ref.startswith("Encounter/"):
                encounter_ids.add(ref.replace("Encounter/", "").strip())

    encounter_ids = list(encounter_ids)
    logging.info(f"Found {len(encounter_ids)} unique Encounter IDs in condition.csv")

    if not encounter_ids: return

    BATCH_SIZE = 100
    all_encounters = []
    batches = [encounter_ids[i:i + BATCH_SIZE] for i in range(0, len(encounter_ids), BATCH_SIZE)]

    logging.info(f"Downloading {len(batches)} batch(es) of max {BATCH_SIZE} encounters...")
    for idx, batch in enumerate(batches, 1):
        url = f"{FHIR_BASE_URL}/Encounter/_search"
        logging.info(f"Batch {idx}/{len(batches)}...")
        all_encounters.extend(fetch_all_pages(url, form_data={"_id": ",".join(batch), "_count": str(BATCH_SIZE)}))

    logging.info(f"Total of {len(all_encounters)} Encounter entries loaded")
    save_csv(all_encounters, os.path.join(OUTPUT_DIR, "encounter.csv"))

def trim_condition_csv_to_patients(path, n):
    """Test/demo mode: keep only the first n patients in condition.csv
    (preferring patients that have a Hauptdiagnose-category condition, since
    only those can enter the cohort)."""
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)

    cat_cols = [c for c in fields if c.endswith("category.coding.display")]

    def has_haupt(row):
        return any("hauptdiagnose" in (row.get(c) or "").lower() for c in cat_cols)

    keep = []
    for row in rows:
        ref = row.get("(1) subject.reference", "")
        if ref and has_haupt(row) and ref not in keep and len(keep) < n:
            keep.append(ref)
    for row in rows:  # fill up with remaining patients if needed
        ref = row.get("(1) subject.reference", "")
        if ref and ref not in keep and len(keep) < n:
            keep.append(ref)

    keep = set(keep)
    trimmed = [r for r in rows if r.get("(1) subject.reference", "") in keep]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(trimmed)
    logging.info(f"TEST MODE: trimmed condition.csv to {len(keep)} patients ({len(trimmed)} rows)")

def fetch_medications_from_medreq_csv():
    """Fetch Medication resources by the IDs referenced in medicationRequest.csv.
    (An unfiltered Medication download can be capped by the server, losing the
    ATC codes of referenced medications.)"""
    med_csv = os.path.join(OUTPUT_DIR, "medication.csv")
    medreq_csv = os.path.join(OUTPUT_DIR, "medicationRequest.csv")

    if os.path.exists(med_csv):
        logging.info(f"Skipping Medication (File already exists: {med_csv})")
        return
    if not os.path.exists(medreq_csv):
        logging.warning("medicationRequest.csv not found - Medication download skipped.")
        return

    med_ids = set()
    with open(medreq_csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ref = row.get("(1) medicationReference.reference", "")
            if ref and ref.startswith("Medication/"):
                med_ids.add(ref.replace("Medication/", "").strip())

    med_ids = list(med_ids)
    logging.info(f"Found {len(med_ids)} unique Medication IDs in medicationRequest.csv")
    if not med_ids:
        save_csv([], med_csv)
        return

    BATCH_SIZE = 100
    all_meds = []
    batches = [med_ids[i:i + BATCH_SIZE] for i in range(0, len(med_ids), BATCH_SIZE)]
    logging.info(f"Downloading {len(batches)} batch(es) of max {BATCH_SIZE} medications...")
    for idx, batch in enumerate(batches, 1):
        logging.info(f"Batch {idx}/{len(batches)}...")
        all_meds.extend(fetch_all_pages(f"{FHIR_BASE_URL}/Medication/_search",
                                        form_data={"_id": ",".join(batch), "_count": str(BATCH_SIZE)}))
    logging.info(f"Total of {len(all_meds)} Medication entries loaded")
    save_csv(all_meds, med_csv)

def main():
    logging.info("=" * 60)
    logging.info("FHIR Download – Distributed Analysis")
    logging.info(f"Server: {FHIR_BASE_URL}")
    logging.info(f"Target Directory: {OUTPUT_DIR}/")
    logging.info("=" * 60)

    # 1. Download Condition first to establish cohort
    condition_csv = os.path.join(OUTPUT_DIR, "condition.csv")
    if not os.path.exists(condition_csv):
        logging.info("Loading Condition (establishing cohort)...")
        save_csv(fetch_resources("Condition", code_list=condition_codes), condition_csv)
    else:
        logging.info("Skipping Condition (File already exists: condition.csv)")

    # Optional patient cap for test/demo runs (e.g. CALMQE_MAX_PATIENTS=1000)
    max_patients = os.getenv("CALMQE_MAX_PATIENTS")
    if max_patients and os.path.exists(condition_csv):
        trim_condition_csv_to_patients(condition_csv, int(max_patients))

    # Extract Patient IDs from Condition cohort
    patient_ids = extract_patient_ids_from_conditions()

    # 2. Download remaining resources filtered by cohort patient_ids
    #    (Medications can be skipped for large runs: the unfiltered per-patient
    #     MedicationRequest fetch is slow and only feeds the secondary med analysis.)
    skip_meds = os.getenv("CALMQE_SKIP_MEDS", "").lower() in ("1", "true", "yes")
    resource_list = ["Observation"] if skip_meds else ["Observation", "MedicationRequest"]
    for resource_type in resource_list:
        csv_name = f"{resource_type[0].lower()}{resource_type[1:]}.csv"
        filepath = os.path.join(OUTPUT_DIR, csv_name)

        if os.path.exists(filepath):
            logging.info(f"Skipping {resource_type} (File already exists: {csv_name})")
            continue

        logging.info(f"Loading {resource_type}...")
        codes = RESOURCES.get(resource_type)
        
        # Filter Observation and MedicationRequest by cohort patient_ids
        if resource_type in ["Observation", "MedicationRequest"] and patient_ids:
            save_csv(fetch_resources(resource_type, code_list=codes, patient_ids=patient_ids), filepath)
        else:
            save_csv(fetch_resources(resource_type, code_list=codes), filepath)

    # 3. Download Medications referenced by the cohort's MedicationRequests
    if not skip_meds:
        fetch_medications_from_medreq_csv()

    # 4. Download Encounters
    fetch_encounters_from_condition_csv()

    logging.info("=" * 60)
    logging.info(f"Download complete! CSVs saved in: {OUTPUT_DIR}")
    logging.info("Next step: Execute analyze_fhir_distributed.py")
    logging.info("=" * 60)

if __name__ == "__main__":
    main()

