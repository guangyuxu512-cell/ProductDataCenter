from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.security.scoped_tokens import Principal
from app.main import create_application
from app.modules.prechecks.api import _rules_authority
from app.modules.prechecks.group_rules import (GroupRule, GroupRules, GroupRuleStore,
                                               RulesConflict, destination)


def rule(source="all", passed="ungrouped", incomplete="keep", enabled=True):
    return GroupRule(source=source, passed=passed, incomplete=incomplete, enabled=enabled)


def test_rules_persist_and_reject_a_stale_save(tmp_path):
    store = GroupRuleStore(tmp_path / "rules.sqlite3")
    assert store.read().model_dump() == {"version": 0, "rules": []}
    saved = store.save(GroupRules(rules=[rule()]))
    assert saved.version == 1 and store.read() == saved
    with pytest.raises(RulesConflict):
        store.save(GroupRules(version=0, rules=[]))
    assert store.read() == saved
    assert store.save(GroupRules(version=1, rules=[])).version == 2


def test_specific_source_wins_and_failures_never_move():
    source, passed, incomplete = (str(uuid4()) for _ in range(3))
    config = GroupRules(rules=[rule("all", "ungrouped", "ungrouped"),
                               rule(source, passed, incomplete)])
    assert destination(config, source, "ready") == passed
    assert destination(config, source, "needs_completion") == incomplete
    assert destination(config, source, "needs_category") == incomplete
    assert destination(config, source, "failed") is None
    assert destination(config, source, "pending") is None
    assert destination(config, None, "ready") is None  # already ungrouped


def test_disabled_rules_and_keep_targets_do_not_move():
    source, target = str(uuid4()), str(uuid4())
    config = GroupRules(rules=[rule(source, "keep", target), rule("all", target, "keep", enabled=False)])
    assert destination(config, source, "ready") is None
    assert destination(config, source, "needs_completion") == target
    assert destination(config, None, "ready") is None


def test_ambiguous_active_sources_and_empty_actions_are_rejected():
    with pytest.raises(ValidationError):
        GroupRules(rules=[rule(), rule()])
    with pytest.raises(ValidationError):
        rule(passed="keep", incomplete="keep")
    assert GroupRules(rules=[rule(), rule(enabled=False)]).rules[1].enabled is False


def test_unrestricted_permission_is_required_for_global_rules():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        _rules_authority(Principal("id", frozenset({"group.read", "group.assign", "precheck.run", "precheck.group_rules"}),
                                   groups=frozenset({str(uuid4())})))
    assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        _rules_authority(Principal("id", frozenset({"group.read", "group.assign", "precheck.run"})))
    assert error.value.status_code == 403


def test_rules_api_requires_authentication_and_saves_only_configuration(tmp_path):
    settings = Settings(_env_file=None, api_token="synthetic-admin", enable_group_writes=True,
                        auto_precheck_enabled=False, precheck_group_rules_file=tmp_path / "rules.sqlite3")
    app = create_application()
    app.dependency_overrides[get_settings] = lambda: settings
    headers = {"Authorization": "Bearer synthetic-admin"}
    with patch("app.core.security.access.get_settings", return_value=settings), \
            patch("app.modules.prechecks.api.get_settings", return_value=settings), TestClient(app) as client:
        assert client.get("/api/v1/prechecks/group-rules").status_code == 401
        assert client.get("/api/v1/prechecks/group-rules", headers=headers).json() == {"version": 0, "rules": []}
        payload = {"version": 0, "rules": [rule().model_dump(mode="json")]}
        saved = client.put("/api/v1/prechecks/group-rules", headers=headers, json=payload)
        assert saved.status_code == 200 and saved.json()["version"] == 1
        assert client.put("/api/v1/prechecks/group-rules", headers=headers, json=payload).status_code == 409
        assert client.get("/api/v1/prechecks/group-rules", headers=headers).json() == saved.json()
