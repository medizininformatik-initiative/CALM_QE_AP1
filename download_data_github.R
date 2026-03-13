# 1. Setup & Configuration ------------------------------------------------
if (!requireNamespace("fhircrackr", quietly = TRUE)) {
  install.packages("fhircrackr", repos = "https://cloud.r-project.org")
}
if (!requireNamespace("tidyr", quietly = TRUE)) {
  install.packages("tidyr", repos = "https://cloud.r-project.org")
}
library(fhircrackr)
library(dplyr)
library(stringr)
library(tidyr)

# --- USER CONFIGURATION ---
# PLEASE UPDATE THESE VALUES
FHIR_SERVER_URL <- ""
FHIR_USER <- ""
FHIR_PW <- ""
AUTH_TOKEN <- NULL # "Bearer YOUR_TOKEN" if needed
START_DATE <- "2014-01-01"
END_DATE <- "2024-12-31"
OUTPUT_DIR <- ""

# Download Limits
# Set to Inf to download ALL data (production).
# Set to a small number (e.g. 50) for testing.
MAX_BUNDLES <- Inf
# ---------------------------

if (!dir.exists(OUTPUT_DIR)) {
  dir.create(OUTPUT_DIR)
}

# Define global function
filter_by_pid <- function(df, pid_list, table_name) {
  if (nrow(df) == 0) {
    return(df)
  }
  if (!"PID" %in% colnames(df)) {
    return(df)
  }
  n_before <- nrow(df)
  return(df) # Return unfiltered for now
}

convert_to_marburg_date <- function(x) {
  d <- as.POSIXct(x, tryFormats = c("%Y-%m-%dT%H:%M:%OSZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"), tz = "UTC")
  paste0(format(d, "%Y-%m-%dT%H:%M:%S"), "Z")
}

pad_to_match <- function(target_list, len_list) {
  mapply(function(x, n) {
    if (length(x) == n) {
      return(x)
    }
    if (length(x) == 1 && !is.na(x) && x == "") {
      return(rep(NA_character_, n))
    }
    if (length(x) != n) {
      return(rep(NA_character_, n))
    }
    return(x)
  }, target_list, len_list, SIMPLIFY = FALSE)
}


# 2. Define Table Designs (Mappings) --------------------------------------

# Design: PSN_Person
design_person <- fhir_table_description(
  resource = "Patient",
  cols = list(
    PID          = "id",
    Geburtsdatum = "birthDate",
    Geschlecht   = "gender"
  )
)

# Design: PSN_Fall_Abteilungskontakt
design_encounter <- fhir_table_description(
  resource = "Encounter",
  cols = list(
    Fallnummer = "id",
    PID = "subject/reference", # Need PID to fetch Patient later
    Fallart = "class/code",
    Beginn = "period/start",
    Ende = "period/end",
    Fachabteilungsschlüssel = "serviceType/coding/code",
    Entlassgrund = "hospitalization/dischargeDisposition/coding/code"
  )
)

# Design: Encounter Ranks & Use (To fix missing Priorities and Types)
design_enc_diag <- fhir_table_description(
  resource = "Encounter",
  cols = list(
    Fallnummer = "id",
    Condition_Ref = "diagnosis/condition/reference",
    Rank = "diagnosis/rank",
    Use = "diagnosis/use/coding/code"
  ),
  sep = " | ",
  brackets = NULL,
  rm_empty_cols = FALSE
)

# Design: PSN_Diagnose
design_condition <- fhir_table_description(
  resource = "Condition",
  cols = list(
    Condition_ID = "id",
    PID = "subject/reference",
    Fallnummer_Ref = "encounter/reference",
    Diagnosecode = "code/coding/code",
    Diagnosecode_System = "code/coding/system",
    Diagnosedatum = "recordedDate"
  )
)

# Design: PSN_Prozedur
design_procedure <- fhir_table_description(
  resource = "Procedure",
  cols = list(
    PID = "subject/reference",
    Fallnummer_Ref = "encounter/reference",
    Prozedurcode = "code/coding/code",
    Prozedurdatum = "performedDateTime"
  )
)

