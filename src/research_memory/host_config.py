"""Add a project MCP entry without rewriting user-owned TOML settings."""
import json
import re
import tomllib
from .storage import atomic, Conflict, Store


def ensure_mcp_server(config, name, settings):
    with Store(config).lock("mcp-config"):
        return _ensure_mcp_server(config, name, settings)


def _ensure_mcp_server(config, name, settings):
    if not re.fullmatch(r"[a-zA-Z0-9_]+", name):
        raise ValueError("Invalid MCP server name")
    path = config.root / ".codex/config.toml"
    original = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    parsed = tomllib.loads(original)
    existing = parsed.get("mcp_servers", {}).get(name)
    if existing is not None:
        if any(existing.get(key) != settings.get(key) for key in ("command", "args")):
            raise Conflict(f"Existing MCP entry {name} uses a different launch command; preserved")
        return "existing_settings_preserved"
    section = f"\n[mcp_servers.{name}]\n"
    for key, value in settings.items():
        if not re.fullmatch(r"[a-zA-Z0-9_]+", key):
            raise ValueError("Invalid MCP setting name")
        # MCP launcher values here use the JSON/TOML common scalar and array subset.
        section += key + " = " + json.dumps(value, ensure_ascii=False) + "\n"
    candidate = original.rstrip() + "\n" + section
    if tomllib.loads(candidate)["mcp_servers"][name] != settings:
        raise ValueError("MCP settings failed TOML round trip")
    atomic(path, candidate.encode("utf-8"))
    return "added"


def exportable(config, source):
    relative = source.relative_to(config.root)
    if not source.resolve().is_relative_to(config.root) or not source.is_file():
        return False
    parts = tuple(part.casefold() for part in relative.parts)
    # Plugin state may contain API tokens and private keys; reinstall from tools instead.
    if ".obsidian" in parts and "plugins" in parts:
        return False
    return source.suffix not in {".lock", ".sqlite"} and "catalog.sqlite" not in source.name
