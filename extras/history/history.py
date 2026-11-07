"""Read scored battle ids and winners from a battles directory."""

import json
from pathlib import Path


def battle_history(battles_dir: str | Path) -> list[dict]:
    """Return scored battles ordered by descending battle id."""
    history = []
    for result_path in Path(battles_dir).glob("*/results.json"):
        try:
            with result_path.open(encoding="utf-8") as result_file:
                result = json.load(result_file)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(result, dict) or not isinstance(result.get("battle_id"), str):
            continue
        winner = result.get("winner")
        history.append({
            "battle_id": result["battle_id"],
            "winner": winner if isinstance(winner, str) else None,
        })
    return sorted(history, key=lambda battle: battle["battle_id"], reverse=True)
