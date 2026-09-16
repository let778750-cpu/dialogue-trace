"""One presentation contract for notes, Bases and graph details."""
import html
import json
from datetime import datetime
import yaml

from .storage import atomic, digest, encode, file_hash, read_json, write_json
from .readability import TYPE_LABELS, REVIEW_LABELS, EVIDENCE_LABELS, RELATION_LABELS, wiki, rewrite_links, source_title
from .research_projects import ResearchProjects, HOME, SYSTEM

AUTHORS = {"user": "用户", "assistant": "AI", "assistant interpretation": "AI 整理与解释", "assistant observation": "AI 观测记录",
           "tool": "工具", "operator": "操作者", "synthetic-demo-program": "合成演示程序"}
RUN_STATES = {"completed": "运行完成", "failed": "运行失败", "cancelled": "已取消", "interrupted": "已中断", "unknown": "状态未知，待核实", "running": "运行中", "starting": "正在启动"}
PROGRESS = {"open": "待继续", "in_progress": "进行中", "completed": "已完成", "shelved": "已搁置", "cancelled": "已取消"}


def display(note, projects, runs=None):
    kind = note["type"]
    if kind == "idea":
        state = REVIEW_LABELS[note.get("human_review", "unreviewed")] + " · " + EVIDENCE_LABELS[note.get("evidence_status", "unassessed")]
    elif kind == "evidence":
        evidence = note.get("evidence", {})
        state = ("来源已核对" if evidence.get("verification") == "verified" else "来源待核对") + " · " + {
            "full_text": "全文", "abstract_only": "仅摘要", "metadata_only": "仅题录", "local_artifact": "本地产物"}.get(evidence.get("access_level"), "访问范围待记录")
    elif kind == "experiment":
        ids = note.get("run_ids", []) or ([note["run_id"]] if note.get("run_id") else [])
        states = list(dict.fromkeys(RUN_STATES.get((runs or {}).get(r, {}).get("status"), "运行待核实") for r in ids))
        state = ("、".join(states) if states else "尚无运行记录") + " · 科学结论未评估"
    elif kind == "decision":
        state = REVIEW_LABELS[note.get("human_review", "unreviewed")]
    else:
        state = PROGRESS.get(note.get("progress", "open"), "待继续")
        if kind == "task" and note.get("progress", "open") == "open":
            state = "待执行"
    return {"type": TYPE_LABELS[kind], "status": state,
            "authors": [AUTHORS.get(a, a) for a in note["authors"]],
            "project": projects.get(projects.note_project(note), disabled=True)["name"],
            "branch": projects.branch_name(note["workstream_id"])}


def run_cache(knowledge):
    if not hasattr(knowledge, "_presentation_runs"):
        from .runs import Runs
        knowledge._presentation_runs = {r["run_id"]: r for r in Runs(knowledge.store).reconcile()}
    return knowledge._presentation_runs


