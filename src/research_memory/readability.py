"""Readable projections, independent of immutable research/event identities."""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import html
import json
from pathlib import Path, PurePosixPath
import re
import unicodedata

from .storage import atomic, digest, encode, read_json, safe_id, write_json

TYPE_LABELS = {"question": "问题", "idea": "候选想法", "evidence": "证据", "experiment": "实验", "task": "验证任务", "decision": "决策"}
RELATION_LABELS = {"derived_from": "来源", "extends": "延伸", "depends_on": "依赖", "supports": "支持", "contradicts": "反驳", "refines": "细化", "replaces": "替代", "related_to": "相关", "tests": "验证", "adopts": "采用", "rejects": "否决"}
REVIEW_LABELS = {"unreviewed": "未审阅", "accepted": "人工认可", "rejected": "未认可", "needs_revision": "待修订"}
EVIDENCE_LABELS = {"unassessed": "待评估", "unsupported": "尚无支持", "supported": "有证据支持", "mixed": "证据不一致", "contradicted": "存在反证"}
AUTHOR_LABELS = {"user": "用户提问", "assistant": "AI 公开记录", "tool": "工具结果"}


def clean_name(value, length=64):
    value = unicodedata.normalize("NFC", str(value))
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .")[:length].rstrip(" .") or "未命名记录"
    if re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", value):
        value = "记录-" + value
    return value


def display_text(value):
    return re.sub(r"[\[\]|\r\n]", " ", str(value)).strip()


def wiki(path, title):
    return "[[" + str(path).replace("\\", "/").removesuffix(".md") + "|" + display_text(title) + "]]"


def rewrite_links(text, aliases):
    """Rewrite current wiki destinations, preserving display text and literal code."""
    def replace(match):
        target, sep, label = match.group(1).partition("|")
        path, anchor, fragment = target.partition("#")
        extension = path.endswith(".md")
        new = aliases.get(path if extension else path + ".md")
        if not new:
            return match.group(0)
        return "[[" + (new if extension else new.removesuffix(".md")) + (anchor + fragment if anchor else "") + (sep + label if sep else "") + "]]"
    result, fence = [], None
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            result.append(line)
        elif fence:
            result.append(line)
        else:
            chunks = re.split(r"(`+[^`\n]*`+)", line)
            result.append("".join(chunk if i % 2 else re.sub(r"\[\[([^\]\n]+)\]\]", replace, chunk) for i, chunk in enumerate(chunks)))
    return "".join(result)


def public_parts(payload):
    """Preserve exposed text blocks in order; do not serialize image data as prose."""
    if isinstance(payload, str):
        return [("text", payload)]
    if not isinstance(payload, dict):
        return [("text", json.dumps(payload, ensure_ascii=False, indent=2))]
    content = payload.get("content")
    if isinstance(content, list):
        result = []
        for item in content:
            if not isinstance(item, dict):
                result.append(("text", str(item)))
            elif item.get("type") in {"input_image", "image", "image_url", "attachment_reference"} or "attachment_hash" in item:
                result.append(("attachment", item))
            elif isinstance(item.get("text"), str):
                result.append(("text", item["text"]))
            else:
                result.append(("text", json.dumps(item, ensure_ascii=False, indent=2)))
        return result
    if isinstance(payload.get("text"), str):
        # Supplementary structured fields remain in the canonical event, accessible in audit details.
        return [("text", payload["text"])]
    return [("text", json.dumps(payload, ensure_ascii=False, indent=2))]


def source_title(envelope):
    event = envelope["event"]
    author = AUTHOR_LABELS.get(event.get("author"), "工具记录" if event["kind"].startswith("tool") else "研究记录")
    text = "\n".join(value for kind, value in public_parts(event["payload"]) if kind == "text")
    if "## My request:" in text:
        text = text.split("## My request:", 1)[1]
    lines = [re.sub(r"^[#>*\s-]+", "", s).strip() for s in text.splitlines()]
    topic = next((s for s in lines if s and not s.startswith(("<image", "</image", "{", "```", "http", "Files mentioned"))), "公开内容")
    topic = clean_name(topic, 24)
    raw_time = event.get("occurred_at") or envelope.get("captured_at")
    try:
        value = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        date = value.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H-%M") if value.tzinfo else value.strftime("%Y-%m-%d %H-%M")
    except (ValueError, TypeError, AttributeError):
        date = "时间未记录"
    return f"{author} · {topic} · {date}"


