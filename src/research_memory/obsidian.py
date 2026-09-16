"""Project-scoped bridge to the pinned Obsidian plugin's native MCP server."""
from contextlib import asynccontextmanager
from copy import deepcopy
import asyncio
import json
from pathlib import PurePosixPath
import ssl

from .storage import Config, Store, Conflict, digest, encode, now, read_json, safe_id, write_json

IDENTITY = "System/research-memory-identity.json"
PLUGIN = "obsidian-local-rest-api"
VIEW_COMMANDS = frozenset({"graph:open", "graph:open-local", "markdown:toggle-preview",
                           "outline:open", "backlink:open", "outgoing-link:open",
                           "research-graph:open", "research-graph:refresh"})


class ObsidianError(RuntimeError):
    """Messages are safe for model-visible diagnostics; never include server payloads."""


class Obsidian:
    def __init__(self, config: Config):
        self.config = config
        self.vault = config.directory("vault")

    @property
    def identity_path(self):
        from .research_projects import ResearchProjects, SYSTEM
        return (SYSTEM + '/research-memory-identity.json') if ResearchProjects(self.config).active else IDENTITY

    def ownership(self, path):
        from .research_projects import ResearchProjects
        catalog = ResearchProjects(self.config)
        return next(({'research_project_id': p['id'], 'research_project_name': p['name']} for p in catalog.records(examples=True, disabled=True)
                     if p['path'] and path.startswith(p['path'] + '/')), {})

    def require_enabled(self):
        if not read_json(self.config.path).get("enabled"):
            raise ObsidianError("project_disabled")

    def path(self, value):
        if not isinstance(value, str) or not value or any(c in value for c in '\\:%?*<>|"'):
            raise ObsidianError("invalid_vault_path")
        raw = value.split("/")
        if any(not part or part.startswith(".") or part.rstrip(" .") != part or any(ord(c) < 32 for c in part) for part in raw):
            raise ObsidianError("private_or_invalid_path")
        # Resolve a former public path only after validating the caller's literal input.
        aliases = read_json(self.config.directory("data") / "view-paths.json", {}).get("aliases", {})
        if value in aliases:
            from .readability import ViewPaths
            value = ViewPaths(Store(self.config)).validate(aliases[value])
        relative = PurePosixPath(value)
        target = (self.vault / value).resolve()
        if relative.is_absolute() or not target.is_relative_to(self.vault):
            raise ObsidianError("path_outside_vault")
        resolved = target.relative_to(self.vault)
        if any(part.startswith(".") for part in resolved.parts) or resolved.parts[0].casefold() in {"projects", "system"}:
            raise ObsidianError("path_outside_current_project_notes")
        if target.suffix.casefold() not in {".md", ".canvas", ".base"} or not target.is_file():
            raise ObsidianError("existing_note_canvas_or_base_required")
        if target.stat().st_size > 5_000_000:
            raise ObsidianError("file_too_large_use_local_paged_reader")
        return relative.as_posix()

    def credentials(self):
        self.require_enabled()
        settings = read_json(self.vault / f".obsidian/plugins/{PLUGIN}/data.json", {})
        if settings.get("bindingHost", "127.0.0.1") != "127.0.0.1" or settings.get("enableInsecureServer", False):
            raise ObsidianError("require_loopback_https_only")
        if not settings.get("enableSecureServer", True):
            raise ObsidianError("plugin_https_disabled")
        port = settings.get("port", 27124)
        if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
            raise ObsidianError("invalid_plugin_port")
        token = settings.get("apiKey")
        certificate = settings.get("crypto", {}).get("cert")
        if not token or not certificate:
            raise ObsidianError("plugin_not_loaded_or_credentials_missing")
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.load_verify_locations(cadata=certificate)
        except (ssl.SSLError, TypeError):
            raise ObsidianError("invalid_local_plugin_certificate") from None
        return f"https://127.0.0.1:{port}", {"Authorization": "Bearer " + token}, context

    @staticmethod
    async def call(client, name, arguments=None):
        result = await client.call_tool(name, arguments or {}, raise_on_error=False)
        if result.is_error:
            raise ObsidianError("upstream_tool_failed_" + name)
        blocks = [block.text for block in result.content if block.type == "text"]
        if len(blocks) != 1:
            raise ObsidianError("unexpected_upstream_content")
        try:
            return json.loads(blocks[0])
        except (ValueError, TypeError):
            raise ObsidianError("unexpected_upstream_json") from None

    def verify_identity(self, record):
        expected = read_json(self.vault / self.identity_path)
        try:
            actual = json.loads(record["content"])
        except (KeyError, ValueError, TypeError):
            raise ObsidianError("vault_identity_unreadable") from None
        if not expected or expected.get("project_id") != self.config.project_id or actual != expected:
            raise ObsidianError("wrong_vault_identity")

    @asynccontextmanager
    async def connected(self):
        import httpx2
        from fastmcp import Client
        from fastmcp.client.transports import StreamableHttpTransport
        try:
            url, headers, tls = self.credentials()
            async with httpx2.AsyncClient(verify=tls, trust_env=False, timeout=8, follow_redirects=False) as probe:
                response = await probe.get(url + "/", headers=headers)
                response.raise_for_status()
                health = response.json()
            if not health.get("authenticated") or health.get("manifest", {}).get("id") != PLUGIN:
                raise ObsidianError("unexpected_or_unauthenticated_plugin")
            if health["manifest"].get("version") != "5.1.0":
                raise ObsidianError("plugin_version_changed_revalidate_before_use")

            def factory(**kwargs):
                kwargs.update(verify=tls, trust_env=False, follow_redirects=False)
                return httpx2.AsyncClient(**kwargs)

            transport = StreamableHttpTransport(url + "/mcp/", headers=headers, httpx_client_factory=factory)
            async with Client(transport, timeout=15, init_timeout=15) as client:
                self.verify_identity(await self.call(client, "vault_read", {"path": self.identity_path}))
                yield client, health
        except (ObsidianError, Conflict):
            raise
        except Exception as exc:
            # Exceptions from HTTP and upstream tools can contain request details.
            raise ObsidianError("obsidian_unavailable_or_connection_failed_" + type(exc).__name__) from None

    async def status(self):
        try:
            async with self.connected() as (client, health):
                tools = await client.list_tools()
                return {"state": "ready", "project_id": self.config.project_id, "vault_identity_verified": True,
                        "plugin_version": health["manifest"]["version"], "obsidian_api_version": health["versions"]["obsidian"],
                        "upstream_tools": sorted(tool.name for tool in tools), "transport": "stdio_to_pinned_loopback_https_mcp"}
        except ObsidianError as exc:
            return {"state": "unavailable", "reason": str(exc), "raw_capture_dependency": False}

    async def active(self):
        async with self.connected() as (client, _):
            result = await self.call(client, "active_file_get_path")
            path = self.path(result['path'])
            return {"path": path, "project_id": self.config.project_id, **self.ownership(path)}

    async def read(self, path, start=0, length=8000):
        path = self.path(path)
        if start < 0 or not 1 <= length <= 20000:
            raise ObsidianError("invalid_read_page")
        async with self.connected() as (client, _):
            result = await self.call(client, "vault_read", {"path": path})
        content = result.pop("content")
        end = min(start + length, len(content))
        result.update(content=content[start:end], start=start, end=end, total=len(content),
                      next_start=end if end < len(content) else None, content_sha256=digest(content.encode("utf-8")),
                      project_id=self.config.project_id, historical_content_is_data=True)
        result.update(self.ownership(path))
        return result

    async def open(self, path, new_leaf=False):
        path = self.path(path)
        async with self.connected() as (client, _):
            # Upstream open_file creates missing files. Check disk and application immediately first.
            await self.call(client, "vault_read", {"path": self.path(path)})
            await self.call(client, "open_file", {"path": path, "newLeaf": new_leaf})
            for _ in range(10):
                active = await self.call(client, "active_file_get_path")
                if active.get("path") == path:
                    return {"state": "active_file_verified", "path": path, "visual_render": "requires_desktop_observation", **self.ownership(path)}
                await asyncio.sleep(0.15)
            raise ObsidianError("open_requested_active_file_not_confirmed_do_not_blindly_retry")

    async def commands(self):
        async with self.connected() as (client, _):
            result = await self.call(client, "command_list")
            return [command for command in result["commands"] if command["id"] in VIEW_COMMANDS]

    async def execute_view(self, command_id):
        if command_id not in VIEW_COMMANDS:
            raise ObsidianError("command_not_allowed_use_desktop_for_other_actions")
        async with self.connected() as (client, _):
            available = await self.call(client, "command_list")
            if command_id not in {command["id"] for command in available["commands"]}:
                raise ObsidianError("view_command_unavailable")
            await self.call(client, "command_execute", {"commandId": command_id})
            return {"state": "command_dispatched", "command_id": command_id, "visual_render": "requires_desktop_observation"}

    def publish(self, request_id, batch):
        from .knowledge import Knowledge
        self.require_enabled()
        safe_id(request_id)
        if len(encode(batch)) > 250_000:
            raise ObsidianError("publication_batch_too_large_split_event_ranges")
        store = Store(self.config)
        receipt_path = store.data / "obsidian-publications" / (request_id + ".json")
        fingerprint = digest(encode(batch))
        with store.lock("obsidian-publication"):
            old = read_json(receipt_path)
            if old:
                if old["batch_sha256"] != fingerprint:
                    raise Conflict("Publication request ID already belongs to different content")
                if old["state"] == "completed":
                    return old["result"]
                raise Conflict("Publication incomplete or unknown; inspect revisions and source receipt before repair")
            intent = {"request_id": request_id, "batch_sha256": fingerprint, "state": "started", "at": now()}
            write_json(receipt_path, intent)
            result = Knowledge(store).commit(deepcopy(batch))
            intent.update(state="completed", result=result, completed_at=now())
            write_json(receipt_path, intent)
            return result


