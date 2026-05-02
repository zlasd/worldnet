#!/usr/bin/env python3
"""Initialize the database."""
import sys

sys.path.insert(0, ".")

from app.core.config import settings
from app.db.init_db import init_db

if __name__ == "__main__":
    print(f"Initializing database: {settings.database_url}")
    init_db()
    print("Database initialized successfully.")