# Design: PSN_Labor / PSN_Lungenfunktion (Observation)
design_observation <- fhir_table_description(
  resource = "Observation",
  cols = list(
    PID = "subject/reference",
    Fallnummer_Ref = "encounter/reference",
    Code = "code/coding/code",
    Display = "code/coding/display",
    System = "code/coding/system",
    Wert = "valueQuantity/value",
    Einheit = "valueQuantity/unit",
    Datum = "effectiveDateTime"
  )
)

# 3. Define FHIR Search Requests ------------------------------------------

# Request: Patient (Standard Fetch - High Volume)
request_patient <- fhir_url(
  url = FHIR_SERVER_URL,
  resource = "Patient"
  # No date filter usually for Patient in standard sets
)

request_encounter <- fhir_url(
  url = FHIR_SERVER_URL,
  resource = "Encounter",
  parameters = list(
    "date" = paste0("ge", START_DATE),
    "date" = paste0("le", END_DATE)
  )
)

request_condition <- fhir_url(
  url = FHIR_SERVER_URL,
  resource = "Condition",
  parameters = list(
    "recorded-date" = paste0("ge", START_DATE)
  )
)

request_procedure <- fhir_url(
  url = FHIR_SERVER_URL,
  resource = "Procedure",
  parameters = list(
    "date" = paste0("ge", START_DATE)
  )
)

request_observation <- fhir_url(
  url = FHIR_SERVER_URL,
  resource = "Observation",
  parameters = list(
    "date" = paste0("ge", START_DATE)
  )
)

# 4. Download & Crack (Extract) -------------------------------------------
cat("Starting download from", FHIR_SERVER_URL, "...\n")

# --- SMART SUBSET STRATEGY ---
# If  in "Testing" mode (MAX_BUNDLES is finite), use:
# ask for Encounters and include EVERYTHING related (Patients, Diagnoses, etc.)
# in the same request. This ensures valid links even with small data amounts.

# --- PRODUCTION MODE (OLD LOGIC) ---
# Separate streams for maximum throughput when downloading EVERYTHING (Inf)

# Patient loading
cat("Downloading Patients...\n")
fhir_search(request_patient, max_bundles = MAX_BUNDLES, verbose = 1, username = FHIR_USER, password = FHIR_PW, save_to_disc = (paste0(OUTPUT_DIR, "/_temp/patient")))
bundles_person <- fhir_load(paste0(OUTPUT_DIR, "/_temp/patient"))
table_person <- fhir_crack(bundles_person, design_person, verbose = 1)

# Patient Postprocessing and saving
if (nrow(table_person) > 0) {
  table_person$Geburtsdatum <- substr(table_person$Geburtsdatum, 1, 4)
  write.table(table_person, file.path(OUTPUT_DIR, paste0("PSN_Person_PA_", format(Sys.Date(), "%Y_%V"), ".csv")),
              sep = ";", dec = ".", row.names = FALSE, quote = TRUE, fileEncoding = "UTF-8"
  )
  cat("Saved PSN_Person\n")
}
valid_pids <- unique(table_person$PID)

rm(bundles_person, table_person)
gc()

# Encounter loading
cat("Downloading Encounters...\n")
fhir_search(request_encounter, max_bundles = MAX_BUNDLES, verbose = 1, username = FHIR_USER, password = FHIR_PW, save_to_disc = (paste0(OUTPUT_DIR, "/_temp/encounter")))
bundles_enc <- fhir_load(paste0(OUTPUT_DIR, "/_temp/encounter"))
table_enc <- fhir_crack(bundles_enc, design_encounter, verbose = 1)
table_enc_diag <- fhir_crack(bundles_enc, design_enc_diag, verbose = 1)

# Encounter Postprocessing and saving
if (nrow(table_enc) > 0) {
  table_enc$Fallnummer <- str_remove(table_enc$Fallnummer, "Encounter/")
  table_enc$PID <- str_remove(table_enc$PID, "Patient/")
  
  if (nrow(table_enc) > 0) {
    if (!is.null(table_enc$Beginn)) table_enc$Beginn <- convert_to_marburg_date(table_enc$Beginn)
    if (!is.null(table_enc$Ende)) table_enc$Ende <- convert_to_marburg_date(table_enc$Ende)
  }
  
  write.table(table_enc[, !names(table_enc) %in% "PID"],
              file.path(OUTPUT_DIR, paste0("PSN_Fall_Abteilungskontakt_PA_", format(Sys.Date(), "%Y_%V"), ".csv")),
              sep = ";", dec = ".", row.names = FALSE, quote = TRUE, fileEncoding = "UTF-8"
  )
  cat("Saved PSN_Fall_Abteilungskontakt\n")
  
  write.table(table_enc, file.path(OUTPUT_DIR, paste0("PSN_Fall_Einrichtungskontakt_PA_", format(Sys.Date(), "%Y_%V"), ".csv")),
              sep = ";", dec = ".", row.names = FALSE, quote = TRUE, fileEncoding = "UTF-8"
  )
  cat("Saved PSN_Fall_Einrichtungskontakt\n")
}

