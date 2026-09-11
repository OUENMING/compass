# The demo video — shot list and narration

Target **4:20**, hard ceiling 5:00. Public on YouTube or Vimeo, English.

Everything below is typed by hand on camera. No slide deck, no music, no
intro animation — the whole video is the product running, which is the point of
the "not just chat about it" criterion.

---

## Before you record

```bash
cd ~/compass
python -m compass.data.generate        # pristine dataset: 2 holds, unfiled plan
python -m pytest tests -q              # 114 passed — put this on screen once

# Nothing stale may be holding the port. A server left over from an earlier
# session serves the code as it was *before* your last edits, and you would
# record a demo that does not match the repository in the submission. This
# actually happened while preparing the take list.
lsof -nP -iTCP:8123 -sTCP:LISTEN       # must print nothing
uvicorn web.app:app --port 8123        # the decision card
```

Two browser tabs and one terminal:

- **Tab A** — `http://127.0.0.1:8123` (the decision card)
- **Tab B** — the GitHub repo page, scrolled to the top so the MIT licence in
  the About box is visible
- **Terminal** — `~/compass`, font size large enough to read on a phone

Set the terminal to a plain prompt and clear the screen before each take. Do one
take per act if you need to; the acts are separated by hard cuts anyway.

> A full sweep takes ~25 seconds because it is a real model call. Do **not**
> cut it out — cut *into* it. Show the "Watching" state while it runs, then jump
> cut to the cards appearing. The wait is evidence that it is doing something.

> **Check the take before you keep it.** The sweep has to report all three
> scenarios; roughly one run in seven comes back with only two, because the
> model sometimes walks past the unfiled plan. If the `[ACT]` line or the
> `degree-plan` card is missing, reset and take it again — it is a 25-second
> retake, and a demo that shows two of three acts is worse than shooting again.
> A good take also often shows a fourth, *silent* finding, which is worth
> leaving in (see Act 1).

---

## Act 0 · Cold open (0:00 – 0:35)

**On screen:** Terminal at `~/compass`. Type nothing yet.

**Say:**

> A university runs on rules that were never written down for students.
>
> Prerequisite chains that don't bite until two semesters later. A library fine
> that quietly becomes a registration block. A rule change published to a
> handbook page instead of sent to an inbox.
>
> None of it is secret. It's published the way a legal code is published —
> complete, unindexed, and written for the people administering it.
>
> The students who get caught aren't the ones struggling academically. They're
> the ones with nobody at home who has already navigated a university.
>
> This is Compass.

**Cut to:** Tab A.

---

## Act 1 · The thesis: silence is a decision (0:35 – 1:10)

**On screen:** The decision card in its **Watching** state. Do not click
anything yet.

**Say:**

> This is what Compass looks like when nothing is wrong. "Nothing has needed you
> yet."
>
> And underneath — this is the part that matters — every situation it looked at
> and deliberately decided *not* to interrupt you about, with the reason.
>
> Because here's the thing. If you ask a language model "is this important?", it
> says yes. About almost everything. That's why every system built this way
> becomes noise, and a student who's learned to ignore her agent is *worse off*
> than one with no agent at all — she's also lost the worry that would have made
> her check.
>
> So Compass never asks the model whether to speak. The model establishes facts.
> The decision to interrupt is made by code.

**Cut to:** Terminal, showing `src/compass/gate.py` open at the six rules.

---

## Act 2 · The withdrawn waiver (1:10 – 2:05)

**On screen:** Terminal. Run:

```bash
python -m compass.agents.compass
```

Let it run — show the sweep output. Then **cut to Tab A** and click **Run a
sweep**.

**While the sweep runs (about 25s), keep talking:**

> A rule changed on the 22nd of September. The notice went to a handbook page —
> it was never pushed to students.
>
> The rule used to let her skip Quantitative Methods and go straight into
> Econometrics I. It doesn't any more. And Econometrics II sits behind
> Econometrics I.

**As the cards slide in:**

> Two cards. Here's the first one.

Point at each element as you say it:

> What happened. What it costs if she ignores it. Why she's seeing it *at all* —
> "R6: irreversible in 25 days, and the choice is yours." And the options.

**Click the recommended option.** The card becomes a receipt.

**Say:**

> It registered her. That's a real registration against the same checks the
> registrar's system runs — prerequisite, credit cap, seat availability. If it
> had failed, the card would have shown the refusal.

**On screen:** Scroll to `data/receipts.jsonl` in the terminal. `cat` it.

