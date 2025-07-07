import os
import requests
import json
from sqlglot import parse_one, ParseError
from groq import Groq
from urllib.parse import urljoin

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GITHUB_EVENT_PATH = os.getenv("GITHUB_EVENT_PATH")
REPO = os.getenv("GITHUB_REPOSITORY")

client = Groq(api_key=GROQ_API_KEY)

def get_changed_sql_files():
    if not GITHUB_EVENT_PATH or not os.path.isfile(GITHUB_EVENT_PATH):
        print("GITHUB_EVENT_PATH is not set or file does not exist.")
        return [], None

    with open(GITHUB_EVENT_PATH, "r") as f:
        event = json.load(f)

    event_name = os.getenv("GITHUB_EVENT_NAME")

    files = []
    pr_number = None

    if event_name == "pull_request":
        pr_url = event.get("pull_request", {}).get("url")
        if not pr_url:
            print("No pull_request URL found in event payload.")
            return [], None

        pr_files_url = urljoin(pr_url, "files")
        headers = {"Authorization": f"token {GITHUB_TOKEN}"}

        while pr_files_url:
            res = requests.get(pr_files_url, headers=headers)
            res.raise_for_status()
            for fobj in res.json():
                if fobj["filename"].endswith(".sql"):
                    files.append((fobj["filename"], fobj["raw_url"]))
            pr_files_url = res.links.get("next", {}).get("url")

        pr_number = event.get("pull_request", {}).get("number")

    elif event_name == "push":
        # Get list of changed files from push event
        commit_sha = event.get("after")
        repo_owner, repo_name = REPO.split("/")
        headers = {"Authorization": f"token {GITHUB_TOKEN}"}

        url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/commits/{commit_sha}"
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        commit_data = res.json()

        for fobj in commit_data.get("files", []):
            if fobj["filename"].endswith(".sql"):
                files.append((fobj["filename"], None))  # raw_url not available here

    else:
        print(f"Unsupported event: {event_name}")
        return [], None

    return files, pr_number

# Your existing validate_sql_syntax, validate_sql_with_llm, post_comment functions remain

def main():
    files, pr_number = get_changed_sql_files()
    if not files:
        print("No SQL files changed.")
        return

    for filename, raw_url in files:
        print(f"Processing file: {filename}")
        if raw_url:
            sql = get_file_content(raw_url)
        else:
            print(f"No raw_url available for {filename}, skipping content fetch.")
            continue

        is_valid, error = validate_sql_syntax(sql)
        if not is_valid:
            comment = f"**SQL Syntax Error in `{filename}`:**\n\n``````"
            if pr_number:
                try:
                    post_comment(REPO, pr_number, comment)
                    print(f"Posted syntax error comment for {filename}")
                except Exception as e:
                    print(f"Failed to post syntax error comment for {filename}: {e}")
            continue

        try:
            suggestions = validate_sql_with_llm(sql)
            comment = f"**SQL Review Suggestions for `{filename}`:**\n\n{suggestions}"
            if pr_number:
                post_comment(REPO, pr_number, comment)
                print(f"Posted LLM suggestions for {filename}")
        except Exception as e:
            print(f"Failed to get/post LLM suggestions for {filename}: {e}")

if __name__ == "__main__":
    main()
