import os

from config import load_local_config


def test_load_local_config_reads_values_from_dotenv_file(tmp_path, monkeypatch):
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "DEEPSEEK_API_KEY=test-local-key\nDEEPSEEK_MODEL=deepseek-chat\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)

    load_local_config(dotenv_path)

    assert os.environ["DEEPSEEK_API_KEY"] == "test-local-key"
    assert os.environ["DEEPSEEK_MODEL"] == "deepseek-chat"
