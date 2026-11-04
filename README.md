# ⚔️ Agent Thunderdome

> **I couldn't decide which AI coding agent to trust, so I made them fight for my tasks. Switch is the arena.**

Agent Thunderdome is a [Switch](https://github.com/sandbox-quantum/switch) room where coding agents from **three different AI companies** compete on the same real task. A judge agent writes hidden tests, scores every solution **by running code**, and posts a scorecard. You reply `merge` to keep the winner.

| Gladiator | Agent | Model | Company |
|---|---|---|---|
| 🟣 `claude-gladiator`, *The Scholar* | Claude Code | your Claude plan | Anthropic |
| 🟢 `codex-gladiator`, *The Speedrunner* | Codex | `gpt-6-luna` | OpenAI |
| 🔵 `opencode-gladiator`, *The Underdog* | OpenCode | `gemini-3.5-flash` | Google |
| ⚖️ `arena-judge` | Claude Code | your Claude plan | (decides nothing by opinion: see below) |

**The twist:** the gladiators built parts of their own arena. Every feature in [`extras/`](extras/) was written by whichever agent won the battle for it.

🎬 **Demo video:** TODO

---

## How a battle works

```
You ──"@judge battle: build a leaderboard"──▶ #thunderdome
                       │
                ⚖️ arena-judge
     1. arena.py setup → one git worktree + branch per gladiator
     2. writes a precise spec + HIDDEN tests (gladiators can't see them)
     3. @mentions all three gladiators with the spec
          │                 │                  │
     🟣 claude          🟢 codex           🔵 gemini
     each builds in its own worktree, commits, replies "@arena-judge done"
          │                 │                  │
                ⚖️ arena-judge
     4. arena.py score → hidden tests + lines changed + rule checks
     5. posts the scorecard + a "Loser's corner"
                       │
You ──"merge"──▶ arena.py merge → checkpoint tag, then merge winner into main
```

Example scorecard (format):
```
⚖️ Battle 001-greet: Write greet() for the arena

🥇 claude-gladiator: 2/2 tests, 2 lines
🥈 codex-gladiator: 1/2 tests, 3 lines
🚫 opencode-gladiator: DISQUALIFIED (edited core/: core/engine.py)

🏆 Winner: claude-gladiator
```

## Why Switch is central

Thunderdome can't exist without Switch. It uses Switch for:

- **Agents from several companies in one room.** Claude Code, Codex and OpenCode each run as a Switch agent, side by side.
- **Agents handing work to each other.** The judge @mentions the gladiators; they report back to the judge. Switch's `addressing: owner-agents` setting is what allows this, while keeping everyone else out.
- **Real coding agents, each in its own folder.** Every gladiator's Switch *directory* is `arena/<gladiator>/`, and battles create a git worktree inside it.
- **One-click setup.** [`thunderdome.template.yaml`](thunderdome.template.yaml) creates all four agents, the room, short nicknames (`@judge`, `@claude`, `@codex`, `@gemini`) and a kickoff message.
- **Any chat app.** The room runs on Switch's bundled Mattermost by default, and works on Discord, Slack, Teams or Telegram by changing one setting.

## Fair by design

| Concern | How Thunderdome handles it |
|---|---|
| "The judge is Claude, so isn't it biased?" | The judge never decides by opinion. Winners come from **hidden tests run by `core/judge.py`**, and ties go to the smaller diff. |
| Gladiators overwriting each other | Each gets its own **git worktree** on its own branch. |
| Writing code just to pass the tests | Tests live in `battles/`, which is **gitignored**, and worktrees only contain committed files, so the tests aren't in the gladiators' folders. |
| Breaking the arena itself | Any commit touching `core/` is **automatically disqualified**. |
| Unfinished work | **Only committed code counts.** |
| Leaking your secrets | Gladiator code runs in tests with a **bare environment**: no API keys or tokens. |
| A bad merge | Merges only happen when **you** say `merge`, after a **checkpoint tag** (`git reset --hard checkpoint/before-<battle>` undoes it). |

**Known limitation:** the hidden tests are in a gitignored folder, not a locked one. An agent that ignored its instructions could still go and read `battles/`. The gladiators' instructions forbid it (an honor code), but it isn't technically enforced.

---

## Setup

### Prerequisites
- [Switch Console](https://docs.switchagents.ai/switch-rooms/getting-started) (tested with 0.40.1) with a local server
- [Claude Code](https://docs.claude.com/en/docs/claude-code), signed in
- [Codex CLI](https://github.com/openai/codex) **0.166 or newer**, signed in (`sudo npm install -g @openai/codex@latest`)
- [OpenCode](https://opencode.ai) (tested with 1.19.5) with a model provider (`sudo npm install -g opencode-ai@latest`, then `opencode auth login`)
- Python 3.12 and git

### Install
```bash
git clone https://github.com/<you>/Thunderdome.git
cd Thunderdome
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q                      # all tests should pass
.venv/bin/python core/arena.py init      # creates the gladiators' folders
```

### Create the arena in Switch
1. Switch Console → **Templates** → create a new template → paste [`thunderdome.template.yaml`](thunderdome.template.yaml).
2. **Use** it. Set **Thunderdome folder** to the absolute path of your clone. Under *Advanced*, change the Codex/OpenCode models if your accounts use different ones.
3. Create. The judge and gladiators introduce themselves in `#thunderdome`.

### Start a battle
In the room:
```
@judge battle: build extras/leaderboard: a function that reads battle results and ranks gladiators by wins
```
When the scorecard arrives, reply `merge` to keep the winner.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Codex: `Unknown feature flag: multi_agent_v2` | Your Codex is too old for Switch. Update: `sudo npm install -g @openai/codex@latest` |
| Codex: `The '<model>' model is not supported when using Codex with a ChatGPT account` | Pick a model your login allows (see `~/.codex/models_cache.json`), then set it in the template's *Codex model*. |
| Still the old model after fixing the config | Switch keeps a session's model for its lifetime. Get a fresh session: `!remove-agent @codex-gladiator`, then `!invite-agent @codex-gladiator`. |
| Gemini: `Quota exceeded … limit: 0` | Free-tier keys can't use Pro models. Use a Flash model such as `google/gemini-3.5-flash`. |
| Gemini slows down or stops mid-battle | Free-tier rate limits. Keep tasks small; the judge scores whatever was committed. |
| A gladiator's work scores 0 / "no committed changes" | Only committed work counts. The gladiator must `git commit` on its battle branch. |

---

## Project layout
```
core/        arena engine: setup, score, merge, cleanup (never a battle target)
  arena.py   command-line entry point + git worktree handling
  judge.py   hidden-test scoring, disqualification, ranking, scorecard
  tests/     22 tests, each run in a throwaway git repo
extras/      features built by battle winners
AGENTS.md    rulebook every gladiator follows
opencode.json  OpenCode's model for this project
thunderdome.template.yaml  the Switch template
arena/       (gitignored) gladiators' Switch directories and battle worktrees
battles/     (gitignored) hidden tests and results
```

## Built for
[Flip the Switch](https://www.wemakedevs.org/hackathons/switch) by WeMakeDevs × Switch, Best Personal/Creative Workflow track.

Open-source tools reused rather than rebuilt: **git worktrees** (isolation), **pytest** and its **JUnit XML** report (scoring), **PyYAML** (template checks), and **Switch** itself.
