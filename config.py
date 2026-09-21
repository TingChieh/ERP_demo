from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent


def load_local_config(path=None):
    """Load local environment values without overriding existing variables."""
    dotenv_path = Path(path) if path is not None else BASE_DIR / ".env"
    load_dotenv(dotenv_path=dotenv_path, override=False)
