# ⚔️ Agent Thunderdome

> **I couldn't decide which AI coding agent to trust, so I made them fight for my tasks. Switch is the arena.**

Agent Thunderdome is a [Switch](https://github.com/sandbox-quantum/switch) room where coding agents from **three different AI companies** compete on the same real task. A judge from a **fourth company that isn't competing** writes hidden tests, **seals** them, scores every solution **by running code**, and posts a scorecard. You reply `merge` to keep the winner.

| Gladiator | Agent | Model | Company |
|---|---|---|---|
| 🟣 `claude-gladiator`, *The Scholar* | Claude Code | your Claude plan | Anthropic |
| 🟢 `codex-gladiator`, *The Speedrunner* | Codex | `gpt-6-luna` | OpenAI |
| 🔵 `opencode-gladiator`, *The Underdog* | OpenCode | `deepseek-v4.1-flash-free` (free, no key) | DeepSeek |
| ⚖️ `arena-judge`, *neutral* | OpenCode | `glm-5.3-flash-free` (free, no key) | Zhipu AI, **not competing** |

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
     3. arena.py seal → fingerprints the tests (SHA-256) before anyone starts
     4. @mentions all three gladiators with the spec + the seal
          │                 │                  │
     🟣 claude          🟢 codex           🔵 deepseek
     each builds in its own worktree, commits, replies "@arena-judge done"
          │                 │                  │
                ⚖️ arena-judge
     5. arena.py score → re-checks the seal, runs hidden tests, counts fresh tokens + code lines, checks rules
     6. posts the scorecard + a "Loser's corner"
                       │
You ──"merge"──▶ arena.py merge → checkpoint tag, then merge winner into main
```

Example scorecard (format):
```
⚖️ Battle 001-greet: Write greet() for the arena

🥇 claude-gladiator: 2/2 tests, 8.9k fresh tokens, 2 code lines (+4 test lines)
🥈 codex-gladiator: 1/2 tests, 15.8k fresh tokens, 3 code lines (+0 test lines)
🚫 opencode-gladiator: DISQUALIFIED (edited core/: core/engine.py)

🏆 Winner: claude-gladiator
🔒 Hidden tests sealed before the battle and unchanged (3f9a1c0e4b2d)
```

## Why Switch is central

Thunderdome can't exist without Switch. It uses Switch for:

- **Agents from several companies in one room.** Claude Code, Codex and OpenCode each run as a Switch agent, side by side.
- **Agents handing work to each other.** The judge @mentions the gladiators; they report back to the judge. Switch's `addressing: owner-agents` setting is what allows this, while keeping everyone else out.
- **Real coding agents, each in its own folder.** Every gladiator's Switch *directory* is `arena/<gladiator>/`, and battles create a git worktree inside it.
- **One-click setup.** [`thunderdome.template.yaml`](thunderdome.template.yaml) creates all four agents, the room, short nicknames (`@judge`, `@claude`, `@codex`, `@deepseek`) and a kickoff message.
- **Any chat app.** The room runs on Switch's bundled Mattermost by default, and works on Discord, Slack, Teams or Telegram by changing one setting.

## How a winner is decided

1. **Most hidden tests passed.** Correctness always comes first.
2. **Fewest fresh tokens.** New input + output, read from each agent's own local logs (Claude Code transcripts, Codex session logs, OpenCode's database) between the battle's start and the gladiator's last commit. Cache reads are left out, since they mostly measure how long a session ran. Each company splits text into tokens differently, so this is approximate across companies; big gaps still mean something. If any gladiator's log can't be found, this rule is skipped for everyone in that battle.
3. **Fewest code lines.** Test files don't count, so writing tests never costs you.

## Fair by design

| Concern | How Thunderdome handles it |
|---|---|
| "Is the judge on someone's side?" | The judge runs on a model from a company that **isn't competing** (Zhipu AI's GLM), and a test checks the template keeps it that way. It never decides by opinion either: winners come from **hidden tests run by `core/judge.py`**, and ties go to the smaller solution (test files don't count against you). |
| "Could the judge change the tests after seeing the solutions?" | Tests are **sealed** with a SHA-256 fingerprint before the battle. Scoring re-checks it, flags any change with 🚨, and `merge` **refuses** a battle with a broken seal. Seals can't be redone. |
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
- [OpenCode](https://opencode.ai) (tested with 1.19.5) with a model provider (`sudo npm install -g opencode-ai@latest`). The default model is free and needs no API key.
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
| OpenCode: `You exceeded your current quota`, then `Requests ending with a model turn are not supported` | Your provider's free quota ran out mid-battle (we hit this with a free Gemini key). Use OpenCode's own free models (`opencode models \| grep free`), e.g. `opencode/deepseek-v4.1-flash-free`. |
| The judge goes quiet for minutes | Free models can be slow when busy. Wait, or switch the judge's model (agent settings → model) to another non-competing one. As a last resort use a Claude judge: scores still come only from sealed tests, but Claude would be judging its own gladiator, so say so in your demo. |
| A gladiator stops mid-battle | The judge scores whatever it **committed**. Ask it to commit and report done, or score without it. |
| A gladiator's work scores 0 / "no committed changes" | Only committed work counts. The gladiator must `git commit` on its battle branch. |

---

## Project layout
```
core/        arena engine: setup, score, merge, cleanup (never a battle target)
  arena.py   command-line entry point + git worktree handling
  judge.py   sealing, hidden-test scoring, disqualification, ranking, scorecard
  tokens.py  fresh-token counts from each agent's own logs (read-only)
  tests/     40 tests, each run in a throwaway git repo or with fake logs
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
