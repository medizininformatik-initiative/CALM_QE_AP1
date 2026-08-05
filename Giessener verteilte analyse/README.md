# CALM-QE – Distributed Analysis: Asthma & COPD

A fully containerized Python pipeline for standardized, multi-site analysis of inpatient Asthma and COPD patients using FHIR data.

---

## Files Included

| File                             | Description                                                                                               |
| -------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `config.json`                  | Central configuration: FHIR server URL, authentication, code file paths, output directories.              |
| `utils.py`                     | Shared helper functions for logging, configuration, OAuth2 authentication, and CSV/JSON I/O.              |
| `download_fhir_distributed.py` | Downloads required FHIR resources from your local server and saves them as flat CSV files.                |
| `analyze_fhir_distributed.py`  | Main analysis script: cohort definition, statistics, JSON results, and interactive HTML charts.           |
| `graphs.py`                    | Helper module containing all Plotly visualization functions (imported by`analyze_fhir_distributed.py`). |
| `requirements.txt`             | Python dependencies (`pandas`, `scipy`, `plotly`, `requests`, `numpy`).                         |
| `Dockerfile`                   | Docker image for reproducible execution across all participating sites.                                   |
| `input_files/`                 | Directory for site-specific local coding files (ICD, LOINC, ATC).                                         |

---

## Configuration (`config.json`)

Before running the pipeline, fill in `config.json` with your site's FHIR server credentials.

**Supported authentication types:** `basic`, `token`, `oauth2`

```json
{
  "fhir": {
    "base_url": "https://your-fhir-server.com/fhir",
    "auth_type": "oauth2",
    "basic_auth": {
      "username": "...",
      "password": "..."
    },
    "token_auth": {
      "bearer_token": "..."
    },
    "oauth2": {
      "token_url": "https://your-keycloak.com/auth/realms/REALM/protocol/openid-connect/token",
      "client_id": "your_client_id",
      "client_secret": "your_client_secret",
      "username": "",
      "password": ""
    }
  },
  "analysis": {
    "output_dir": "data_calmqe_distributed",
    "results_dir": "results"
  }
}
```

---

## Customizing Local Codes (`input_files/`)

If your site uses custom or local codes, add them to the JSON files in the `input_files/` directory:

- `asthma_copd_codes.json` – ICD codes for cohort selection (Asthma J45, COPD J44)
- `loinc_codes.json` – LOINC codes for Eosinophils, IgE, and Body Weight
- `atc_codes.json` – ATC codes for inhaled medications
- `icd_codes.json` – ICD codes for exacerbations

> [!NOTE]
> The script automatically detects the dominant measurement unit for Eosinophils found in your data (e.g. `10*9/L`, `/uL`, `Giga/L`, `µL`). This unit is then used dynamically in all charts and JSON outputs.

---

## Running the Pipeline – Option A: Docker (Recommended)

Docker guarantees that all dependencies match the exact required versions across all sites.

**1. Build the image:**

```bash
docker build -t calmqe-analysis .
```

**2. Run the container:**

```bash
docker run \
  -v $(pwd)/results:/app/results \
  -v $(pwd)/data_calmqe_distributed:/app/data_calmqe_distributed \
  -v $(pwd)/logs:/app/logs \
  calmqe-analysis
```

The container automatically runs the download step first (which may take up to 30 minutes depending on FHIR server performance), followed by the analysis.

---

## Running the Pipeline – Option B: Python Locally

**1. Install dependencies:**

```bash
pip install -r requirements.txt
```

**2. Download FHIR data:**

```bash
python download_fhir_distributed.py
```

> [!NOTE]
> Depending on your FHIR server's performance, network latency, and the size of your cohort, the download process may take anywhere from a few minutes up to 1 hour to complete.

This script queries your FHIR server and saves the following resources as flat CSV files in `data_calmqe_distributed/`:

| CSV File                  | FHIR Resource     | Content                                                           |
| ------------------------- | ----------------- | ----------------------------------------------------------------- |
| `condition.csv`         | Condition         | Diagnoses (ICD J44/J45 + exacerbations)                           |
| `observation.csv`       | Observation       | Lab values (Eosinophils, IgE, Body Weight)                        |
| `medicationRequest.csv` | MedicationRequest | Prescribed medications                                            |
| `medication.csv`        | Medication        | Medication master data (ATC codes, brand names)                   |
| `encounter.csv`         | Encounter         | Inpatient cases with admission/discharge dates and diagnosis rank |

**3. Run the analysis:**

```bash
python analyze_fhir_distributed.py
```

---

## What the Analysis Does

### Cohort Definition

