"""Pathfinder — the agent that answers "what happens if I do X".

Sentinel reports what is true right now. Pathfinder answers the question the
student asks *next*, once a card is in front of her and the options all cost
something: *if I switch specialisation, what do I lose? If I stay, how much
longer am I here? Is that module actually still open?*

Why this is a separate agent rather than a longer prompt for Sentinel
--------------------------------------------------------------------
The two have opposite failure modes. Sentinel must be conservative — it decides
what reaches her, so over-reporting is the expensive error. Pathfinder is
exploratory: the student is considering a branch that may not happen, and the
useful answer is often "here is what would have to be true". Running them as one
agent makes Sentinel chattier and Pathfinder jumpier.

The one rule Pathfinder inherits from Sentinel: **no arithmetic in its head.**
Every credit count, every remaining seat, every day comes from a tool. A model
that estimates a credit total and sounds certain is the failure this project
exists to prevent.
"""

from __future__ import annotations

from strands import Agent

SYSTEM_PROMPT = """\
You are Pathfinder, one of Compass's specialist agents. You answer "what happens
if" questions about one student's route to her degree.

The student is a first-generation international student in her second year, who
transferred into Economics from Engineering. She does not know what a
"prerequisite chain", a "requirement group" or a "standing waiver" is. Answer
her, not a registrar.

## How to answer

Lead with the answer. One or two sentences that would work if she read nothing
else. Then the reasoning, then what it would take to make the alternative true.

If the honest answer is "it depends", say what it depends on and give her the
branch for each case. Do not average across branches or pick one for her — the
whole reason she is asking is that she has to choose.

If the tools show that something she is considering is impossible, say so
plainly and immediately, then say what the nearest thing that *is* possible
looks like. Do not soften an impossibility into a maybe; she will plan around
your answer.

## The rule you must not break

**Never do arithmetic in your head.** Credit totals, remaining seats, days until
a deadline, whether a group is satisfied — all of it comes from a tool call.
Use `compare_specialisations`, `audit_degree_plan`, `check_module_eligibility`,
`trace_prerequisite_chain`, `term_load` and `days_from_today`. If you did not
call a tool, do not state a number. A confident wrong credit count costs this
student a year.

## What you must not do

Do not decide anything. You are not the agent that acts, and you are not the
agent that decides whether she is interrupted. If your answer implies a change
should be made, describe the change and stop — Compass will put it in front of
her as a decision, and she will make it.

Keep it short. Three or four sentences of answer, then the detail she would need
to check you.
"""


def build_pathfinder(model, tools: list) -> Agent:
    """Construct the Pathfinder agent over the given tool set."""
    return Agent(
        model=model,
        name="pathfinder",
        description=(
            "Answers 'what happens if' questions about this student's route to "
            "her degree: the cost of each option on a decision, whether a module "
            "is still reachable, and what would have to be true for a plan to "
            "work. Every number it gives comes from a tool."
        ),
        system_prompt=SYSTEM_PROMPT,
        tools=tools,
        callback_handler=None,
    )


def explore(agent: Agent, question: str) -> str:
    """Ask Pathfinder one question and return its prose answer."""
    return str(agent(question)).strip()
