"""Blind-vote battles: anonymous ballots, one vote, a reveal, and merge as usual."""

import json

import pytest

from arena import merge_winner, run_git, setup_battle
from blind import cast_vote, format_ballot, format_reveal, make_ballot, scrub_identity
from judge import score_battle

GLADIATORS = ["claude-gladiator", "codex-gladiator", "opencode-gladiator"]
POEMS = {
    "claude-gladiator": "Rain taps the glass like a patient friend.\n",
    "codex-gladiator": "Drops race down. Fast. Done.\n",
    "opencode-gladiator": "Free tier clouds, rate-limited rain.\n",
}


@pytest.fixture
def repo(tmp_path):
    run_git(tmp_path, "init", "-b", "main", "-q")
    run_git(tmp_path, "config", "user.email", "test@example.com")
    run_git(tmp_path, "config", "user.name", "Test")
    (tmp_path / ".gitignore").write_text("arena/\nbattles/\n")
    (tmp_path / "README.md").write_text("project\n")
    run_git(tmp_path, "add", ".")
    run_git(tmp_path, "commit", "-q", "-m", "first")
    return tmp_path


def write_entry(repo, gladiator, battle_id, text, path="entries/poem.md"):
    worktree = repo / "arena" / gladiator / battle_id
    (worktree / path).parent.mkdir(parents=True, exist_ok=True)
    (worktree / path).write_text(text)
    run_git(worktree, "add", ".")
    run_git(worktree, "commit", "-q", "-m", "my entry")


def blind_battle(repo, gladiators=GLADIATORS):
    battle = setup_battle(repo, "rain", "write a short poem about rain", gladiators,
                          mode="blind", deliverable="entries/poem.md")
    for gladiator in gladiators:
        write_entry(repo, gladiator, battle["id"], POEMS[gladiator])
    return battle["id"]


def test_the_ballot_shows_entries_but_no_names(repo):
    ballot = make_ballot(repo, blind_battle(repo))
    text = format_ballot(ballot)

    for poem in POEMS.values():
        assert poem.strip() in text
    for gladiator in GLADIATORS:
        assert gladiator not in text
    assert set(ballot["entries"]) == {"A", "B", "C"}


def test_entries_that_sign_their_name_are_redacted(repo):
    battle = setup_battle(repo, "rain", "poem", ["claude-gladiator"], mode="blind", deliverable="entries/poem.md")
    write_entry(repo, "claude-gladiator", battle["id"], "A poem.\n\n— written by Claude (Anthropic)\n")

    ballot = make_ballot(repo, battle["id"])

    entry = ballot["entries"]["A"]
    assert "Claude" not in entry["text"] and "Anthropic" not in entry["text"]
    assert entry["signed_with"] == ["Anthropic", "Claude"]


def test_scrubbing_leaves_normal_words_alone():
    clean, found = scrub_identity("The cloud-like rain fell on the googly-eyed glass.")
    # 'googly' starts with 'google'? No: whole-word match on the name, so it stays.
    assert found == [] and clean.startswith("The cloud-like rain")


def test_the_order_is_shuffled(repo):
    # With 3 entries there are 6 possible orders; 20 fresh ballots should show more than one.
    battle_id = blind_battle(repo)
    orders = set()
    for _ in range(20):
        ballot = make_ballot(repo, battle_id)
        orders.add(tuple(entry["gladiator"] for entry in ballot["entries"].values()))
        (repo / "battles" / battle_id / "ballot.json").unlink()   # allow a fresh shuffle
    assert len(orders) > 1


def test_voting_reveals_and_picks_the_winner(repo):
    battle_id = blind_battle(repo)
    ballot = make_ballot(repo, battle_id)
    letter_of_codex = next(l for l, e in ballot["entries"].items() if e["gladiator"] == "codex-gladiator")

    results = cast_vote(repo, battle_id, letter_of_codex.lower())   # lowercase is fine

    assert results["winner"] == "codex-gladiator"
    reveal = format_reveal(results)
    assert all(gladiator in reveal for gladiator in GLADIATORS)
    assert f"You picked {letter_of_codex}" in reveal


def test_you_can_only_vote_once(repo):
    battle_id = blind_battle(repo)
    make_ballot(repo, battle_id)
    cast_vote(repo, battle_id, "A")

    with pytest.raises(ValueError, match="already decided"):
        cast_vote(repo, battle_id, "B")


def test_the_ballot_cannot_be_reshuffled(repo):
    battle_id = blind_battle(repo)
    make_ballot(repo, battle_id)
    with pytest.raises(ValueError, match="already has a ballot"):
        make_ballot(repo, battle_id)


def test_a_letter_that_doesnt_exist_is_refused(repo):
    battle_id = blind_battle(repo)
    make_ballot(repo, battle_id)
    with pytest.raises(ValueError, match="Pick one of"):
        cast_vote(repo, battle_id, "Z")


def test_missing_entries_are_disqualified_not_on_the_ballot(repo):
    battle = setup_battle(repo, "rain", "poem", GLADIATORS, mode="blind", deliverable="entries/poem.md")
    write_entry(repo, "claude-gladiator", battle["id"], POEMS["claude-gladiator"])
    write_entry(repo, "codex-gladiator", battle["id"], "oops\n", path="entries/wrong-name.md")
    # opencode commits nothing at all

    ballot = make_ballot(repo, battle["id"])

    assert list(ballot["entries"]) == ["A"]
    assert "entries/poem.md" in ballot["disqualified"]["codex-gladiator"]
    assert ballot["disqualified"]["opencode-gladiator"] == "no committed changes"


def test_the_winning_entry_merges_like_any_battle(repo):
    battle_id = blind_battle(repo)
    ballot = make_ballot(repo, battle_id)
    cast_vote(repo, battle_id, "B")

    merge_winner(repo, battle_id)

    # git output is stripped, so compare without the trailing newline.
    assert (repo / "entries" / "poem.md").read_text().strip() == ballot["entries"]["B"]["text"]


def test_blind_battles_need_a_deliverable(repo):
    with pytest.raises(ValueError, match="deliverable"):
        setup_battle(repo, "rain", "poem", GLADIATORS, mode="blind")


def test_score_points_blind_battles_to_ballot_and_vote(repo):
    battle_id = blind_battle(repo)
    with pytest.raises(ValueError, match="ballot"):
        score_battle(repo, battle_id)


def test_ballot_refuses_a_normal_battle(repo):
    battle = setup_battle(repo, "code", "write code", GLADIATORS)
    with pytest.raises(ValueError, match="isn't a blind battle"):
        make_ballot(repo, battle["id"])


def test_results_are_saved_for_the_leaderboard(repo):
    battle_id = blind_battle(repo)
    make_ballot(repo, battle_id)
    cast_vote(repo, battle_id, "A")

    saved = json.loads((repo / "battles" / battle_id / "results.json").read_text())
    assert saved["mode"] == "blind" and saved["winner"] in GLADIATORS