def render_note(knowledge, note, paths):
    projects = paths.projects
    known = {n["id"]: n for n in knowledge.records()}
    known.update(getattr(knowledge, "batch_records", {}))
    known[note["id"]] = note
    p = projects.get(projects.note_project(note), disabled=True)
    d = display(note, projects, run_cache(knowledge))
    metadata = {k: note[k] for k in ("id", "title", "type", "workstream_id", "version", "updated_at", "human_review", "evidence_status")}
    metadata.update(research_project_id=p["id"], project_name=p["name"], project_kind=p["kind"],
                    authors=note["authors"], conditions=note["conditions"], source_event_ids=[s["event_id"] for s in note["sources"]],
                    permalink="notes/" + note["id"], tags=["research", note["type"]], cssclasses=["research-note"],
                    aliases=list(dict.fromkeys([note["id"], *note.get("aliases", [])])),
                    display_status=d["status"], display_authors=d["authors"], workstream_name=d["branch"])
    parts = ["---", yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip(), "---", "",
             wiki(HOME, "科研工作台") + " / " + wiki(p["path"] + "/项目首页.md", p["name"]), "", "# " + note["title"], "",
             f"{d['type']} · {d['status']}", "", f"提出者：{'、'.join(d['authors'])}　｜　研究分支：{d['branch']}", "",
             rewrite_links(note["body"], paths.value["aliases"]), "", "## 适用条件", ""]
    parts.extend(["- " + c for c in note["conditions"]] or ["尚未记录适用条件。"])
    if note["type"] == "experiment":
        parts += ["", "## 实际运行", ""]
        ids = note.get("run_ids", []) or ([note["run_id"]] if note.get("run_id") else [])
        for r in ids:
            state = run_cache(knowledge).get(r, {})
            rel = paths.value.get("runs", {}).get(r)
            title = state.get("title", "实验运行")
            parts.append("- " + (wiki(rel, title) if rel else title) + " · " + RUN_STATES.get(state.get("status"), "待核实"))
        if not ids:
            parts.append("尚无运行记录。")
    if evidence := note.get("evidence"):
        from pathlib import Path
        url = evidence['url']
        if Path(url).is_absolute():
            url = Path(url).as_uri()
        citation = '[查看证据资料](<' + url + '>)' if url.startswith(('https://', 'http://', 'file:///')) else url
        parts += ["", "## 证据内容", "", f"来源：{citation}", "", f"位置：{evidence['locator']}", "",
                  "> " + evidence["excerpt"].replace("\n", "\n> "), "", "来源核对与是否支持某个假设分别判断。"]
    parts += ["", "## 原话与来源", ""]
    for source in note["sources"]:
        parts.append("- " + wiki(paths.source(source["event_id"]), source_title(knowledge.store.get(source["event_id"]))) + ": " + source.get("quote", source.get("locator", "公开记录")))
    parts += ["", "## 关联关系", ""]
    outgoing = [(note, r, known.get(r["target"])) for r in note.get("relations", [])]
    incoming = [(n, r, note) for n in known.values() if n["id"] != note["id"] for r in n.get("relations", []) if r["target"] == note["id"]]
    if not outgoing and not incoming:
        parts.append("尚未建立关系。")
    for heading, relations in (("从本条出发", outgoing), ("指向本条", incoming)):
        if not relations:
            continue
        parts += ["### " + heading, ""]
        for src, relation, target in relations:
            left = "本条" if src["id"] == note["id"] else wiki(paths.note(src["id"], src["title"], src), src["title"])
            right = "目标缺失，待核实" if target is None else ("本条" if target["id"] == note["id"] else wiki(paths.note(target["id"], target["title"], target), target["title"]))
            middle = " — " + RELATION_LABELS[relation["type"]] + (" — " if relation["type"] == "related_to" else " → ")
            # Outgoing canonical predicates remain parseable by Basic Memory; our
            # Obsidian postprocessor localizes them. Incoming lines aren't assertions.
            text = ("- " + relation['type'] + " " + right) if src['id'] == note['id'] else ("- " + left + middle + right)
            context = []
            if relation.get("basis"):
                context.append("依据：" + relation["basis"])
            if relation.get("conditions"):
                context.append("条件：" + "、".join(relation["conditions"]))
            if target and projects.note_project(src) != projects.note_project(target):
                context.append("跨项目")
            if context:
                text += ' (' + '；'.join(context).replace('(', '（').replace(')', '）') + ')'
            parts.append(text)
        parts.append("")
    audit = f"稳定标识：{note['id']}\n修订：{note['version']} · {note['updated_at']}\n规范提出者：{'、'.join(note['authors'])}"
    parts += ["", "<details><summary>溯源与修订信息</summary><pre>" + html.escape(audit) + "</pre></details>"]
    return "\n".join(parts) + "\n"


def base_definition(project):
    def formula(field, labels):
        expression = '"未记录"'
        for key, label in reversed(list(labels.items())):
            expression = f'if({field} == "{key}", "{label}", {expression})'
        return expression
    columns = {"formula.note_link": "名称", "formula.type_label": "类型", "note.display_status": "当前状态", "formula.author_label": "提出者",
               "note.workstream_name": "研究分支", "formula.review_label": "人工审阅", "formula.evidence_label": "证据状态", "note.updated_at": "最近更新"}
    views = [{"type": "table", "name": "全部知识", "order": ["formula.note_link", "formula.type_label", "note.display_status", "formula.author_label", "note.workstream_name"]}]
    for kind, label in TYPE_LABELS.items():
        order = ["formula.note_link", "note.display_status", "formula.author_label", "note.workstream_name"]
        if kind == "idea":
            order = ["formula.note_link", "formula.review_label", "formula.evidence_label", "formula.author_label", "note.workstream_name"]
        views.append({"type": "table", "name": label, "filters": {"and": [f'type == "{kind}"']}, "order": order})
    return {"filters": {"and": [f'research_project_id == "{project}"', 'file.hasTag("research")', 'file.ext == "md"']},
            "formulas": {"note_link": 'link(file.path, title)', "author_label": 'list(display_authors).join("、")', "type_label": formula("type", TYPE_LABELS), "review_label": formula("human_review", REVIEW_LABELS), "evidence_label": formula("evidence_status", EVIDENCE_LABELS)},
            "properties": {k: {"displayName": v} for k, v in columns.items()}, "views": views}


