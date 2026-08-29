#!/usr/bin/env python3
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def main():
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
