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

def load_config(config_file="config.json"):
    if not os.path.exists(config_file):
        logging.error(f"Configuration file {config_file} not found. Please create it.")
        sys.exit(1)
    
    with open(config_file, "r", encoding="utf-8") as f:
        return json.load(f)

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

def safe_read_csv(filepath):
    """Safely read a CSV file using pandas."""
    if os.path.exists(filepath):
        return pd.read_csv(filepath, low_memory=False)
    else:
        logging.warning(f"File {filepath} not found.")
        return pd.DataFrame()

def save_json(data, filepath):
    """Safely save a dictionary as JSON."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
