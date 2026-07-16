"""Production composition root. Invalid configuration or release fails startup."""

from __future__ import annotations

from sadar.api.factory import create_app
from sadar.api.settings import Settings
from sadar.releases.approach import load_release_directory

settings = Settings()
release = load_release_directory(settings.release_dir)
app = create_app(settings, release)
