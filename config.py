import os
import secrets
from pathlib import Path

ENVIRON = os.environ.get("ENVIRON", "PRODUCTION")
DEBUG = True if os.environ.get("DEBUG", "True") == "True" else False
IN_DOCKER = True if os.environ.get("IN_DOCKER", False) == "True" else False

# OS-portable default: use current directory as fallback for Linux-only paths
_DEFAULT_BASE = str(Path.cwd() / "google_translator_data")
BASE_PATH = os.environ.get("GOOGLE_TRANSLATOR", str(Path.cwd()))
BASE_DATA_PATH = os.environ.get("GOOGLE_TRANSLATOR_DATA", _DEFAULT_BASE)

SESSION_KEY = secrets.token_hex(8)

print(f"connecting to the {ENVIRON} database")
print(f"CurrentSessionKey: {SESSION_KEY}")
print(f"DEBUG: {DEBUG}")
print(f"IN_DOCKER: {IN_DOCKER}")

HOST = "0.0.0.0"
APP_MAIN_PORT = int(os.environ.get("APP_MAIN_PORT", 3131))

DEFAULT_LANGUAGE = "en"