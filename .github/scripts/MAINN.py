import os
import requests
import json
import base64
from sqlglot import parse_one, ParseError
from urllib.parse import urljoin

# Environment
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
GITHUB_EVENT_PATH = os.getenv("GITHUB_EVENT_PATH")
GITHUB_EVENT_NAME = os.getenv("GITHUB_EVENT_NAME")
REPO = os.getenv("GITHUB_REPOSITORY")

PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"
PERPLEXITY_MODEL = "sonar-pro"

# ---- Prompt Templates ----
PROMPT_CREATE_TABLE = (
    "You are a senior data engineer. Review the SQL which creates a table.\n"
    "1. Ensure proper usage of column types (e.g., NOT NULL where necessary).\n"
    "2. Suggest constraints like primary keys or uniqueness.\n"
    "3. Recommend default values or comments.\n"
    "4. Advise on best naming practices.\n"
)

PROMPT_INDEX = (
    "You are a database performance expert.\n"
    "Review any INDEX or CREATE INDEX statements:\n"
    "1. Suggest index types (e.g., composite, partial).\n"
    "2. Point out redundant or unused indexes.\n"
    "3. Recommend best practices for naming.\n"
    "4. Consider performance for large datasets.\n"
)

PROMPT_GENERAL_SQL = (
    "You are a SQL reviewer.\n"
    "1. Check for SELECT * usage\n"
    "2. Recommend JOIN optimizations\n"
    "3. Suggest formatting, aliases, and naming improvements\n"
)

# Select prompt based on content
def choose_prompt(sql_text):
    lower_sql = sql_text.lower()
    if "create table" in lower_sql:
        return PROMPT_CREATE_TABLE
    elif "index" in lower_sql or "create index" in lower_sql:
        return PROMPT_INDEX
    else:
        return PROMPT_GENERAL_SQL

# GitHub API
def post_comment(pr_number, message):
    url = f"https://api.github.com/repos/{REPO}/issues/{pr_number}/comments"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    payload = {"body": message}
    res = requests.post(url, headers=headers, json=payload)
    res.raise_for_status()

def get_changed_sql_files():
    with open(GITHUB_EVENT_PATH, "r") as f:
        event = json.load(f)

    if GITHUB_EVENT_NAME != "pull_request" or event.get("action") != "opened":
        print("Not a PR creation event.")
        return [], None

    pr_number = event.get("number")
    pr_url = event.get("pull_request", {}).get("url")
    if not pr_url or not pr_number:
        return [], None

    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    pr_files_url = urljoin(pr_url, "files")

    sql_files = []
    while pr_files_url:
        response = requests.get(pr_files_url, headers=headers)
        response.raise_for_status()
        for file_info in response.json():
            if file_info["filename"].endswith(".sql"):
                sql_files.append((file_info["filename"], file_info["raw_url"]))
        pr_files_url = response.links.get("next", {}).get("url")

    return sql_files, pr_number

# Content Utilities
def get_file_content(raw_url):
    response = requests.get(raw_url)
    response.raise_for_status()
    return response.text

def validate_sql_syntax(sql_text):
    try:
        parse_one(sql_text)
        return True, None
    except ParseError as e:
        return False, str(e)

def get_llm_suggestions(sql_text):
    prompt = choose_prompt(sql_text)
    final_prompt = f"{prompt}\n\nHere is the SQL:\n\n{sql_text}"

    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": PERPLEXITY_MODEL,
        "messages": [
            {"role": "system", "content": "You are an expert SQL code reviewer."},
            {"role": "user", "content": final_prompt}
        ],
        "max_tokens": 800
    }

    response = requests.post(PERPLEXITY_API_URL, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

def main():
    files, pr_number = get_changed_sql_files()
    if not files:
        print("No SQL files found.")
        return

    for filename, raw_url in files:
        print(f"🔍 Reviewing: {filename}")
        try:
            sql_content = get_file_content(raw_url)
        except Exception as e:
            post_comment(pr_number, f"❗ Failed to fetch `{filename}`: {str(e)}")
            continue

        syntax_valid, error = validate_sql_syntax(sql_content)
        if not syntax_valid:
            post_comment(pr_number, f"❌ **Syntax error in `{filename}`**:\n``````")
        else:
            print("✅ Syntax passed.")

        # Regardless of syntax, attempt LLM suggestion
        try:
            response = get_llm_suggestions(sql_content)
            comment = f"🧠 **Review Suggestions for `{filename}`**\n\n{response}"
            post_comment(pr_number, comment)
        except Exception as e:
            post_comment(pr_number, f"⚠️ Failed to get LLM suggestions for `{filename}`:\n``````")

if __name__ == "__main__":
    main()
