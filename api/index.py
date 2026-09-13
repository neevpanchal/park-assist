import os
import sys

# Ensure project root is on Python's search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app

# Vercel's Python runtime requires WSGI callable 'app'
if __name__ == "__main__":
    app.run()
