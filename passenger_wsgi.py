"""cPanel/Phusion Passenger entry point. Passenger looks for `application` here."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import create_app

application = create_app()
