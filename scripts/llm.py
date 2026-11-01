"""Model backends for AI Radar, tried in order until one succeeds.

Backends are configured with AIRADAR_BACKENDS (comma-separated), e.g.
    opencode:opencode-go/deepseek-v4.1-flash,claude:sonnet,openrouter:deepseek/deepseek-v4-flash

- opencode:<provider/model>  — headless `opencode run` (OpenCode Go subscription).
  Uses the official client rather than raw HTTP: Go's terms scope it to OpenCode
  and coding agents.
- claude:<model>             — headless `claude -p` (Claude subscription).
- openrouter:<model>         — OpenRouter chat completions (pay-as-you-go credits).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BACKENDS = "opencode:opencode-go/deepseek-v4.1-flash,claude:sonnet"
TIMEOUT_S = 900
HOME = Path.home()
OPENCODE_BIN = shutil.which("opencode") or str(HOME / ".opencode" / "bin" / "opencode")
CLAUDE_BIN = shutil.which("claude") or str(HOME / ".local" / "bin" / "claude")


class BackendError(RuntimeError):
    pass


def backends() -> list[tuple[str, str]]:
    spec = os.environ.get("AIRADAR_BACKENDS", DEFAULT_BACKENDS)
    out = []
    for entry in spec.split(","):
        kind, _, model = entry.strip().partition(":")
        if kind and model:
            out.append((kind, model))
    return out


def _run(cmd: list[str], prompt: str) -> str:
    # Empty working dir so agent CLIs don't pick up project files or instructions.
    with tempfile.TemporaryDirectory(prefix="airadar-") as cwd:
        try:
            r = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                               cwd=cwd, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired as e:
            raise BackendError(f"timeout after {TIMEOUT_S}s") from e
    if r.returncode != 0 and not r.stdout.strip():
        raise BackendError(f"exit {r.returncode}: {r.stderr.strip()[:300]}")
    return r.stdout


def _opencode(model: str, prompt: str) -> str:
    out = _run([OPENCODE_BIN, "run", "--pure", "-m", model, "--format", "json",
                "--title", "ai-radar (auto)"], prompt)
    texts, errors, session_ids = [], [], set()
    for line in out.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("sessionID"):
            session_ids.add(event["sessionID"])
        if event.get("type") == "text":
            texts.append(event.get("part", {}).get("text", ""))
        elif event.get("type") == "error":
            errors.append(event.get("error", {}).get("data", {}).get("message", "unknown error"))
    # Every `opencode run` creates a session that shows up in the user's
    # Desktop/remote session list; remove ours so the pipeline leaves no clutter.
    for sid in session_ids:
        subprocess.run([OPENCODE_BIN, "session", "delete", sid],
                       capture_output=True, timeout=60)
    if errors:
        raise BackendError(errors[0][:300])
    if not texts:
        raise BackendError("no text in opencode output")
    return "".join(texts)


def _claude(model: str, prompt: str) -> str:
    out = _run([CLAUDE_BIN, "-p", "--model", model, "--output-format", "json"], prompt)
    try:
        data = json.loads(out)
    except json.JSONDecodeError as e:
        raise BackendError(f"unparseable claude output: {out[:200]}") from e
    if data.get("is_error"):
        raise BackendError(str(data.get("result"))[:300])
    return data.get("result", "")


def _openrouter(model: str, prompt: str, api_key: str) -> str:
    if not api_key:
        raise BackendError("OPENROUTER_API_KEY missing")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens": 16000,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/ethan-m25/ai-radar",
            "X-Title": "AI Radar",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise BackendError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from e
    if not data.get("choices"):
        raise BackendError(f"no choices: {str(data)[:300]}")
    return data["choices"][0]["message"]["content"]


def complete(prompt: str, *, secrets: dict, log) -> tuple[str, str, list[str]]:
    """Return (text, backend label used, failures from earlier backends)."""
    failures: list[str] = []
    for kind, model in backends():
        label = f"{kind}:{model}"
        log(f"  → {label} — sending {len(prompt)} chars...")
        try:
            if kind == "opencode":
                text = _opencode(model, prompt)
            elif kind == "claude":
                text = _claude(model, prompt)
            elif kind == "openrouter":
                text = _openrouter(model, prompt, secrets.get("OPENROUTER_API_KEY", ""))
            else:
                raise BackendError(f"unknown backend kind '{kind}'")
        except (BackendError, OSError) as e:
            log(f"  ⚠️ {label} failed: {e}")
            failures.append(f"{label}: {e}")
            continue
        log(f"  ← {label}: {len(text)} chars")
        return text, label, failures
    raise BackendError("all backends failed — " + " | ".join(failures))
