"""
Cursor Cloud Agents API – setup and usage.

The Cloud Agents API is for launching AI agents that work on your GitHub repos
(list agents, launch agent with a prompt, get status, conversation, etc.).
It does NOT provide chat completions; use OpenAI (or compatible) for that.

Docs: https://cursor.com/docs/cloud-agent/api/endpoints
Auth: Basic Auth with API key as username, empty password.
"""

import base64
import os
import sys

try:
    import requests
except ImportError:
    print("Install requests: pip install requests")
    sys.exit(1)

# Set your Cursor API key: Cursor Dashboard → Integrations, or https://cursor.com/docs/api
# Option A: set here (keep private, do not commit)
HARDCODED_CURSOR_API_KEY = ""  # e.g. "key_xxxxxxxx..."
# Option B: env var: export CURSOR_API_KEY="key_xxx..."
CURSOR_API_KEY = HARDCODED_CURSOR_API_KEY or os.getenv("CURSOR_API_KEY", "").strip() or None
CURSOR_BASE = "https://api.cursor.com"


def _auth_headers():
    if not CURSOR_API_KEY:
        raise ValueError(
            "Set CURSOR_API_KEY (env var or in this file). "
            "Get it from: Cursor Dashboard → Integrations"
        )
    token = base64.b64encode(f"{CURSOR_API_KEY}:".encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def cursor_get(path: str, params: dict = None):
    """GET a Cursor Cloud Agents API endpoint."""
    url = f"{CURSOR_BASE}{path}"
    r = requests.get(url, headers=_auth_headers(), params=params, timeout=30)
    r.raise_for_status()
    return r.json() if r.content else {}


def cursor_post(path: str, json_body: dict):
    """POST to a Cursor Cloud Agents API endpoint."""
    url = f"{CURSOR_BASE}{path}"
    r = requests.post(url, headers=_auth_headers(), json=json_body, timeout=30)
    r.raise_for_status()
    return r.json() if r.content else {}


# --- Example: list agents ---
def list_agents(limit: int = 20, cursor: str = None):
    """List cloud agents. See https://cursor.com/docs/cloud-agent/api/endpoints#list-agents"""
    params = {"limit": limit}
    if cursor:
        params["cursor"] = cursor
    return cursor_get("/v0/agents", params=params)


# --- Example: get agent status ---
def get_agent(agent_id: str):
    """Get agent status and details."""
    return cursor_get(f"/v0/agents/{agent_id}")


# --- Example: launch agent (requires a GitHub repo URL) ---
def launch_agent(
    prompt_text: str,
    repository: str,
    ref: str = "main",
    auto_create_pr: bool = False,
    branch_name: str = None,
    model: str = None,
):
    """
    Launch a cloud agent to work on your repo.

    :param prompt_text: Task for the agent (e.g. "Add a README with installation steps")
    :param repository: GitHub repo URL (e.g. "https://github.com/your-org/your-repo")
    :param ref: Branch/tag/commit (default: main)
    :param auto_create_pr: Create a PR when done
    :param branch_name: Custom branch name for the agent
    :param model: Optional model (e.g. claude-4-sonnet). Omit for auto.
    """
    body = {
        "prompt": {"text": prompt_text},
        "source": {"repository": repository, "ref": ref},
        "target": {"autoCreatePr": auto_create_pr},
    }
    if branch_name:
        body["target"]["branchName"] = branch_name
    if model:
        body["model"] = model
    return cursor_post("/v0/agents", body)


# --- Example: get agent conversation ---
def get_agent_conversation(agent_id: str):
    """Get the conversation (prompts + assistant replies) for an agent."""
    return cursor_get(f"/v0/agents/{agent_id}/conversation")


# --- Example: API key info ---
def me():
    """Check your API key (name, email)."""
    return cursor_get("/v0/me")


# --- Example: list available models ---
def list_models():
    """List models you can use for agents."""
    return cursor_get("/v0/models")


def main():
    if not CURSOR_API_KEY:
        print("Set CURSOR_API_KEY in env or in this file, then run again.")
        print("Example: export CURSOR_API_KEY='key_xxx...'")
        return

    print("Cursor Cloud Agents API – quick check\n")

    # 1) Verify key
    try:
        info = me()
        print("API key info:", info)
    except Exception as e:
        print("Auth failed:", e)
        return

    # 2) List models
    try:
        models = list_models()
        print("Models:", models.get("models", []))
    except Exception as e:
        print("List models error:", e)

    # 3) List your agents
    try:
        data = list_agents(limit=5)
        agents = data.get("agents", [])
        print(f"\nRecent agents ({len(agents)}):")
        for a in agents[:5]:
            print(f"  - {a.get('id')} | {a.get('name')} | {a.get('status')}")
    except Exception as e:
        print("List agents error:", e)

    # Uncomment to launch an agent (replace repo URL and prompt):
    # result = launch_agent(
    #     prompt_text="Add a short README with setup instructions",
    #     repository="https://github.com/YOUR_ORG/YOUR_REPO",
    #     ref="main",
    #     auto_create_pr=True,
    # )
    # print("Launched:", result)


if __name__ == "__main__":
    main()
