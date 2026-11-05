"""Battles in another repo (--repo). Two throwaway repos: the arena and a separate project."""

import json

import pytest

from arena import cleanup_battle, merge_winner, run_git, setup_battle
from judge import score_battle

HIDDEN_TEST = """
from shop.prices import with_tax

def test_adds_ten_percent():
    assert with_tax(100) == 110

def test_zero():
    assert with_tax(0) == 0
"""


def make_repo(path, branch, files):
    path.mkdir()
    run_git(path, "init", "-b", branch, "-q")
    run_git(path, "config", "user.email", "test@example.com")
    run_git(path, "config", "user.name", "Test")
    for relative_path, content in files.items():
        (path / relative_path).parent.mkdir(parents=True, exist_ok=True)
        (path / relative_path).write_text(content)
    run_git(path, "add", ".")
    run_git(path, "commit", "-q", "-m", "first")
    return path


@pytest.fixture
def arena(tmp_path):
    return make_repo(tmp_path / "thunderdome", "main", {".gitignore": "arena/\nbattles/\n", "core/engine.py": "#\n"})


@pytest.fixture
def project(tmp_path):
    # A separate project on 'master', with a bug-free module to build on.
    return make_repo(tmp_path / "shop-project", "master", {
        "shop/prices.py": "def with_tax(amount):\n    raise NotImplementedError\n",
        "shop/settings.py": "TAX = 0.10\n",
    })


def commit_in_worktree(arena, gladiator, battle_id, files):
    worktree = arena / "arena" / gladiator / battle_id
    for relative_path, content in files.items():
        (worktree / relative_path).write_text(content)
    run_git(worktree, "add", ".")
    run_git(worktree, "commit", "-q", "-m", "solution")


def test_full_battle_in_another_repo(arena, project):
    battle = setup_battle(arena, "tax", "implement with_tax", ["good", "bad"], target_repo=project)

    # The battle remembers where it happens, and starts from the project's own branch.
    assert battle["repo"] == str(project.resolve())
    assert battle["base_branch"] == "master"
    # Branches are created in the PROJECT, worktrees in the ARENA's folders.
    assert "battle/001-tax/good" in run_git(project, "branch", "--list", "battle/*")
    assert (arena / "arena" / "good" / "001-tax" / "shop" / "prices.py").exists()

    (arena / "battles" / "001-tax" / "hidden_tests" / "test_tax.py").write_text(HIDDEN_TEST)
    commit_in_worktree(arena, "good", "001-tax", {"shop/prices.py": "def with_tax(amount):\n    return round(amount * 1.1)\n"})
    commit_in_worktree(arena, "bad", "001-tax", {"shop/prices.py": "def with_tax(amount):\n    return amount\n"})

    assert score_battle(arena, "001-tax")["winner"] == "good"

    merge_winner(arena, "001-tax")
    assert "round(amount * 1.1)" in (project / "shop" / "prices.py").read_text()
    assert run_git(project, "branch", "--show-current") == "master"

    cleanup_battle(arena, "001-tax")
    assert run_git(project, "branch", "--list", "battle/*") == ""
    assert not (arena / "arena" / "good" / "001-tax").exists()


def test_judge_files_never_go_into_the_project(arena, project):
    setup_battle(arena, "tax", "implement with_tax", ["good"], target_repo=project)
    assert not (project / "battles").exists()
    assert (arena / "battles" / "001-tax" / "battle.json").exists()


def test_protected_paths_disqualify_in_another_repo(arena, project):
    setup_battle(arena, "tax", "implement with_tax", ["sneaky", "honest"],
                 target_repo=project, protected=["./shop/settings.py"])
    (arena / "battles" / "001-tax" / "hidden_tests" / "test_tax.py").write_text(HIDDEN_TEST)
    solution = "def with_tax(amount):\n    return round(amount * 1.1)\n"
    commit_in_worktree(arena, "sneaky", "001-tax", {"shop/prices.py": solution, "shop/settings.py": "TAX = 0\n"})
    commit_in_worktree(arena, "honest", "001-tax", {"shop/prices.py": solution})

    scorecard = score_battle(arena, "001-tax")

    assert scorecard["winner"] == "honest"
    assert "shop/settings.py" in scorecard["ranking"][-1]["disqualified"]


def test_core_is_not_protected_in_other_repos(arena, project):
    battle = setup_battle(arena, "tax", "task", ["good"], target_repo=project)
    assert battle["protected"] == []


def test_core_stays_protected_in_thunderdome(arena):
    battle = setup_battle(arena, "self", "task", ["good"])
    assert battle["protected"] == ["core/"]
    assert battle["base_branch"] == "main"


def test_a_subfolder_points_at_the_whole_repo(arena, project):
    battle = setup_battle(arena, "tax", "task", ["good"], target_repo=project / "shop")
    assert battle["repo"] == str(project.resolve())


def test_not_a_git_repo_is_refused(arena, tmp_path):
    plain = tmp_path / "plain-folder"
    plain.mkdir()
    with pytest.raises(ValueError, match="not a git repository"):
        setup_battle(arena, "x", "task", ["good"], target_repo=plain)


def test_detached_head_is_refused(arena, project):
    run_git(project, "checkout", "-q", "--detach")
    with pytest.raises(ValueError, match="detached"):
        setup_battle(arena, "x", "task", ["good"], target_repo=project)


def test_old_battles_without_a_repo_still_work(arena):
    # Battle 001 was created before --repo existed: no "repo"/"base_branch"/"protected" keys.
    battle = setup_battle(arena, "old", "task", ["good"])
    record = arena / "battles" / "001-old" / "battle.json"
    data = json.loads(record.read_text())
    for key in ("repo", "base_branch", "protected"):
        data.pop(key)
    record.write_text(json.dumps(data))

    cleanup_battle(arena, "001-old")
    assert run_git(arena, "branch", "--list", "battle/*") == ""
