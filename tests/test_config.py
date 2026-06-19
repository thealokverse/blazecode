"""Tests for the config and permissions modules."""
import pytest

from blazecode.core.config import Config, apply_env, load_config, save_config
from blazecode.core.permissions import PermissionPolicy


def test_config_default_not_configured():
    assert Config().is_configured() is False


def test_save_and_load_round_trip(tmp_path):
    cfg = Config(model="claude", permission="ask", max_iterations=10)
    cfg.provider_keys["anthropic"] = "sk-test"
    path = save_config(cfg, path=tmp_path / "cfg.toml")
    loaded = load_config(global_path=path)
    assert loaded.model == "claude"
    assert loaded.permission == "ask"
    assert loaded.max_iterations == 10
    assert loaded.provider_keys.get("anthropic") == "sk-test"
    assert loaded.is_configured() is True


def test_apply_env_does_not_override_existing(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "real-key")
    cfg = Config()
    cfg.provider_keys["openai"] = "config-key"
    set_vars = apply_env(cfg)
    assert "OPENAI_API_KEY" not in set_vars
    import os
    assert os.environ["OPENAI_API_KEY"] == "real-key"


def test_apply_env_sets_when_unset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = Config()
    cfg.provider_keys["anthropic"] = "sk-ant-test"
    set_vars = apply_env(cfg)
    assert "ANTHROPIC_API_KEY" in set_vars
    import os
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-test"


def test_permission_modes():
    p = PermissionPolicy()
    p.set_mode("ask")
    assert p.requires_prompt("write", tool_requires_approval=True) is True
    assert p.requires_prompt("read", tool_requires_approval=False) is False
    p.set_mode("auto")
    assert p.requires_prompt("write", tool_requires_approval=True) is False
    p.set_mode("deny-shell")
    assert p.requires_prompt("write", tool_requires_approval=True) is False
    assert p.requires_prompt("shell", tool_requires_approval=True) is True


def test_permission_approve_all_for_session():
    p = PermissionPolicy()
    p.approve_all_for_session()
    assert p.requires_prompt("write", tool_requires_approval=True) is False


def test_permission_unknown_mode_raises():
    p = PermissionPolicy()
    with pytest.raises(ValueError):
        p.set_mode("nope")
