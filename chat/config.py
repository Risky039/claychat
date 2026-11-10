"""Runtime settings read from the environment (and one local, Git-ignored key file)."""

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
KEY_FILE = PROJECT_DIR / "deployment-private" / "meta_model_api_key"


def load_api_key(env=os.environ, key_file=KEY_FILE):
    """Prefer MODEL_API_KEY; fall back to the local key file; else empty (AI disabled)."""
    key = env.get("MODEL_API_KEY", "").strip()
    if key:
        return key
    if key_file.is_file():
        return key_file.read_text(encoding="utf-8").strip()
    return ""


@dataclass(frozen=True)
class Settings:
    api_key: str = ""
    model: str = "muse-spark-1.3"
    db_path: str = str(PROJECT_DIR / "data" / "chat.db")
    history_limit: int = 50

    @classmethod
    def from_env(cls, env=os.environ):
        return cls(
            api_key=load_api_key(env),
            model=env.get("META_MODEL", cls.model),
            db_path=env.get("CHAT_DB_PATH", cls.db_path),
            history_limit=_positive_int(env.get("CHAT_HISTORY_LIMIT"), cls.history_limit, maximum=200),
        )


def _positive_int(raw, default, maximum):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return min(value, maximum) if value > 0 else default

