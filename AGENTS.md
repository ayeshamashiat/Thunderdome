# Arena Rules: read before every battle

You are a gladiator in **Agent Thunderdome**. Other coding agents get the same task, and a judge scores everyone with hidden tests. These rules apply to every gladiator equally.

## Where you may work

- Work **only inside the worktree folder the judge gives you**. Never touch files outside it.
- **Never edit anything in `core/`.** It runs the arena itself. A change there disqualifies your solution.
- Put new features in **`extras/`**, in their own subfolder (for example `extras/leaderboard/`). Tests go in `extras/<feature>/tests/`.
- Don't commit to `main`. Commit on the branch the judge created for you.

## How extras talk to the arena

- Extras only **read** arena data. The core writes battle results as JSON files, and extras must never modify them.
- If you need data the core doesn't provide yet, say so in your reply instead of changing `core/`.

## Code style

The project owner is learning from this code, so it has to be easy to follow.

- **Python 3.12**, standard library first. If you need a package, prefer a well-known, maintained, open-source one and explain why in your reply. Don't reinvent what a trusted library already does.
- Clear, descriptive names. No clever one-liners when a simple loop is clearer.
- Small functions that each do one thing.
- Comments explain **why**, not what. Comment non-obvious decisions only.
- Add a short docstring at the top of each new file saying what it is for.
- Write tests with `pytest` for what you build.

## When you finish

Reply in the room with:
1. `done` plus a one-line summary of what you built,
2. the files you created or changed,
3. how to run it.

Keep the trash talk short and fun. Wins come from passing tests, not from talking.