class ViewPaths:
    def __init__(self, store, value=None):
        self.store = store
        self.vault = store.config.directory("vault")
        self.file = store.data / "view-paths.json"
        self.value = value if value is not None else read_json(self.file, {"schema_version": 1, "enabled": False, "notes": {}, "sources": {}, "aliases": {}})
        self.before = deepcopy(read_json(self.file, {}))
        from .research_projects import ResearchProjects
        self.projects = ResearchProjects(store.config)

    def validate(self, path):
        if self.value.get("schema_version", 1) >= 2:
            return self.projects.validate_path(path)
        path = str(path).replace("\\", "/")
        parts = path.split("/")
        if len(parts) != 2 or parts[0] not in {"Notes", "Sources"} or not path.endswith(".md") or any(c in parts[1] for c in ':*?"<>|') or parts[1].startswith(".") or parts[1].rstrip(" .") != parts[1] or any(ord(c) < 32 for c in path):
            raise ValueError("Invalid research view path")
        if not (self.vault / path).resolve().is_relative_to(self.vault.resolve()):
            raise ValueError("Research path escapes vault")
        return path

    def allocate(self, kind, identity, title, record=None):
        safe_id(identity)
        section, folder = ("notes", "Notes") if kind == "note" else ("sources", "Sources")
        if identity in self.value[section]:
            return self.validate(self.value[section][identity])
        if self.value.get("schema_version", 1) >= 2:
            from .research_projects import TYPE_FOLDERS
            if kind == "note":
                record = record or read_json(self.store.data / "notes" / (identity + ".json"))
                if not record:
                    raise ValueError("A structured note requires its project and type before allocating a path")
                project = self.projects.note_project(record)
                folder = self.projects.get(project, disabled=True)["path"] + "/知识记录/" + TYPE_FOLDERS[record["type"]]
            else:
                event = self.store.get(identity)["event"]
                project = self.projects.event_project(event)
                stamp = event.get("occurred_at") or "时间未记录"
                month = stamp[:7] if len(stamp) >= 7 else "时间未记录"
                sessions = self.value.setdefault("sessions", {})
                key = project + ":" + event["session_id"]
                if key not in sessions:
                    siblings = [x for k, x in sessions.items() if k.startswith(project + ":")]
                    sessions[key] = "会话 " + str(len(siblings) + 1).zfill(2)
                folder = self.projects.get(project, disabled=True)["path"] + "/对话与来源/" + month + "/" + sessions[key]
            used = {p.casefold() for p in self.value[section].values()}
            used.update(p.relative_to(self.vault).as_posix().casefold() for p in (self.vault / folder).glob("*.md"))
            stem = clean_name(title, length=60)
            candidate = f"{folder}/{stem}.md"
            number = 1
            while candidate.casefold() in used:
                number += 1
                candidate = f"{folder}/{stem}（{number}）.md"
            self.value[section][identity] = self.validate(candidate)
            return candidate
        if not self.value["enabled"]:
            return f"{folder}/{identity}.md"
        used = {p.casefold() for p in self.value[section].values()}
        used.update(p.relative_to(self.vault).as_posix().casefold() for p in (self.vault / folder).glob("*.md"))
        stem = clean_name(title)
        candidate = f"{folder}/{stem}.md"
        suffix = digest(identity.encode())[:8]
        number = 0
        while candidate.casefold() in used:
            number += 1
            candidate = f"{folder}/{stem} · {suffix}{('-'+str(number)) if number > 1 else ''}.md"
        self.value[section][identity] = self.validate(candidate)
        return candidate

    def note(self, identity, title=None, record=None):
        if identity in self.value["notes"]:
            return self.validate(self.value["notes"][identity])
        if record and record.get("path"):
            return self.validate(record["path"])
        return self.allocate("note", identity, title or identity, record)

    def source(self, event_id):
        return self.allocate("source", event_id, source_title(self.store.get(event_id)))

    def save(self):
        # Independent source/note publishers may have read the same old map.
        # Merge disjoint additions; never silently discard another window's IDs.
        from .storage import Conflict
        def merge(before, proposed, current):
            result = deepcopy(current)
            for key in before.keys() | proposed.keys():
                if key in before and key in proposed and before[key] == proposed[key]:
                    continue
                if all(isinstance(v.get(key), dict) for v in (before, proposed, current)):
                    result[key] = merge(before[key], proposed[key], current[key])
                elif current.get(key) != before.get(key) and current.get(key) != proposed.get(key):
                    raise Conflict('View path changed in another window: ' + key)
                elif key in proposed:
                    result[key] = deepcopy(proposed[key])
                else:
                    result.pop(key, None)
            return result
        with self.store.lock('view-path-map'):
            current = read_json(self.file, {})
            result = merge(self.before, self.value, current)
            for section in ('notes', 'sources', 'runs'):
                paths = [p.casefold() for p in result.get(section, {}).values()]
                if len(paths) != len(set(paths)):
                    raise Conflict('Concurrent view filename collision; reload paths before retry')
            if result != current:
                write_json(self.file, result)
            self.value, self.before = result, deepcopy(result)


