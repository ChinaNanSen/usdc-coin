from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import load_config


def test_simulated_mode_switches_default_ws_urls(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
mode: live
exchange:
  simulated: true
  api_key: demo_key
  secret_key: demo_secret
  passphrase: demo_pass
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.exchange.public_ws_url == "wss://wspap.okx.com:8443/ws/v5/public"
    assert config.exchange.private_ws_url == "wss://wspap.okx.com:8443/ws/v5/private"


def test_telemetry_paths_resolve_from_config_scope(tmp_path, monkeypatch):
    project_root = tmp_path / "trend_bot_6"
    config_dir = project_root / "config"
    data_dir = project_root / "data"
    config_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    config_path = config_dir / "config.yaml"
    config_path.write_text(
        """
mode: shadow
telemetry:
  journal_path: data/journal.jsonl
  sqlite_path: trend_bot_6/data/audit.db
  state_path: data/state_snapshot.json
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    config = load_config(config_path, validate_live_credentials=False)

    assert Path(config.telemetry.journal_path) == data_dir / "journal.jsonl"
    assert Path(config.telemetry.sqlite_path) == project_root.parent / "trend_bot_6" / "data" / "audit.db"
    assert Path(config.telemetry.state_path) == data_dir / "state_snapshot.json"
