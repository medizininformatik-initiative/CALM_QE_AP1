import pandas as pd
import numpy as np
import scipy.stats as stats
import os
import sys
import logging
import json
from utils import setup_logging, load_config, safe_read_csv, save_json
import graphs


# Setup Logging
setup_logging("analysis.log")

# Load Configuration
config = load_config()

DATA_PATH = config["analysis"]["output_dir"]
OUTPUT_PATH = config["analysis"]["results_dir"]
os.makedirs(OUTPUT_PATH, exist_ok=True)

def load_asthma_copd_codes(filepath):
    """Load Asthma and COPD cohort ICD codes from JSON file."""
    # Default fallbacks
    asthma_codes = {"J45", "J45.0", "J45.00", "J45.01", "J45.02", "J45.03", "J45.04", "J45.05", "J45.09",
                    "J45.1", "J45.10", "J45.11", "J45.12", "J45.13", "J45.14", "J45.15", "J45.19",
                    "J45.8", "J45.80", "J45.81", "J45.82", "J45.83", "J45.84", "J45.85", "J45.89",
                    "J45.9", "J45.90", "J45.91", "J45.92", "J45.93", "J45.94", "J45.95", "J45.99", "J46"}
    
    copd_codes = {"J44", "J44.0", "J44.00", "J44.01", "J44.02", "J44.03", "J44.09",
                  "J44.1", "J44.10", "J44.11", "J44.12", "J44.13", "J44.19",
                  "J44.8", "J44.80", "J44.81", "J44.82", "J44.83", "J44.89",
                  "J44.9", "J44.90", "J44.91", "J44.92", "J44.93", "J44.99"}
                  
    exacerbation_codes = {"J44.10"}
    
    if filepath and os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            if isinstance(data, dict) and "codes" in data:
                found_asthma = []
                found_copd = []
                for item in data["codes"]:
                    code = item.get("code", "")
                    if code.startswith("J45") or code.startswith("J46"):
                        found_asthma.append(code)
                    elif code.startswith("J44"):
                        found_copd.append(code)
                
                if found_asthma:
                    asthma_codes = set(found_asthma)
                if found_copd:
                    copd_codes = set(found_copd)
        except Exception as e:
            logging.error(f"Error loading asthma/COPD codes from {filepath}: {e}")
            
    return list(asthma_codes), list(copd_codes), list(exacerbation_codes)

def load_loinc_groups(filepath):
    """Load LOINC codes from JSON and dynamically categorize them into Eos, IgE, and Weight."""
    # Default baseline fallbacks
    eosinophil_loincs = ["26449-9", "711-2", "712-0", "26453-1"]
    ige_loincs = ["19113-0", "83102-4", "2462-0"]
    weight_loincs = ["29463-7", "3141-9"]
    
    if filepath and os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            if isinstance(data, dict) and "codes" in data:
                found_eos = []
                found_ige = []
                found_weight = []
                
                for item in data["codes"]:
                    code = item.get("code")
                    desc = item.get("description", "").lower()
                    if not code:
                        continue
                    
                    # Match Eosinophils (absolute count/volume)
                    if "eosinophil" in desc:
                        if ("#/volume" in desc or "count" in desc) and "leukocytes" not in desc:
                            found_eos.append(code)
                        elif code in eosinophil_loincs:
                            found_eos.append(code)
                            
                    # Match IgE (total IgE, excluding specific allergen IgE antibodies)
                    elif "ige" in desc:
                        allergens = ["cat", "dog", "mite", "grass", "timothy", "birch", "mugwort", "allergen", "dust", "dander"]
                        if not any(a in desc for a in allergens):
                            found_ige.append(code)
                        elif code in ige_loincs:
                            found_ige.append(code)
                            
                    # Match Body Weight
                    elif "weight" in desc:
                        found_weight.append(code)
                        
                # Merge lists, keeping fallbacks as guarantee
                eosinophil_loincs = list(set(eosinophil_loincs + found_eos))
                ige_loincs = list(set(ige_loincs + found_ige))
                weight_loincs = list(set(weight_loincs + found_weight))
        except Exception as e:
            logging.error(f"Error loading LOINC groups from {filepath}: {e}")
            
    return eosinophil_loincs, ige_loincs, weight_loincs

