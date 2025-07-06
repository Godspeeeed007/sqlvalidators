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
                    files.append((fobj["filename"], fobj["raw_url"]))
            pr_files_url = res.links.get("next", {}).get("url")
    pr_number = event.get("pull_request", {}).get("number")
    return files, pr_number

def get_file_content(raw_url):
    res = requests.get(raw_url)
    res.raise_for_status()
    return res.text

def validate_sql_syntax(sql_text):
    try:
        parse_one(sql_text)
        return True, None
    except ParseError as e:
        return False, str(e)

def validate_sql_with_llm(sql_text):
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You're a SQL expert. Validate and suggest improvements to the SQL code."},
            {"role": "user", "content": sql_text}
        ],
        max_tokens=500
    )
    return response.choices.message.content

def post_comment(repo, pr_number, body):
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    data = {"body": body}
    res = requests.post(url, headers=headers, json=data)
    res.raise_for_status()

def main():
    files, pr_number = get_changed_sql_files()
    if not files or not pr_number:
        print("No SQL files changed or not a pull request event.")
        return

    for filename, raw_url in files:
        print(f"Processing file: {filename}")
        sql = get_file_content(raw_url)
        is_valid, error = validate_sql_syntax(sql)
        if not is_valid:
            comment = (
                f"**SQL Syntax Error in `{filename}`:**\n\n"
                f"``````"
            )
            try:
                post_comment(REPO, pr_number, comment)
                print(f"Posted syntax error comment for {filename}")
            except Exception as e:
                print(f"Failed to post syntax error comment for {filename}: {e}")
            continue

        try:
            suggestions = validate_sql_with_llm(sql)
            comment = (
                f"**SQL Review Suggestions for `{filename}`:**\n\n"
                f"``````"
            )
            post_comment(REPO, pr_number, comment)
            print(f"Posted LLM suggestions for {filename}")
        except Exception as e:
            print(f"Failed to get/post LLM suggestions for {filename}: {e}")

if __name__ == "__main__":
    main()
