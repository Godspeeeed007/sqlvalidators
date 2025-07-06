import os
import requests
import json
from sqlglot import parse_one, ParseError
from groq import Groq

# Environment variables
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GITHUB_EVENT_PATH = os.getenv("GITHUB_EVENT_PATH")
REPO = os.getenv("GITHUB_REPOSITORY")

# Initialize Groq client
client = Groq(api_key=GROQ_API_KEY)

def get_changed_sql_files():
    if not GITHUB_EVENT_PATH or not os.path.isfile(GITHUB_EVENT_PATH):
        print("GITHUB_EVENT_PATH is not set or file does not exist.")
        return [], None

    with open(GITHUB_EVENT_PATH, "r") as f:
        event = json.load(f)

    files = []
    pr_files_url = event.get("pull_request", {}).get("url", "") + "/files"

    if pr_files_url:
        headers = {"Authorization": f"token {GITHUB_TOKEN}"}
        while pr_files_url:
            res = requests.get(pr_files_url, headers=headers)
            res.raise_for_status()
            for fobj in res.json():
                if fobj["filename"].endswith(".sql"):