rm(bundles_enc, table_enc)
gc()

# Condition loading
cat("Downloading Conditions...\n")
fhir_search(request_condition, max_bundles = MAX_BUNDLES, verbose = 1, username = FHIR_USER, password = FHIR_PW, save_to_disc = (paste0(OUTPUT_DIR, "/_temp/condition")))
bundles_cond <- fhir_load(paste0(OUTPUT_DIR, "/_temp/condition"))
table_cond <- fhir_crack(bundles_cond, design_condition, verbose = 1)

# Condition Postprocessing and saving
if (nrow(table_cond) > 0) {
  table_cond$Fallnummer <- str_remove(table_cond$Fallnummer_Ref, "Encounter/")
  table_cond$Fallnummer_Ref <- NULL
  table_cond$PID <- str_remove(table_cond$PID, "Patient/")

  # Merge Rank/Use
  if (nrow(table_enc_diag) > 0) {
    table_enc_diag$Condition_Ref <- sub(" \\| $", "", table_enc_diag$Condition_Ref)
    table_enc_diag$Rank <- sub(" \\| $", "", table_enc_diag$Rank)
    table_enc_diag$Use <- sub(" \\| $", "", table_enc_diag$Use)

    ref_list <- str_split(table_enc_diag$Condition_Ref, " \\| ")
    rank_list <- str_split(table_enc_diag$Rank, " \\| ")
    use_list <- str_split(table_enc_diag$Use, " \\| ")

    n_refs <- sapply(ref_list, length)

    rank_list_fixed <- pad_to_match(rank_list, n_refs)
    use_list_fixed <- pad_to_match(use_list, n_refs)

    dummy_df <- tibble(Rank = rank_list_fixed, Use = use_list_fixed, Condition_Ref = ref_list)
    table_enc_diag_long <- dummy_df %>% unnest(cols = c(Condition_Ref, Rank, Use))
    table_enc_diag_long$Condition_Ref <- str_remove(table_enc_diag_long$Condition_Ref, "Condition/")

    table_cond <- merge(table_cond, table_enc_diag_long[, c("Condition_Ref", "Rank", "Use")], by.x = "Condition_ID", by.y = "Condition_Ref", all.x = TRUE)

    if ("Rank" %in% colnames(table_cond)) {
      table_cond$Diagnoseprioritaet <- table_cond$Rank
      table_cond$Rank <- NULL
    } else {
      table_cond$Diagnoseprioritaet <- NA
    }
    if ("Use" %in% colnames(table_cond)) {
      table_cond$Diagnosetyp <- table_cond$Use
      table_cond$Use <- NULL
    } else {
      table_cond$Diagnosetyp <- NA
    }
  } else {
    table_cond$Diagnoseprioritaet <- NA
    table_cond$Diagnosetyp <- NA
  }
  table_cond$Condition_ID <- NULL

  # table_cond <- filter_by_pid(table_cond, valid_pids, "PSN_Diagnose")

  write.table(table_cond, file.path(OUTPUT_DIR, paste0("PSN_Diagnose_PA_", format(Sys.Date(), "%Y_%V"), ".csv")),
              sep = ";", dec = ".", row.names = FALSE, quote = TRUE, fileEncoding = "UTF-8"
  )
  cat("Saved PSN_Diagnose\n")
}

rm(bundles_cond, table_cond, ref_list, rank_list, use_list, rank_list_fixed, use_list_fixed, dummy_df, table_enc_diag_long)
gc()

# Procedure loading
cat("Downloading Procedures...\n")
fhir_search(request_procedure, max_bundles = MAX_BUNDLES, verbose = 1, username = FHIR_USER, password = FHIR_PW, save_to_disc = (paste0(OUTPUT_DIR, "/_temp/procedure")))
bundles_proc <- fhir_load(paste0(OUTPUT_DIR, "/_temp/procedure"))
table_proc <- fhir_crack(bundles_proc, design_procedure, verbose = 1)

