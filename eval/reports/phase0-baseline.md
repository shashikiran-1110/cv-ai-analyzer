# Eval report — 2026-10-03

Deterministic suites (no network, no LLM). Gold labels are in `eval/datasets/`.

| Suite | Metric | Value | Baseline |
|---|---|---|---|
| skills | precision | 0.9821 | — |
| skills | recall | 0.8333 | — |
| skills | f1 | 0.9016 | — |
| skills | trap_pass_rate | 0.9091 | — |
| skills | negation_accuracy | 0.9091 | — |
| skills | cases | 40 | — |
| experience | mae_months | 0.0 | — |
| experience | within_1_month | 1.0 | — |
| experience | cases | 17 | — |
| education | accuracy | 0.8 | — |
| education | cases | 20 | — |
| location | accuracy | 0.8 | — |
| location | cases | 20 | — |
| requirements | precision | 0.8824 | — |
| requirements | recall | 0.7143 | — |
| requirements | f1 | 0.7895 | — |
| requirements | cases | 6 | — |
| fairness | identical_rate | 1.0 | — |
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

## requirements: 3 failing case(s)

- `{"id": "short-bullets", "missed": ["Python", "SQL", "AWS and Docker"], "extra": [], "note": "finding F1: bullets under 15 characters are dropped"}`
- `{"id": "trailing-blurb", "missed": [], "extra": ["We are a friendly team. We are a friendly team. We are a friendly team."], "note": "finding F2: a trailing paragraph inside the Requirements section becomes a requirement"}`
- `{"id": "no-headings", "missed": ["You must hold an active RN license", "At least 2 years of acute care experience is required", "Experience with Epic EHR is a plus"], "extra": ["We're hiring a nurse for our surgical ward. You must hold an active RN license. At least 2 years of acute care experience is required. Experience with Epic EHR is a plus. We offer flexible shifts."]}`

## match: skipped

No human-reviewed pairs yet (ROADMAP Phase 1 needs ≥ 300). See eval/datasets/match/README.md.
