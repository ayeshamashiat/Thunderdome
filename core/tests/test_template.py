"""Checks the Switch template stays consistent with the arena engine."""

from pathlib import Path

import yaml

from arena import GLADIATORS

TEMPLATE = Path(__file__).resolve().parents[2] / "thunderdome.template.yaml"


def load_template():
    return yaml.safe_load(TEMPLATE.read_text())


def test_every_gladiator_in_the_engine_has_an_agent():
    names = {agent["name"] for agent in load_template()["agents"]}
    assert set(GLADIATORS) | {"arena-judge"} == names


def test_gladiators_work_in_their_own_arena_folder():
    # arena.py puts each battle worktree inside arena/<gladiator>/, so the
    # agent's Switch directory must be exactly that folder.
    for agent in load_template()["agents"]:
        if agent["name"] in GLADIATORS:
            assert agent["directory"] == f"{{thunderdome_dir}}/arena/{agent['name']}"


def test_three_different_companies():
    providers = {agent["provider"] for agent in load_template()["agents"] if agent["name"] in GLADIATORS}
    assert providers == {"claude", "codex", "opencode"}


def test_every_agent_is_in_the_room():
    template = load_template()
    assert set(template["room"]["agents"]) == {agent["name"] for agent in template["agents"]}


def test_the_judge_is_not_one_of_the_competitors():
    template = load_template()
    params = template["params"]
    judge = next(a for a in template["agents"] if a["name"] == "arena-judge")
    gladiator_models = {params["codex_model"]["default"], params["opencode_model"]["default"]}

    assert judge["provider"] != "claude", "a Claude judge would be judging claude-gladiator"
    assert params["judge_model"]["default"] not in gladiator_models


def test_the_judge_is_told_to_seal_the_tests():
    judge = next(a for a in load_template()["agents"] if a["name"] == "arena-judge")
    assert "arena.py seal" in judge["instructions"]
