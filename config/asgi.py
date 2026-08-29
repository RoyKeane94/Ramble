import os
from pathlib import Path

from dotenv import load_dotenv
from django.core.asgi import get_asgi_application

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_asgi_application()
