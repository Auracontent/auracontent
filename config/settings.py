# config/settings.py
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# CHEMINS ABSOLUS DU PROJET
# ==========================================
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
ASSETS_DIR = BASE_DIR / "assets"
TEMP_DIR = BASE_DIR / "temp"

# ==========================================
# FORMAT VIDÉO PAR DÉFAUT (vertical 9:16)
# ==========================================
DEFAULT_VIDEO_WIDTH = 1080
DEFAULT_VIDEO_HEIGHT = 1920
DEFAULT_FPS = 30

# ==========================================
# CONFIGURATION DES LLMs
# ==========================================
GEMINI_CONFIG = {
    "text": "gemini-3.6-flash",
    "voice": "gemini-2.5-flash-preview-tts"
}
# Modèles TTS Gemini essayés dans l'ordre (quotas séparés par modèle, mêmes voix Charon/Orus...)
GEMINI_TTS_MODELS = [GEMINI_CONFIG["voice"], "gemini-2.5-pro-preview-tts"]

# Ordre des fournisseurs LLM (surchargeable : LLM_PROVIDERS=groq,gemini,openrouter).
# Gemini en premier : API stable et JSON fiable, alors que les modèles gratuits Groq/OpenRouter
# changent ou disparaissent sans prévenir (principale source d'instabilité de la v1).
LLM_PROVIDER_ORDER = ["gemini", "groq", "openrouter"]
GEMINI_TEXT_MODELS = [GEMINI_CONFIG["text"]]  # gemini-2.5-flash : 404

# Groq : essayés dans l'ordre (un modèle décommissionné est ignoré automatiquement)
# Point de départ seulement : llm_client interroge Groq pour ne garder que les modèles accessibles à ton compte
GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]

# OpenRouter : les modèles GRATUITS sont découverts automatiquement (llm_client._discover_free_models),
# puis le routeur "openrouter/free". Les modèles listés ici (PAYANTS, consomment tes crédits) passent en dernier.
OPENROUTER_ROUTING = [
    "meta-llama/llama-3.3-70b-instruct",
]

# ==========================================
# CLÉS API & SÉCURITÉ
# ==========================================
# Centralisation pour faire crasher l'appli tôt si une clé manque
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY")
WIKIMEDIA_CONTACT = os.getenv("WIKIMEDIA_CONTACT", "contact non configuré")
