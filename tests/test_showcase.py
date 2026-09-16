import importlib.util
from pathlib import Path
import pytest
from research_memory.storage import Config, Store
from research_memory.event_detail import inspect_event


def test_public_showcase_is_synthetic_and_preserves_existing_instance(tmp_path):
    package = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('showcase', package/'scripts/showcase.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.create(tmp_path/'example')
    store = Store(Config(tmp_path/'example'))
    detail = inspect_event(store, result['tool_result'])
    assert result['synthetic_only'] is True
    assert result['sessions'] == 2
    assert detail['outputs'][0]['value']['sample_kind'] == 'synthetic'
    assert detail['outputs'][0]['value']['stable'] is False
    assert detail['inputs'][0]['name'] == 'analyze_stability'
    before = (store.config.root/'config.json').read_bytes()
    with pytest.raises(ValueError, match='preserved'):
        module.create(store.config.root)
    assert (store.config.root/'config.json').read_bytes() == before