def managed_write(store, relative, content, title=None):
    """Generated navigation has the same human-edit guard as generated knowledge."""
    path = store.config.directory("vault") / relative
    if path.suffix == ".md":
        if content.startswith("---\n"):
            _, frontmatter, body = content.split("---", 2)
            metadata = yaml.safe_load(frontmatter) or {}
        else:
            metadata, body = {"type": "navigation"}, "\n\n" + content
        metadata.setdefault("title", path.stem)
        if title:
            metadata['title'] = title
        metadata.setdefault('cssclasses', ['research-note'])
        metadata.setdefault("permalink", "views/" + digest(relative.encode())[:24])
        content = "---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip() + "\n---" + body
    manifest_path = store.data / "navigation-views.json"
    manifest = read_json(manifest_path, {})
    before = manifest.get(relative)
    if path.suffix == '.base' and path.exists():
        def semantics(text):
            value = yaml.safe_load(text)
            for view in value.get('views', []):
                view['order'] = [key.removeprefix('note.') for key in view.get('order', [])]
            return value
        # Obsidian rewrites YAML and strips note. from view orders. Accept only
        # complete semantic equality; user filters/layout changes remain protected.
        if semantics(path.read_text(encoding='utf-8')) == semantics(content):
            actual = file_hash(path)
            if manifest.get(relative) != actual:
                manifest[relative] = actual
                write_json(manifest_path, manifest)
            return
    if path.exists() and before == digest(content.encode('utf-8')) and file_hash(path) == before:
        return
    if path.exists() and (not before or file_hash(path) != before):
        from .storage import Conflict
        write_json(store.data / 'conflicts' / ('navigation-' + digest(relative.encode())[:20] + '.json'),
                   {'path':relative,'disk_hash':file_hash(path),'proposed_view':content})
        raise Conflict("Navigation was edited; merge before regeneration: " + relative)
    atomic(path, content.encode("utf-8"))
    manifest[relative] = file_hash(path)
    write_json(manifest_path, manifest)