- Only patients with **Asthma (J45)** or **COPD (J44)** as a **primary diagnosis** (`rank = 1` in the Encounter resource) are included.
- Cases with an admission date before 2018 are excluded.
- Each patient is assigned to exactly one group:
  - **Asthma-only**: primary Asthma diagnosis, no COPD in the medical history
  - **COPD-only**: primary COPD diagnosis, no Asthma in the medical history
  - **Overlap**: both Asthma and COPD present in the medical history

### Additional Analyses

- **Eosinophils vs. Exacerbations** – Pearson correlation (COPD cohort)
- **Eosinophils vs. Body Weight** – Pearson correlation (Asthma and COPD cohorts, outlier filter >15 Gpt/L and >250 kg)
- **Inhaled Medications** – Frequency by ATC code for both cohorts
- **IgE Summary** – Median, mean, and quartiles for both cohorts

---

## Results Overview

All results are saved under the `results/` directory:

### Folder `1_erstvorstellung/` (Auswertung 1: Patient-based – First Presentation)

| File                                                                                      | Content                                                                                                                      |
| ----------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `auswertung1_erstvorstellung.json`                                                       | Descriptive statistics + Kruskal-Wallis p-values + sunburst distribution for initial patient admission                       |
| `auswertung1_erstvorstellung_fhir_boxplot_eos_log_faelle_<DATE>.html`                    | Interactive boxplot: Eosinophils (log scale) at initial presentation for the 3 main groups                                   |
| `auswertung1_erstvorstellung_fhir_boxplot_eos_log_subkategorie_faelle_<DATE>.html`       | Interactive boxplot: Eosinophils by subcategory at initial presentation                                                      |
| `auswertung1_erstvorstellung_fhir_eos_sunburst_subkategorie_combined_faelle_<DATE>.html` | Interactive sunburst chart: Eosinophil status per subcategory at initial presentation                                        |

### Folder `2_behandlungsindikation/` (Auswertung 2: Patient-based – Max Eos / Indication)

| File                                                                        | Content                                                                                                                      |
| --------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `auswertung2_indikation.json`                                               | Descriptive statistics (median, mean, min, max, quartiles) + Kruskal-Wallis p-values + sunburst distribution + detected unit |
| `auswertung2_indikation_fhir_boxplot_eos_log_faelle_<DATE>.html`           | Interactive boxplot: Eosinophils (log scale) for the 3 main groups                                                           |
| `auswertung2_indikation_fhir_boxplot_eos_log_subkategorie_faelle_<DATE>.html`  | Interactive boxplot: Eosinophils by COPD subcategory                                                                         |
| `auswertung2_indikation_fhir_eos_sunburst_subkategorie_combined_faelle_<DATE>.html` | Interactive sunburst chart: Eosinophil status per subcategory                                                                |

### Folder `3_bestimmungsrate/` (Auswertung 3: Determination Rate Over Time)

| File                                                    | Content                                                                               |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `fhir_eos_bestimmungsrate_tabelle.json`               | Annual Eosinophil determination rates (2018–present) per subcategory, including unit |
| `fhir_eos_bestimmungsrate_verlauf_Linien_<DATE>.html` | Interactive line chart: determination rate over time                                  |

### Folder `4_durchgaengig_erhoeht/` (Auswertung 4: Persistently Elevated Eosinophils)

| File                                                           | Content                                                                                                          |
| -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `fhir_eos_durchgaengig_erhoeht.json`                         | Share of patients with persistently elevated Eosinophils (both ≥90% and ≥50% thresholds), including cohort details |
| `durchgaengig_erhoeht_bericht.txt`                           | Plain-text summary report for both ≥90% and ≥50% thresholds                                                        |
| `fhir_eos_durchgaengig_erhoeht_anteil_copd_90pct_<DATE>.html`   | Interactive pie chart: share of persistently elevated patients (COPD-only, ≥90% threshold)                       |
| `fhir_eos_durchgaengig_erhoeht_anteil_asthma_90pct_<DATE>.html` | Interactive pie chart: share of persistently elevated patients (Asthma-only, ≥90% threshold)                     |
| `fhir_eos_durchgaengig_erhoeht_anteil_overlap_90pct_<DATE>.html`| Interactive pie chart: share of persistently elevated patients (Overlap, ≥90% threshold)                         |
| `fhir_eos_durchgaengig_erhoeht_anteil_copd_50pct_<DATE>.html`   | Interactive pie chart: share of persistently elevated patients (COPD-only, ≥50% threshold)                       |
| `fhir_eos_durchgaengig_erhoeht_anteil_asthma_50pct_<DATE>.html` | Interactive pie chart: share of persistently elevated patients (Asthma-only, ≥50% threshold)                     |
| `fhir_eos_durchgaengig_erhoeht_anteil_overlap_50pct_<DATE>.html`| Interactive pie chart: share of persistently elevated patients (Overlap, ≥50% threshold)                         |

### Folder `5_letztvorstellung/` (Auswertung 5: Patient-based – Last Presentation)

