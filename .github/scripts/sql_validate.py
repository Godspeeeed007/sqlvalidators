import os
import requests
import json
import base64
from sqlglot import parse_one, ParseError
from groq import Groq
from urllib.parse import urljoin

# Environment variables
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GITHUB_EVENT_PATH = os.getenv("GITHUB_EVENT_PATH")
REPO = os.getenv("GITHUB_REPOSITORY")

if not all([GITHUB_TOKEN, GROQ_API_KEY, GITHUB_EVENT_PATH, REPO]):
    print("Missing one or more required environment variables: GITHUB_TOKEN, GROQ_API_KEY, GITHUB_EVENT_PATH, REPO")
    exit(1)

client = Groq(api_key=GROQ_API_KEY)

def get_available_groq_models():
    url = "https://api.groq.com/openai/v1/models"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    models = resp.json()
    # Pick a preferred model, e.g., first LLaMA model or fallback to first available
    for model in models.get("data", []):
        model_id = model.get("id", "")
        if "llama" in model_id.lower():
            return model_id
    return models.get("data", [])[0].get("id") if models.get("data") else None

def get_changed_sql_files():
    if not os.path.isfile(GITHUB_EVENT_PATH):
        print("GITHUB_EVENT_PATH does not exist.")
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
        commit_sha = event.get("after")
        repo_owner, repo_name = REPO.split("/")
        headers = {"Authorization": f"token {GITHUB_TOKEN}"}

        url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/commits/{commit_sha}"
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        commit_data = res.json()

        for fobj in commit_data.get("files", []):
            if fobj["filename"].endswith(".sql"):
                files.append((fobj["filename"], None))  # raw_url not available for push

    else:
        print(f"Unsupported event: {event_name}")
        return [], None

    return files, pr_number

def get_file_content(raw_url):
    res = requests.get(raw_url)
    res.raise_for_status()
    return res.text

def get_file_content_from_push(repo_owner, repo_name, file_path, commit_sha):
    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{file_path}?ref={commit_sha}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    res = requests.get(url, headers=headers)
    res.raise_for_status()
    content_json = res.json()
    content = base64.b64decode(content_json['content']).decode('utf-8')
    return content

def validate_sql_syntax(sql_text):
    try:
        parse_one(sql_text)
        return True, None
    except ParseError as e:
        return False, str(e)

def validate_sql_with_llm(sql_text, model):
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You're a SQL expert. Validate and suggest improvements to the SQL code."},
            {"role": "user", "content": sql_text}
        ],
        max_tokens=500
    )
    # Correctly access the first choice's message content
    return response.choices[0].message.content

def post_comment(repo, pr_number, body):
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    data = {"body": body}
    res = requests.post(url, headers=headers, json=data)
    res.raise_for_status()

def main():
    model = get_available_groq_models()
    if not model:
        print("No available Groq models found. Exiting.")
        exit(1)
    print(f"Using Groq model: {model}")

    files, pr_number = get_changed_sql_files()
    if not files:
        print("No SQL files changed.")
        return

    repo_owner, repo_name = REPO.split("/")
    commit_sha = None
    if os.getenv("GITHUB_EVENT_NAME") == "push":
        with open(GITHUB_EVENT_PATH, "r") as f:
            event = json.load(f)
        commit_sha = event.get("after")

    for filename, raw_url in files:
        print(f"Processing file: {filename}")
        if raw_url:
            sql = get_file_content(raw_url)
        else:
            sql = get_file_content_from_push(repo_owner, repo_name, filename, commit_sha)

        is_valid, error = validate_sql_syntax(sql)
        if not is_valid:
            comment = f"**SQL Syntax Error in `{filename}`:**\n\n``````"
            if pr_number:
                try:
                    post_comment(REPO, pr_number, comment)
                    print(f"Posted syntax error comment for {filename}")
                except Exception as e:
                    print(f"Failed to post syntax error comment for {filename}: {e}")
            else:
                print(comment)  # For push events, print to logs
            continue

        try:
            suggestions = validate_sql_with_llm(sql, model)
            comment = f"**SQL Review Suggestions for `{filename}`:**\n\n{suggestions}"
            if pr_number:
                post_comment(REPO, pr_number, comment)
                print(f"Posted LLM suggestions for {filename}")
            else:
                print(comment)  # For push events, print to logs
        except Exception as e:
            print(f"Failed to get/post LLM suggestions for {filename}: {e}")

if __name__ == "__main__":
    main()