# Procedure Postprocessing and saving
if (nrow(table_proc) > 0) {
  table_proc$Fallnummer <- str_remove(table_proc$Fallnummer_Ref, "Encounter/")
  table_proc$Fallnummer_Ref <- NULL
  table_proc$PID <- str_remove(table_proc$PID, "Patient/")
  # table_proc <- filter_by_pid(table_proc, valid_pids, "PSN_Prozedur")

  if (!is.null(table_proc$Prozedurdatum)) table_proc$Prozedurdatum <- convert_to_marburg_date(table_proc$Prozedurdatum)

  write.table(table_proc, file.path(OUTPUT_DIR, paste0("PSN_Prozedur_PA_", format(Sys.Date(), "%Y_%V"), ".csv")),
              sep = ";", dec = ".", row.names = FALSE, quote = TRUE, fileEncoding = "UTF-8"
  )
  cat("Saved PSN_Prozedur\n")
}

rm(bundles_proc, table_proc)
gc()

# Observation
cat("Downloading Observations...\n")
fhir_search(request_observation, max_bundles = MAX_BUNDLES, verbose = 1, username = FHIR_USER, password = FHIR_PW, save_to_disc = (paste0(OUTPUT_DIR, "/_temp/observation")))
bundles_obs <- fhir_load(paste0(OUTPUT_DIR, "/_temp/observation"))
table_obs <- fhir_crack(bundles_obs, design_observation, verbose = 1)

# Observation Postprocessing and saving
if (nrow(table_obs) > 0) {
  table_obs$Fallnummer <- str_remove(table_obs$Fallnummer_Ref, "Encounter/")
  table_obs$Fallnummer_Ref <- NULL
  table_obs$PID <- str_remove(table_obs$PID, "Patient/")
  # table_obs <- filter_by_pid(table_obs, valid_pids, "PSN_Labor")

  if (!is.null(table_obs$Datum)) table_obs$Datum <- convert_to_marburg_date(table_obs$Datum)
  # --- SPLIT: Labor vs. Lungenfunktion ---
  # Keywords for Lungenfunktion (Spirometry) & specific LOINC codes from sample
  lung_keywords <- c(
    "FEV", "FVC", "PEF", "FEF", "Spirometry", "Lungenfunktion", "Lung function",
    "SlowSpirometry", "Pleth", "VC", "TLC", "RV", "DLCO", "Diffusionskapazität",
    "82615-6", "20157-4", "81452-5", "82619-8", "82616-4", "81450-9" # Specific LOINC codes from user sample
  )

  lung_pattern <- paste(lung_keywords, collapse = "|")

  # Helper to check if Code or Display Name matches
  is_lung_func <- function(code, display) {
    match_code <- grepl(lung_pattern, code, ignore.case = TRUE)
    match_display <- grepl(lung_pattern, display, ignore.case = TRUE)
    return(match_code | match_display)
  }

  lung_rows <- is_lung_func(table_obs$Code, table_obs$Display)

  table_files_lung <- table_obs[lung_rows, ]
  table_files_labor <- table_obs[!lung_rows, ] # Everything else is Labor

  # 1. Save PSN_Labor
  write.table(table_files_labor, file.path(OUTPUT_DIR, paste0("PSN_Labor_PA_", format(Sys.Date(), "%Y_%V"), ".csv")),
              sep = ";", dec = ".", row.names = FALSE, quote = TRUE, fileEncoding = "UTF-8"
  )
  cat("Saved PSN_Labor (Rows:", nrow(table_files_labor), ")\n")

  # 2. Save PSN_Lungenfunktion
  write.table(table_files_lung, file.path(OUTPUT_DIR, paste0("PSN_Lungenfunktion_PA_", format(Sys.Date(), "%Y_%V"), ".csv")),
              sep = ";", dec = ".", row.names = FALSE, quote = TRUE, fileEncoding = "UTF-8"
  )
  cat("Saved PSN_Lungenfunktion (Rows:", nrow(table_files_lung), ")\n")
}

rm(bundles_obs, table_obs)
gc()


cat("Done!\n")
