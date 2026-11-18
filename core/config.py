import os
import sys
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import dotenv_values

# Keep diagnostic prints safe when this module is imported outside main.py
# (which already does the same guarded reconfigure on a Windows cp1252 console).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

class Settings(BaseSettings):
    """
    Manages application settings and loads them from a .env file.
    All defaults should be production-safe values that match .env file settings.
    """
    # Required API Keys (no defaults - must be provided)
    DEEPGRAM_API_KEY: str
    
    
    # Logging Configuration
    LOG_LEVEL: str = "INFO"
    
    # Development Mode - Controls debugging features
    # Default to False for production safety, .env file controls actual value
    DEV_MODE: bool = False
    
    # AI Configuration - Defaults match .env file values
    TRACK_CANDIDATE_RESPONSES: bool = True
    INCLUDE_CONVERSATION_HISTORY: bool = True
    MAX_CONVERSATION_HISTORY: int = 24
    GENERATE_FULL_ANSWERS: bool = True
    PERSONALIZE_ANSWERS: bool = True
    COMPACT_ANSWER_PROMPT: bool = True

    # Latency budgets. The vision total must stay below the UI's 45s timeout so
    # the backend always replies before the client gives up.
    VISION_TIMEOUT_S: float = 22.0          # per model/key attempt
    VISION_TOTAL_TIMEOUT_S: float = 35.0    # whole fallback chain
    VISION_MAX_TOKENS: int = 4096
    VISION_COMPACT_PROMPT: bool = True
    LLM_TIMEOUT_S: float = 25.0             # per model/key attempt
    LLM_TOTAL_TIMEOUT_S: float = 32.0       # whole fallback chain
    MAX_HISTORY_CHARS: int = 1200           # cap each past AI answer in prompts
    MAX_VISION_HISTORY_CHARS: int = 350     # vision analyses are much larger
    MAX_FALLBACK_MODELS_PER_PROVIDER: int = 2

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding='utf-8',
        case_sensitive=True,
        extra='ignore'  # <-- This is the simple fix. It tells Pydantic to ignore unknown env vars.
    )

# --- Manual Override for .env Priority ---
# Load settings from .env file first
env_settings = Settings(_env_file=".env", _env_file_encoding='utf-8')

# Now create the final settings instance.
# By passing `env_settings` as keyword arguments, we force its values to take
# priority over any system environment variables that Pydantic would otherwise load.
settings = Settings(**env_settings.model_dump())


PLACEHOLDER_DEEPGRAM_KEY = "your_deepgram_api_key_here"


def config_issues() -> list:
    """Return human-readable startup problems (empty when config looks sane).

    Used at launch to replace confusing downstream failures (Deepgram 401s,
    "no providers configured") with a single clear, actionable message.
    """
    issues = []

    key = (settings.DEEPGRAM_API_KEY or "").strip().strip('"').strip("'")
    if not key or key.lower() == PLACEHOLDER_DEEPGRAM_KEY or "your_deepgram" in key.lower():
        issues.append(
            "DEEPGRAM_API_KEY is not configured. Live transcription is disabled "
            "until you add a real key to .env (or the Advanced Config tab)."
        )

    if not Path("ai_providers.json").exists():
        issues.append(
            "ai_providers.json is missing. AI answers will be unavailable until "
            "provider credentials are configured."
        )

    return issues


def print_startup_diagnostics() -> None:
    """Print concise, production-friendly startup status."""
    issues = config_issues()
    if not issues:
        print("✅ Configuration check passed.")
        return
    print("⚠️  Configuration check found issue(s):")
    for issue in issues:
        print(f"   - {issue}")


def print_config_debug():
    """Debug function to show current configuration values and their sources"""
    print("🔧 CONFIGURATION DEBUG:")
    
    # --- DEV_MODE Debugging ---
    raw_dev_mode_os = os.getenv('DEV_MODE', 'Not Set')
    env_file_vals = dotenv_values(".env")
    dev_mode_in_file = env_file_vals.get('DEV_MODE', 'Not found in .env')

    if raw_dev_mode_os != 'Not Set' and raw_dev_mode_os.lower() != str(settings.DEV_MODE).lower():
        print("   ⚠️  WARNING: Environment variable conflict detected!")
        print(f"      - System environment sets DEV_MODE='{raw_dev_mode_os}'")
        print(f"      - .env file sets DEV_MODE='{dev_mode_in_file}'")
        print(f"      - ✅ Using value from .env file: {settings.DEV_MODE}")

    print(f"\n   --- Final Values ---")
    print(f"   ⚙️ DEV_MODE (Final Value Used) = {settings.DEV_MODE}")
    
    # --- Other Settings ---
    print(f"   📊 LOG_LEVEL = {settings.LOG_LEVEL}")
    print(f"   🤖 AI Settings:")
    print(f"      TRACK_CANDIDATE_RESPONSES = {settings.TRACK_CANDIDATE_RESPONSES}")
    print(f"      INCLUDE_CONVERSATION_HISTORY = {settings.INCLUDE_CONVERSATION_HISTORY}")
    print(f"      MAX_CONVERSATION_HISTORY = {settings.MAX_CONVERSATION_HISTORY}")
    print(f"      GENERATE_FULL_ANSWERS = {settings.GENERATE_FULL_ANSWERS}")
    print(f"      PERSONALIZE_ANSWERS = {settings.PERSONALIZE_ANSWERS}")
    print(f"      VISION_TOTAL_TIMEOUT_S = {settings.VISION_TOTAL_TIMEOUT_S}")
    print(f"      LLM_TOTAL_TIMEOUT_S = {settings.LLM_TOTAL_TIMEOUT_S}")
    print(f"   🔑 API Keys: DEEPGRAM={'*' * 20 if settings.DEEPGRAM_API_KEY else 'Not Set'}")