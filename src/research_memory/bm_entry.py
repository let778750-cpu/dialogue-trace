"""Small adapter for one Obsidian vault containing separately indexed BM projects.

Only project-root link prefixes are translated; relationship type, alias and source
remain upstream data. Upstream packages and user Markdown are never rewritten here.
"""
import sys
from .storage import Config


def project_reference(config, link):
    from .research_projects import ResearchProjects
    catalog = ResearchProjects(config)
    if not catalog.active:
        return link
    path, sep, alias = link.partition('|')
    path = path.replace('\\', '/')
    for project in catalog.records(examples=True):
        prefix = project['path'] + '/'
        if path.startswith(prefix):
            return project['bm_project'] + '::' + path[len(prefix):] + (sep + alias if sep else '')
    return link


def install(config):
    from .research_projects import ResearchProjects
    if not ResearchProjects(config).active:
        return
    from basic_memory.services.link_resolver import LinkResolver
    original = LinkResolver.resolve_link
    if getattr(original, '_research_adapter', False):
        return
    async def resolve(self, link_text, *args, **kwargs):
        return await original(self, project_reference(config, link_text), *args, **kwargs)
    resolve._research_adapter = True
    LinkResolver.resolve_link = resolve
    # v0.23.2 bulk indexing uses a separate exact-match resolver.
    from basic_memory.services.bulk_link_resolver import BulkLinkResolver
    original_bulk = BulkLinkResolver.resolve_relation_targets
    async def resolve_bulk(self, link_texts, *, session):
        translated = {text: project_reference(config, text) for text in link_texts}
        result = await original_bulk(self, list(translated.values()), session=session)
        return {text: result[converted] for text, converted in translated.items()}
    BulkLinkResolver.resolve_relation_targets = resolve_bulk


def main():
    from .basic_memory import configure
    config = Config()
    configure(config)
    install(config)
    from basic_memory.cli.main import app
    app()


if __name__ == '__main__':
    main()
