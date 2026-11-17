---
name: orchestrate
description: Split the user's list of tasks into separate Claude Code sessions (threads), one per independent task, each on its own worktree and with a model chosen by the task's difficulty, then track them and report back. Use when the user says "/orchestrate", "zaorkiestruj", "rozdziel na wątki", "zascheduluj w osobnych wątkach" or gives several independent tasks to run in parallel.
---

# Orchestrate

Turn a batch of requests into parallel sessions that each finish one task, while this
session stays free to talk to the user. Reply to the user in Polish.

## 1. Split the request into tasks

- Arguments, or the user's latest message, hold the tasks. One bullet, sentence or
  paragraph is usually one task; a question ("ile to trwa?") is a task too (investigate
  and answer with numbers).
- Merge pieces that touch the same files or must land in one change: one session each.
- Keep here anything a few tool calls settle (a one-line fix, a quick answer). Say so.
- Before starting, check `git status` and the linked sessions
  (`mcp__ccd_session_mgmt__list_sessions` with `linked: true`). Note uncommitted
  work in this checkout and sessions already working on the same area; a new brief
  must mention both so nobody overwrites anyone.

## 2. Pick the model by difficulty

| Difficulty | Signs | Model |
|---|---|---|
| Mechanical | rename, copy text, one widget option, config tweak, docs line | `claude-haiku-5-5` |
| Standard | one page or module, clear expected behaviour, UI fix, mapping, small feature with tests | `claude-sonnet-5-5` |
| Hard | performance or numbers to measure, financial maths (returns, FX, tax, bonds), data model or migration, parser of a new format, cross-module refactor, unclear root cause | omit `model` (inherits the strongest, this session's) |

When unsure between two levels, pick the higher one. Say in one line per task which
model it got and why.

## 3. Write each brief

Every session starts `fresh`, `use_worktree: true` (its own branch; two writers never
share files) and gets:
- **prompt**: the task in the user's words (quoted), the files or area (find them
  first with a quick grep if cheap), the likely cause if you already know it, and what
  done looks like: tests (`pytest`, `ruff check .`), a browser check for UI work (skill
  `/ui-page`, light and dark mode), a numbered `docs/decisions.md` entry when a
  decision changes (give the next free ID, counting uncommitted entries), and a short
  report to the user in Polish with what is not verified.
- **background** (≥80 chars): the project in one sentence and the hard rules from
  `CLAUDE.md`, restated because a fresh session has not seen this conversation:
  - never read `data/` (the user's real data); check on `fa demo` / `data-demo/`;
  - network only in `market/`, offline mode respected (R-015, D-031);
  - do not commit unless the user asks; never `--no-verify`; privacy check before any commit;
  - ask the user before an architectural decision;
  - other sessions working nearby and files to leave alone.
- `branch_name`: a short slug; `name`: a short handle.

## 4. Start them

- Mark a chapter (`mcp__ccd_session__mark_chapter`) when starting two or more.
- Right before each `mcp__ccd_session__start_session` call write a bold title line and
  one sentence. Use `initiation: "user_asked"` (the user asked for separate threads).
- Then end the turn with one line on how you will report back. Do not wait or poll.

## 5. When sessions report back

- A note is the session's own report, not proof. Before telling the user something is
  done, look at its branch diff (`git diff main...<branch>`) and its test result.
- Report each in one line in Polish: what changed, the branch, what is not verified.
- Follow-ups go to the same session (`SendMessage` with its `local_…` id), not a new one.
- Merging: branches stay apart until the user says to merge. Then merge one at a time
  into a feature branch, resolve conflicts (decision IDs!), run `pytest` and the privacy
  check, and commit or push only on the user's word.
