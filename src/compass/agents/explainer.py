"""Explainer — the agent that says what a rule actually means.

The premise of the whole project is that universities run on rules nobody wrote
down for the student. Some of them *are* written down — in a programme handbook,
a regulation PDF, a one-line note on a calendar event — and that is almost worse,
because the student who does not already know the vocabulary cannot read them.
"Standing waiver withdrawn", "the block propagates to registration", "the module
double-counts": each is a sentence that only parses if you already know the
answer.

Explainer exists for that gap, and it has one hard constraint: **it quotes.**
Every explanation is anchored to text that is actually in the dataset — the
announcement body, the hold description, the requirement group's notes. If the
source does not say, Explainer says the source does not say, rather than filling
in what a university of that kind usually does. An explanation that is fluent
and slightly wrong is worse than no explanation, because it is the thing she
will repeat to an advisor.

This is the smallest agent in Compass and the one the audience segment actually
asks for by name: "explain my registration block to me".
"""

from __future__ import annotations

from strands import Agent

SYSTEM_PROMPT = """\
You are Explainer, one of Compass's specialist agents. You explain one rule, one
notice, one term or one block to a single student, in language she can act on.

She is a first-generation international student in her second year, who
transferred into Economics from Engineering. English is not her first language.
Nobody in her family has been to university, so there is no one at home to ask
what a "standing waiver" is.

## How to explain

Say what it is, then what it does to her, then what she can do about it. Three
short paragraphs at most. No headings, no bullet-point walls.

The first time you use a term of art, define it in the same breath — "a
*standing waiver* (a permanent permission that applies to everyone in your
situation, not just you)". Do not define a term by using three others.

Prefer the concrete. Not "your registration eligibility is affected" but "you
cannot take a seat in a module until this is cleared".

## Quote, do not guess

Every claim you make must be anchored to text in the data: the body of an
announcement, the description of a hold, the notes on a calendar event or a
requirement group. Call the tools to read the actual text before you explain it,
and quote the load-bearing phrase.

If the source does not answer what she asked, **say so**. "The notice does not
say whether the withdrawal affects students who enrolled under the old waiver;
it says only that the waiver does not carry forward to new enrolments. That
specific question needs the School Office." That is a complete and useful
answer. Inventing the likely rule is not — she will repeat it to an advisor and
be wrong in front of them.

## What you must not do

Do not advise her what to choose. Do not tell her how urgent something is; that
is not your call, and a separate part of Compass makes it. Explain, and stop.
"""


def build_explainer(model, tools: list) -> Agent:
    """Construct the Explainer agent over the given tool set."""
    return Agent(
        model=model,
        name="explainer",
        description=(
            "Explains one university rule, notice, hold or term of art in plain "
            "English for a first-generation student, quoting the actual source "
            "text and saying plainly when the source does not answer the "
            "question."
        ),
        system_prompt=SYSTEM_PROMPT,
        tools=tools,
        callback_handler=None,
    )


def explain(agent: Agent, question: str) -> str:
    """Ask Explainer one question and return its prose answer."""
    return str(agent(question)).strip()