> Every action lands in an append-only receipt log with a confirmation number.
> The numbers are derived from the action, not random, so re-running the demo
> gives you the same receipt. That's what makes "it did real work" checkable
> rather than a claim.

---

## Act 3 · The hold: money versus time (2:05 – 2:50)

**On screen:** Back to Tab A, the second card.

**Say:**

> Second card. Three overdue library items. Cheap today. On the 5th of October
> they become a forty-five euro charge *and* a financial hold that takes ten
> working days to clear — which won't land before registration opens.
>
> Two ways out. Return them in person, which costs a trip. Or authorise the
> forty-five euro, which costs money.

**Hover over the €45 button. Do not click it. Say:**

> Compass is not allowed to press this one for her.
>
> And that's not a prompt instruction. `AUTO_ACT_PERMITTED` in the policy module
> is a whitelist of two actions — repairing a degree plan and filing one. Both
> are bookkeeping where the programme's own written rules fix the outcome
> completely. Spending her money is not on the list, and never will be.
>
> This caught a real bug, actually. Early on, the model looked at this charge
> and reported "no judgement required" — reasoning that it has to be paid
> eventually. A gate that trusted that field would have paid it.

**Click "Return the items in person."** Show the receipt.

> Asked. Executed. Receipted.

---

## Act 4 · The one it did without asking (2:50 – 3:20)

**On screen:** Scroll the first sweep output in the terminal to the `[ACT]` line.

**Say:**

> And third — the one it did on its own.
>
> Her degree plan was never audited and isn't on file, and filing it is a
> prerequisite for registration opening. It double-counts one module across two
> requirement groups.

**Point at the receipt:**

> It repaired the plan, filed it, and left two receipts. No card, because there
> was nothing to ask. The programme's written rules *1* and *2* determine the
> outcome completely — asking would be theatre.
>
> That's the whole design in one screen, actually. Two cards and one silent
> action, and the silent one is the only one the rules let it take alone.

---

## Act 5 · The gate, in code (3:20 – 3:50)

**On screen:** `src/compass/gate.py`, scrolled to `AUTO_ACT_PERMITTED` and the
R6 branch.

**Say:**

> Six rules, evaluated in order, in about a hundred and fifty lines of plain
> Python. Confidence too low, the window's closed, it's recoverable, it needs no
> judgement, it's too far out — all silent. Only R6 reaches a person.
>
> Three properties fall out of that. It's *explainable*, because every verdict
> cites the rule that produced it, in language written for the student. It's
> *reproducible*, because the same finding on the same date always gives the
> same verdict — which means the tests and this video are testing the same
> thing. And it's *auditable*, because silence carries a reason too. "It did
> nothing" is distinguishable from "it crashed."

---

## Act 6 · The same agent, on AWS (3:50 – 4:20)

**On screen:** Terminal.

```bash
agentcore status
agentcore invoke "when is the W deadline?"
```

**Say:**

> And all of this is one agent. It runs locally and it runs on Amazon Bedrock
> AgentCore Runtime in eu-west-1 — same code, packaged from the repository root,
> so the deployed version and the local version can't drift apart.
>
> The runtime has no writable storage, so the first invocation of a session
> copies the dataset somewhere writable. Within a session the writes are real;
> they end with the session, which is the right lifetime for fabricated data.

**Cut to:** Tab B, the repo top, MIT licence visible in the About box.

**Say:**

> All the data in here is fabricated. The institution is fictional — I built it
> that way deliberately, because the scenarios depend on specific readings of
> regulations, and shipping them onto a real university's handbook would mean
> asserting things about a real institution's rules that could mislead a real
> student.
>
> A hundred and fourteen tests, no network.

**Close on the terminal, `pytest` output still on screen.**

> Compass.
>
> It stays quiet by default. When it does speak, it's because staying quiet
> would have cost you something you couldn't get back.

---

## Edit notes

- **Hard cuts, no crossfades.** The energy should be "this is a tool", not
  "this is a pitch".
- **Every mouse click gets a caption** naming what it did (`resolve_library_hold
  · return_in_person`). Small, bottom-left, two seconds.
- **The 25-second sweep gets one jump cut**, at the point where the cards appear.
  Cut *into* the wait, never out of it.
- **Zoom in on `AUTO_ACT_PERMITTED`** for Act 5. It is the single most important
  line in the repository and it should be readable on a phone.
- If you run long, cut Act 4 first — Act 3 carries the same argument. Never cut
  Act 3 or the receipt in Act 2; those are the two things the judges are
  explicitly scoring for.
