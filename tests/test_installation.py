from pathlib import Path
import pytest
from research_memory.storage import Config, Store, Conflict, read_json, write_json
from research_memory.installation import setup, configure_host, uninstall


def test_setup_repeat_uninstall_preserves_private_data(tmp_path,monkeypatch):
    package=Path(__file__).resolve().parents[1]
    monkeypatch.setenv('RESEARCH_MEMORY_PACKAGE_ROOT',str(package))
    # A simulated package location outside this test's private instance.
    monkeypatch.setenv('RESEARCH_MEMORY_PACKAGE_ROOT',str(tmp_path/'软件 包'))
    workspace=tmp_path/'中文 工作区';workspace.mkdir()
    root=tmp_path/'私有 数据'
    result=setup(root,workspace)
    assert result['automatic_capture']=='not_verified'
    assert not (root/'vault/.obsidian').exists()
    config=Config(root);id=config.project_id
    identity_path=root/'vault/系统视图/research-memory-identity.json'
    identity=read_json(identity_path)
    assert identity['project_id']==id and identity['vault_instance']
    assert setup(root,workspace)['state']=='existing_preserved'
    assert read_json(identity_path)==identity
    assert Config(root).project_id==id
    private=root/'vault/private.md';private.write_text('保留')
    uninstall(config)
    assert private.read_text()=='保留'
    assert (root/'data/registry.json').exists()
    assert 'mcp_servers.research_memory' not in (workspace/'.codex/config.toml').read_text()


def test_existing_foreign_vault_identity_is_not_overwritten(tmp_path,monkeypatch):
    monkeypatch.setenv('RESEARCH_MEMORY_PACKAGE_ROOT',str(tmp_path/'package'))
    workspace=tmp_path/'workspace';workspace.mkdir()
    root=tmp_path/'private';setup(root,workspace)
    path=root/'vault/系统视图/research-memory-identity.json'
    foreign={'project_id':'another-archive','vault_instance':'retain-me'}
    write_json(path,foreign)
    with pytest.raises(Conflict,match='another archive'):
        setup(root,workspace)
    assert read_json(path)==foreign


def test_host_conflict_preserves_existing_settings(store,tmp_path):
    workspace=tmp_path/'workspace';workspace.mkdir()
    config=workspace/'.codex/config.toml';config.parent.mkdir()
    original='[mcp_servers.research_memory]\ncommand = "someone-else"\nargs = []\n'
    config.write_text(original)
    with pytest.raises(Conflict):
        configure_host(store.config,workspace)
    assert config.read_text()==original
    assert not (workspace/'.codex/hooks.json').exists()


def test_registered_external_inputs_only(store,tmp_path):
    external=tmp_path/'registered';external.mkdir()
    store.config.value['workspaces']=[str(external)]
    assert store.config.input_path(external/'input.py')==external/'input.py'
    with pytest.raises(ValueError):
        store.config.input_path(Path(tmp_path.anchor)/'unregistered/input.py')


def test_new_instance_unrelated_task_does_not_activate_capture(tmp_path,monkeypatch):
    from research_memory.capture import hook
    from research_memory.continuity import Continuity
    monkeypatch.setenv('RESEARCH_MEMORY_PACKAGE_ROOT',str(tmp_path/'skill-package'))
    workspace=tmp_path/'workspace';workspace.mkdir()
    root=tmp_path/'data';setup(root,workspace)
    store=Store(Config(root))
    ordinary=dict(hook_event_name='UserPromptSubmit',cwd=str(workspace),session_id='unrelated',prompt='普通无关任务',turn_id='turn-a')
    assert hook(store,ordinary)=={'continue':True}
    assert store.status()['captured']==0
    # A relevant skill invocation explicitly enters this task, then reconciles its first prompt.
    Continuity(store).bind(workspace,'research-task','main')
    hook(store,dict(ordinary,session_id='research-task',prompt='研究新的对照条件'))
    assert store.status()['captured']==1
