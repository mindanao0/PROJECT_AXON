"""Model and effort per agent: a cost/quality dial the user owns. Empty means the CLI's own default.

A value resolves task override > [agents] setting in config.toml > the CLI default. Only Claude and Codex take
these (the local model has its own [local] section, the fake agent has nothing to choose)."""

import json
import re
import tomllib
from pathlib import Path

EFFORTS = {"claude": ("low", "medium", "high", "xhigh", "max"), "codex": ("low", "medium", "high", "xhigh", "max", "ultra")}
# Claude accepts aliases and full ids; these are suggestions, any well-formed id is passed through to the CLI.
CLAUDE_MODELS = ("sonnet", "opus", "haiku", "claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-haiku-4-5-20251001")
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\[\]-]{0,79}$")
AGENTS = tuple(EFFORTS)


def known_models(agent, home=None):
    """Suggestions for the GUI: Claude's list is fixed, Codex's comes from the models its CLI cached."""
    if agent == "claude":
        return list(CLAUDE_MODELS)
    try:
        cache = json.loads((Path(home) / "codex" / "models_cache.json").read_text())
        return [m["slug"] for m in cache.get("models", cache) if isinstance(m, dict) and m.get("visibility") == "list"]
    except (OSError, ValueError, TypeError, AttributeError):
        return []


def validate(agent, model="", effort=""):
    """(model, effort) normalised, or ValueError. '' keeps the CLI default."""
    if agent not in AGENTS:
        raise ValueError(f"{agent} has no model or effort setting")
    model, effort = (model or "").strip(), (effort or "").strip().lower()
    if model and not MODEL_RE.match(model):
        raise ValueError("model must be letters, digits and . _ : [ ] - only (max 80 characters)")
    if effort and effort not in EFFORTS[agent]:
        raise ValueError(f"effort for {agent} must be one of: {', '.join(EFFORTS[agent])}")
    return model, effort


def effective(cfg, agent, model=None, effort=None):
    """What an attempt passes to the CLI: the task's own value, else the [agents] setting, else '' (CLI default)."""
    a = cfg.get("agents", {})
    return (model or a.get(f"{agent}_model", "") or ""), (effort or a.get(f"{agent}_effort", "") or "")


def flags(agent, model, effort):
    """Command-line arguments for the CLI; nothing when both are the default."""
    if agent == "claude":
        return [*(["--model", model] if model else []), *(["--effort", effort] if effort else [])]
    if agent == "codex":
        return [*(["-m", model] if model else []), *(["-c", f"model_reasoning_effort={json.dumps(effort)}"] if effort else [])]
    return []


def dump(cfg):
    """Config holds only tables of scalars and scalar lists, so JSON syntax is valid TOML."""
    out = []
    for section, values in cfg.items():
        out.append(f"[{section}]")
        out += [f"{k} = {json.dumps(v)}" for k, v in values.items()]
        out.append("")
    return "\n".join(out)


def save(config_file, agent, model, effort):
    """Write the agent's setting into config.toml (atomically, keeping every other section)."""
    model, effort = validate(agent, model, effort)
    f = Path(config_file)
    cfg = tomllib.loads(f.read_text()) if f.exists() else {}
    cfg.setdefault("agents", {}).update({f"{agent}_model": model, f"{agent}_effort": effort})
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(dump(cfg))
    tmp.replace(f)
    return model, effort
