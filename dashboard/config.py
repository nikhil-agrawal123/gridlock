import os
import sys

# Streamlit only puts each page's own directory on sys.path, not the
# project root -- add it so `modules.*` (geocode, etc.) importable from
# any dashboard page, not just app.py.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Hosted FastAPI backend (Render). Override with TRAFFICSENSE_API for local dev,
# e.g. set TRAFFICSENSE_API=http://localhost:8000 when running the API locally.
API_BASE = os.environ.get(
    "TRAFFICSENSE_API", "https://gridlock-fpzs.onrender.com"
).rstrip("/")
