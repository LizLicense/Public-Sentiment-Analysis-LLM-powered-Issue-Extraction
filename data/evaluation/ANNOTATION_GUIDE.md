# Blind evaluation annotation guide

## Purpose

These files replace the previous model-prefilled sample. Annotators must not view
VADER, transformer, or LLM predictions while labeling.

- `representative_annotator_a.csv`: primary model evaluation set.
- `challenge_annotator_a.csv`: difficult cases for separate error analysis.
- `double_annotation_annotator_b.csv`: independent overlap for a second annotator.
- `sampling_metadata.json`: seed, source allocation, and sampling weights.

Do not combine challenge-set results with representative-set headline metrics.

## Labeling order

Read the thread title and post text, then fill these columns:

1. `telco_relevance_manual`
2. `telco_targets_manual`
3. `sentiment_manual`
4. `issues_manual`
5. `confidence_manual`
6. `notes_manual`

Do not change `sample_id`, `evaluation_set`, `source`, `thread_title`, or
`post_text`.

## Telco relevance

Allowed values:

- `yes`: the text expresses information or an opinion about a telco, mobile
  network, mobile plan, or related telco service.
- `no`: the detected term is unrelated, such as the ordinary number "eight".
- `unclear`: context is insufficient.

If the value is `no`, leave sentiment and issues blank and briefly explain why
in `notes_manual`.

## Telco targets

Enter the operator or operators that the statement concerns, separated by
commas. Mentioned brands are not automatically targets. For example, a user may
compare StarHub and Singtel but express an opinion only about StarHub.

Use consistent names:

`Singtel`, `StarHub`, `M1`, `SIMBA`, `Giga`, `Eight`, `Zym`, `redONE`, `GOMO`,
`Circles`, `Vivifi`, `MyRepublic`, `Maxx`, `Heya`, `Zero1`, or `Other`.

## Sentiment

Label sentiment toward the telco target, not the mood of the surrounding thread.

- `happy`: explicit approval, satisfaction, recommendation, successful use, or
  clearly positive comparison.
- `not_happy`: complaint, dissatisfaction, warning, switching intent, service
  failure, or clearly negative comparison.
- `neutral`: factual question or statement, balanced/mixed view with no dominant
  polarity, or insufficient evidence of positive or negative sentiment.

Examples:

- "Giga no issue. Don't need to think about data." → `happy`
- "Time to cancel and change telcos." → `not_happy`
- "Does this plan include roaming in Malaysia?" → `neutral`

Do not infer sentiment from the thread title when the post itself clearly takes
a different position. Treat sarcasm, negation, and quoted speech using their
intended meaning.

## Issues

Enter one or more labels separated by commas:

- `Network Quality`: coverage, signal, speed, latency, outage, 4G/5G, or reliability
- `Pricing & Promotions`: prices, discounts, deals, vouchers, cashback, or promotion fulfilment
- `Mobile Plans`: SIM-only plans, allowances, contract terms, minutes, SMS, or plan features
- `Roaming`: overseas data, IDD, regional use, or travel connectivity
- `Porting`: number transfer, port-in, port-out, or switching process
- `Customer Service`: hotline, agent, support, complaint handling, or escalation
- `Billing & Payment`: bills, unexpected charges, refunds, invoices, GIRO, or card payments
- `App & Account`: app access, login, password, OTP, verification, account, or portal
- `Devices`: phones, eSIM/SIM cards, routers, modems, ONR/ONT, or operator equipment
- `General Discussion`: telco news, opinions, or discussion without a specific service issue

Use `General Discussion` only when none of the nine specific categories applies.
Multiple specific labels are allowed; do not add `General Discussion` alongside
a specific label.

## Confidence

- `high`: explicit and unambiguous
- `medium`: reasonable interpretation but some context is missing
- `low`: sarcasm, mixed targets, unclear reference, or substantial ambiguity

Use `notes_manual` to explain low-confidence decisions.

## Independent annotation

Annotator A labels the representative and challenge files. Annotator B labels
only `double_annotation_annotator_b.csv` without seeing Annotator A's work.
Calculate agreement before discussing disagreements:

- Cohen's kappa for telco relevance and sentiment
- per-label agreement or F1 for issues

Resolve disagreements in a separate adjudication copy. Never overwrite the two
original annotation files.

## Reporting

Use the representative set for the primary confusion matrices, per-class
precision, recall, F1, and macro F1. Because sources were stratified, use the
source weights in `sampling_metadata.json` for an overall prevalence-sensitive
accuracy estimate, and also report source-specific metrics.

Report challenge-set performance separately by difficulty type. Record the
exact model identifier, prompt, run date, runtime, token usage, retries, and
cost for every LLM experiment.
