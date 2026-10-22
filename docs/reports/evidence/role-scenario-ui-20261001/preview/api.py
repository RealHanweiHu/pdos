"""Run the unchanged API with explicitly synthetic config and no dotenv read."""
from app.settings import Settings

Settings.model_config["env_file"] = None

from app.main import app  # noqa: E402,F401
