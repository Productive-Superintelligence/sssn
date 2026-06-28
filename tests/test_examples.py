import importlib.util
from pathlib import Path

from sssn import LocalStore


ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_channel_processor_example_reads_and_writes_channels(tmp_path):
    module = load_module(
        ROOT / "examples" / "channel_processor" / "processor.py",
        "channel_processor",
    )
    store = LocalStore(tmp_path / "store")
    store.create_channel({"name": "raw"})
    store.create_channel({"name": "analysis"})
    sub = store.create_subscription("raw")
    raw = store.append_event(
        {
            "channel": "raw",
            "payload": {"frame": 1},
            "correlation_id": "episode-1",
        }
    )

    outputs = module.process_once(store, subscription_id=sub.id)

    assert len(outputs) == 1
    assert outputs[0].channel == "analysis"
    assert outputs[0].parent_ids == (raw.id,)
    assert outputs[0].correlation_id == "episode-1"
    assert store.query_events("analysis")[0].payload["source_event_id"] == raw.id