| File                                                                                       | Content                                                                                                                      |
| ------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------- |
| `auswertung5_letztvorstellung.json`                                                       | Descriptive statistics + Kruskal-Wallis p-values + sunburst distribution for last patient admission                          |
| `auswertung5_letztvorstellung_fhir_boxplot_eos_log_faelle_<DATE>.html`                    | Interactive boxplot: Eosinophils (log scale) at last presentation for the 3 main groups                                      |
| `auswertung5_letztvorstellung_fhir_boxplot_eos_log_subkategorie_faelle_<DATE>.html`       | Interactive boxplot: Eosinophils by subcategory at last presentation                                                         |
| `auswertung5_letztvorstellung_fhir_eos_sunburst_subkategorie_combined_faelle_<DATE>.html` | Interactive sunburst chart: Eosinophil status per subcategory at last presentation                                           |

### Directly in `results/`

| File                                   | Content                                                            |
| -------------------------------------- | ------------------------------------------------------------------ |
| `correlation_eos_exacerbations.json` | Pearson correlation: Eosinophils ↔ number of exacerbations (COPD) |
| `correlation_eos_weight_asthma.json` | Pearson correlation: Eosinophils ↔ body weight (Asthma)           |
| `correlation_eos_weight_copd.json`   | Pearson correlation: Eosinophils ↔ body weight (COPD)             |
| `medications_asthma.json`            | Inhaled medications by ATC code (Asthma)                           |
| `medications_copd.json`              | Inhaled medications by ATC code (COPD)                             |
| `ige_summary.json`                   | IgE statistics: median, mean, quartiles, unit                      |

---

## JSON Fields – Reference

### `auswertung1_indikation.json`

| Field                               | Description                                                                      |
| ----------------------------------- | -------------------------------------------------------------------------------- |
| `unit_eos`                        | Automatically detected Eosinophil unit (e.g.`10*9/L`)                          |
| `kruskal_p_3groups`               | Kruskal-Wallis p-value across the 3 main groups                                  |
| `kruskal_p_subcategories`         | Kruskal-Wallis p-value across all subcategories                                  |
| `descriptive_stats_3groups`       | Median, mean, min, max, Q25, Q75, n per main group                               |
| `descriptive_stats_subcategories` | Same statistics per COPD subcategory                                             |
| `sunburst_distribution`           | Case counts and percentages (No measurement / Normal / Elevated) per subcategory |

### `fhir_eos_bestimmungsrate_tabelle.json`

| Field              | Description                                                                    |
| ------------------ | ------------------------------------------------------------------------------ |
| `Year_int`       | Year of admission                                                              |
| `Subcategory`    | Diagnosis subcategory                                                          |
| `Total_Cases`    | Total number of cases                                                          |
| `Measured_Cases` | Cases with an Eosinophil measurement within the time window [−1 day, +3 days] |
| `Rate_Percent`   | Determination rate in %                                                        |
| `unit_eos`       | Automatically detected measurement unit                                        |

### `fhir_eos_durchgaengig_erhoeht.json`

| Field                                             | Description                                                    |
| ------------------------------------------------- | -------------------------------------------------------------- |
| `unit_eos`                                      | Automatically detected measurement unit                        |
| `total_patients_with_eos`                       | Patients with at least 1 Eosinophil measurement                |
| `consistently_elevated_count`                   | Patients with ≥90% of measurements above the threshold        |
| `consistently_elevated_percent`                 | Percentage of persistently elevated patients                   |
| `median_measurements_consistently_elevated`     | Median number of measurements per patient (elevated group)     |
| `median_measurements_not_consistently_elevated` | Median number of measurements per patient (non-elevated group) |
| `threshold_used`                                | Threshold value used (default:`0.3`)                         |

### `correlation_eos_exacerbations.json`

| Field                      | Description                                                      |
| -------------------------- | ---------------------------------------------------------------- |
| `n_patients`             | Patients with both Eosinophil measurements and exacerbation data |
| `pearson_r`              | Pearson correlation coefficient                                  |
| `p_value`                | Statistical significance                                         |
| `mean_eos_all`           | Mean Eosinophil value                                            |
| `unit_eos`               | Measurement unit                                                 |
| `mean_exacerbations_all` | Mean number of exacerbations                                     |

### `ige_summary.json`

| Field                         | Description                              |
| ----------------------------- | ---------------------------------------- |
| `diagnosis`                 | `"Asthma"` or `"COPD"`               |
| `n_measurements`            | Total number of IgE measurements         |
| `n_patients`                | Patients with at least 1 IgE measurement |
| `median_ige` / `mean_ige` | Median / mean IgE value                  |
| `q25` / `q75`             | 25th / 75th percentile                   |
| `min_ige` / `max_ige`     | Minimum / maximum IgE value              |
| `unit_ige`                  | Automatically detected IgE unit          |
