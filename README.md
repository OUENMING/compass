# Compass

**The missing manual for students nobody handed a manual to.**

A background agent that reads a university's degree rules the way a registrar
does, stays completely silent while everything is fine, and speaks up only when
staying quiet would cost a student something they cannot get back.

> Status: under active development for the **AWS Agents for Humans** hackathon
> (Good Neighbor track). Full documentation lands before submission.

## The problem

Universities run on rules that were never written down for students: prerequisite
chains that only bite two semesters later, holds that block registration, module
cap rules, and — the sharpest one — **rules that change mid-degree**, announced
to a handbook page rather than an inbox.

The students who get caught are not the ones who are struggling academically.
They are the ones with nobody at home who has already navigated a university.
That is the whole audience of this project: **first-generation and international
students.**

## What makes it different

Most "important!" systems become noise, because when you ask a model *is this
important?* the answer is almost always *yes, somewhat*. Compass never asks.

The model's job is to establish **facts** about a situation — what changed, what
it costs, when the last safe moment is, how confident it is. The decision to
interrupt is then made by a small deterministic gate
([`src/compass/gate.py`](src/compass/gate.py)) with six numbered rules. Every
verdict cites the rule that produced it, including the verdicts that produce
silence. "Compass stays quiet by default" is therefore a testable property, not
a prompt suggestion.

## Status of the data

**Every record in `data/` is fabricated.** No real student, institution or
programme data is present. Module codes follow common Irish/EU conventions for
realism only. See `data/meta.json`.

## Licence

MIT — see [LICENSE](LICENSE).
