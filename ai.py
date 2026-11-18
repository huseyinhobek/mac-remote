"""Message -> tool calls. Local Claude Code CLI by default, or any OpenAI-compatible API."""
import json
import os
import subprocess
import tempfile

import httpx

PROMPT = """You plan tool calls for the user's Mac. You never run them; the app runs your plan.
Tools:
{tools}
Rules:
- Use only these tools and args. Several actions: several calls, in order.
- Request not covered by a tool: calls = [], reply names what you can do instead.
- reply: max one short sentence, in the user's language. Never write other content."""


def parse(cfg, text, tools_text, tool_names):
    schema = {"type": "object", "required": ["calls", "reply"], "properties": {
        "calls": {"type": "array", "items": {"type": "object", "required": ["tool", "args"], "properties": {
            "tool": {"type": "string", "enum": tool_names}, "args": {"type": "object"}}}},
        "reply": {"type": "string"}}}
    system = PROMPT.format(tools=tools_text)
    c = cfg.get("ai", {})
    if c.get("provider", "claude") == "claude":
        return _claude(c, system, text, schema)
    return _openai(c, system, text, schema)


def _claude(c, system, text, schema):
    # no tools, no MCP, no user settings/hooks: a plain, fast model call on your Claude login
    p = subprocess.run(
        ["claude", "-p", "--model", c.get("model", "sonnet"), "--tools", "", "--no-session-persistence",
         "--strict-mcp-config", "--setting-sources", "", "--output-format", "json",
         "--system-prompt", system, "--json-schema", json.dumps(schema)],
        input=text, capture_output=True, text=True, timeout=90, cwd=tempfile.gettempdir())
    try:
        d = json.loads(p.stdout)
    except ValueError:
        raise RuntimeError((p.stderr or p.stdout).strip()[-300:] or "claude failed") from None
    if d.get("is_error") or "structured_output" not in d:
        raise RuntimeError(str(d.get("result"))[:300])
    return d["structured_output"]


def _openai(c, system, text, schema):
    r = httpx.post(
        c["base_url"].rstrip("/") + "/chat/completions", timeout=60,
        headers={"Authorization": f"Bearer {os.environ[c.get('api_key_env', 'AI_API_KEY')]}"},
        json={"model": c["model"], "response_format": {"type": "json_object"}, "messages": [
            {"role": "system", "content": f"{system}\nAnswer only with JSON matching this schema: {json.dumps(schema)}"},
            {"role": "user", "content": text}]})
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])
