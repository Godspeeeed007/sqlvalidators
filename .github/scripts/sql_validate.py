import os, subprocess, sys
from github import Github
import openai

openai.api_key = os.getenv("OPENAI_API_KEY")
gh = Github(os.getenv("GITHUB_TOKEN"))

# Fetch PR info
repo = gh.get_repo(os.getenv("GITHUB_REPOSITORY"))
pr_number = int(os.getenv("GITHUB_REF").split("/")[-2])
pr = repo.get_pull(pr_number)

# Determine changed .sql files in the PR diff
base = os.getenv("BASE_BRANCH", "main")
subprocess.run(f"git fetch origin {base}", shell=True, check=True)
diff = subprocess.getoutput(f"git diff --name-only origin/{base}")
sql_files = [f.strip() for f in diff.splitlines() if f.strip().endswith(".sql")]

if not sql_files:
    print("✅ No SQL files changed.")
    sys.exit(0)

print(f"🔍 Validating {len(sql_files)} SQL file(s): {sql_files}")

# Iterate each file
all_comments = []
for path in sql_files:
    # Read file
    try:
        with open(path, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        continue

    # LLM prompt
    prompt = (
        "You are an expert SQL LLM. Review the following SQL code and provide:\n"
        "- Syntax issues\n"
        "- Logical errors\n"
        "- Security risks (e.g., SQL injection)\n"
        "- Performance issues\n"
        "- Suggestions or improvements\n\n"
        f"SQL:\n```\n{content}\n```"
    )

    resp = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    review = resp.choices[0].message.content
    print(f"✏️ Review for {path}:\n{review}\n")

    comment = f"### AI SQL Review for `{path}`\n\n{review}"
    all_comments.append(comment)

# Post a single comment to the PR
pr.create_issue_comment(
    "## 🤖 AI-Powered SQL Validation Results\n\n" +
    "\n---\n\n".join(all_comments)
)

# Optionally, exit with failure if issues found
if any("error" in c.lower() or "issue" in c.lower() for c in all_comments):
    print("❌ SQL issues found.")
    sys.exit(1)

print("✅ SQL validation passed.")
