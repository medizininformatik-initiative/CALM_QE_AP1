# FHIR Data Downloader & Converter (Marburg Format)

Dieses Skript lädt Daten von einem FHIR-Server herunter und konvertiert sie in das **Marburg CSV-Format** für die verteilte Analyse.

**Getestet:** Gießen (FHIR-Server, 300 Bundles)  


---

## Voraussetzungen

- **R** (≥ 4.0)
- Folgende R-Pakete (werden beim ersten Start automatisch installiert, falls fehlend):
  - `fhircrackr` – FHIR-Daten herunterladen & parsen
  - `dplyr` – Datenmanipulation
  - `stringr` – String-Operationen
  - `tidyr` – Daten-Reshaping

---

## Schnellstart

### 1. Konfiguration anpassen

Öffne `download_data_github.R` und trage in **Zeile 17–25** die lokalen Werte ein:

```r
# --- USER CONFIGURATION ---
FHIR_SERVER_URL <- "https://euer-fhir-server.de/fhir"   # FHIR-Endpunkt
FHIR_USER       <- "benutzername"                        # Benutzername
FHIR_PW         <- "passwort"                            # Passwort
OUTPUT_DIR       <- "source_data"                        # Ausgabe-Ordner
```

| Parameter | Beschreibung | Beispiel |
|-----------|-------------|----------|
| `FHIR_SERVER_URL` | Basis-URL eures FHIR-Servers | `https://fhir.uni-marburg.de/fhir` |
| `FHIR_USER` | Benutzername für Basic Auth | `mein_user` |
| `FHIR_PW` | Passwort für Basic Auth | `mein_passwort` |
| `AUTH_TOKEN` | Bearer-Token (falls statt User/PW) | `"Bearer abc123..."` |
| `START_DATE` | Startdatum für die Abfrage | `"2014-01-01"` |
| `END_DATE` | Enddatum für die Abfrage | `"2024-12-31"` |
| `OUTPUT_DIR` | Ordner für die CSV-Ausgabe | `"source_data"` |
| `MAX_BUNDLES` | Anzahl Bundles (Test: 50–300, Produktion: `Inf`) | `300` |

### 2. Script ausführen

In R oder RStudio:

```r
source("download_data_github.R")
```

### 3. Ergebnis prüfen

Im `OUTPUT_DIR` werden folgende CSV-Dateien erzeugt:

| Datei | Inhalt |
|-------|--------|
| `PSN_Person_PA_YYYY_WW.csv` | Patienten (PID, Geburtsjahr, Geschlecht) |
| `PSN_Fall_Abteilungskontakt_PA_YYYY_WW.csv` | Fälle/Kontakte (ohne PID) |
| `PSN_Fall_Einrichtungskontakt_PA_YYYY_WW.csv` | Fälle/Kontakte (mit PID) |
| `PSN_Diagnose_PA_YYYY_WW.csv` | Diagnosen (ICD-Codes, Typ, Priorität) |
| `PSN_Prozedur_PA_YYYY_WW.csv` | Prozeduren (OPS-Codes, Datum) |
| `PSN_Labor_PA_YYYY_WW.csv` | Labordaten (LOINC-Codes, Werte) |
| `PSN_Lungenfunktion_PA_YYYY_WW.csv` | Lungenfunktionsdaten (Spirometrie) |

> `YYYY_WW` = Jahr und Kalenderwoche des Downloads (z.B. `2026_08`)

**CSV-Format:** Semikolon-separiert (`;`), Punkt als Dezimalzeichen, UTF-8.

---

## Download-Modi

Das Script hat zwei Modi, gesteuert über `MAX_BUNDLES`:

### Test-Modus (`MAX_BUNDLES = 50–300`)
- **Smart Subset:** Encounter + alle verknüpften Ressourcen in einer Abfrage
- Garantiert referentielle Integrität auch bei kleinen Datenmengen
- Empfohlen für den ersten Test

### Produktions-Modus (`MAX_BUNDLES = Inf`)
- Separate Streams für jede Ressource (höherer Durchsatz)
- Lädt **alle** Daten herunter
- Kann auf Windows sehr lange dauern (weil nur 1 CPU-Kern vorhanden ist)
- Empfehlung: Auf einer Linux-VM laufen lassen (weil mehr CPU-Kerne vorhanden sind bzw. mehr power vorhanden ist)

---

## FHIR-Ressourcen Mapping

Das Script extrahiert folgende FHIR-Ressourcen:

```
FHIR-Ressource    →  Marburg CSV-Tabelle
─────────────────────────────────────────
Patient           →  PSN_Person
Encounter         →  PSN_Fall_Abteilungskontakt
                     PSN_Fall_Einrichtungskontakt
Condition         →  PSN_Diagnose
Procedure         →  PSN_Prozedur
Observation       →  PSN_Labor
                     PSN_Lungenfunktion
```

---

## Troubleshooting

| Problem | Lösung |
|---------|--------|
| Timeout beim Download | `MAX_BUNDLES` reduzieren (z.B. auf 50) |
| Leere CSV-Dateien | FHIR-Server URL und Zugangsdaten prüfen |
| Pakete fehlen | `install.packages(c("fhircrackr", "dplyr", "stringr", "tidyr"))` |
| Lungenfunktionsdaten fehlen | Prüfen ob LOINC-Codes auf eurem Server anders sind |

---

## Kontakt

Bei Fragen: **Maher Gammoudi** (DIZ Gießen)
email: [Maher.Gammoudi@uniklinikum-giessen.de]