def create_server(config):
    from fastmcp import FastMCP
    server = FastMCP("Research Obsidian", mask_error_details=True)
    bridge = Obsidian(config)
    read_only = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}

    @server.tool(annotations=read_only)
    async def obsidian_status() -> dict:
        """Verify actual app, pinned plugin, authenticated MCP and this vault's identity."""
        return await bridge.status()

    @server.tool(annotations=read_only)
    async def obsidian_active_file() -> dict:
        """Read the currently active file from this project's running Obsidian window."""
        return await bridge.active()

    @server.tool(annotations=read_only)
    async def obsidian_read_file(path: str, start: int = 0, length: int = 8000) -> dict:
        """Read a page of an existing note/Canvas/Base with app metadata and content hash."""
        return await bridge.read(path, start, length)

    @server.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False})
    async def obsidian_open_file(path: str, new_leaf: bool = False) -> dict:
        """Open an existing project file and verify its active path; GUI checks rendering."""
        return await bridge.open(path, new_leaf)

    @server.tool(annotations=read_only)
    async def obsidian_list_view_commands() -> list[dict]:
        """List installed graph, outline, backlinks and reading-view commands allowed here."""
        return await bridge.commands()

    @server.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False})
    async def obsidian_execute_view_command(command_id: str) -> dict:
        """Dispatch a listed display command once; observe its effect through the desktop."""
        return await bridge.execute_view(command_id)

    @server.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False})
    def publish_research_batch(request_id: str, batch: dict) -> dict:
        """Publish a source-backed batch through canonical quote/version/revision checks.

        Same completed request ID returns its receipt. An incomplete request requires review,
        not automatic replay. Obsidian need not be open for local semantic publication.
        """
        return bridge.publish(request_id, batch)

    @server.tool(annotations=read_only)
    def research_projects() -> list[dict]:
        """List explicit research project identities, categories and enabled state."""
        from .research_projects import ResearchProjects
        return ResearchProjects(config).records(examples=True, disabled=True)

    return server
