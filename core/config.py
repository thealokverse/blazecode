import os

from dotenv import load_dotenv

# Load variables from .env
load_dotenv()

# API key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Default model
MODEL = "gpt-4.1-mini"

# Agent settings
MAX_ITERATIONS = 10
