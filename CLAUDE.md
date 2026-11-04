# Agent Thunderdome

Hackathon entry for **Flip the Switch** (WeMakeDevs × Switch) — Best Personal/Creative Workflow track.
Event page: https://www.wemakedevs.org/hackathons/switch
Switch docs: https://docs.switchagents.ai/ · Repo: https://github.com/sandbox-quantum/switch

**Submission deadline: November 7, 2026, 11:59 PM IST.** Aim to submit by the evening of Nov 7, not the last minute.

## The idea

A Switch room where coding agents from different providers (Claude Code, Codex, OpenCode) compete to complete the same real task on the user's repos. Each agent works in its own isolated copy of the repo (git worktree/branch). A judge agent runs the tests, compares the results, and declares a winner. The user replies `merge` to accept it.

- **Gladiators**: one agent per provider, each with a trash-talking personality. Each works in its own worktree.
- **@arena-judge**: trusts no one's claims. It runs the tests (the existing ones plus its own), compares correctness, code size and quality, and posts a scorecard and the winner.
- **Leaderboard**: tracks which model wins which kind of task over time (refactors, scripts, backend, and so on).
- **Loser's Corner**: what the losing solutions got wrong.
- Optional **Night Shift** mode: queue tasks before going offline, and the agents compete overnight. A morning report lists the winners waiting to be merged.

## Project layout & self-building rules

Chosen approach: we build the **core** ourselves, and the gladiators build the **extras** (leaderboard, history, scorecards) through real battles. That's the demo story: "half the arena was built by its own gladiators."

```
Thunderdome/
├── core/        # arena.py + judge logic. Built by us. NEVER a battle target.
├── extras/      # add-ons built by gladiators in battles. They only READ core's JSON output.
├── docs/        # how-it-works.md, a plain-language walkthrough for the user
├── AGENTS.md    # rulebook for all gladiators (Codex/OpenCode read it automatically)
├── arena/       # (gitignored) each gladiator's Switch directory; battle worktrees live here
└── battles/     # (gitignored) judge's hidden tests + raw results; invisible to worktrees
```

- **Gladiators: read and follow `AGENTS.md`.** It applies to Claude Code gladiators too.
- Nothing is merged without passing the tests **and** the user's explicit `merge`. Tag a checkpoint before each merge.
- After every merged battle, walk the user through the winning code.
- If a battle produces nothing usable, we build that extra ourselves. The core never depends on battles.

## Judging criteria (25% each). Build toward these.

1. **Switch integration**: Switch must be central. Multi-provider agents in one room, handing off work to each other, is the core point.
2. **Technical execution**: reproducible setup. A Switch template (`*.template.yaml`) plus a README.
3. **Creativity & impact**
4. **Presentation**: demo video plus clear docs.

Submission needs: a working workflow, a repo with reproducible setup, a demo video, and a README explaining how Switch is used.

## User constraints

- The user values **privacy**. Agents only touch repos the user explicitly chooses, and never read chats, email, or accounts. The room is the user alone (a private Discord server or self-hosted Mattermost).
- Nothing is merged, pushed, or published without the user's explicit approval.
- The user has ADHD and wants the workflow to be witty and fun, not a dry tool.

## How to code with the user: they want to understand everything

The user wants Claude to write code **and** to understand all of it, so they don't become dependent on AI. Treat every coding session as pair programming with a learner, not as a code dump.

- **Explain before writing.** Before each chunk of work, say in a few plain sentences what you're about to build, why it's needed, and how it fits into the whole.
- **Small steps.** Build one concept or file at a time. Don't generate many files at once. After each step, show how to run or test it, so the user sees it working before moving on.
- **Readable over clever.** Use clear, descriptive names and simple control flow. Avoid one-liners, heavy abstractions, and patterns a student wouldn't recognize, unless they're needed. If they are, explain them.
- **Comments explain *why*, not *what*.** Comment non-obvious decisions, tricky logic, and anything Switch-specific. Don't comment the obvious.
- **Introduce every new tool.** When adding a library, package, or Switch feature, say in 1–2 lines what it is, why it was chosen (see the reuse rule below), and link its docs.
- **Recap after each step.** End with a short summary: which files changed, what each one does, and the one key idea to remember.
- **Check understanding sometimes.** At important points (the core judge logic, how agents hand off work), ask the user to predict what something does, or offer them a small piece to write themselves. Keep it optional and quick, because the deadline is tight.
- **Keep `docs/how-it-works.md` up to date.** It's a plain-language walkthrough of the architecture and the flow of a task through the arena. It helps the user learn, and it also feeds the README and the demo.
- **Never say "just trust me."** If the user asks why something works, explain it until it makes sense.

## Rules

- **For any module or package: before writing it yourself, check whether a free, open-source, or otherwise trusted solution already exists on GitHub or the internet, and use it.** Prefer maintained, widely used, permissively licensed projects. Only build from scratch when nothing suitable exists, and note in the README what was reused and why.
- Verify Switch behavior against the docs or repo rather than assuming it. Things not yet confirmed: whether agents can post on a schedule, and how agents from different providers behave together in one room.
- Every result reported by @arena-judge must come from actually running code (tests, builds), never from an LLM's opinion.