def main():
    logging.info("=" * 60)
    logging.info("  DISTRIBUTED ANALYSIS – Asthma & COPD")
    logging.info(f"  Data path: {DATA_PATH}")
    logging.info("=" * 60)

    # =============================================================================
    # PART 1: LOAD DATA
    # =============================================================================
    logging.info("[1/4] Loading data...")
    observation = safe_read_csv(os.path.join(DATA_PATH, "observation.csv"))
    condition = safe_read_csv(os.path.join(DATA_PATH, "condition.csv"))
    medicationRequest = safe_read_csv(os.path.join(DATA_PATH, "medicationRequest.csv"))
    medication = safe_read_csv(os.path.join(DATA_PATH, "medication.csv"))
    encounter = safe_read_csv(os.path.join(DATA_PATH, "encounter.csv"))
    logging.info("  -> Data loaded.")

    if condition.empty or observation.empty:
        logging.error("Essential data tables (condition/observation) are empty. Exiting.")
        sys.exit(1)

    # Load configurable code files
    asthma_copd_file = config["analysis"].get("asthma_copd_codes_file")
    loinc_file = config["analysis"].get("loinc_codes_file")

    asthma_codes, copd_codes, exacerbation_codes = load_asthma_copd_codes(asthma_copd_file)
    eosinophil_loincs, ige_loincs, weight_loincs = load_loinc_groups(loinc_file)

    logging.info(f"Configured Asthma ICD codes: {len(asthma_codes)}")
    logging.info(f"Configured COPD ICD codes: {len(copd_codes)}")
    logging.info(f"Configured Eosinophil LOINC codes: {eosinophil_loincs}")
    logging.info(f"Configured IgE LOINC codes: {ige_loincs}")
    logging.info(f"Configured Weight LOINC codes: {weight_loincs}")

    # =============================================================================
    # PART 2: PREPARE DATA
    # =============================================================================
    logging.info("[2/4] Preparing data...")

    # Condition: Extract patient_id and ICD-Code
    if "(1) subject.reference" in condition.columns:
        condition['patient_id'] = condition['(1) subject.reference'].str.replace('Patient/', '')
    else:
        condition['patient_id'] = np.nan
        
    if "(1.1) code.coding.code" in condition.columns:
        condition['icd_code'] = condition['(1.1) code.coding.code'].astype(str)
    else:
        condition['icd_code'] = np.nan

    # Observation
    if "(1) subject.reference" in observation.columns:
        observation['patient_id'] = observation['(1) subject.reference'].str.replace('Patient/', '')
    else:
        observation['patient_id'] = np.nan

    if "(1.2) code.coding.code" in observation.columns:
        observation['loinc_code'] = observation['(1.2) code.coding.code'].astype(str)
    else:
        observation['loinc_code'] = np.nan

    if "(1) valueQuantity.value" in observation.columns:
        observation['value'] = pd.to_numeric(observation['(1) valueQuantity.value'], errors='coerce')
    else:
        observation['value'] = np.nan

    if "(1) valueQuantity.unit" in observation.columns:
        observation['unit'] = observation['(1) valueQuantity.unit']
    else:
        observation['unit'] = np.nan

    if "(1) effectiveDateTime" in observation.columns:
        observation['obs_dt'] = pd.to_datetime(observation['(1) effectiveDateTime'], errors='coerce', utc=True).dt.tz_localize(None)
    else:
        observation['obs_dt'] = pd.NaT

    # Medication
    if not medication.empty:
        medication['medication_id'] = medication['(1) id'] if "(1) id" in medication.columns else np.nan
        medication['atc_code'] = medication['(1.1) code.coding.code'] if "(1.1) code.coding.code" in medication.columns else np.nan
        medication['medication_display'] = medication['(1) code.text'] if "(1) code.text" in medication.columns else np.nan

    # MedicationRequest
    if not medicationRequest.empty:
        medicationRequest['patient_id'] = medicationRequest['(1) subject.reference'].str.replace('Patient/', '') if "(1) subject.reference" in medicationRequest.columns else np.nan
        medicationRequest['medication_id'] = medicationRequest['(1) medicationReference.reference'].str.replace('Medication/', '') if "(1) medicationReference.reference" in medicationRequest.columns else np.nan

    # =============================================================================
    # COHORT DEFINITION: Primary Diagnosis
    # =============================================================================
    logging.info("  -> Extracting primary diagnoses from Encounter (rank = 1)...")
    
    encounter_diag = pd.DataFrame()
    if not encounter.empty:
        diag_ref_cols = [c for c in encounter.columns if c.endswith('diagnosis.condition.reference')]
        
        if len(diag_ref_cols) == 0:
            logging.warning("  WARNING: Encounter contains no diagnosis columns. Falling back to all diagnoses.")
        else:
            slot_dfs = []
            for ref_col in diag_ref_cols:
                rank_col = ref_col.replace('condition.reference', 'rank')
                temp_df = pd.DataFrame()
                temp_df['encounter_id'] = encounter['(1) id'].astype(str) if "(1) id" in encounter.columns else np.nan
                temp_df['patient_id'] = encounter['(1) subject.reference'].str.replace('Patient/', '')
                temp_df['condition_ref'] = encounter[ref_col].astype(str)
                temp_df['rank_value'] = pd.to_numeric(encounter[rank_col], errors='coerce') if rank_col in encounter.columns else np.nan
                temp_df = temp_df.dropna(subset=['condition_ref']).copy()
                # filter out 'nan' strings
                temp_df = temp_df[temp_df['condition_ref'] != 'nan']
                slot_dfs.append(temp_df)
            
            if slot_dfs:
                encounter_diag = pd.concat(slot_dfs, ignore_index=True)
                encounter_diag['condition_id'] = encounter_diag['condition_ref'].str.replace('Condition/', '')

    condition_with_id = condition.copy()
    if "(1) id" in condition_with_id.columns:
        condition_with_id['condition_id'] = condition_with_id['(1) id'].astype(str)
    else:
        condition_with_id['condition_id'] = np.nan

    valid_patients = []
    if encounter_diag.empty:
        logging.warning("  WARNING: Encounter diagnosis data is empty. No primary diagnoses can be resolved.")
        asthma_patients = pd.DataFrame(columns=['patient_id'])
        copd_patients = pd.DataFrame(columns=['patient_id'])
        hauptdiagnose_icd = pd.DataFrame()
    else:
        hauptdiagnose_icd = encounter_diag[encounter_diag['rank_value'] == 1].merge(
            condition_with_id[['condition_id', 'icd_code']], on='condition_id', how='left'
        )
        hauptdiagnose_icd = hauptdiagnose_icd.dropna(subset=['icd_code'])
        
        # Get encounter start and end dates
        if not encounter.empty and '(1) id' in encounter.columns:
            cols_to_use = ['(1) id']
            if '(1) period.start' in encounter.columns:
                cols_to_use.append('(1) period.start')
            if '(1) period.end' in encounter.columns:
                cols_to_use.append('(1) period.end')
                
            encounter_info = encounter[cols_to_use].copy()
            encounter_info = encounter_info.rename(columns={
                '(1) id': 'encounter_id',
                '(1) period.start': 'admission_str',
                '(1) period.end': 'discharge_str'
            })
            if 'admission_str' not in encounter_info.columns:
                encounter_info['admission_str'] = pd.NaT
            if 'discharge_str' not in encounter_info.columns:
                encounter_info['discharge_str'] = pd.NaT
                
            encounter_info['encounter_id'] = encounter_info['encounter_id'].astype(str)
            hauptdiagnose_icd = hauptdiagnose_icd.merge(encounter_info, on='encounter_id', how='left')
        else:
            hauptdiagnose_icd['admission_str'] = pd.NaT
            hauptdiagnose_icd['discharge_str'] = pd.NaT
            
        hauptdiagnose_icd['admission_dt'] = pd.to_datetime(hauptdiagnose_icd['admission_str'], errors='coerce', utc=True).dt.tz_localize(None)
        hauptdiagnose_icd['discharge_dt'] = pd.to_datetime(hauptdiagnose_icd['discharge_str'], errors='coerce', utc=True).dt.tz_localize(None)
        hauptdiagnose_icd['effective_discharge_dt'] = hauptdiagnose_icd['discharge_dt'].combine_first(hauptdiagnose_icd['admission_dt'])
        
        # Filter cohort (earliest admission year >= 2018)
        earliest_admission = hauptdiagnose_icd.dropna(subset=['admission_dt']).groupby('patient_id')['admission_dt'].min().reset_index()
        if not earliest_admission.empty:
            earliest_admission['earliest_year'] = earliest_admission['admission_dt'].dt.year
            valid_patients = earliest_admission[earliest_admission['earliest_year'] >= 2018]['patient_id'].unique()
        else:
            valid_patients = hauptdiagnose_icd['patient_id'].unique()
            
        # Filter patients to only valid ones
        asthma_patients = hauptdiagnose_icd[(hauptdiagnose_icd['icd_code'].isin(asthma_codes)) & (hauptdiagnose_icd['patient_id'].isin(valid_patients))][['patient_id']].drop_duplicates()
        copd_patients = hauptdiagnose_icd[(hauptdiagnose_icd['icd_code'].isin(copd_codes)) & (hauptdiagnose_icd['patient_id'].isin(valid_patients))][['patient_id']].drop_duplicates()

    logging.info(f"  -> Asthma patients (Primary): {len(asthma_patients)}")
    logging.info(f"  -> COPD patients   (Primary): {len(copd_patients)}")

    # Unit Detection
    def get_dominant_unit(obs_df, loinc_list):
        subset = obs_df[(obs_df['loinc_code'].isin(loinc_list)) & (obs_df['unit'].notna())]
        if subset.empty:
            return "unknown"
        return subset['unit'].value_counts().idxmax()

    unit_eos = get_dominant_unit(observation, eosinophil_loincs)
    unit_ige = get_dominant_unit(observation, ige_loincs)
    unit_weight = get_dominant_unit(observation, weight_loincs)

    logging.info(f"  -> Units detected: Eos = {unit_eos} | IgE = {unit_ige} | Weight = {unit_weight}")

    # =============================================================================
    # PART 3: ANALYSES
    # =============================================================================
    logging.info("[3/4] Running analyses...")

    # --- ANALYSIS 1: Eosinophils vs. Exacerbations (COPD) ---
    logging.info("  -> Analysis 1: Correlation Eosinophils / Exacerbations...")
    exac_enc_col = "(1) encounter.reference"
    
    if exac_enc_col in condition.columns:
        exac = condition[(condition['icd_code'].isin(exacerbation_codes)) & (condition[exac_enc_col].notna())]
        copd_exacerbations = exac.groupby('patient_id')[exac_enc_col].nunique().reset_index(name='num_exacerbations')
    else:
        exac = condition[condition['icd_code'].isin(exacerbation_codes)]
        copd_exacerbations = exac.groupby('patient_id').size().reset_index(name='num_exacerbations')
        logging.warning(f"     WARNING: No encounter.reference column found – counting all {exacerbation_codes} records")

    if unit_eos != "unknown":
        eos_filtered_for_unit = observation[(observation['loinc_code'].isin(eosinophil_loincs)) & (observation['unit'] == unit_eos)]
    else:
        eos_filtered_for_unit = observation[observation['loinc_code'].isin(eosinophil_loincs)]
    
    eosinophil_obs = eos_filtered_for_unit.groupby('patient_id')['value'].mean().reset_index(name='mean_eos')

    copd_corr = copd_patients.merge(copd_exacerbations, on='patient_id', how='left').merge(eosinophil_obs, on='patient_id', how='left')
    copd_corr = copd_corr.dropna(subset=['mean_eos', 'num_exacerbations'])

    if len(copd_corr) >= 3:
        r, p = stats.pearsonr(copd_corr['mean_eos'], copd_corr['num_exacerbations'])
        pearson_r = round(r, 4)
        p_value = round(p, 6)
    else:
        pearson_r = None
        p_value = None
        logging.warning("     WARNING: Insufficient data points for correlation test.")

    result_correlation = {
        "n_patients": len(copd_corr),
        "pearson_r": pearson_r,
        "p_value": p_value,
        "mean_eos_all": round(float(copd_corr['mean_eos'].mean()), 4) if not copd_corr.empty else None,
        "unit_eos": str(unit_eos),
        "mean_exacerbations_all": round(float(copd_corr['num_exacerbations'].mean()), 4) if not copd_corr.empty else None
    }

    # --- ANALYSIS 2: Inhaled Medications ---
    logging.info("  -> Analysis 2: Inhaled Medications (ATC Codes)...")
    result_medications_asthma = []
    result_medications_copd = []

    if not medicationRequest.empty and not medication.empty:
        route_cols = [c for c in medicationRequest.columns if c.endswith('dosageInstruction.route.coding.display')]
        
        mr_melt = medicationRequest.melt(id_vars=['patient_id', 'medication_id'], value_vars=route_cols, value_name='route_display')
        inhalation_requests = mr_melt[mr_melt['route_display'] == 'Intrapulmonary use'].copy()
        
        if not inhalation_requests.empty:
            inhalation_requests = inhalation_requests.merge(medication[['medication_id', 'atc_code', 'medication_display']], on='medication_id', how='left')
            inhalation_requests = inhalation_requests.dropna(subset=['atc_code'])

            def aggregate_meds(reqs, pts_df, diag_label):
                subset = reqs[reqs['patient_id'].isin(pts_df['patient_id'])]
                if subset.empty:
                    return pd.DataFrame(columns=['diagnosis', 'atc_code', 'n_patients', 'brand_names'])
                grouped = subset.groupby('atc_code').agg(
                    n_patients=('patient_id', 'nunique'),
                    brand_names=('medication_display', lambda x: " | ".join(sorted(set(x.dropna()))))
                ).reset_index()
                grouped['diagnosis'] = diag_label
                return grouped[['diagnosis', 'atc_code', 'n_patients', 'brand_names']].sort_values('n_patients', ascending=False)

            result_medications_asthma = aggregate_meds(inhalation_requests, asthma_patients, "Asthma").to_dict(orient='records')
            result_medications_copd = aggregate_meds(inhalation_requests, copd_patients, "COPD").to_dict(orient='records')

    # --- ANALYSIS 3: IgE Values ---
    logging.info("  -> Analysis 3: IgE Values...")
    if unit_ige != "unknown":
        ige_obs = observation[(observation['loinc_code'].isin(ige_loincs)) & (observation['unit'] == unit_ige) & (observation['value'].notna())]
    else:
        ige_obs = observation[(observation['loinc_code'].isin(ige_loincs)) & (observation['value'].notna())]

    def summarise_ige(obs, pts, diag):
        subset = obs[obs['patient_id'].isin(pts['patient_id'])]['value']
        if subset.empty:
            return {"diagnosis": diag, "n_measurements": 0, "n_patients": 0}
        
        return {
            "diagnosis": diag,
            "n_measurements": len(subset),
            "n_patients": obs[obs['patient_id'].isin(pts['patient_id'])]['patient_id'].nunique(),
            "median_ige": round(float(subset.median()), 2),
            "mean_ige": round(float(subset.mean()), 2),
            "q25": round(float(subset.quantile(0.25)), 2),
            "q75": round(float(subset.quantile(0.75)), 2),
            "min_ige": round(float(subset.min()), 2),
            "max_ige": round(float(subset.max()), 2),
            "unit_ige": str(unit_ige)
        }

    result_ige = [summarise_ige(ige_obs, asthma_patients, "Asthma"), summarise_ige(ige_obs, copd_patients, "COPD")]

    # --- ANALYSIS 4: Eosinophils vs Weight ---
    logging.info("  -> Analysis 4: Correlation Eosinophils / Body Weight...")
    if unit_eos != "unknown":
        eos_filtered_for_unit = observation[(observation['loinc_code'].isin(eosinophil_loincs)) & (observation['unit'] == unit_eos)]
    else:
        eos_filtered_for_unit = observation[observation['loinc_code'].isin(eosinophil_loincs)]
    eos_filtered_obs = eos_filtered_for_unit.groupby('patient_id')['value'].mean().reset_index()
    eos_filtered_obs = eos_filtered_obs[eos_filtered_obs['value'] <= 15.0].rename(columns={'value': 'mean_eos'})

    if unit_weight != "unknown":
        weight_filtered_for_unit = observation[(observation['loinc_code'].isin(weight_loincs)) & (observation['unit'] == unit_weight)]
    else:
        weight_filtered_for_unit = observation[observation['loinc_code'].isin(weight_loincs)]
    weight_obs = weight_filtered_for_unit.groupby('patient_id')['value'].mean().reset_index()
    weight_obs = weight_obs[weight_obs['value'] <= 250.0].rename(columns={'value': 'mean_weight'})

    def calculate_weight_corr(pts):
        df = pts.merge(eos_filtered_obs, on='patient_id', how='left').merge(weight_obs, on='patient_id', how='left')
        df = df.dropna(subset=['mean_eos', 'mean_weight'])
        
        if len(df) >= 3:
            r, p = stats.pearsonr(df['mean_eos'], df['mean_weight'])
        else:
            r, p = None, None
            
        return {
            "n_patients": len(df),
            "pearson_r": round(r, 4) if r is not None else None,
            "p_value": round(p, 6) if p is not None else None,
            "mean_eos_all": round(float(df['mean_eos'].mean()), 4) if not df.empty else None,
            "mean_weight_all": round(float(df['mean_weight'].mean()), 4) if not df.empty else None,
            "unit_eos": str(unit_eos),
            "unit_weight": str(unit_weight)
        }

    result_corr_weight_asthma = calculate_weight_corr(asthma_patients)
    result_corr_weight_copd = calculate_weight_corr(copd_patients)

    # -------------------------------------------------------------------------
    # NEW EVALUATIONS INTEGRATION
    # -------------------------------------------------------------------------
    logging.info("\n=== Running Integrated Evaluations ===")
    
    # Create subdirectories for output (Numbered 1-5 according to specification)
    dir1_erstvorstellung = os.path.join(OUTPUT_PATH, "1_erstvorstellung")
    dir2_indikation = os.path.join(OUTPUT_PATH, "2_behandlungsindikation")
    dir3_bestimmungsrate = os.path.join(OUTPUT_PATH, "3_bestimmungsrate")
    dir4_durchgaengig = os.path.join(OUTPUT_PATH, "4_durchgaengig_erhoeht")
    dir5_letztvorstellung = os.path.join(OUTPUT_PATH, "5_letztvorstellung")

    os.makedirs(dir1_erstvorstellung, exist_ok=True)
    os.makedirs(dir2_indikation, exist_ok=True)
    os.makedirs(dir3_bestimmungsrate, exist_ok=True)
    os.makedirs(dir4_durchgaengig, exist_ok=True)
    os.makedirs(dir5_letztvorstellung, exist_ok=True)
    
    import datetime
    current_date_str = datetime.date.today().strftime("%Y_%m_%d")
    today_str = datetime.date.today().strftime("%d.%m.%Y")
    
    if hauptdiagnose_icd.empty or len(valid_patients) == 0:
        logging.warning("  WARNING: No valid patients or cases for evaluations. Creating empty results.")
        save_json({}, os.path.join(dir1_erstvorstellung, "auswertung1_erstvorstellung.json"))
        save_json({}, os.path.join(dir2_indikation, "auswertung2_indikation.json"))
        save_json([], os.path.join(dir3_bestimmungsrate, "fhir_eos_bestimmungsrate_tabelle.json"))
        save_json({}, os.path.join(dir4_durchgaengig, "fhir_eos_durchgaengig_erhoeht.json"))
        save_json({}, os.path.join(dir5_letztvorstellung, "auswertung5_letztvorstellung.json"))
        with open(os.path.join(dir4_durchgaengig, "durchgaengig_erhoeht_bericht.txt"), "w", encoding="utf-8") as f:
            f.write("No data available.")
    else:
        # Define Case_Group for each case
        hauptdiagnose_icd['Case_Group'] = np.select(
            [hauptdiagnose_icd['icd_code'].isin(copd_codes), hauptdiagnose_icd['icd_code'].isin(asthma_codes)],
            ['COPD', 'Asthma'],
            default=None
        )
        # Keep cases where Case_Group is set and patient is valid
        df_cases_all = hauptdiagnose_icd[
            hauptdiagnose_icd['Case_Group'].notna() & 
            hauptdiagnose_icd['patient_id'].isin(valid_patients)
        ].copy()
        
        df_cases_all['Year'] = df_cases_all['admission_dt'].dt.year.astype(str)
        
        # Patient level diagnosis profile
        copd_pat_ids = condition[condition['icd_code'].str.startswith('J44', na=False)]['patient_id'].unique()
        asthma_pat_ids = condition[condition['icd_code'].str.startswith('J45', na=False) | condition['icd_code'].str.startswith('J46', na=False)]['patient_id'].unique()
        
        df_cases_all['has_copd'] = df_cases_all['patient_id'].isin(copd_pat_ids)
        df_cases_all['has_asthma'] = df_cases_all['patient_id'].isin(asthma_pat_ids)
        
        # Categorizations
        conditions_final = [
            (df_cases_all['Case_Group'] == 'COPD') & df_cases_all['has_asthma'],
            (df_cases_all['Case_Group'] == 'COPD') & ~df_cases_all['has_asthma'],
            (df_cases_all['Case_Group'] == 'Asthma') & df_cases_all['has_copd'],
            (df_cases_all['Case_Group'] == 'Asthma') & ~df_cases_all['has_copd']
        ]
        choices_final = [
            "Overlap (HD: COPD, ND: Asthma)",
            "COPD-exklusiv",
            "Overlap (HD: Asthma, ND: COPD)",
            "Asthma-exklusiv"
        ]
        df_cases_all['Final_Category'] = np.select(conditions_final, choices_final, default="Andere")

        conditions_three = [
            df_cases_all['Final_Category'] == 'COPD-exklusiv',
            df_cases_all['Final_Category'] == 'Asthma-exklusiv',
            df_cases_all['Final_Category'].str.contains('Overlap', na=False)
        ]
        choices_three = [
            "COPD-exklusiv",
            "Asthma-exklusiv",
            "Overlap"
        ]
        df_cases_all['Three_Group_Category'] = np.select(conditions_three, choices_three, default="Andere")

        conditions_sub = [
            df_cases_all['Final_Category'] == 'Asthma-exklusiv',
            df_cases_all['Final_Category'].str.contains('Overlap', na=False),
            df_cases_all['icd_code'].str.startswith('J44.0', na=False),
            df_cases_all['icd_code'].str.startswith('J44.1', na=False),
            df_cases_all['icd_code'].str.startswith('J44.8', na=False) | df_cases_all['icd_code'].str.startswith('J44.9', na=False)
        ]
        choices_sub = [
            "Asthma-exklusiv",
            "Overlap",
            "COPD J44.0 (Infekt)",
            "COPD J44.1 (Exazerbation)",
            "COPD J44.8/9 (Sonstige/Unspez.)"
        ]
        df_cases_all['Subcategory'] = np.select(conditions_sub, choices_sub, default="COPD Sonstige")
        
        # Match observations to cases
        obs_clean = observation.dropna(subset=['obs_dt', 'value', 'patient_id']).copy()
        obs_eos = obs_clean[obs_clean['loinc_code'].isin(eosinophil_loincs)].copy()
        
        merged_obs = df_cases_all[['encounter_id', 'patient_id', 'admission_dt', 'effective_discharge_dt']].merge(
            obs_eos[['patient_id', 'value', 'obs_dt']], on='patient_id', how='inner'
        )
        
        merged_obs['obs_dt'] = pd.to_datetime(merged_obs['obs_dt']).dt.tz_localize(None)
        merged_obs['admission_dt'] = pd.to_datetime(merged_obs['admission_dt']).dt.tz_localize(None)
        merged_obs['effective_discharge_dt'] = pd.to_datetime(merged_obs['effective_discharge_dt']).dt.tz_localize(None)
        
        valid_obs = merged_obs[
            (merged_obs['obs_dt'] >= merged_obs['admission_dt'] - pd.Timedelta(days=1)) &
            (merged_obs['obs_dt'] <= merged_obs['effective_discharge_dt'] + pd.Timedelta(days=3))
        ].copy()
        
        case_eos = valid_obs.groupby('encounter_id')['value'].max().reset_index(name='max_eo')
        df_all_cases_processed = df_cases_all.merge(case_eos, on='encounter_id', how='left')
        
        # Threshold definition
        eos_threshold = 0.3
        if unit_eos and any(u in str(unit_eos).lower() for u in ["/µl", "/ul", "µl", "ul", "microliter"]):
            eos_threshold = 300.0
        logging.info(f"  -> Using threshold: {eos_threshold} (dominant unit: {unit_eos})")
        
        # Helper for Kruskal-Wallis
        def safe_kruskal(df, val_col, group_col, exclude_groups=None):
            if exclude_groups is None:
                exclude_groups = []
            subset = df[df[val_col].notna() & (~df[group_col].isin(exclude_groups))].copy()
            groups = [group[val_col].values for name, group in subset.groupby(group_col)]
            if len(groups) < 2 or any(len(g) == 0 for g in groups):
                return None
            try:
                stat, p_val = stats.kruskal(*groups)
                return float(p_val)
            except Exception:
                return None

        def categorize_eos(val):
            if pd.isna(val):
                return "Ohne Messung"
            elif val <= eos_threshold:
                return f"Normal (<={eos_threshold})"
            else:
                return f"Erhöht (>{eos_threshold})"

        subcats = ["COPD J44.0 (Infekt)", "COPD J44.1 (Exazerbation)", "COPD J44.8/9 (Sonstige/Unspez.)", "Asthma-exklusiv", "Overlap"]
        eos_cats = ["Ohne Messung", f"Normal (<={eos_threshold})", f"Erhöht (>{eos_threshold})"]

        # ---------------------------------------------------------------------
        # AUSWERTUNG 1: Erstvorstellung (Patientenbasiert - Erste Vorstellung)
        # ---------------------------------------------------------------------
        logging.info("  -> Processing Auswertung 1 (Erstvorstellung - Erste Vorstellung)...")
        df_dedup_erst = df_all_cases_processed.sort_values(
            by=['admission_dt'],
            ascending=[True]
        ).drop_duplicates(subset=['patient_id'], keep='first').copy()

        p_val_3g_erst = safe_kruskal(df_dedup_erst, 'max_eo', 'Three_Group_Category', exclude_groups=['Andere'])
        p_val_sub_erst = safe_kruskal(df_dedup_erst, 'max_eo', 'Subcategory', exclude_groups=['COPD Sonstige', 'Andere'])

        stats_3g_erst = {}
        for g, sub in df_dedup_erst[df_dedup_erst['Three_Group_Category'] != 'Andere'].groupby('Three_Group_Category'):
            vals = sub['max_eo'].dropna()
            stats_3g_erst[g] = {
                "count": int(len(vals)),
                "mean": round(float(vals.mean()), 4) if not vals.empty else None,
                "median": round(float(vals.median()), 4) if not vals.empty else None,
                "min": round(float(vals.min()), 4) if not vals.empty else None,
                "max": round(float(vals.max()), 4) if not vals.empty else None
            }

        stats_sub_erst = {}
        for g, sub in df_dedup_erst[~df_dedup_erst['Subcategory'].isin(['COPD Sonstige', 'Andere'])].groupby('Subcategory'):
            vals = sub['max_eo'].dropna()
            stats_sub_erst[g] = {
                "count": int(len(vals)),
                "mean": round(float(vals.mean()), 4) if not vals.empty else None,
                "median": round(float(vals.median()), 4) if not vals.empty else None,
                "min": round(float(vals.min()), 4) if not vals.empty else None,
                "max": round(float(vals.max()), 4) if not vals.empty else None
            }

        df_dedup_erst['Eos_Category'] = df_dedup_erst['max_eo'].apply(categorize_eos)
        df_sun_erst = df_dedup_erst[df_dedup_erst['Subcategory'].isin(subcats)].copy()

        sun_dist_erst = {}
        for sc in subcats:
            df_sc = df_sun_erst[df_sun_erst['Subcategory'] == sc]
            n_sc = len(df_sc)
            sun_dist_erst[sc] = {
                "total_cases": int(n_sc),
                "categories": {}
            }
            for ec in eos_cats:
                n_ec = len(df_sc[df_sc['Eos_Category'] == ec])
                pct = (n_ec / n_sc * 100) if n_sc > 0 else 0
                sun_dist_erst[sc]["categories"][ec] = {
                    "count": int(n_ec),
                    "percent": round(pct, 2)
                }

        auswertung1_erstvorstellung = {
            "unit_eos": str(unit_eos),
            "kruskal_p_3groups": p_val_3g_erst,
            "kruskal_p_subcategories": p_val_sub_erst,
            "descriptive_stats_3groups": stats_3g_erst,
            "descriptive_stats_subcategories": stats_sub_erst,
            "sunburst_distribution": sun_dist_erst
        }
        save_json(auswertung1_erstvorstellung, os.path.join(dir1_erstvorstellung, "auswertung1_erstvorstellung.json"))

        graphs.generate_boxplot_3groups(
            df_dedup_erst, dir1_erstvorstellung, current_date_str, today_str, p_val_3g_erst, unit_eos,
            prefix="auswertung1_erstvorstellung_", subtitle_extra="Eosinophile (log-Skala) – Erstvorstellung"
        )
        graphs.generate_boxplot_subcategories(
            df_dedup_erst, dir1_erstvorstellung, current_date_str, today_str, p_val_sub_erst, subcats, unit_eos,
            prefix="auswertung1_erstvorstellung_", subtitle_extra="Eosinophile (log-Skala) nach Subkategorie – Erstvorstellung"
        )
        graphs.generate_sunburst_chart(
            df_dedup_erst, dir1_erstvorstellung, current_date_str, today_str, subcats,
            prefix="auswertung1_erstvorstellung_", subtitle_extra="Eosinophilen-Status nach Erkrankungsuntergruppe – Erstvorstellung"
        )

        # ---------------------------------------------------------------------
        # AUSWERTUNG 2: Behandlungsindikation (Patientenbasiert Absolut / Max Eos)
        # ---------------------------------------------------------------------
        logging.info("  -> Processing Auswertung 2 (Behandlungsindikation - Max Eos)...")
        df_all_cases_processed['has_eo'] = df_all_cases_processed['max_eo'].notna()
        df_dedup_3 = df_all_cases_processed.sort_values(
            by=['has_eo', 'max_eo', 'admission_dt'],
            ascending=[False, False, True]
        ).drop_duplicates(subset=['patient_id'], keep='first').copy()
        
        p_val_3g = safe_kruskal(df_dedup_3, 'max_eo', 'Three_Group_Category', exclude_groups=['Andere'])
        p_val_sub = safe_kruskal(df_dedup_3, 'max_eo', 'Subcategory', exclude_groups=['COPD Sonstige', 'Andere'])
        
        stats_3g = {}
        for g, sub in df_dedup_3[df_dedup_3['Three_Group_Category'] != 'Andere'].groupby('Three_Group_Category'):
            vals = sub['max_eo'].dropna()
            stats_3g[g] = {
                "count": int(len(vals)),
                "mean": round(float(vals.mean()), 4) if not vals.empty else None,
                "median": round(float(vals.median()), 4) if not vals.empty else None,
                "min": round(float(vals.min()), 4) if not vals.empty else None,
                "max": round(float(vals.max()), 4) if not vals.empty else None
            }
        
        stats_sub = {}
        for g, sub in df_dedup_3[~df_dedup_3['Subcategory'].isin(['COPD Sonstige', 'Andere'])].groupby('Subcategory'):
            vals = sub['max_eo'].dropna()
            stats_sub[g] = {
                "count": int(len(vals)),
                "mean": round(float(vals.mean()), 4) if not vals.empty else None,
                "median": round(float(vals.median()), 4) if not vals.empty else None,
                "min": round(float(vals.min()), 4) if not vals.empty else None,
                "max": round(float(vals.max()), 4) if not vals.empty else None
            }
            
        df_dedup_3['Eos_Category'] = df_dedup_3['max_eo'].apply(categorize_eos)
        df_sun = df_dedup_3[df_dedup_3['Subcategory'].isin(subcats)].copy()
        
        sun_dist = {}
        for sc in subcats:
            df_sc = df_sun[df_sun['Subcategory'] == sc]
            n_sc = len(df_sc)
            sun_dist[sc] = {
                "total_cases": int(n_sc),
                "categories": {}
            }
            for ec in eos_cats:
                n_ec = len(df_sc[df_sc['Eos_Category'] == ec])
                pct = (n_ec / n_sc * 100) if n_sc > 0 else 0
                sun_dist[sc]["categories"][ec] = {
                    "count": int(n_ec),
                    "percent": round(pct, 2)
                }
                
        auswertung2_indikation = {
            "unit_eos": str(unit_eos),
            "kruskal_p_3groups": p_val_3g,
            "kruskal_p_subcategories": p_val_sub,
            "descriptive_stats_3groups": stats_3g,
            "descriptive_stats_subcategories": stats_sub,
            "sunburst_distribution": sun_dist
        }
        save_json(auswertung2_indikation, os.path.join(dir2_indikation, "auswertung2_indikation.json"))
        
        graphs.generate_boxplot_3groups(df_dedup_3, dir2_indikation, current_date_str, today_str, p_val_3g, unit_eos, prefix="auswertung2_indikation_")
        graphs.generate_boxplot_subcategories(df_dedup_3, dir2_indikation, current_date_str, today_str, p_val_sub, subcats, unit_eos, prefix="auswertung2_indikation_")
        graphs.generate_sunburst_chart(df_dedup_3, dir2_indikation, current_date_str, today_str, subcats, prefix="auswertung2_indikation_")

        # ---------------------------------------------------------------------
        # AUSWERTUNG 3: Bestimmungsrate
        # ---------------------------------------------------------------------
        logging.info("  -> Processing Auswertung 3 (Bestimmungsrate)...")
        df_leitlinie = df_all_cases_processed[
            ~df_all_cases_processed['Subcategory'].isin(['COPD Sonstige', 'Andere'])
        ].copy()
        df_leitlinie['is_measured'] = df_leitlinie['max_eo'].notna()
        
        df_leitlinie['Year_int'] = pd.to_numeric(df_leitlinie['Year'], errors='coerce')
        df_leitlinie = df_leitlinie[df_leitlinie['Year_int'] >= 2018].copy()
        
        if not df_leitlinie.empty:
            df_leitlinie_rate = df_leitlinie.groupby(['Year_int', 'Subcategory']).agg(
                Total_Cases=('encounter_id', 'count'),
                Measured_Cases=('is_measured', 'sum')
            ).reset_index()
            df_leitlinie_rate['Rate_Percent'] = df_leitlinie_rate['Measured_Cases'] / df_leitlinie_rate['Total_Cases'] * 100
            df_leitlinie_rate['unit_eos'] = str(unit_eos)
            
            rate_table_records = df_leitlinie_rate.to_dict(orient='records')
            save_json(rate_table_records, os.path.join(dir3_bestimmungsrate, "fhir_eos_bestimmungsrate_tabelle.json"))
            
            # Generate graph using graphs.py module
            graphs.generate_bestimmungsrate_chart(df_leitlinie_rate, dir3_bestimmungsrate, current_date_str, today_str, subcats)
        else:
            save_json([], os.path.join(dir3_bestimmungsrate, "fhir_eos_bestimmungsrate_tabelle.json"))
            
        # ---------------------------------------------------------------------
        # AUSWERTUNG 4: Durchgängig erhöht (Schwellen 90% und 50%)
        # ---------------------------------------------------------------------
        logging.info("  -> Processing Auswertung 4 (Durchgängig erhöht - 90% & 50%)...")
        df_patient_eos_profile = df_all_cases_processed[df_all_cases_processed['max_eo'].notna()].copy()
        
        if not df_patient_eos_profile.empty:
            patient_stats = df_patient_eos_profile.groupby('patient_id').agg(
                Total_Measurements=('max_eo', 'count'),
                Elevated_Measurements=('max_eo', lambda x: int(sum(x > eos_threshold))),
                Cohort=('Three_Group_Category', 'first')
            ).reset_index()
            
            patient_stats['Pct_Elevated'] = patient_stats['Elevated_Measurements'] / patient_stats['Total_Measurements'] * 100
            patient_stats['Consistently_Elevated_90'] = np.where(
                patient_stats['Pct_Elevated'] >= 90.0,
                "Durchgängig erhöht (>=90%)",
                "Nicht durchgängig erhöht (<90%)"
            )
            patient_stats['Consistently_Elevated_50'] = np.where(
                patient_stats['Pct_Elevated'] >= 50.0,
                "Durchgängig erhöht (>=50%)",
                "Nicht durchgängig erhöht (<50%)"
            )
            # Legacy column
            patient_stats['Consistently_Elevated'] = patient_stats['Consistently_Elevated_90']
            
            total_pat_with_eos = int(len(patient_stats))
            
            # 90% stats
            cons_count_90 = int(sum(patient_stats['Consistently_Elevated_90'] == "Durchgängig erhöht (>=90%)"))
            cons_pct_90 = (cons_count_90 / total_pat_with_eos * 100) if total_pat_with_eos > 0 else 0.0
            cons_subset_90 = patient_stats[patient_stats['Consistently_Elevated_90'] == "Durchgängig erhöht (>=90%)"]
            non_subset_90 = patient_stats[patient_stats['Consistently_Elevated_90'] == "Nicht durchgängig erhöht (<90%)"]
            median_tests_cons_90 = float(cons_subset_90['Total_Measurements'].median()) if not cons_subset_90.empty else 0.0
            median_tests_non_90 = float(non_subset_90['Total_Measurements'].median()) if not non_subset_90.empty else 0.0

            # 50% stats
            cons_count_50 = int(sum(patient_stats['Consistently_Elevated_50'] == "Durchgängig erhöht (>=50%)"))
            cons_pct_50 = (cons_count_50 / total_pat_with_eos * 100) if total_pat_with_eos > 0 else 0.0
            cons_subset_50 = patient_stats[patient_stats['Consistently_Elevated_50'] == "Durchgängig erhöht (>=50%)"]
            non_subset_50 = patient_stats[patient_stats['Consistently_Elevated_50'] == "Nicht durchgängig erhöht (<50%)"]
            median_tests_cons_50 = float(cons_subset_50['Total_Measurements'].median()) if not cons_subset_50.empty else 0.0
            median_tests_non_50 = float(non_subset_50['Total_Measurements'].median()) if not non_subset_50.empty else 0.0

            # Save Report TXT & calculate cohort details
            report_content = f"""=== BERICHT: DURCHGÄNGIG ERHÖHTE EOSINOPHILE ===
Delta-Stand: {today_str}

Anzahl Patienten mit mindestens 1 Eos-Messung: {total_pat_with_eos}

--- SCHWELLE >= 90% ---
Davon durchgängig erhöht (in >=90% der Messungen > {eos_threshold}): {cons_count_90} ({cons_pct_90:.2f}%)
  Gruppe 'Durchgängig erhöht (>=90%)': {median_tests_cons_90} Messungen pro Patient (Mediane)
  Gruppe 'Nicht durchgängig erhöht (<90%)': {median_tests_non_90} Messungen pro Patient (Mediane)

--- SCHWELLE >= 50% ---
Davon durchgängig erhöht (in >=50% der Messungen > {eos_threshold}): {cons_count_50} ({cons_pct_50:.2f}%)
  Gruppe 'Durchgängig erhöht (>=50%)': {median_tests_cons_50} Messungen pro Patient (Mediane)
  Gruppe 'Nicht durchgängig erhöht (<50%)': {median_tests_non_50} Messungen pro Patient (Mediane)

=== KOHORTEN-DETAILS ===

"""
            cohorts_to_plot = ["COPD-exklusiv", "Asthma-exklusiv", "Overlap"]
            cohort_details_90 = {}
            cohort_details_50 = {}
            
            for coh in cohorts_to_plot:
                df_coh = patient_stats[patient_stats['Cohort'] == coh]
                coh_total = len(df_coh)
                
                # 90%
                coh_cons_90 = int(sum(df_coh['Consistently_Elevated_90'] == "Durchgängig erhöht (>=90%)"))
                coh_pct_90 = (coh_cons_90 / coh_total * 100) if coh_total > 0 else 0.0
                cons_coh_subset_90 = df_coh[df_coh['Consistently_Elevated_90'] == "Durchgängig erhöht (>=90%)"]
                non_coh_subset_90 = df_coh[df_coh['Consistently_Elevated_90'] == "Nicht durchgängig erhöht (<90%)"]
                median_tests_cons_coh_90 = float(cons_coh_subset_90['Total_Measurements'].median()) if not cons_coh_subset_90.empty else 0.0
                median_tests_non_coh_90 = float(non_coh_subset_90['Total_Measurements'].median()) if not non_coh_subset_90.empty else 0.0

                # 50%
                coh_cons_50 = int(sum(df_coh['Consistently_Elevated_50'] == "Durchgängig erhöht (>=50%)"))
                coh_pct_50 = (coh_cons_50 / coh_total * 100) if coh_total > 0 else 0.0
                cons_coh_subset_50 = df_coh[df_coh['Consistently_Elevated_50'] == "Durchgängig erhöht (>=50%)"]
                non_coh_subset_50 = df_coh[df_coh['Consistently_Elevated_50'] == "Nicht durchgängig erhöht (<50%)"]
                median_tests_cons_coh_50 = float(cons_coh_subset_50['Total_Measurements'].median()) if not cons_coh_subset_50.empty else 0.0
                median_tests_non_coh_50 = float(non_coh_subset_50['Total_Measurements'].median()) if not non_coh_subset_50.empty else 0.0

                report_content += f"""Kohorte: {coh}
  Patienten mit Eos: {coh_total}
  [>=90% Schwelle] Davon durchgängig erhöht: {coh_cons_90} ({coh_pct_90:.2f}%)
    Mediane Messungen (durchg. erhöht >=90%): {median_tests_cons_coh_90} | (nicht durchg.): {median_tests_non_coh_90}
  [>=50% Schwelle] Davon durchgängig erhöht: {coh_cons_50} ({coh_pct_50:.2f}%)
    Mediane Messungen (durchg. erhöht >=50%): {median_tests_cons_coh_50} | (nicht durchg.): {median_tests_non_coh_50}

"""
                cohort_details_90[coh] = {
                    "total_patients": coh_total,
                    "consistently_elevated_count": coh_cons_90,
                    "consistently_elevated_percent": round(coh_pct_90, 2),
                    "median_measurements_consistently_elevated": median_tests_cons_coh_90,
                    "median_measurements_not_consistently_elevated": median_tests_non_coh_90
                }
                cohort_details_50[coh] = {
                    "total_patients": coh_total,
                    "consistently_elevated_count": coh_cons_50,
                    "consistently_elevated_percent": round(coh_pct_50, 2),
                    "median_measurements_consistently_elevated": median_tests_cons_coh_50,
                    "median_measurements_not_consistently_elevated": median_tests_non_coh_50
                }

            # Save JSON
            result_durchgaengig = {
                "unit_eos": str(unit_eos),
                "total_patients_with_eos": total_pat_with_eos,
                "threshold_used": eos_threshold,
                "threshold_90pct": {
                    "consistently_elevated_count": cons_count_90,
                    "consistently_elevated_percent": round(cons_pct_90, 2),
                    "median_measurements_consistently_elevated": median_tests_cons_90,
                    "median_measurements_not_consistently_elevated": median_tests_non_90,
                    "cohort_details": cohort_details_90
                },
                "threshold_50pct": {
                    "consistently_elevated_count": cons_count_50,
                    "consistently_elevated_percent": round(cons_pct_50, 2),
                    "median_measurements_consistently_elevated": median_tests_cons_50,
                    "median_measurements_not_consistently_elevated": median_tests_non_50,
                    "cohort_details": cohort_details_50
                },
                "legacy_90pct_cohort_details": cohort_details_90
            }
            save_json(result_durchgaengig, os.path.join(dir4_durchgaengig, "fhir_eos_durchgaengig_erhoeht.json"))
            
            with open(os.path.join(dir4_durchgaengig, "durchgaengig_erhoeht_bericht.txt"), "w", encoding="utf-8") as f:
                f.write(report_content)
                
            # Generate pie charts for 90% and 50%
            graphs.generate_durchgaengig_pie(patient_stats, dir4_durchgaengig, current_date_str, today_str, eos_threshold, unit_eos, pct_threshold=90)
            graphs.generate_durchgaengig_pie(patient_stats, dir4_durchgaengig, current_date_str, today_str, eos_threshold, unit_eos, pct_threshold=50)
        else:
            save_json({}, os.path.join(dir4_durchgaengig, "fhir_eos_durchgaengig_erhoeht.json"))
            with open(os.path.join(dir4_durchgaengig, "durchgaengig_erhoeht_bericht.txt"), "w", encoding="utf-8") as f:
                f.write("No patients with Eosinophil measurements.")

        # ---------------------------------------------------------------------
        # AUSWERTUNG 5: Letztvorstellung (Letzte Vorstellung)
        # ---------------------------------------------------------------------
        logging.info("  -> Processing Auswertung 5 (Letztvorstellung - Letzte Vorstellung)...")
        
        # Determine exacerbation / infection stays for historical upgrade
        exac_stays = df_all_cases_processed[
            df_all_cases_processed['icd_code'].str.startswith('J44.1', na=False) |
            df_all_cases_processed['icd_code'].str.startswith('J44.0', na=False)
        ].sort_values(by=['admission_dt'], ascending=[False]).drop_duplicates(subset=['patient_id'], keep='first')
        
        exac_stays_lookup = exac_stays.set_index('patient_id')[['admission_dt', 'icd_code']].to_dict('index')

        # Most recent stay (Letztvorstellung) per patient
        df_dedup_letzt = df_all_cases_processed.sort_values(
            by=['admission_dt'],
            ascending=[False]
        ).drop_duplicates(subset=['patient_id'], keep='first').copy()

        # Apply Historical Upgrade logic for COPD J44.8/9
        def apply_upgrade(row):
            pid = row['patient_id']
            sub = row['Subcategory']
            if sub == "COPD J44.8/9 (Sonstige/Unspez.)" and pid in exac_stays_lookup:
                upgrade_info = exac_stays_lookup[pid]
                upg_icd = str(upgrade_info['icd_code'])
                if upg_icd.startswith('J44.1'):
                    return "COPD J44.1 (Exazerbation)"
                elif upg_icd.startswith('J44.0'):
                    return "COPD J44.0 (Infekt)"
            return sub

        df_dedup_letzt['Subcategory'] = df_dedup_letzt.apply(apply_upgrade, axis=1)

        p_val_3g_letzt = safe_kruskal(df_dedup_letzt, 'max_eo', 'Three_Group_Category', exclude_groups=['Andere'])
        p_val_sub_letzt = safe_kruskal(df_dedup_letzt, 'max_eo', 'Subcategory', exclude_groups=['COPD Sonstige', 'Andere'])

        stats_3g_letzt = {}
        for g, sub in df_dedup_letzt[df_dedup_letzt['Three_Group_Category'] != 'Andere'].groupby('Three_Group_Category'):
            vals = sub['max_eo'].dropna()
            stats_3g_letzt[g] = {
                "count": int(len(vals)),
                "mean": round(float(vals.mean()), 4) if not vals.empty else None,
                "median": round(float(vals.median()), 4) if not vals.empty else None,
                "min": round(float(vals.min()), 4) if not vals.empty else None,
                "max": round(float(vals.max()), 4) if not vals.empty else None
            }

        stats_sub_letzt = {}
        for g, sub in df_dedup_letzt[~df_dedup_letzt['Subcategory'].isin(['COPD Sonstige', 'Andere'])].groupby('Subcategory'):
            vals = sub['max_eo'].dropna()
            stats_sub_letzt[g] = {
                "count": int(len(vals)),
                "mean": round(float(vals.mean()), 4) if not vals.empty else None,
                "median": round(float(vals.median()), 4) if not vals.empty else None,
                "min": round(float(vals.min()), 4) if not vals.empty else None,
                "max": round(float(vals.max()), 4) if not vals.empty else None
            }

        df_dedup_letzt['Eos_Category'] = df_dedup_letzt['max_eo'].apply(categorize_eos)
        df_sun_letzt = df_dedup_letzt[df_dedup_letzt['Subcategory'].isin(subcats)].copy()

        sun_dist_letzt = {}
        for sc in subcats:
            df_sc = df_sun_letzt[df_sun_letzt['Subcategory'] == sc]
            n_sc = len(df_sc)
            sun_dist_letzt[sc] = {
                "total_cases": int(n_sc),
                "categories": {}
            }
            for ec in eos_cats:
                n_ec = len(df_sc[df_sc['Eos_Category'] == ec])
                pct = (n_ec / n_sc * 100) if n_sc > 0 else 0
                sun_dist_letzt[sc]["categories"][ec] = {
                    "count": int(n_ec),
                    "percent": round(pct, 2)
                }

        auswertung5_letztvorstellung = {
            "unit_eos": str(unit_eos),
            "kruskal_p_3groups": p_val_3g_letzt,
            "kruskal_p_subcategories": p_val_sub_letzt,
            "descriptive_stats_3groups": stats_3g_letzt,
            "descriptive_stats_subcategories": stats_sub_letzt,
            "sunburst_distribution": sun_dist_letzt
        }
        save_json(auswertung5_letztvorstellung, os.path.join(dir5_letztvorstellung, "auswertung5_letztvorstellung.json"))

        graphs.generate_boxplot_3groups(
            df_dedup_letzt, dir5_letztvorstellung, current_date_str, today_str, p_val_3g_letzt, unit_eos,
            prefix="auswertung5_letztvorstellung_", subtitle_extra="Eosinophile (log-Skala) – Letztvorstellung"
        )
        graphs.generate_boxplot_subcategories(
            df_dedup_letzt, dir5_letztvorstellung, current_date_str, today_str, p_val_sub_letzt, subcats, unit_eos,
            prefix="auswertung5_letztvorstellung_", subtitle_extra="Eosinophile (log-Skala) nach Subkategorie – Letztvorstellung"
        )
        graphs.generate_sunburst_chart(
            df_dedup_letzt, dir5_letztvorstellung, current_date_str, today_str, subcats,
            prefix="auswertung5_letztvorstellung_", subtitle_extra="Eosinophilen-Status nach Erkrankungsuntergruppe – Letztvorstellung"
        )

    # =============================================================================
    # PART 4: SAVE RESULTS
    # ==============================================================================================================
    logging.info("\n[4/4] Saving results...")
    
    save_json(result_correlation, os.path.join(OUTPUT_PATH, "correlation_eos_exacerbations.json"))
    save_json(result_corr_weight_asthma, os.path.join(OUTPUT_PATH, "correlation_eos_weight_asthma.json"))
    save_json(result_corr_weight_copd, os.path.join(OUTPUT_PATH, "correlation_eos_weight_copd.json"))
    save_json(result_medications_asthma, os.path.join(OUTPUT_PATH, "medications_asthma.json"))
    save_json(result_medications_copd, os.path.join(OUTPUT_PATH, "medications_copd.json"))
    save_json(result_ige, os.path.join(OUTPUT_PATH, "ige_summary.json"))

    logging.info(f"Saved files in '{OUTPUT_PATH}/'")
    logging.info("  ANALYSIS COMPLETE")

if __name__ == "__main__":
    main()
