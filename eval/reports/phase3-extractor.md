# Eval report — 2026-10-03

Deterministic suites (no network, no LLM). Gold labels are in `eval/datasets/`.

| Suite | Metric | Value | Baseline |
|---|---|---|---|
| skills | precision | 0.9821 | — |
| skills | recall | 0.8333 | — |
| skills | f1 | 0.9016 | 0.9016 |
| skills | trap_pass_rate | 0.9091 | 0.9091 |
| skills | negation_accuracy | 0.9091 | 0.9091 |
| skills | cases | 40 | — |
| experience | mae_months | 0.0 | 0.0 |
| experience | within_1_month | 1.0 | 1.0 |
| experience | cases | 17 | — |
| education | accuracy | 0.8 | 0.8 |
| education | cases | 20 | — |
| location | accuracy | 0.8 | 0.8 |
| location | cases | 20 | — |
| requirements | precision | 0.9535 | — |
| requirements | recall | 0.9762 | — |
| requirements | f1 | 0.9647 | 0.7895 |
| requirements | holdout_f1 | 0.9302 | — |
| requirements | cases | 12 | — |
| fairness | identical_rate | 1.0 | 1.0 |
| fairness | jobs | 14 | — |
| fairness | variants | 7 | — |
| match | labelled_pairs | 0 | — |

## Regressions vs baseline

None.

## skills: 10 failing case(s)

- `{"text": "Maintained a Ruby on Rails monolith with RSpec tests", "expected": ["Rails", "Ruby", "Unit Testing"], "got": ["Rails", "Ruby"]}`
- `{"text": "Excelled at stakeholder communication", "expected": ["Communication", "Stakeholder Management"], "got": ["Communication"]}`
- `{"text": "Designed RESTful APIs and GraphQL endpoints", "expected": ["GraphQL", "REST APIs"], "got": ["API Design", "GraphQL", "REST APIs"]}`
- `{"text": "Statistical modelling in R and Python (pandas, scikit-learn)", "expected": ["Pandas", "Python", "R", "Statistics", "scikit-learn"], "got": ["Pandas", "Python", "Statistics", "scikit-learn"]}`
- `{"text": "Figma prototypes and user research interviews", "expected": ["Figma", "Prototyping", "UX Design"], "got": ["Figma", "UX Design"]}`
- `{"text": "Led a team of six engineers and mentored juniors", "expected": ["Leadership"], "got": []}`
- `{"text": "Forklift operation and warehouse inventory management", "expected": ["Forklift Operation", "Inventory Management"], "got": [], "note": "out-of-taxonomy domain: measures open-set gap"}`
- `{"text": "Taught GCSE maths; lesson planning and classroom management", "expected": ["Classroom Management", "Lesson Planning"], "got": [], "note": "out-of-taxonomy domain"}`
- `{"text": "Drafted contracts and conducted legal research", "expected": ["Contract Drafting", "Legal Research"], "got": [], "note": "out-of-taxonomy domain"}`
- `{"text": "You don't need to know Go; we'll teach you", "expected": [], "got": [], "expected_negated": ["Go"], "got_negated": []}`

## education: 4 failing case(s)

- `{"text": "BA (Hons) English Literature", "expected": "Bachelor's", "got": null}`
- `{"text": "LLB Law, University of Leeds", "expected": "Bachelor's", "got": null}`
- `{"text": "Doctor of Philosophy in Chemistry", "expected": "PhD", "got": null}`
- `{"text": "B.S. in Nursing", "expected": "Bachelor's", "got": null}`

## location: 4 failing case(s)

- `{"user": "New York", "job": "NYC", "remote": null, "expected": true, "got": false}`
- `{"user": "Bengaluru", "job": "Bangalore, Karnataka", "remote": null, "expected": true, "got": false}`
- `{"user": "San Francisco", "job": "SF Bay Area", "remote": null, "expected": true, "got": false}`
- `{"user": "Paris", "job": "Remote - EMEA", "remote": true, "expected": true, "got": false}`

## requirements: 2 failing case(s)

- `{"id": "holdout-sales-mixed", "split": "holdout", "missed": [], "extra": ["Our culture", "We celebrate wins together and give back to the community every quarter."]}`
- `{"id": "holdout-nurse-bullets-no-heading", "split": "holdout", "missed": ["BLS and ACLS certification"], "extra": []}`

## match: skipped

No human-reviewed pairs yet (ROADMAP Phase 1 needs ≥ 300). See eval/datasets/match/README.md.
