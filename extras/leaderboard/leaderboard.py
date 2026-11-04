"""Leaderboard extra: ranks gladiators by wins, reading the judge's results.json files (read only)."""
import json
from pathlib import Path

# Minimum column widths, chosen to reproduce the layout in the battle spec.
RANK_WIDTH = 6
NAME_WIDTH = 20
WINS_WIDTH = 6


def load_results(battles_dir):
    """Yield the parsed results.json of every scored battle, skipping broken ones."""
    battles_path = Path(battles_dir)
    if not battles_path.is_dir():
        return
    for results_file in sorted(battles_path.glob("*/results.json")):
        try:
            data = json.loads(results_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            yield data


def build_leaderboard(battles_dir):
    """Return [{"gladiator", "wins", "battles"}] sorted by wins (desc), then name (A-Z)."""
    stats = {}
    for battle in load_results(battles_dir):
        ranking = battle.get("ranking")
        if not isinstance(ranking, list):
            continue
        # A set, so a gladiator listed twice in one battle still counts once.
        players = {entry["gladiator"] for entry in ranking
                   if isinstance(entry, dict) and isinstance(entry.get("gladiator"), str)}
        for name in players:
            row = stats.setdefault(name, {"gladiator": name, "wins": 0, "battles": 0})
            row["battles"] += 1
            if battle.get("winner") == name:
                row["wins"] += 1
    return sorted(stats.values(), key=lambda row: (-row["wins"], row["gladiator"]))


def format_leaderboard(rows):
    """Format leaderboard rows as an aligned text table."""
    if not rows:
        return "No battles scored yet."
    # Widen columns when a value is too long, keeping two spaces of padding.
    rank_width = max(RANK_WIDTH, len(str(len(rows))) + 2)
    name_width = max(NAME_WIDTH, max(len(row["gladiator"]) for row in rows) + 2)
    wins_width = max(WINS_WIDTH, max(len(str(row["wins"])) for row in rows) + 2)

    def line(rank, name, wins, battles):
        return f"{rank:<{rank_width}}{name:<{name_width}}{wins:<{wins_width}}{battles}"

    lines = [line("Rank", "Gladiator", "Wins", "Battles")]
    for position, row in enumerate(rows, start=1):
        lines.append(line(str(position), row["gladiator"], str(row["wins"]), str(row["battles"])))
    return "\n".join(lines)
