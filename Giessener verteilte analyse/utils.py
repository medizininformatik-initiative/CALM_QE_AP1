import os
import sys
import json
import csv
import logging
import pandas as pd
import requests

def setup_logging(log_filename, log_dir="logs"):
    os.makedirs(log_dir, exist_ok=True)
    
    # Remove existing handlers to avoid duplicates if called multiple times
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
        
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(os.path.join(log_dir, log_filename), mode="a", encoding="utf-8")
        ]
    )

def load_dotenv_vars(path=None):
    """Read KEY=VALUE pairs from a .env file (values may be quoted). Existing env vars win."""
    env = {}
    if path is None:
        path = next((p for p in (".env", os.path.join("..", ".env")) if os.path.exists(p)), ".env")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith("SHIP_")})
    return env

def load_config(config_file="config.json"):
    if not os.path.exists(config_file):
        logging.error(f"Configuration file {config_file} not found. Please create it.")
        sys.exit(1)
    with open(config_file, "r", encoding="utf-8") as f:
        config = json.load(f)
    if config["fhir"].get("auth_type") == "ship":
        env = load_dotenv_vars()
        base = env.get("SHIP_BASE_URL", "").rstrip("/")
        if base:
            config["fhir"]["base_url"] = base if "/app/FHIR" in base else f"{base}/app/FHIR/r4"
    return config


def setup_auth(config):
    auth = None
    headers = {}
    auth_type = config["fhir"].get("auth_type", "basic")
    
    if auth_type == "basic":
        username = config["fhir"]["basic_auth"]["username"]
        password = config["fhir"]["basic_auth"]["password"]
        if username and password and "your_username" not in username:
            auth = (username, password)
        else:
            logging.error("Basic auth selected but credentials are not configured properly.")
            sys.exit(1)
    elif auth_type == "token":
        token = config["fhir"]["token_auth"]["bearer_token"]
        if token and "YOUR_TOKEN_HERE" not in token:
            headers["Authorization"] = f"Bearer {token}"
        else:
            logging.error("Token auth selected but token is not configured properly.")
            sys.exit(1)
    elif auth_type == "ship":
        env = load_dotenv_vars()
        base = env.get("SHIP_BASE_URL", "").rstrip("/")
        base = base.split("/app/FHIR")[0]
        username = env.get("SHIP_USERNAME", "")
        password = env.get("SHIP_PASSWORD", "")
        if not base or not username or not password:
            logging.error("SHIP auth selected but SHIP_BASE_URL/SHIP_USERNAME/SHIP_PASSWORD are missing (.env).")
            sys.exit(1)
        try:
            session = requests.Session()
            resp = session.post(f"{base}/app/Auth/login",
                                data={"username": username, "password": password},
                                allow_redirects=False, timeout=30)
            token = session.cookies.get("shipToken")
            if not token:
                logging.error(f"SHIP login failed - no shipToken cookie received (HTTP {resp.status_code}).")
                sys.exit(1)
            headers["Cookie"] = f"shipToken={token}"
            logging.info("Successfully authenticated with SHIP.")
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to authenticate with SHIP: {e}")
            sys.exit(1)
    elif auth_type == "oauth2":
        oauth_cfg = config["fhir"].get("oauth2", {})
        token_url = oauth_cfg.get("token_url")
        client_id = oauth_cfg.get("client_id")
        client_secret = oauth_cfg.get("client_secret")
        username = oauth_cfg.get("username", "")
        password = oauth_cfg.get("password", "")
        
        if not token_url or not client_id:
            logging.error("OAuth2 selected but token_url or client_id is missing in config.")
            sys.exit(1)
            
        payload = {
            "client_id": client_id,
            "client_secret": client_secret
        }
        
        if username and password and "your_username" not in username:
            payload["grant_type"] = "password"
            payload["username"] = username
            payload["password"] = password
        else:
            payload["grant_type"] = "client_credentials"
            
        logging.info(f"Fetching OAuth2 token from {token_url} using grant_type='{payload['grant_type']}'...")
        try:
            resp = requests.post(token_url, data=payload, timeout=30)
            resp.raise_for_status()
            token_data = resp.json()
            access_token = token_data.get("access_token")
            if not access_token:
                logging.error("OAuth2 response did not contain an access_token.")
                sys.exit(1)
            headers["Authorization"] = f"Bearer {access_token}"
            logging.info("Successfully retrieved OAuth2 token.")
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to fetch OAuth2 token: {e}")
            if e.response is not None:
                logging.error(f"Response: {e.response.text}")
            sys.exit(1)
    else:
        logging.warning("No valid authentication method selected or unknown type.")
        
    return auth, headers