def views(knowledge, project=None):
    projects = ResearchProjects(knowledge.store.config)
    from .readability import ViewPaths, clean_name
    paths = ViewPaths(knowledge.store)
    records = knowledge.records()
    runs = run_cache(knowledge)
    selected = [projects.get(project)] if project else projects.records(examples=True, disabled=True)
    # Prepare run links before any project/knowledge view references them.
    for r, state in runs.items():
        owner = state["research_project_id"]
        p = projects.get(owner, disabled=True)
        mapping = paths.value.setdefault("runs", {})
        if r not in mapping:
            stem = clean_name(state.get("created_at", "")[:10] + " " + state["title"], 72)
            target = p["path"] + "/知识记录/实验/运行记录/" + stem + ".md"
            count = 1
            while target in mapping.values():
                count += 1
                target = p["path"] + "/知识记录/实验/运行记录/" + stem + f"（{count}）.md"
            mapping[r] = target
        folder = knowledge.store.config.directory("runs") / r
        intent = read_json(folder / "intent.json")
        params = json.dumps(intent["spec"]["parameters"], ensure_ascii=False, indent=2)
        text = f"---\ntype: run-view\nresearch_project_id: {owner}\ncssclasses: [research-note]\n---\n\n" + wiki(p["path"] + "/项目首页.md", p["name"]) + f"\n\n# {state['title']}\n\n{RUN_STATES[state['status']]} · 科学结论未评估\n\n目的：{intent['spec']['purpose']}\n\n开始时间：{intent['created_at']}\n\n## 参数\n\n```json\n{params}\n```\n\n## 日志与工件\n\n"
        for file in [folder / "stdout.log", folder / "stderr.log", folder / "intent.json", folder / "result.json", *sorted((folder / "artifacts").rglob("*"))]:
            if file.is_file():
                text += f"- [{file.name}]({file.as_uri()})\n"
        if state.get("artifact_drift"):
            text += "\n工件已变化，需核实：" + "、".join(state["artifact_drift"]) + "\n"
        text += "\n<details><summary>运行身份</summary><pre>" + html.escape(r) + "</pre></details>\n"
        managed_write(knowledge.store, mapping[r], text)
    paths.save()
    home = ["# 科研工作台", "", "按研究项目继续讨论、查看候选想法并核实实验。", "", "## 研究项目", ""]
    for p in projects.records():
        members = [n for n in records if projects.note_project(n) == p["id"]]
        home += ["### " + wiki(p["path"] + "/项目首页.md", p["name"]), "", p["goal"], "", f"已启用 · {len(members)} 条知识记录", ""]
    home += ["> [!info]- 示例与维护", "> " + wiki(SYSTEM + "/记录状态.md", "采集、整理与索引状态")]
    home += ["> - " + wiki(p["path"] + "/项目首页.md", p["name"]) + ("（已停用）" if not p["enabled"] else "（示例）")
             for p in projects.records(examples=True, disabled=True) if p["kind"] == "example" or not p["enabled"]]
    managed_write(knowledge.store, HOME, "\n".join(home) + "\n")
    for p in selected:
        projects.scaffold(p["id"])
        members = [n for n in records if projects.note_project(n) == p["id"]]
        parts = ["# " + p["name"], "", wiki(HOME, "科研工作台"), "", p["goal"], "",
                 ("已启用" if p["enabled"] else "已停用") + f" · {len(members)} 条知识记录", "",
                 wiki(p["path"] + "/研究记录表.base", "全部研究记录") + "　·　" +
                 wiki(p["path"] + "/对话与来源/会话索引.md", "对话与来源"), ""]
        if p["kind"] == "example":
            parts += ["> 示例与验收资料，不构成真实科研结论。", ""]
        parts += ["## 下一步", ""]
        has_steps = False
        for w, owner in projects.value["branches"].items():
            if owner == p["id"]:
                steps = read_json(knowledge.store.data / "checkpoints" / (w + ".json"), {}).get("data", {}).get("next_steps", [])
                if steps:
                    has_steps = True
                    parts += ["### " + projects.branch_name(w), "", *["- " + s for s in steps], ""]
        if not has_steps:
            parts += ["尚未记录下一步；从一个具体问题开始。", ""]
        parts += ["## 最近更新", ""]
        recent = sorted(members, key=lambda n: (n.get("updated_at", ""), n["id"]), reverse=True)[:5]
        for n in recent:
            d = display(n, projects, runs)
            parts.append("- " + wiki(paths.note(n["id"], n["title"], n), n["title"]) + " · " + d["type"] + " · " + d["status"])
        if not recent:
            parts.append("尚无知识记录。")
        parts += ["", wiki(p["path"] + "/研究记录表.base", f"查看全部 {len(members)} 条记录"), ""]
        managed_write(knowledge.store, p["path"] + "/项目首页.md", "\n".join(parts), p['name'] + ' · 项目首页')
        managed_write(knowledge.store, p["path"] + "/研究记录表.base", yaml.safe_dump(base_definition(p["id"]), allow_unicode=True, sort_keys=False))
        timeline = ["# 对话与来源", "", wiki(p["path"] + "/项目首页.md", p["name"]), "", "此索引列出已生成的原文阅读页；整理进度另行记录。", ""]
        grouped = {}
        for event, path in paths.value["sources"].items():
            if projects.event_project(knowledge.store.get(event)["event"]) == p["id"]:
                grouped.setdefault(str(path.rsplit("/", 1)[0]).split("/对话与来源/")[-1], []).append((event, path))
        for session, items in sorted(grouped.items()):
            timeline += ["## " + session, ""]
            timeline += ["- " + wiki(path, source_title(knowledge.store.get(e))) for e, path in sorted(items, key=lambda pair: knowledge.store.get(pair[0])["event"].get("occurred_at") or "")]
            timeline.append("")
        managed_write(knowledge.store, p["path"] + "/对话与来源/会话索引.md", "\n".join(timeline), p['name'] + ' · 对话与来源')
    paths.save()
    conflicts = refresh_notes(knowledge, paths)
    health = knowledge.store.status()
    text = f"# 记录状态\n\n{wiki(HOME, '科研工作台')}\n\n已采集 {health['captured']} 条事件；已整理 {health['organized']} 条；待整理 {health['pending']} 条。事件包括工具记录，不等于候选想法数量。\n\nHooks：{health['hooks']['state']}\n\n索引：{health['index']['state']}\n\n这是生成视图时的快照，实时状态请使用 status。\n"
    managed_write(knowledge.store, SYSTEM + "/记录状态.md", text)
    from .graph_view import publish_projection
    graph = publish_projection(knowledge)
    return {"notes": len(records), "home": str(knowledge.vault / HOME), "graph": graph, 'view_conflicts': conflicts}


def refresh_notes(knowledge, paths=None):
    """Refresh reverse links/status only when the previous published view is intact."""
    from .readability import ViewPaths
    from .storage import now
    conflicts = []
    with knowledge.store.lock('knowledge'):
        paths = paths or ViewPaths(knowledge.store)
        for note in knowledge.records():
            path = knowledge.vault / note['path']
            text = render_note(knowledge, note, paths).encode('utf-8')
            actual = file_hash(path) if path.is_file() else None
            if actual != note['published_hash'] or note.get('needs_semantic_reconciliation'):
                conflicts.append(note['id'])
                write_json(knowledge.store.data / 'conflicts' / ('view-' + note['id'] + '.json'),
                           {'note_id': note['id'], 'disk_hash': actual, 'proposed_view': text.decode(), 'at': now()})
                continue
            if digest(text) != actual:
                note.update(published_hash=digest(text), view_updated_at=now())
                write_json(knowledge.store.data / 'view-revisions' / note['id'] / (note['published_hash'] + '.json'), note)
                atomic(path, text)
                write_json(knowledge.store.data / 'notes' / (note['id'] + '.json'), note)
        paths.save()
    return conflicts
