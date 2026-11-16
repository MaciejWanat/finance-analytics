---
name: grill-me
description: Interview the user relentlessly about a plan, feature or design until every branch of the decision tree is resolved, one question at a time with a recommended answer for each, then record the outcome in docs/decisions.md. Use when the user says "grill me", "/grill-me", or asks to be challenged on a plan before building it.
---

# Grill me

Reach a shared, concrete understanding of a plan before any code is written. Do this
by asking hard questions one at a time until nothing important is left open.

## 1. Set the subject

- If arguments were given, they name the subject. Otherwise ask what to grill (a view, an
  integration, a calculation, a refactor), in one short question.
- Read `docs/decisions.md` first: requirements (R-), decisions (D-), open questions (Q-).
  Do not re-ask what is already decided unless the subject contradicts it. In that
  case, say which entry is affected.
- Read the code, docs and masked sample reports the subject touches.

## 2. Map the decision tree (privately)

List the decisions the subject depends on. Order them so that upstream decisions come
first: data model before views, definitions before formulas, scope before details.
Revisit the map whenever an answer opens a new branch.

## 3. Ask, one question at a time

For each question:
- give 1–2 sentences of context: why it matters, and what depends on it;
- ask the question itself, concretely, with an example where it helps (a sample
  transaction, a date, an amount);
- list the realistic options with their trade-offs;
- give **your recommended answer and why**, first in the list.

Use the AskUserQuestion tool when the options are discrete (recommended option
first, marked "(Recommended)"). Otherwise ask in plain text. Never batch unrelated
questions; one decision per question.

**If the answer can be found by reading code, docs or data, look it up instead of
asking.** Then state what you found and move on.

## 4. Push on the weak spots

Probe especially:
- **money correctness:** rounding, currencies and FX dates, taxes, corporate actions (splits, dividends), partial fills, duplicates across overlapping imports;
- **edge cases:** empty data, the first day, holidays, missing prices, negative values;
- **privacy** (D-011, D-014): does anything leave the machine or end up in git?
- **definitions:** what exactly counts as a cash flow, a return, a "day";
- **testability:** how we will know it is right (a hand-computed example);
- **scope:** what is explicitly *not* in this step.

Challenge vague answers ("normally", "it depends") by asking for a concrete case. If
an answer conflicts with an earlier one, point it out and resolve it.

## 5. Finish

Stop when every branch is resolved or the user says stop. Then summarize:
- **Decisions** made (each with a one-line rationale);
- **Requirements** discovered;
- **Open questions** left, and what would resolve them.

Offer to append them to `docs/decisions.md` with the next free IDs, today's date and a
status. A changed decision is marked `Superseded by D-xxx`, never deleted. Write to
the file only after the user confirms.

## Rules

- Converse in the user's language. Write the decision log in English (D-005).
- Do not change code during the grill; the only file you may edit is
  `docs/decisions.md`, after confirmation.
- Never invent the user's preferences; when unsure, ask.
- Never name commercial products used as inspiration in anything you write.