def flatten_fhir(resource):
    """Flatten a FHIR resource using a (1.x.y) prefix convention."""
    result = {}
    def _flatten(obj, path_parts, index_parts):
        if isinstance(obj, dict):
            for key, value in obj.items():
                _flatten(value, path_parts + [key], index_parts)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _flatten(item, path_parts, index_parts + [str(i + 1)])
        else:
            idx = "(" + ".".join(index_parts) + ") " if index_parts else ""
            result[idx + ".".join(path_parts)] = obj

    _flatten(resource, [], ["1"])
    return result

def save_csv(resources, filepath):
    """Save flattened resources as CSV."""
    if not resources:
        logging.warning(f"No data for {filepath} – file will not be created.")
        return

    flat_rows = [flatten_fhir(r) for r in resources]
    all_cols = sorted({col for row in flat_rows for col in row})

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flat_rows)

    logging.info(f"Saved: {filepath} ({len(flat_rows)} rows, {len(all_cols)} columns)")

class CsvStreamWriter:
    """Streams flattened FHIR resources to disk and writes CSV without keeping all data in memory."""
    def __init__(self, filepath):
        self.filepath = filepath
        self.tmp_filepath = filepath + ".tmp.jsonl"
        self.columns = set()
        self.count = 0
        self._tmp_file = open(self.tmp_filepath, "w", encoding="utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def write_resource(self, resource):
        flat = flatten_fhir(resource)
        self.columns.update(flat.keys())
        self._tmp_file.write(json.dumps(flat) + "\n")
        self.count += 1

    def close(self):
        if self._tmp_file and not self._tmp_file.closed:
            self._tmp_file.close()

        if self.count == 0:
            if os.path.exists(self.tmp_filepath):
                os.remove(self.tmp_filepath)
            logging.warning(f"No data for {self.filepath} – file will not be created.")
            return

        all_cols = sorted(self.columns)
        with open(self.tmp_filepath, "r", encoding="utf-8") as in_f, \
             open(self.filepath, "w", newline="", encoding="utf-8") as out_f:
            writer = csv.DictWriter(out_f, fieldnames=all_cols, extrasaction="ignore")
            writer.writeheader()
            for line in in_f:
                writer.writerow(json.loads(line))

        if os.path.exists(self.tmp_filepath):
            os.remove(self.tmp_filepath)

        logging.info(f"Saved: {self.filepath} ({self.count} rows, {len(all_cols)} columns)")

def safe_read_csv(filepath, usecols=None, chunksize=None):
    """Safely read a CSV file using pandas, optionally filtering columns and reading in chunks."""
    if not os.path.exists(filepath):
        logging.warning(f"File {filepath} not found.")
        return pd.DataFrame() if chunksize is None else []

    filename = os.path.basename(filepath)
    logging.info(f"  -> Reading {filename}...")

    if usecols is not None:
        try:
            # Read only header to find which columns actually exist in the CSV
            header_cols = pd.read_csv(filepath, nrows=0).columns.tolist()
            if callable(usecols):
                matched = [c for c in header_cols if usecols(c)]
            elif isinstance(usecols, (list, set, tuple)):
                target_set = set(usecols)
                matched = [c for c in header_cols if c in target_set]
            else:
                matched = None

            if matched:
                if chunksize:
                    return pd.read_csv(filepath, usecols=matched, chunksize=chunksize, low_memory=False)
                df = pd.read_csv(filepath, usecols=matched, low_memory=False)
                logging.info(f"  -> {filename} loaded ({len(df)} rows, {len(df.columns)} cols).")
                return df
            else:
                logging.warning(f"None of requested columns matched in {filepath}. Reading all columns.")
        except Exception as e:
            logging.warning(f"Error filtering columns for {filepath}: {e}. Falling back to standard read.")

    if chunksize:
        return pd.read_csv(filepath, chunksize=chunksize, low_memory=False)
    df = pd.read_csv(filepath, low_memory=False)
    logging.info(f"  -> {filename} loaded ({len(df)} rows, {len(df.columns)} cols).")
    return df

def save_json(data, filepath):
    """Safely save a dictionary as JSON."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