def render_source(store, envelope, path, title, permalink=None):
    import yaml
    event = envelope["event"]
    header = {"title": title, "type": "source", "tags": ["raw-source"], "cssclasses": ["research-source"],
              "event_id": event["event_id"], "canonical_sha256": envelope["content_hash"], "aliases": [event["event_id"]],
              "permalink": permalink or "sources/" + event["event_id"].replace("_", "-")}
    from .research_projects import ResearchProjects
    projects = ResearchProjects(store.config)
    owner = projects.event_project(event)
    project = projects.get(owner, disabled=True) if projects.active else None
    if project:
        header.update(research_project_id=owner, project_kind=project["kind"], project_name=project["name"])
    blocks = ["---", yaml.safe_dump(header, allow_unicode=True, sort_keys=False).strip(), "---", "", "# " + title, "",
              "公开原始内容 · " + AUTHOR_LABELS.get(event.get("author"), event.get("author") or "来源记录"), ""]
    if project:
        blocks += [wiki(project["path"] + "/项目首页.md", project["name"]), "",
                   "发生时间：" + (event.get("occurred_at") or "来源未提供") + "　｜　场景：" + {"message": "对话", "tool_result": "工具结果", "source": "资料读取"}.get(event["kind"], "研究操作"), ""]
    attachments = []
    for kind, value in public_parts(event["payload"]):
        if kind == "text":
            # Host image delimiters are transport scaffolding, not the user's prose.
            if not re.fullmatch(r"\s*</?image(?:\s[^>]*)?>\s*", value):
                blocks += [value, ""]
            continue
        reference = value.get("reference") or value.get("image_url") or value.get("url") or ""
        if isinstance(reference, dict):
            reference = reference.get("url", "")
        match = re.fullmatch(r"data:image/(png|jpeg|jpg|gif|webp);base64,([A-Za-z0-9+/=\r\n]+)", reference)
        if match and len(match[2]) <= 70_000_000:
            try:
                content = base64.b64decode(match[2], validate=True)
            except ValueError:
                content = None
            if content:
                folder = project["path"] + "/附件" if project else "Attachments"
                name = f"{folder}/图片-{digest(content)[:16]}.{match[1].replace('jpeg','jpg')}"
                target = store.config.directory("vault") / name
                if target.exists() and target.read_bytes() != content:
                    raise ValueError("Attachment digest collision")
                attachments.append((name, content))
                blocks += ["![[" + name + "]]", ""]
                continue
        if reference.startswith(("https://", "http://")):
            blocks += ["附件引用：" + reference, ""]
        else:
            blocks += ["附件保留在完整事件记录中（未生成可预览副本）。", ""]
    audit = {key: event.get(key) for key in ("event_id", "author", "kind", "source", "occurred_at", "source_sequence", "session_id", "workstream_id", "completeness")}
    audit.update(captured_at=envelope["captured_at"], content_hash=envelope["content_hash"], canonical_file="data/events/" + event["event_id"] + ".json")
    blocks += ["<details><summary>溯源与采集信息</summary><pre>" + html.escape(json.dumps(audit, ensure_ascii=False, indent=2)) + "</pre><p>完整事件保存在项目目录的 data/events 中；此页为可重建阅读视图。</p></details>", ""]
    return "\n".join(blocks), attachments
