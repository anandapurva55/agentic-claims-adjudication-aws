# Agentic Motor Claims Adjudication on AWS: Full-Stack Multi-Agent AI with RAG, MCP, Memory, Guardrails and Human in the Loop

Built with: a **React** 19, **TypeScript** and **Vite** frontend; a **FastAPI** and **Python** backend with a locked **uv** environment; **Amazon Bedrock**, **Strands Agents**, **Bedrock AgentCore Memory**, **Bedrock Knowledge Bases** on **S3 Vectors** (**retrieval-augmented generation**), **Bedrock Guardrails** and **Bedrock Data Automation**; the **Model Context Protocol**; **QLoRA** **fine-tuning** on **Amazon SageMaker**; **Amazon Cognito** managed login and **AWS WAF** rate limiting; **Amazon CloudFront** with a VPC origin to an internal load balancer, **Amazon ECS** on **Fargate** in a **VPC** with isolated subnets, **Amazon ECR**, **AWS Secrets Manager**, **Amazon DynamoDB**, **Amazon S3** and **Amazon CloudWatch**, all defined in **AWS CDK**; **AWS Glue**, **Amazon Athena** and **Amazon QuickSight** for the telemetry lake; and **GitHub Actions**, **CodeQL**, **Dependabot** and **GitHub Pages** for the CI, security scanning and the interactive demo.

[![CI](https://github.com/anandapurva55/agentic-claims-adjudication-aws/actions/workflows/ci.yml/badge.svg)](https://github.com/anandapurva55/agentic-claims-adjudication-aws/actions/workflows/ci.yml)
[![CodeQL](https://github.com/anandapurva55/agentic-claims-adjudication-aws/actions/workflows/codeql.yml/badge.svg)](https://github.com/anandapurva55/agentic-claims-adjudication-aws/actions/workflows/codeql.yml)
[![Interactive demo](docs/images/badges/interactive-demo.svg)](https://anandapurva55.github.io/agentic-claims-adjudication-aws/)
![Python](docs/images/badges/python.svg)
![AWS](docs/images/badges/aws.svg)
![Strands](docs/images/badges/strands.svg)
![MCP](docs/images/badges/mcp.svg)
![RAG](docs/images/badges/rag.svg)
![Guardrails](docs/images/badges/guardrails.svg)
![Cognito](docs/images/badges/cognito.svg)
![WAF](docs/images/badges/waf.svg)
![CloudFront](docs/images/badges/cloudfront.svg)
![DynamoDB](docs/images/badges/dynamodb.svg)
![S3](docs/images/badges/s3.svg)
![Secrets Manager](docs/images/badges/secrets-manager.svg)
![React](docs/images/badges/react.svg)
![TypeScript](docs/images/badges/typescript.svg)
![FastAPI](docs/images/badges/fastapi.svg)
![uv](docs/images/badges/uv.svg)

## Summary

This repository implements a decision support system for motor insurance claims. A team of AI agents reads the claim packet, reads the damage photo, retrieves policy clauses with **retrieval-augmented generation** (**RAG**), checks records over the **Model Context Protocol** (**MCP**), recalls lessons from earlier cases and recommends a decision. Deterministic code calculates the payable amount and makes the final recommendation. A human adjuster, signed in through **Amazon Cognito**, approves, overrides or escalates it, and the system records every step under the adjuster's verified name and role.

It is a full stack application. A **React** and **TypeScript** single page app streams a live agent run from a **FastAPI** backend that hosts the **Strands** agent graph, and the whole system runs on **AWS** and is defined in **AWS CDK**. It uses synthetic claim data, real policy wording and real damage photographs. Status: built, deployed to **AWS**, verified end to end by an automated check (29 of 29 checks on the latest deployment) and then torn down. It is measured against held-out claims, a free-form benchmark written by other model families, a **red team** suite and a cost model.

![A live run on the deployed system: Bedrock Data Automation and a vision model read the photo, agents use memory and MCP tools, risk signals appear, and a person decides](docs/images/demo/photo_evidence_and_signals.gif)

*A live run on the deployed system. The photo is read at ingestion, an agent recalls a lesson from long term memory, the photo and the repair estimate disagree, and the recommendation waits for a person.*

**Try it.** An [interactive demo](https://anandapurva55.github.io/agentic-claims-adjudication-aws/) of the app runs on GitHub Pages, with no server and no cost. It opens on the same sign-in screen as the live site, then a login page laid out like Cognito's, where any username works with any password that meets the real password rule, and everything after that is up to the visitor: pick a claim, run it, review it, try the senior approval rule. The AI agents are switched off there to avoid cost, so each run replays the rule baseline, and a banner says so on every page. [Interactive demo](#interactive-demo-on-github-pages) explains how it works and what it leaves out.

| Measure | Result | n |
|---|---|---|
| Decision accuracy on claims with wording the system had not seen | **98.7%** (95% interval 93.1% to 99.8%) | 78 claims in two held-out sets |
| Decision accuracy on 124 free-form narratives written and labelled by other model families | Agent team **98.4%** and a single model call **98.4%** | 124 claims |
| Unsafe approvals (a claim that must be denied, approved) | 0 on the golden set and on held-out set 2. 1 on held-out set 1, caused by a defect in the test data, analysed below. 1 each for the agent team and the single call on the free-form set | 63 + 78 + 124 claims |
| Payable amount exact | 100% on the template sets. The rules engine also reproduces 20 hand-calculated boundary claims | 141 + 20 claims |
| Red team attacks that succeeded against the hardened system | 0 | 30 attacks |
| Policy retrieval, recall at 3 (the default) and at 5 | 79.2% and 85.4% with clause cards (66.7% and 77.1% without) | 48 questions |
| Model cost per claim | 0.046 to 0.049 USD at the baseline, 0.035 USD with the optimised configuration (measured twice) | 22 claims, twice |
| Automated tests | 467 (409 Python, 58 frontend) | |

A single model call followed by the same rules engine matched the agent team on every accuracy benchmark at roughly one fiftieth of the cost, so the case for the agents does not rest on accuracy. It rests on what they add when the facts live in records: [Agents compared with a single call](#agents-compared-with-a-single-call) sets out the evidence, including where the agents lose.

---

## Contents

| Section | What it covers |
|---|---|
| [Problem and scope](#problem-and-scope) | The problem, the user, and what is in and out of scope |
| [Tenets](#tenets) | The principles that settled the design questions |
| [Solution architecture](#solution-architecture) | AWS services, the three paths and the release pipeline |
| [Design decisions](#design-decisions) | Each choice, the alternatives considered and what it costs |
| [How a claim is decided](#how-a-claim-is-decided) | The flow from claim packet to human decision |
| [Agents, MCP and memory](#agents-mcp-and-memory) | The Strands agent graph, MCP servers and two tiers of memory |
| [Document and image understanding](#document-and-image-understanding) | Bedrock Data Automation on forms and real damage photos, with measurements |
| [Retrieval-augmented generation (RAG)](#retrieval-augmented-generation-rag) | Chunking, embeddings, metadata, retrieval and its evaluation |
| [Human in the loop](#human-in-the-loop) | The sign-off gate that the API enforces |
| [Security and red team testing](#security-and-red-team-testing) | Threat model, defence layers and 30 attacks with controls |
| [Frontend: the workbench UI](#frontend-the-workbench-ui) | React and TypeScript app with a live agent graph |
| [Evaluation](#evaluation) | Golden and held-out sets, an independent oracle, ablations and the quality gate |
| [Agents compared with a single call](#agents-compared-with-a-single-call) | A single call baseline, a free-form benchmark and a planted problem investigation test |
| [Cost, latency and observability](#cost-latency-and-observability) | Telemetry lake, measured optimisations and alerting |
| [Fine-tuning a small model with QLoRA](#fine-tuning-a-small-model-with-qlora) | Method, results and when fine-tuning pays off |
| [Deployment](#deployment) | Acceptance test, console evidence and deploy commands |
| [Operating the system](#operating-the-system) | Alarms, failure modes and responses |
| [Quick start](#quick-start) | Run it locally |
| [Issues found and resolved](#issues-found-and-resolved) | Diagnoses and fixes |
| [Limitations](#limitations) | Open gaps and how to close them |
| [What I would do next](#what-i-would-do-next) | Planned improvements across retrieval, ingestion, identity and the fine-tuning study |
| [Repository layout](#repository-layout) | Where things live |
| [Data sources and references](#data-sources-and-references) | Datasets, policy wordings and papers |

---

## Problem and scope

An adjuster handling a motor claim reads a form, a repair estimate and a photo, compares them with the policy wording, decides whether an exclusion applies, and calculates what to pay. Most of the time goes to reading and cross-checking. The failure that matters is a wrong approval: paying a claim that the policy excludes.

**In scope.** Reading the packet, retrieving the relevant clauses, judging the narrative against exclusions, calculating the payable amount, surfacing risk signals, and recording a human decision with an audit trail.

**Out of scope.** Paying claims, fraud adjudication, customer communication, and any decision made without a person.

**Customer.** The claims adjuster. The metric that matters most is the unsafe approval count. Accuracy, cost and latency are secondary, and they are measured because they decide whether the system is usable.

---

## Tenets

These resolved the design questions below.

1. **Models judge, code decides.** A model sets six judgement flags. A tested rules engine turns flags and facts into a decision and a payable amount. A manipulated model can change a flag and cannot invent a payout.
2. **A person owns every outcome.** The **API** refuses to settle a claim without a recorded human decision. The UI is not the control.
3. **Customer text is hostile.** Narratives and garage remarks are data. They are scanned before any agent reads them, and no agent holds a tool that can act on them.
4. **Least privilege, including for memory.** Each agent receives only the tools it needs. Long term memory is writable only by a human.
5. **Measure against a baseline, on data not tuned against.** Every claim of improvement states its baseline, its sample size and its uncertainty.
6. **Report what failed.** Defects, retracted conclusions and open gaps are part of the result.

---

## Solution architecture

![AWS architecture](docs/images/aws_architecture.png)

| Path | Purpose | Services |
|---|---|---|
| **Serving** | Answer the adjuster | AWS WAF and Amazon CloudFront at the edge, Amazon Cognito for sign in, a CloudFront VPC origin to an internal Application Load Balancer, Amazon ECS on Fargate (arm64) running FastAPI and the agent graph |
| **Reasoning** | Decide | Amazon Bedrock models, Guardrails, Knowledge Bases, Bedrock Data Automation, AgentCore Memory |
| **Learning and operations** | Measure and improve | S3 telemetry lake, AWS Glue, Amazon Athena, Amazon QuickSight, Amazon CloudWatch, Amazon SageMaker |

| Service | Role in the system |
|---|---|
| Amazon Bedrock | Nova 2 Lite for the intake and investigator agents, Claude Haiku 4.5 for the coverage agent, Claude Sonnet 4.6 for the adjudicator memo. Model identifiers are configuration |
| Bedrock Guardrails | Prompt attack filter, hate and insult filters, PII handling, regex detectors for Aadhaar and PAN numbers, a denied topic for approval overrides |
| Bedrock Knowledge Bases on Amazon S3 Vectors | Policy clause retrieval with Titan Text Embeddings V2 ([RAG](#retrieval-augmented-generation-rag)) |
| Amazon Bedrock Data Automation | Reads the claim form and the damage photo into structured fields with two custom blueprints |
| Bedrock AgentCore Memory | Short term notes per claim, long term lessons (semantic strategy) writable only by a human |
| Amazon ECS on Fargate, internal ALB, CloudFront | Serving. The load balancer is internal, in isolated subnets with no route to the internet. CloudFront reaches it through a VPC origin, its security group admits only the group CloudFront attaches to that origin, and the listener rejects requests without a secret header |
| Amazon Cognito | Sign in. Only administrators create users. Two groups, `adjuster` and `senior`, become the reviewer's role. The site signs in through Cognito's hosted page with the authorization code flow and PKCE |
| AWS WAF | Rate limits per client address on CloudFront: 20 agent runs and 600 requests in 5 minutes |
| AWS Secrets Manager | Generates the secret header value at deploy time, so it never appears in the repository |
| Amazon DynamoDB | Policies, per claim extraction records, the human audit log, run metrics |
| Amazon S3 | Claim inputs and outputs, policy corpus, telemetry lake, fine-tuning artifacts |
| AWS Glue, Amazon Athena, Amazon QuickSight | One JSON record per model call lands in S3. Athena queries it with partition projection. QuickSight shows cost and latency |
| Amazon CloudWatch | Dashboard, latency and 5xx alarms, and a cost spike alarm fed by a custom metric |
| Amazon SageMaker | QLoRA fine-tuning job on one GPU instance |
| AWS CDK (Python) | Two stacks, `ClaimsAdjudicationData` and `ClaimsAdjudicationApp`. Synthesis needs no credentials, and tests assert the security properties of the synthesised template. The task role names its models, guardrail and resources instead of using wildcards. `-c production=true` keeps the data and logs when the stack is deleted |
| GitHub Actions | Workflows for lint, types, tests, the eval gate, the red team, CodeQL and deploy. The Python environment comes from `uv.lock`. Deploy and live evaluation authenticate through OIDC with a role supplied as a repository variable, so no long lived keys are stored |

![Release path](docs/images/release_path.png)

The **CI** workflow runs on every push and pull request in **GitHub Actions** and passes: lint with the security rules, **mypy**, the **Python** tests, the replay quality gate, the **red team** in replay mode, the frontend tests, an **npm** audit, the type check and build, the infrastructure security tests, and **CDK** synthesis. A separate **CodeQL** workflow scans the **Python** and **TypeScript** on every push. Deploy and live evaluation are manual workflows. They need an **OIDC** provider and a deploy role that this **CDK** app does not create.

The architecture diagrams are written as code with the **Python** `diagrams` library ([docs/diagrams/generate.py](docs/diagrams/generate.py)), so they are versioned and reviewed with the system.

---

## Design decisions

| Decision | Alternatives considered | Rationale | Cost of the choice |
|---|---|---|---|
| A rules engine decides, models set flags | Let an agent decide and calculate | Money and exclusions need exactness and resistance to injection. The engine reproduces all 63 golden outcomes and 20 hand-calculated boundary claims exactly given correct flags | The engine must be maintained as policy changes. Novel situations route to a human instead of being guessed |
| ECS on Fargate | EC2, Lambda | No servers to patch, scales per task, costs nothing when scaled to zero. Agent runs last 20 to 40 seconds with streaming, which suits a long lived container better than Lambda | Live runs are serialised per task because tool state is per process. Scaling out means more tasks |
| S3 Vectors | OpenSearch Serverless, pgvector | The corpus is small (hundreds of chunks). S3 Vectors has no standing hourly charge | No hybrid (keyword plus vector) search |
| Public subnets for tasks, isolated subnets for the load balancer, no NAT gateway | Private subnets with NAT | Saves roughly one dollar a day for a workload with no private resources. The load balancer is internal, so it has no public address at all, and tasks accept traffic only from it | Tasks have public IPs. Acceptable here, not for a regulated workload |
| CloudFront reaches the API through a VPC origin to an internal ALB | A public ALB limited by CloudFront's prefix list and a secret header. HTTPS to the origin, which needs a certificate and a domain name | Traffic never crosses the public internet, the load balancer cannot be reached except through CloudFront, and no domain has to be bought. The secret header stays as a second check | More moving parts: CloudFront attaches its own security group to the origin's network interfaces, and the load balancer has to admit that group by id (see [issues found and resolved](#issues-found-and-resolved)) |
| Cognito hosted sign in, authorization code flow with PKCE | A login form in the app, a shared API key | No password passes through the application, tokens never appear in a URL, and the role is a group inside a token the API verifies | The hosted page has Cognito's default look. Administrators create users |
| Python dependencies locked with uv | pip and requirements files | `uv sync` rebuilds the exact environment CI tests, down to the hash of every package. A warm install took 1 second against 27 for pip on the same requirements | Contributors need one extra tool |
| Bedrock Data Automation for documents | A local PDF parser, Amazon Textract | Managed, handles forms and images with one project, custom blueprints give typed fields. A deterministic parser runs beside it as an independent second reader | 15 to 30 seconds per job, so it runs at ingestion, not on click. Two readers can disagree, which is the point of the check |
| Two MCP servers, stdio | Direct function calls | One protocol for tools. The same servers can be reused by another agent. Tool access is scoped per agent | Process startup per run |
| Human write only long term memory | Let agents store lessons | Closes the memory poisoning route | Lessons arrive only through human review and seeding |
| Model identifiers as configuration | Hard coded models | The account's Bedrock quotas are small and differ per model, so the system spreads models across quotas and can swap them | Behaviour depends on which models are configured, so evaluations record them |

---

## How a claim is decided

![Agent graph](docs/images/agent_graph.png)

1. **Ingest.** **Bedrock Data Automation** and a vision model read the form and the photo at ingestion. The run loads their output, and compares **Bedrock Data Automation**'s reading of the form with a deterministic parser's.
2. **Quarantine.** The narrative is customer controlled. **Guardrails** scan it, remove injected sentences and keep the legitimate facts.
3. **Intake agent.** Recalls lessons from memory and records six judgement flags (intoxicated, commercial use, unlicensed driver, mechanical failure, tyre only, theft), quoting the sentence behind each. It respects negation.
4. **Coverage and Investigator agents run in parallel.** Coverage retrieves clauses through an **MCP** server and calls the payable calculator. The Investigator checks garage history, benchmark repair costs, repeat claims and the police report through a second **MCP** server and records advisory risk signals.
5. **Bounded collaboration.** Agents may post questions to each other for a limited number of rounds.
6. **Photo check and rule checks.** Code compares the parts the photo shows as damaged with the parts on the estimate and adds an advisory signal if they disagree. It also adds any finding the Investigator should have recorded and did not: a repair cost above its benchmark, a flagged garage, a repeat claim, a missing police report. Every signal carries its source, `agent` or `rules`.
7. **Adjudicator.** The deterministic engine applies the rules in precedence order and produces the decision, calculation and next step. A model writes the memo.
8. **Human adjuster.** Accepts, overrides or escalates. An override becomes a candidate evaluation case and a lesson in long term memory.

If an agent does not finish, the claim is referred to a person with reason `INT.AGENT`. The system does not guess.

---

## Agents, MCP and memory

**Strands agent graph.** Four agents are nodes in a **Strands** graph. Hooks emit an event for every model call, tool call and handoff, and the animated graph in the UI is drawn from that stream, so every pulse corresponds to something that ran. A call budget of 40 model calls per run bounds a runaway agent.

**MCP servers.** Two servers expose tools over stdio: `policy_records` (policy wording search, schedule, claim history) and `claims_ops` (garage check, repair cost benchmark, police report verification). Each agent receives only the tools it needs, and no tool pays money, edits a policy or reaches another customer.

**Findings the agent does not record.** Looking things up is code's job, and an agent is asked to record what it finds. The investigation test ([below](#where-the-agents-do-earn-their-place-investigating-records)) showed that a model sometimes describes a finding without calling the tool that records it. In a traced run the Investigator received a flagged garage with six flagged estimates, wrote in its summary that it had recorded a medium risk signal, and never called `record_risk_signal`, so the adjuster would have seen nothing. Across the 9 single-finding garage runs it recorded none. The run therefore ends with `add_rule_signals`, which adds every finding the rules can reach that the agent did not record, keeps the agent's own signals, and recognises a second inflated repair line when the agent flagged only the first. Applied to the 84 stored agent runs, exact matches rose from 62 to 73 at no extra cost. This guarantees delivery of what the rules can find. It does not make the agent better at judgement, which is what the agent is for.

**Memory in two tiers.**

| Tier | Holds | Written by |
|---|---|---|
| Short term (AgentCore events) | Agent to agent notes for the current claim | Agents |
| Long term (AgentCore semantic memory) | Lessons from senior adjusters and from overrides, for example that "a few drinks" or "whiskeys" mean the driver was intoxicated even without the word alcohol | **Humans only** |

**Effect of memory and collaboration.** Removing either one brought back one specific failure on the hard cases (see [ablations](#evaluation)): with no memory a claim describing "whiskeys at a wedding" was approved in 1 of 3 runs, and with no collaboration a claim about a parcel from a friend was wrongly denied in 2 of 3 runs. These are single claims with small repeat counts. They point to where to look and do not establish a mechanism.

---

## Document and image understanding

**Amazon Bedrock Data Automation** turns unstructured files into structured fields. One project holds two custom blueprints.

| Blueprint | Input | Fields |
|---|---|---|
| `claims-adjudication-motor-claim-form` | Claim form PDF | claim id, policy number, holder, registration, incident and report dates, police FIR, claimed amount, narrative |
| `claims-adjudication-vehicle-damage-photo` | Damage photo | `is_vehicle_photo`, `damaged_parts`, `severity`, `description` |

Jobs are asynchronous and take 15 to 30 seconds, so they run as an ingestion step, not when an adjuster opens a claim. Ingestion is a batch script here, and an **S3** event would trigger it in production. Results are stored with the claim (**DynamoDB** in **AWS**, files locally) and the agent run reads them. [scripts/run_bda_ingest.py](scripts/run_bda_ingest.py) processes every file and scores the output.

![Bedrock Data Automation blueprint tested on a real damage photo in the console](docs/images/aws/bda_blueprint_photo_result.png)

**Claim forms.** At run time the form fields come from a deterministic parser, because the generated PDFs have a known layout. **Bedrock Data Automation** reads the same forms independently, and a disagreement between the two readers raises an advisory signal. Across 63 forms, `claim_id`, `policy_no`, `vehicle_reg`, `incident_date`, `report_date` and `claimed_amount` were 100% correct and `holder` was 92.1%. The five misses are one surname: the **OCR** read "Iyer" as "lyer". 58 of 63 forms were fully correct, and the five holder-name misses surface to the adjuster as low severity signals.

**Damage photos.** The photos are real: 70 photographs from the public **Kaggle** Coco Car Damage Detection Dataset (CC0), annotated with which parts are damaged (headlamp, front bumper, rear bumper, hood, door). [scripts/attach_real_photos.py](scripts/attach_real_photos.py) gives each claim the unused photo whose damaged parts best match the parts on its estimate. 44 of 63 claims receive one. The other 19 list only parts outside those five, and the UI says so. The annotations allow the reading step to be scored against ground truth over all 70 photos:

| System | Precision | Recall | F1 |
|---|---|---|---|
| Bedrock Data Automation plus Claude Haiku 4.5, union (used) | 0.87 | **0.74** | **0.80** |
| Claude Haiku 4.5 | 0.86 | 0.68 | 0.76 |
| Claude Sonnet 4.6 | 0.94 | 0.61 | 0.74 |
| Nova 2 Lite | 0.93 | 0.59 | 0.72 |
| Bedrock Data Automation, revised blueprint | 0.95 | 0.51 | 0.66 |
| Bedrock Data Automation, first blueprint | 0.96 | 0.44 | 0.60 |
| Intersection of BDA and Haiku | 0.95 | 0.45 | 0.61 |

**Bedrock Data Automation** is cautious: when it names a part it is right 95% of the time, but it finds about half of the labelled parts. The blueprint instruction was revised once, and evaluated on the half of the photos not examined while editing: F1 rose from 0.64 to 0.69. Combining it with a vision model recovers most of the missing recall. The union rule was fixed before it was scored, nothing was tuned, and on the held-out half F1 is 0.82 against 0.80 for **Haiku** alone and 0.69 for BDA alone. The product therefore reads each photo with both and uses the union. Ingestion cost is one extra vision call per photo.

The photo never affects the decision. It feeds an advisory signal, so a false alarm costs an adjuster a glance and a miss changes nothing about payment.

![Claim packet with the real photo and the parts detected](docs/images/app/claim_packet_photo.png)

---

## Retrieval-augmented generation (RAG)

Policy wording is retrieved at run time and cited. It is not placed in prompts. The retrieval layer has one job: return the clause an exclusion lives in, with an identifier the adjuster can check.

| Stage | Choice | Reason |
|---|---|---|
| Corpus | Three insurers' private car package wordings (PDF), plus 16 clause cards | Cards are one short document per clause: 12 verbatim policy clauses and 4 internal controls |
| Chunking | Fixed size with 20% overlap. 150, 300 and 800 tokens compared. Cards are ingested as separate documents at 500 tokens | Clauses are short and cross-referenced, so chunk boundaries decide whether an exclusion and its condition stay together |
| Metadata | A sidecar file per card carries `clause_id` and `origin`, and it is returned with every hit | The agent cites `SEC1.EXCL.1c`, not a page number |
| Embeddings | Amazon Titan Text Embeddings V2, 1,024 dimensions, float | One model for chunks and queries |
| Index | Amazon S3 Vectors, one index per knowledge base | No standing hourly cost for a corpus of a few hundred vectors |
| Retrieval | Approximate nearest neighbour, top 3 by default, exposed to agents as the MCP tool `search_policy_wording` | The agent can request more |
| Grounding | The coverage agent reasons over the returned text and cites clause identifiers | The rules engine decides, so retrieval is not on the payout path |

**Evaluation.** 48 questions, each tied to the clause that answers it and phrased the way an adjuster or customer would ask, not in the policy's words. A question is a hit at k if its clause is in the top k. Four configurations were compared on the same questions:

| Configuration | Recall at 1 | Recall at 3 | Recall at 5 | MRR at 5 |
|---|---|---|---|---|
| 300 token chunks | 35.4% | 66.7% | 77.1% | 0.52 |
| 150 token chunks | 52.1% | 66.7% | 72.9% | 0.60 |
| 800 token chunks | 45.8% | 68.8% | 70.8% | 0.56 |
| 300 token chunks plus clause cards | **60.4%** | **79.2%** | **85.4%** | **0.70** |

Small chunks gave better recall at 1 and lost context by 5. Large chunks did the reverse. Clause cards improved every measure, so the product uses them, and the operating point is recall at 3 because the tool returns 3 chunks by default. The weakest topics with plain chunks were coverage ("is a flood covered?"), tyres and mechanical failure, where the customer's words and the policy's words share few terms.

**Trade-offs and failure modes.**
- **S3 Vectors** has no hybrid (keyword plus vector) search, which is the usual fix for that vocabulary gap. A managed search cluster would add it at a standing cost that a corpus this size does not justify.
- A retrieval miss weakens the explanation and the citation. It cannot change a decision or a payout.
- Ingestion allows one concurrent job per **knowledge base**, so the deployment runs them in sequence. Changing the embedding model means re-ingesting, which is cheap because the index is rebuilt from **S3**.
- 48 questions over 16 clauses rank configurations. They do not establish production recall.

---

## Human in the loop

The AI recommends and a person decides. The **API** enforces this, so it cannot be bypassed by calling an endpoint directly.

![The human sign-off gate: an adjuster is blocked above the authority limit, a senior adjuster signs in through Cognito and accepts, and the decision is logged](docs/images/demo/human_in_the_loop.gif)

| Rule | Mechanism |
|---|---|
| Nothing is settled without a human | A claim moves new, AI recommended, reviewed. The only exit from AI recommended is a recorded human decision. Reviewing before the agents ran returns 409 |
| Four eyes above the authority limit | A payable above INR 200,000 can be approved only by a senior adjuster. An adjuster receives 403 and can always escalate |
| Overrides need a reason | An override carries a final decision and a written reason of at least 10 characters, stored beside the AI recommendation |
| A review names the run it looked at | Every review carries the id of the run the reviewer was shown, and the API refuses it with 409 if the latest recommendation has a different id, so "accept" always means the result on screen and not whatever a colleague produced a second later. A recommendation that came from another mode than the deployment's, or that predates run ids, cannot be approved either |
| One decision per claim | A conditional DynamoDB write allows exactly one human review per claim. Two reviewers deciding at the same moment get one success and one 409, tested with eight concurrent writers and mutation checked, so the trail cannot be rewritten even with several tasks running |
| Attributable | Each record holds who, their role, the AI recommendation and clauses, the final decision and the outcome. The name and role come from the sign in token, never from the request body, so a caller cannot promote themselves by editing JSON |
| Never a dead end | Every referral names the next action: a senior adjuster, resubmitted documents when form and estimate disagree, a delay investigation, a police report for theft |
| Disagreement becomes data | An override is saved as a candidate evaluation case and as a lesson in long term memory |

The audit log lives in **DynamoDB**, which is the single source of truth. Every task reads it directly, so scaling out cannot split it, and listing the claims takes one read of the log instead of one per claim.

---

## Security and red team testing

**Red team testing** means attacking the system on purpose, the way a malicious claimant or garage would, and counting what gets through. It is the adversarial counterpart of the functional tests.

**Threat model.** The attacker is a claimant or a garage who controls the narrative, the remarks or a document. Goals: get an excluded claim approved, make the system reveal a secret (identifiers, prompts, another customer's data), misuse a tool, or plant a rule in memory.

| Layer | Control |
|---|---|
| 1. Input guardrail | Bedrock Guardrails scans text for prompt attacks. If a whole text is blocked, each sentence is checked alone so only offending sentences are removed |
| 2. Data, not instructions | Prompts state that the narrative is data. Instructions inside it are reported, never followed |
| 3. Least privilege tools | Each agent reads only the claim in front of it. No tool pays money, edits a policy or reaches another customer |
| 4. Code decides | Agents set flags and an engine decides, so a hijacked agent cannot produce a payout |
| 5. Memory is human write only | Agents recall lessons and cannot write them |
| 6. Human in the loop | Every recommendation is reviewed and logged |
| 7. Sign in and input limits | Every route except the health check needs a valid Amazon Cognito ID token, checked for signature against the pool's keys, issuer, audience, expiry and token type. A caller in no group gets 403. Review actions, decisions and run modes are fixed value types, free text has length limits, and the reviewer's name is cleaned before it reaches the audit log |
| 8. Private network | The load balancer has no public address. CloudFront reaches it through a VPC origin, and its security group admits only the group CloudFront attaches to that origin. The task role names the three models, the guardrail and the resources it uses |
| 7b. One mode per deployment | A deployment runs in the mode its operator set. A live deployment refuses a replay run with 409, so the keyword baseline's answer can never be stored as the AI recommendation that a person then approves, and a replay deployment refuses live runs |
| 9. Rate and spend limits | AWS WAF limits each address to 20 agent runs and 600 requests in 5 minutes. A daily spend limit (5 USD by default, summed from DynamoDB across all tasks) refuses new live runs with 429 and fails closed with 503 if the spend cannot be read |

![Attack lab: scan an attack and see exactly which sentence the guardrail removed](docs/images/demo/attack_lab.gif)

![A guardrail blocking an injected instruction inside a claim narrative, and the claim being denied](docs/images/demo/guardrail_demo.gif)

**Suite.** [redteam/attacks.json](redteam/attacks.json) holds 30 attacks in six types: instruction override, hidden text in a document, secret extraction, tool misuse, memory poisoning and plausible fabrication. Each attack is appended to a genuine narrative that must be denied. An attack succeeds if the system approves, or reveals a real secret value.

**Results, with controls.**

| System | Attacks scored | Flagged by the guardrail | Succeeded | Attributable to the attack |
|---|---|---|---|---|
| Hardened, defences on | 29 (1 errored) | 15 (52%) | 0 | 0 |
| Hardened, defences off | 30 | not applicable | 0 | 0 |
| Naive single agent, no graph, engine or guardrail | 30 | not applicable | 2 | **0** |

With defences on, the **guardrail** flagged instruction override 5 of 5, hidden text 4 of 5, plausible fabrication 2 of 5, secret extraction 2 of 5, tool misuse 1 of 5 and memory poisoning 1 of 4.

**Interpretation.**
- The naive agent's 2 raw successes are not attributable to the attacks. A no-attack control (the same 10 base claims with no injected text) showed the naive agent wrongly approves 2 of 10 claims even when nobody attacks it. An earlier version of this experiment reported a 20% attack success for the naive agent. The control showed that figure was mostly its baseline error rate, so the table reports attribution.
- The **guardrail** flags only 52% of attacks. It is weakest on attacks that use ordinary words: fabrication, tool misuse and memory poisoning. That is the reason the controls do not rely on it, and why layers 3 to 6 exist.
- 0 of 30 is a result against attacks written by the system's author, with one **guardrail** configuration. It shows the pipeline held against these attacks. It does not show that the system cannot be attacked.

**Verified on the deployed stack.** Layers 7 to 9 were checked on **AWS**, not only in tests. A headless browser followed the real sign in flow: a wrong password was refused, a valid login returned to the app with the right name and role, the token worked on the **API**, the session survived a reload, the evidence photo loaded through the cookie, sign out cleared the session, and a senior adjuster received the senior role. A review sent with a body claiming another role and name was recorded under the role and name in the token. A burst of 30 run requests without a token all reached the **API** and received 401. A minute later the same 30 were blocked at the edge with 403, while ordinary requests such as the health check still passed. The first deployment also exposed a defect that no test had caught, described in [issues found and resolved](#issues-found-and-resolved).

---

## Frontend: the workbench UI

The frontend is a **React** 19 and **TypeScript** single page application built with **Vite**. It starts a claim run with a `POST` and reads the server-sent event stream from the response with `fetch`, because `EventSource` can only send `GET` and cannot carry the sign in token. It draws the agent graph as hand-written **SVG** animation, so each node and pulse corresponds to an event emitted by a **Strands** hook or a service call. It is served from **S3** through **CloudFront**, and the `/api` path is routed to the backend.

Signed out visitors see the sign in screen: the form on the left and a fixed example of the review card on the right, so a reviewer sees what they are about to work with. The button sends them to **Amazon Cognito**'s managed login page, styled to match (dark, the same wordmark and buttons, the same example card as its background), using the authorization code flow with **PKCE**. They return with a code that is exchanged for tokens, and the address bar is cleaned. The ID token is refreshed before it expires and sent on every call, and a cookie scoped to the read-only file path lets the evidence photo load, since an image tag cannot send a header. When the site has no sign in configuration, as in local development, the wall is skipped and a demo role selector appears.

![The sign in screen, shown to a signed out visitor](docs/images/app/signin_gate.png)

![Cognito's managed login page, styled to match the app](docs/images/app/signin_cognito_hosted_page.png)

![Signing in: the app's screen, Cognito's page, the credentials, and the workbench with the account menu](docs/images/demo/sign_in.gif)

**Passwords.** Sign up is off: an administrator creates each account, and its group sets the role. The sign-in screen says so: there is no sign up, and an administrator provides the credentials. Someone without an account sees a "Request access" link that writes to an address set at build time (on the Pages site, from the repository variable `REQUEST_ACCESS_EMAIL`, so it is in the repository's settings and not in the code). "Forgot your password?" sends a code by email, which needs a verified email address on the account, so administrators create users with one. A user created without an email has no way to reset a password, which this project found when the first test user could not.

![The forgot password page](docs/images/app/signin_forgot_password.png)

![The reset code email, as Cognito sends it](docs/images/app/password_reset_email.png)

![Workbench mid run, live](docs/images/app/workbench_live_run.png)

- **Workbench.** Claim queue with filters, the live agent graph, the claim packet with the photo and detected parts, a reasoning trace, and the decision panel with checks, calculation, clause citations, risk signals, recalled lessons and review controls. The header shows the signed in person's initials, and their menu gives the name, the role from the token (which is what the four eyes rule uses), what that role may approve, and sign out.

![The account menu: name, role and approval limit](docs/images/app/account_menu.png)
- **Architecture.** The graph, static, with the design principles.
- **Security.** The attack lab, **red team** results and defence layers.
- **Observability.** Cost, latency, where the money goes, alert rules and review statistics.

![Decision panel with risk signals, memory and the sign-off gate](docs/images/app/risk_signals.png)

![Architecture tab](docs/images/app/architecture_tab.png)

The mode badge states whether a run was the offline baseline or live on **Bedrock**.

**Tests.** 58 **Vitest** tests cover the **PKCE** challenge against the test vector in RFC 7636, token decoding and role mapping, the **server-sent events** parser (including every way a stream can be cut into chunks and the queue position events) the **API** layer against a fake server, and the interactive demo's review rules and sign in (below). Five planted bugs, among them a `GET` where the run should be a `POST`, were each caught. A headless browser run against the built app checks the same flow end to end: the run streams, the review is recorded under the right identity, the photo loads and the console stays clean.

---

### Interactive demo on GitHub Pages

GitHub Pages serves files, so it cannot run the **FastAPI** backend, **Cognito** or the agents. The Pages site is the same **React** app built in a demo mode that needs no server, and it is honest about that: a banner on every page, the sign-in screen included, says the agents are switched off to avoid cost.

- **Data from the real backend.** `scripts/build_static_demo.py` runs the real backend once in replay mode and saves what it said: the 63 claims, the extracted fields, every claim's photo and PDFs, each claim's run as the exact event stream, the recommendation each run stores, the 30 sample attacks with the guardrail's answer, and the red team report. If the backend changes, running the script again changes the demo.
- **A fetch layer instead of an API.** A small module in the frontend (`frontend/src/demo/staticBackend.ts`) answers the app's `/api` calls from that saved output. A run plays back at a natural pace, the graph lights up, and the recommendation is stored in the visitor's own browser, so a reload keeps their work and Reset demo clears it. Nothing is sent anywhere, and nothing starts by itself: the visitor picks the claim and presses Run agents.
- **The same sign-off rules.** The review gate is a port of the server's: a review must name the run it looked at, an adjuster cannot approve above the authority limit but can escalate, an override needs a decision and a reason, and one decision settles a claim. 16 tests pin this, and nine deliberate breakages (no four eyes check, no run match, recording at the start of a run, a second decision allowed, a short reason accepted, claiming a lesson was stored, allowing a live run, trusting an old saved state, treating escalation as approval) were each caught.
- **What it leaves out, and says so.** The agents do not run, so decisions come from the rule baseline. A reason typed for an override is not scanned for prompt attacks and is not stored as a long term lesson, and the response says no lesson was stored. The attack lab answers the sample attacks only. The Observability tab shows screenshots from the live deployment instead of invented numbers.
- **A "Try it" strip.** A visitor does not know to pick a claim first, so the top of the workbench lists four steps: pick a claim, run the agents, make the call, and change roles from the account menu. Each step is ticked off as it is done and the next one is highlighted, with two suggested claims (CLM-2026044, which carries an injected instruction, and CLM-2026043, whose payout needs a senior). 4 tests pin the order and the ticking, and 5 deliberate breakages were each caught.
- **Sign in is a stand-in that behaves like the real one.** The demo opens on the same sign-in screen as the live site, with its line that there is no sign up and that an administrator provides credentials. "Continue with your account" leads to a login page laid out like Cognito's, where any username works with any password that meets the real user pool's rule: 12 or more characters with upper and lower case letters, a digit and a symbol. The rule appears under the password box, once the person starts typing, as a checklist that is red until each requirement is met and turns green in real time, and signing in is refused until all five are green. A made-up user has no group to give them a role, so they start as an adjuster and switch to senior adjuster from the account menu (marked demo) to try the approval rule. Nothing typed leaves the browser, and the sign in protects nothing, because a public static site holds nothing to protect. A reload keeps the visitor signed in, and signing out returns to the sign-in screen. 13 tests cover the password rule, the sign in, the role switch (which does nothing outside the demo) and the saved session, and 16 deliberate breakages (the rule skipped, a shorter minimum, no symbol or digit required, an empty or uncleaned or over long username, a new user starting as senior, a switch that ignores the role or is not remembered or works signed out or outside the demo, sign out keeping the login, a reload losing it, a saved role not checked) were each caught.
- **Cost.** None. The workflow `.github/workflows/pages.yml` saves the data from the backend, builds the site and publishes it on every push to `main`.

## Evaluation

**Golden set.** 63 claims in 22 scenarios, with expected decisions, clauses and payable amounts, including negations ("had not consumed any alcohol"), paraphrases ("ferrying paying passengers through an app"), injected instructions and documents that disagree. The first golden set was too easy: the keyword baseline scored 100%. Adding negation and paraphrase cases dropped it to 82.5% with 8 unsafe approvals, and that gap is what the agents are measured on.

**The golden set was iterated on**, so its 100% shows coverage of the scenarios the system was built for. It does not show generalisation. Two held-out sets were built to measure that.

**Held-out sets.** Each has 39 claims, a new random seed, new claim identifiers, and new wording for every hard scenario and for the accident sentence. None of that text appears in the golden set, the memory lessons or the agent prompts. Each was generated once and scored once.

| Set | Keyword baseline | Agents | Unsafe approvals | Payable exact | Injection handled |
|---|---|---|---|---|---|
| Golden, 63 claims (iterated on) | 82.5%, 8 unsafe | 100% | 0 | 100% | 100% |
| Held-out 1, 39 claims | 84.6%, 4 unsafe | 97.4% (38 of 39) | 1 | 100% | 100% |
| Held-out 2, 39 claims | 66.7%, 7 unsafe | **100%** (39 of 39) | 0 | 100% | 100% |
| Held-out 1 and 2 together, 78 claims | | **98.7%** (77 of 78), 95% interval 93.1% to 99.8% | | | |

**Root cause of the one miss.** In held-out 1 the narrative reads: "Another motorist reversed into the parked car outside the owner's house. The driver admitted to having had several drinks at a party before the trip." The label says deny. The agents approved. The insured car was parked and nobody was driving it, so approving is defensible. The generator had combined an accident sentence that implies a parked car with a driver-condition clause. The label was not changed after the result, because that would tune the test to the answer. The result stands as measured and it fails the live gate. The generator was fixed (the insured must be driving in every accident sentence), held-out 1 is kept byte for byte reproducible, and held-out 2 was produced by the fixed generator, a new seed and the same agents. No agent code or prompt changed between the two runs.

**An independent oracle.** The golden labels were produced by the same logic that implements the rules, so matching them cannot catch a rule that is wrong in both places. [evals/golden/independent_cases.json](evals/golden/independent_cases.json) holds 20 claims whose answers were worked out by hand from the policy wording and the standard age depreciation schedule, with the working written beside each. Every case sits on a boundary: the age bands, exactly 75% of the insured value (which is not a total loss) and one rupee over, the authority limit, notice on day 15 and day 16, half a rupee rounding up, and the first and last day of the policy. Eight deliberate engine bugs, each on one of those boundaries, were each caught by exactly one case.

**The engine under random testing.** A random test of 20,000 claims found four defects that the golden set had hidden, all now fixed and pinned by tests that fail on the old engine: a report date before the incident date was approved (2,801 cases), an estimate whose total did not match its own lines was approved, an unreadable date raised an exception, and float arithmetic with banker's rounding left 1,916 of 19,005 partial payables one rupee off. Money now uses exact decimals with halves rounded up, and the repository keeps property tests over 10,000 random claims.

**Gate.** Thresholds live in [evals/thresholds.json](evals/thresholds.json) and are versioned with the code:

| Gate | Metric | Bound |
|---|---|---|
| Baseline regression guard | decision accuracy, payable exact, injection handled | at least 0.80, 0.85, 1.0 |
| Live agent ship bar | decision accuracy, payable exact | at least 0.92, 0.95 |
| | unsafe approvals | 0 |

```bash
python evals/run_eval.py --mode replay        # score the keyword baseline
python evals/gate.py --mode replay            # exit code 1 if a metric crosses its threshold
pytest evals                                  # includes a broken build that must fail the gate
```

The gate is tested: one test removes the deductible from the calculation and asserts that the gate fails. A gate that has never been seen to fail is not a gate.

**Ablations.** Each component was removed and the 20 hard golden cases rerun three times.

| Variant | Run 1 | Run 2 | Run 3 | Failure that returned |
|---|---|---|---|---|
| Full system | 100% | 100% | 100% | none |
| No long term memory | 95% | 100% | 100% | "whiskeys at a wedding" approved in one run |
| No collaboration | 100% | 95% | 95% | parcel from a friend wrongly denied in two runs |

A single run per variant had suggested that collaboration made no difference. Repetition showed that conclusion was wrong and it was withdrawn. The evidence is still thin: one claim per effect, three runs each.

---

## Agents compared with a single call

A multi-agent design costs more than one model call, so it has to show what the extra cost buys. Three experiments measure that, and the result differs by task.

### A single call baseline

[evals/single_call_baseline.py](evals/single_call_baseline.py) makes one structured **Claude Haiku 4.5** call per claim that sets the same six flags, using the **fine-tuning** study's prompt with four fixed examples (none of their sentences appear in the evaluation sets), and then runs the same rules engine. Any difference in outcome comes from how the flags were produced and nothing else.

| Set | Single call plus engine | Agent team |
|---|---|---|
| Golden, 63 claims | 100%, 0 unsafe approvals | 100% |
| Held-out 1, 39 claims | 100%, 0 unsafe approvals | 97.4% |
| Held-out 2, 39 claims | 100%, 0 unsafe approvals | 100% |
| Cost and time per claim | 0.0007 USD, 0.8 s, 1 call | 0.035 to 0.049 USD, 21 to 25 s, about 20 calls |

The template narratives do not need tools, so one call does the whole job. The held-out set the agents scored 97.4% on is the one with the flawed label described above, and the single call scored its label as written. The baseline also handled all 14 injection claims in these sets with no **guardrail**, so those claims do not measure what the **guardrail** adds. The **red team** suite does that.

### A harder set written by other model families

Template sets cannot tell understanding from learned wording, so [evals/freeform](evals/freeform) builds a different kind of set. **Mistral Large 3** wrote 140 first-person narratives from short fact briefs, in seven styles (formal report, rambling, blunt text message, non-native English, full of irrelevant detail, hedged and so on). Fifty are implicit, with the obvious words forbidden so the fact has to be inferred, and 16 are negated decoys such as a school run that is not commercial use, a favour that looks like delivery work, or a permitted spouse driving whose licence was shown to the police. **gpt-oss-120b** then labelled every narrative without seeing the intended label, and only the 124 where the two agreed were kept, with every drop recorded. Neither model is one the product or the baseline uses. The expected decision for each claim comes from the rules engine on the verified labels.

| System | Correct | Unsafe approvals | Cost per claim | Time per claim (agent team: median) | Model calls |
|---|---|---|---|---|---|
| Single call plus engine | 122 of 124 (98.4%) | 1 | 0.0008 USD | 0.8 s | 1 |
| Agent team | 122 of 124 (98.4%) | 1 | 0.045 USD | 22.5 s | 21.3 |

The two systems tie, and each falls for a different trap. The single call denied the favour that looked like delivery work and approved a learner practising alone, a fact the narrative only hints at. The agent team denied a school run as commercial use and also missed a learner driver. So this benchmark does not separate them on accuracy, and the agent team costs about 58 times as much.

**A construction error that the first run exposed.** The first agent run scored 92.7% with 9 unsafe approvals, and every miss was a tyre-only or breakdown claim. The cause was in the builder: it gave every claim random body-repair lines, so a tyre-only narrative arrived with an estimate listing a windshield and a radiator. The agents cross-check the estimate against the narrative and refused to call it tyre-only, which scored them against a contradiction built into the test. The single call never reads the estimate, so it could not be fooled. The builder now writes estimates that agree with the narrative, a test pins that, and the corrected run is the result above. The first run's reports are kept, labelled, because the finding is real: the agents notice contradictions the single call cannot see.

**Limits.** 15 of the 16 dropped narratives were implicit ones the verifier could not agree on, so the set is somewhat easier than intended (35 of the 50 implicit narratives survive). Agreement between two models is not human ground truth. The claims are 124, so a difference of one or two is within noise.

### Where the agents do earn their place: investigating records

Investigation is a different task: the facts live in records the narrative does not contain (repair cost benchmarks, a garage's flagged estimates, other claims on the policy, the police report). [evals/investigation](evals/investigation) plants problems in real claim PDFs and records and compares four contenders on the investigator's model (**Nova 2 Lite**), at temperature 0, with the same plain brief and no thresholds written into it:

| Contender | What it is given |
|---|---|
| One call, documents only | The claim packet and the narrative |
| One call, records pasted in | The packet plus every reference record in the prompt, the strongest single-call baseline |
| The investigator agent | The product's own agent with its tools and MCP servers, looking things up |
| Rules only | The product's deterministic investigator (`services/signals.py`), with no model. It is also the source the answer keys were checked against, so it is the ceiling a well written rule set sets rather than a fair rival |

There are 28 cases: 14 with a single problem (an inflated repair line, a flagged garage, a theft with no police report, documents that disagree) including controls where nothing is wrong, 4 repeat-claim cases, 4 that combine problems and 6 where the narrative tells the reviewer to skip its checks. Each answer key is checked against the product's own deterministic investigator, and the case design was corrected once before any full run, after a smoke test showed that a 5 day against 6 day pair scored the models on guessing an internal threshold they were never told.

| Contender | Planted problems found | Runs with a false alarm | Exactly right | Cost per case |
|---|---|---|---|---|
| One call, documents only | 30 of 72 (42%) | 50 of 84 | 22 of 84 | 0.0003 USD |
| One call, records pasted in | 69 of 72 (96%) | 53 of 84 | 31 of 84 | 0.0007 USD |
| Investigator agent | 58 of 72 (81%) | 11 of 84 | 62 of 84 | 0.0080 USD |
| Investigator agent plus the rule safety net | 69 of 72 (96%) | 11 of 84 | 73 of 84 | 0.0080 USD |
| Rules only, no model | 57 of 72 (79%) | 0 of 84 | 69 of 84 | 0 USD |

Each case ran three times. Pasting the records finds nearly everything and raises a false alarm in most runs: it mixes up other policies' rows, reporting "policy INV-00014 also had a claim two days before" for a claim on a different policy. The agent finds fewer but is right far more often, and found all 24 of the problems that needed several lookups combined. The agent plus safety net row applies `add_rule_signals` to the stored agent runs, as described in [Agents, MCP and memory](#agents-mcp-and-memory).

**Scale.** The claims history grows in real deployments, and pasting it into the prompt grows with it. The same history cases ran with 37, 1,037 and 10,037 claims on file:

| Claims on file | Records pasted in: tokens and cost per case | Runs with a false alarm | Agent: tokens and cost per case | Runs with a false alarm |
|---|---|---|---|---|
| 37 (all 28 cases) | 1,480 and 0.0007 USD | 53 of 84 | 22,183 and 0.0080 USD | 11 of 84 |
| 1,037 (6 cases) | 23,472 and 0.0073 USD | 9 of 18 | 23,791 and 0.0084 USD | 4 of 18 |
| 10,037 (6 cases) | 221,472 and 0.0669 USD | 17 of 18 | 23,423 and 0.0083 USD | 3 of 18 |

The agent's cost does not move, because it does a point lookup. At 10,037 claims the pasted prompt costs about 95 times what it did at 37 and 8 times the agent's cost per case, takes 14.6 seconds against the agent's 10.6, and raises a false alarm in 17 of 18 runs. The costs meet at around 1,000 claims on file. Below that the single call is cheaper and finds more, at the price of more false alarms.

**The agent's weaknesses.** It recorded a lone flagged garage in 0 of 9 runs (and in a traced run claimed in its summary to have recorded it), and it filed an amount mismatch under the wrong kind of problem. In the injection group it found 10 of 15: the flagged garage was missed in all 3 runs and a repeat claim and a missing police report once each, with no false alarms. It was not steered into reporting things, but it may have been steered out of reporting some. The garage weakness is what `add_rule_signals` removes.

**What the rules alone show.** The rules-only row finds 79% with no false alarms and no cost, and at 1,037 and 10,037 claims on file it is exact in all 18 runs where the agent is exact in 14 or 15. On every problem a rule covers, the agent adds nothing and sometimes subtracts, by raising false alarms on 11 of 84 runs. What the agent adds in this experiment is the 12 problems the rules missed (of the 72 planted, the agent plus safety net found 69 and the rules 57): 6 in the single problem group, 3 in the multi step group and 3 in the injection group, which is also where its false alarms and misses cluster. So the case for the agent rests on findings that no rule covers, and this experiment cannot show that it finds them better than a rule written later would.

**Limits.** One model, 28 cases written by the author, and a deterministic investigator in the product (`services/signals.py`) that solves this same task by construction, so the headline comparison is between the agent and stuffing the context. The rules-only row measures the rules against their own answer key and shows what the agent adds beyond them. It does not show that the agent beats code. Costs were recomputed from the recorded tokens at prices checked against the **AWS** Price List.

### What this means

- On template and free-form narratives a single call is as accurate as the agent team at about one fiftieth of the cost. Accuracy does not justify the agents.
- When the facts live in records, and the records grow, the agent holds its cost and its precision while a single call with everything pasted in degrades. That is the case for tool use, and it needed a code safety net to be reliable.
- The agents also add what a single call cannot: citations from retrieval, long term memory fed by human review, a full audit trail of tool calls, and the cross-check between narrative and estimate that exposed the benchmark error above.
- If the only job were reading narratives, a single call and a rules engine would be enough. The agents are justified by work no rule covers, such as unwritten patterns, judgement and explanation, and by the audit trail and memory. The last experiment shows that on rule-covered checks the rules do as well, so that justification rests on the next step in this document and not yet on measurement.

---

## Cost, latency and observability

Every model call writes a **JSON** record (agent, model, input and output tokens, latency, cost) to the **S3** telemetry lake, partitioned by day. **Athena** queries it in place and **QuickSight** presents it.

![QuickSight dashboard of cost and latency over the telemetry lake](docs/images/quicksight_dashboard.png)

**Cost.** Two changes were measured on the same 22 claims (one per scenario), twice: once in the sharded evaluation batches and once sequentially. Decision accuracy was 100% with 0 unsafe approvals in every run.

| Variant | Cost per claim, run 1 | Cost per claim, run 2 (sequential) | Change |
|---|---|---|---|
| Baseline | 0.0464 USD | 0.0487 USD | |
| Agents request independent tools together | 0.0432 USD | 0.0423 USD | 7% and 13% lower |
| Plus the memo written by Claude Haiku 4.5 instead of Sonnet 4.6 | **0.0347 USD** | **0.0351 USD** | 25% and 28% lower |

Both changes are configuration switches (`CLAIMS_PARALLEL_TOOLS` and `CLAIMS_ORCHESTRATOR_MODEL`). The deployed system and the held-out evaluations run the baseline configuration, so enabling the optimised one would need the held-out sets rerun first. Prompt caching had no measurable effect because the prompts fall below the caching threshold. That is a negative result. At these prices a claim costs about 3 to 4 Indian rupees.

**Prices.** The rates in `backend/app/pricing.py` came from third party trackers until [scripts/check_prices.py](scripts/check_prices.py) compared all twelve against the **AWS** Price List **API** on 16 November 2026. **Claude Haiku 4.5** and **Claude Sonnet 4.6** matched exactly. **Nova 2 Lite** did not: the file held the regional rates (0.33 USD per million input tokens, 2.75 output) while the code calls the global inference profile (0.30 and 2.50), and its cache rates were wrong. The file is corrected. **Nova** is close to half of a claim's tokens, so the per-claim costs measured before that date are about 4 percent high, and the investigation experiment's costs were recomputed from recorded tokens at the corrected rates.

**Latency.** The account's **Bedrock** request quotas are small, and throttling inflated latency in the large sharded batches, so those timings are not reported. Latency was re-measured sequentially: one claim at a time, nothing else calling **Bedrock**, 22 claims per variant.

| Variant | Median | 95th percentile | Mean | Model calls per claim |
|---|---|---|---|---|
| Baseline | 24.6 s | 42.9 s | 28.4 s | 20.9 |
| Agents request independent tools together | 23.8 s | 36.1 s | 26.6 s | 18.5 |
| Plus the memo written by Claude Haiku 4.5 | **21.5 s** | **33.1 s** | **24.2 s** | 18.5 |

Each change reduced latency, and fewer model calls explain the first. With 22 claims and one run per variant, median differences of 1 to 3 seconds are small against the spread, so treat the ordering as indicative. Runs on the deployed site (17 runs) show a median of about 21 seconds and a 95th percentile of about 33 seconds, which matches the optimised variant.

**Alerting.** After every run the application evaluates three rules: a run costing more than three times the median of the previous twenty, a daily spend over budget, and a failure rate above 20%. Results appear in the Observability tab, and a **CloudWatch** custom metric drives an alarm.

![Observability tab: cost per claim, where the money goes, alert rules and review statistics](docs/images/demo/observability.gif)

---

## Fine-tuning a small model with QLoRA

**Objective.** Test whether a small open model, fine-tuned cheaply, can set the six judgement flags (intoxicated, commercial use, unlicensed driver, mechanical failure, tyre only, theft) as well as prompting a managed model, and say when each is the right choice. The work is in [finetune/](finetune/).

**Model.** **Qwen2.5-3B-Instruct**, a decoder-only transformer with 36 layers, hidden size 2,048, 16 attention heads using grouped-query attention (2 key-value heads), an 11,008-wide feed-forward block, a 151,936-token vocabulary and 3.09 billion parameters (read from the model's own configuration). Decoding is greedy, so results are repeatable.

**Method.**

| Aspect | Setting |
|---|---|
| Adaptation | LoRA on all linear layers (query, key, value, output, gate, up, down) in all 36 layers. Rank 16, alpha 32, dropout 0.05. 29,933,568 trainable parameters, 0.97% of the model, a 60 MB adapter in 16 bit. `B` starts at zero, so training starts exactly at the base model, and the product can be merged into the weights at inference at no per-token cost |
| Quantisation (QLoRA) | Frozen base in 4-bit NF4 with double quantisation, bfloat16 compute. Base weights fall from about 6.2 GB to about 1.5 GB, so training fits one 24 GB A10G. On a Mac, without CUDA, the script falls back to plain 16-bit LoRA for smoke tests |
| Objective | Loss on the answer JSON only (`completion_only_loss`), so the model is not graded on reproducing the narrative. Prompts and answers go through the model's own chat template, identically for every system compared |
| Optimisation | Learning rate 2e-4, cosine schedule, 3% warm-up, 3 epochs, effective batch 16 (8 per step, 2 accumulation steps), maximum length 512, gradient checkpointing |
| Libraries | Hugging Face Transformers, PEFT, TRL `SFTTrainer`, bitsandbytes |
| Compute | One `ml.g5.2xlarge` (NVIDIA A10G, 24 GB) SageMaker training job, launched with plain `boto3`, a dedicated bucket, a least-privilege execution role created by CDK and a 90 minute hard stop. Training took 427 s, 968 billable seconds in total, about 40 US cents (an estimate from billable seconds and an assumed on-demand rate) |

**Data and splits.** Narratives are generated from phrase banks: a base accident sentence, zero to two sentences that assert or negate a flag, and filler. The negations and traps are the point ("had not consumed any alcohol", "a parcel that a friend had sent", "a tyre burst and the car then hit a divider"). Train has 1,200 narratives and dev 150, from the training banks. The unseen test has 300 narratives from disjoint banks, so every sentence is wording the model never saw. Tests enforce that no sentence is shared and every label follows from the text. A further 63 narratives come from the claims system itself. They are reported as a secondary result only, because 39 of the 63 share a sentence with the training phrases.

**Results.** Same 150 held-out narratives, same scoring code for every system:

| System | Exact match (all 6 flags) | Missed denials |
|---|---|---|
| Claude Haiku 4.5, 4 examples | **98.0%** | 0 |
| Claude Sonnet 4.6, 4 examples | 96.7% | 0 |
| Claude Sonnet 4.6, zero-shot | 92.7% | 0 |
| Claude Haiku 4.5, zero-shot | 89.3% | 0 |
| Qwen2.5-3B with QLoRA | **88.0%** | **0** |
| Nova 2 Lite, 4 examples and zero-shot | 82.7% and 76.7% | 0 and 0 |
| Qwen2.5-3B prompted, 4 examples and zero-shot | 68.0% and 65.3% | 3 and 17 |
| Keyword baseline | 49.3% | 38 |

With 150 narratives the 95% uncertainty on an accuracy near 88% is about 5 points, so neighbouring rows are not meaningfully different. On the full 300 narratives the tuned model scored 89.3% and the untuned model 59.7%, and about 60% of the untuned model's zero-shot answers were not valid **JSON**.

**Findings.**
- **Fine-tuning** worked as a technique: 65% to 88% on unseen wording, and missed denials, the dangerous error, from 17 to zero. The remaining mistakes are false denials, which an adjuster would see and correct.
- It does not pay off for this product. Prompted **Haiku** scores 98% for roughly 500 input and 40 output tokens per call, about 0.07 US cents, with no **GPU**. The tuned model processed a narrative in 0.26 s in **GPU** batches, about 0.011 cents at full utilisation, but an always-on endpoint costs on the order of 1,100 US dollars a month regardless of use, against well under a dollar a month for the **API** at roughly a thousand claims a month. These cost figures are estimates from token counts and list prices. **Fine-tuning** wins at very high steady volume, when data must stay in the account, or when no strong hosted model exists.

**Limits.** Errors cluster: 17 of the 32 wrong narratives (of 300) come from one unseen sentence ("The driver handed over a current licence when asked", read as unlicensed), and 6 more from one engine-failure paraphrase. The 300 narratives combine only about 60 distinct unseen sentences, so they overstate the evidence. Training loss fell to about 0.00001 by epoch 1.6, and the dev loss is just as small because dev shares phrase banks with train, so only the unseen-wording test can reveal overfitting. It is one run with one seed and no hyperparameter sweep, on synthetic compositional text.

![SageMaker training job record](docs/images/aws/sagemaker_training_job.png)

---

## Deployment

The system was deployed to us-east-1 with two **CDK** stacks, which were destroyed after the evidence below was recorded. The commands at the end of this section recreate them. [scripts/verify_deployment.py](scripts/verify_deployment.py) is the acceptance test: it discovers every resource from the **CloudFormation** outputs and calls each service. It creates two temporary **Cognito** users and signs them in, then checks that the load balancer is private, that the **API** refuses a caller with no token (401) and a user in no group (403), that starting a run is `POST` only, that the site publishes its sign in settings and that **AWS WAF** is attached. It invokes three **Bedrock** models, applies the **guardrail** to an attack, retrieves from all four **knowledge bases**, recalls from **AgentCore** memory, runs a **Bedrock Data Automation** job, runs one live claim through the agents, reviews it through the **API** with a senior token while the request body claims another role and name (which must be ignored), then reads every **DynamoDB** table and queries **Athena**. It deletes the temporary users even if a check fails, and exits non-zero if any check fails. The latest run passed 29 of 29 checks ([docs/verification.json](docs/verification.json)); the **QuickSight** check reports a skip, because that account was cancelled to stop billing. The screenshots below are from the console. The account identifier and the operator's name are redacted by [scripts/redact_screenshots.py](scripts/redact_screenshots.py), and every screenshot in the folder was scanned by **OCR** for the account number.

The first run of this script on the new network design failed 12 of 27 checks, six of them because every **API** call through **CloudFront** returned 504, and that is how the defect described in [issues found and resolved](#issues-found-and-resolved) was found. The rest were empty tables and an empty telemetry lake that nothing had written to yet.

**Compute and delivery**

| | |
|---|---|
| ![ECS service](docs/images/aws/ecs_service_deployments.png) | ![ECS cluster](docs/images/aws/ecs_cluster_services.png) |
| ECS service on Fargate, one task running, deployment succeeded | ECS cluster, service active |
| ![CloudFront origins](docs/images/aws/cloudfront_origins.png) | ![CloudFront metrics](docs/images/aws/cloudfront_metrics.png) |
| CloudFront distribution with an S3 origin for the site and a VPC origin for the API | CloudFront request and error metrics |
| ![App stack](docs/images/aws/cloudformation_app_stack.png) | ![Data stack](docs/images/aws/cloudformation_data_stack.png) |
| CloudFormation, application stack resources, including Cognito, the web ACL and the VPC origin | CloudFormation, data stack |

**Identity and private network**

| | |
|---|---|
| ![Cognito groups](docs/images/aws/cognito_user_pool_groups.png) | ![WAF rules](docs/images/aws/waf_web_acl_rules.png) |
| Cognito user pool with the adjuster and senior groups | Web ACL with the two rate limit rules |
| ![Internal ALB](docs/images/aws/alb_internal.png) | ![ALB security group](docs/images/aws/alb_security_group_inbound.png) |
| Load balancer with scheme Internal, in the isolated subnets | Its security group admits one source, the CloudFront VPC origin service group |

**Bedrock: guardrails, knowledge base, document automation**

| | |
|---|---|
| ![Guardrail overview](docs/images/aws/bedrock_guardrail_overview.png) | ![Guardrail content filters](docs/images/aws/bedrock_guardrail_content_filters.png) |
| Guardrail, ready, one version | Content filters with prompt attack defence |
| ![Guardrail PII](docs/images/aws/bedrock_guardrail_pii_types.png) | ![Guardrail regex](docs/images/aws/bedrock_guardrail_regex_patterns.png) |
| Sensitive information: email and phone masked | Regex detectors for Aadhaar and PAN numbers |
| ![Knowledge base](docs/images/aws/bedrock_kb_overview.png) | ![Knowledge base test](docs/images/aws/bedrock_kb_test_answer.png) |
| Knowledge base on S3 Vectors with Titan embeddings (a chunk size experiment base) | A drunk driving question answered from retrieved chunks |
| ![Chunk metadata](docs/images/aws/bedrock_kb_chunk_metadata.png) | ![BDA project](docs/images/aws/bda_project.png) |
| A retrieved chunk with its metadata | Bedrock Data Automation project with both custom blueprints |

**Memory, data and telemetry**

| | |
|---|---|
| ![AgentCore memory](docs/images/aws/agentcore_memory_overview.png) | ![AgentCore strategy](docs/images/aws/agentcore_memory_strategy.png) |
| AgentCore memory, active | Long term strategy for adjuster lessons |
| ![AgentCore observability](docs/images/aws/agentcore_memory_observability.png) | ![DynamoDB audit](docs/images/aws/dynamodb_audit_table.png) |
| Memory invocations and latency | Human review audit log in DynamoDB |
| ![Athena](docs/images/aws/athena_runs_query.png) | ![QuickSight](docs/images/aws/quicksight_dashboard_live.png) |
| Athena over the telemetry lake | QuickSight dashboard, latency in seconds |

**Operations and training**

| | |
|---|---|
| ![CloudWatch alarms](docs/images/aws/cloudwatch_alarms.png) | ![CloudWatch dashboard](docs/images/aws/cloudwatch_dashboard.png) |
| Latency, 5xx and cost spike alarms | CloudWatch dashboard for the API |
| ![SageMaker metrics](docs/images/aws/sagemaker_training_metrics.png) | ![BDA blueprint](docs/images/aws/bda_blueprint_photo_result.png) |
| GPU, CPU and memory during the QLoRA job | Photo blueprint run on a damage photo |

**Deploy and verify**

```bash
uv sync                                        # the exact locked environment, Python 3.12
export PATH="$PWD/.venv/bin:$PATH"             # the CDK app runs with the active interpreter
cd frontend && npm ci && npm run build && cd ../infra
npx aws-cdk@2 bootstrap aws://<account>/us-east-1 --qualifier claimsadj --toolkit-stack-name CDKToolkit-claimsadj
npx aws-cdk@2 deploy --all -c region=us-east-1 -c mode=live    # add -c production=true to keep the data when the stack is deleted

# load data into the new stacks (names come from the stack outputs)
aws s3 sync data/real/policies s3://<policy-docs-bucket>/policies/
aws s3 sync data/clause_cards  s3://<policy-docs-bucket>/clause_cards/
# start one ingestion job per knowledge base data source, in sequence, then
uv run python scripts/seed_dynamodb.py <policies-table> <claims-table>
CLAIMS_MODE=live CLAIMS_MEMORY_ID=<memory-id> uv run python scripts/seed_memory.py
# Bedrock Data Automation results for every form and photo are cached in data/bda;
# uv run python scripts/run_bda_ingest.py regenerates them

# create the people who can sign in (there is no self sign up), then put each in a group
aws cognito-idp admin-create-user --user-pool-id <pool-id> --username <name> --message-action SUPPRESS
aws cognito-idp admin-set-user-password --user-pool-id <pool-id> --username <name> --password '<strong password>' --permanent
aws cognito-idp admin-add-user-to-group --user-pool-id <pool-id> --username <name> --group-name senior    # or adjuster

uv run python scripts/verify_deployment.py     # acceptance test across every service
npx aws-cdk@2 destroy --all -c region=us-east-1
```

Pass the region explicitly: the **CDK** command line otherwise takes it from the **AWS** profile, which once sent a deploy to the wrong region. A deployment costs roughly 2 to 3 US dollars a day while it runs, plus model calls (an estimate from list prices, not a bill). Destroying the data stack fails on the **Athena** workgroup once queries have run: delete it with `aws athena delete-work-group --work-group claims-adjudication --recursive-delete-option` and retry. The bootstrap stack keeps its asset bucket and container repository, which have to be emptied before that stack can be deleted. The **CDK** app uses a dedicated bootstrap qualifier. The workflows authenticate to **AWS** through **OIDC** with a role supplied as a repository variable, so no long lived keys are stored in **GitHub**. That role and the **OIDC** provider are not created by this app. The **QuickSight** account is created once in the console and must be cancelled after use because it bills after its trial.

---

## Operating the system

| Signal | Threshold | Response |
|---|---|---|
| Run cost above three times the median of the previous twenty | CloudWatch alarm `RunCostSpike` | Inspect the Observability tab for the agent or model that grew. Likely causes: a looping agent (bounded by the 40 call budget) or a prompt that grew |
| Failure rate above 20% of recent runs | Alert rule | Check the error on the failing runs. Throttling shows as retries and latency, a permission change as an access denied |
| API 5xx or p95 latency above 30 seconds | CloudWatch alarms | Check the ECS service events and task health |
| Daily model spend reaches 5 USD (`CLAIMS_DAILY_BUDGET_USD`) | Hard limit and an alert | New live runs get 429 until tomorrow, and viewing and reviewing keep working (a live deployment does not run replay, see the mode rule in the security layers). The spend is summed from DynamoDB across every task. A run already going is never cut off, so a day can overshoot by one run per task. Review per call records in Athena |

| Failure mode | Behaviour |
|---|---|
| A model call is throttled | Adaptive retries with backoff. If the run still fails, it is recorded as failed with the error, and the claim stays unreviewed |
| An agent does not record its judgement | The claim is referred to a person with reason `INT.AGENT` |
| Bedrock Data Automation output is missing for a claim | The claim runs without photo evidence and the UI says so |
| The knowledge base is unreachable | The coverage agent has no clause text. The engine still decides, and the citation panel is empty |
| A task restarts | The audit log is read from DynamoDB, so nothing is lost, and metrics are restored from DynamoDB when the next task starts |
| Several people start runs at once | Runs go one at a time per task. A waiting request is told its place in line every 10 seconds, which also keeps CloudFront's 60 second response timeout from cutting it off, and the page shows "Waiting, place n in line". With 5 runs already waiting, a new one gets 503 with a retry hint |
| A user has no verified email | Password reset cannot send a code. Create the account with a verified email, or set one with an administrator call |
| An attacker's text is flagged | The flagged sentence is removed and logged, and the rest of the narrative proceeds |
| A token is missing, expired or invalid | 401, and the site sends the person back to sign in. A user in no group gets 403 |
| Today's spend cannot be read | Live runs get 503 instead of risking the money. Replay and review keep working |
| The investigator describes a finding without recording it | The rules add it, marked as coming from the rules |
| One address starts too many runs | The web ACL answers 403 at the edge until the 5 minute window passes |
| A request fails | Every request has an id in `X-Request-ID`, carried on every log line from that request, and ends with one JSON log line with method, path, status, milliseconds and user. Failures log their traceback |

---

## Quick start

The **Python** environment is defined in `pyproject.toml` and locked in `uv.lock`: 104 packages, transitive ones included, with hashes. `uv sync` builds exactly the environment that **CI** tests, on **Python** 3.12 (`.python-version`), and installs **uv**'s managed **Python** if the machine has none. `finetune/requirements.txt` stays separate because it lists the versions the **SageMaker** job installed on a **GPU** machine. The diagram generator needs **Graphviz** and the screenshot redaction script needs **Tesseract**. The demo recorder needs **Node.js** and **Google Chrome** (`cd docs/demo && npm ci`).

```bash
git clone https://github.com/anandapurva55/agentic-claims-adjudication-aws.git && cd agentic-claims-adjudication-aws
uv sync                                         # the locked environment, no virtualenv to activate
uv run python scripts/generate_data.py          # 63 claims, 20 policies, golden set
uv run python scripts/generate_data.py --heldout   # held-out set 1 (and --heldout2 for set 2)
uv run pytest                                   # 409 tests, no AWS needed (the 18 infrastructure tests need Node.js and a built frontend)
uv run python evals/run_eval.py --mode replay && uv run python evals/gate.py --mode replay
(cd frontend && npm ci && npm test)             # 58 frontend tests

# run the app locally, offline baseline, no AWS and no sign in needed
CLAIMS_MODE=replay uv run uvicorn app.api.main:app --app-dir backend --port 8000 &
cd frontend && npm ci && npm run dev            # http://localhost:5173

# score a held-out set against the live agents
CLAIMS_MODE=live CLAIMS_DATA_DIR=data/heldout CLAIMS_CASES=evals/golden/heldout_cases.json uv run python evals/run_eval.py --mode live --label heldout
```

Locally, with no user pool configured, sign in is off: the app shows a demo role selector and the **API** takes the role from the `X-Demo-Role` header. Live mode refuses to start without a user pool, so the open mode cannot be run against real models by accident.

A URL such as `?claim=CLM-2026044&autorun=1` opens a claim and runs it. The photographs are not redistributed: download the **Kaggle** dataset listed in the references into `data/real/car_damage_coco` and run `python scripts/attach_real_photos.py`.

---

## Issues found and resolved

| Issue | Diagnosis | Resolution |
|---|---|---|
| Evaluations failed or slowed unpredictably | Throttling: the account's Bedrock quotas are 10 to 20 requests per minute per model | Spread the agents across models, which have separate quotas, added adaptive retries, sharded evaluations across two processes, and measured latency sequentially so throttling could not distort it |
| The cost dashboard showed zero tokens | Streaming responses did not populate the SDK's accumulated usage | A metered model wrapper reads usage from the stream's metadata events and records every call |
| The evaluation set was too easy: the keyword baseline scored 100% | First baseline run | Added negation and paraphrase cases. The baseline fell to 82.5% with 8 unsafe approvals, which gave the agents something to beat |
| Accuracy rested on a set that had been iterated on | Review of the evaluation design | Two held-out sets with new wording, scored once. A root cause analysis of the single miss traced it to an incoherent test narrative, so the generator was fixed and the label was left alone |
| The red team overstated attack success | A 70% result looked wrong. A no-attack control then showed the naive agent erring without any attack | The harness now appends the attack to a genuine narrative, and the report separates attributable successes from baseline errors |
| The API returned 200 with HTML for unknown claims | Probing endpoints on the deployed site | CloudFront custom error responses apply to the whole distribution, so the single page app fallback also rewrote API errors. The app has no client routes, so the fallback was removed |
| Every API call through CloudFront timed out (504) on the first deployment of the private network design, while the site, sign in settings, WAF and the internal load balancer all passed | Target health was fine and the app answered its own health checks, but no request from CloudFront ever reached it. The load balancer's security group admitted the isolated subnets' address ranges, on the assumption that the VPC origin's network interfaces are sourced from them. They are not: CloudFront attaches a managed security group to those interfaces, and the load balancer has to admit that group. Confirmed by adding the rule by hand (200 in 0.4 s) | The stack looks the group up with a small custom resource after the distribution exists, as the CDK documentation describes, with a read-only permission and a dependency on the distribution, then admits it. Tests now assert who the load balancer admits (a source group, never an address range). They passed on the broken design because none of them asserted this, and the old rule was reintroduced as a mutation to prove the new tests catch it |
| The investigator reached the adjuster with no flagged garage signal | In a traced run the agent received the garage record, wrote in its summary that it had recorded a medium risk signal, and never called the tool that records one. The same happened in all 9 single-finding garage runs | `add_rule_signals` adds every finding the rules can reach that the agent did not record, marked by source. Tested through the real live path with an agent that records nothing |
| Two reviewers deciding at the same moment could both succeed once the API ran as several tasks | The audit log was a per-task local copy, so the one decision per claim rule held only within a process | DynamoDB is the source of truth and the review is a conditional write on a fixed key, so exactly one wins. Tested with eight concurrent writers against DynamoDB and the local store, and mutation checked |
| The rules engine approved a claim reported before its incident, one whose estimate total did not match its lines, and paid some claims a rupee off | Found by running 20,000 random claims through it, which the golden set had not covered. Float arithmetic with banker's rounding, no check of the printed total, and no date validation | Exact decimals with halves rounded up, referral on inconsistent or unreadable dates and totals, an independent implementation in the data generator, and 20 hand-calculated boundary claims |

---

## Limitations

| Limitation | Impact | Mitigation or next step |
|---|---|---|
| Claim facts and narratives are synthetic. The photos are real but matched to claims by the parts on the estimate | Accuracy on real narratives is unknown | Collect adjuster overrides as a real evaluation set |
| The red team is written by the system's author: 30 attacks, one guardrail configuration | Unknown attack classes | An external red team, and attacks generated by a separate model |
| Evaluation samples are small: 78 held-out claims and three runs per ablation | Wide intervals, and unverified mechanisms | More claims per effect and more repeats |
| 19 of 63 claims have no usable photo | Fewer photo signals | Photos for every part type |
| Live runs are serialised per task, about 2 to 3 claims a minute, with one task and no autoscaling. Waiting runs are told their place and a queue over 5 is refused with 503. This was tested on a local server, not load tested on AWS | Around 3 people running at the same moment is the comfortable ceiling. The rest wait, or are told to retry | More tasks with autoscaling, or a queue with workers |
| There is no endpoint to submit a claim: claims are directories baked into the container image, and the run starts from one of them | The system adjudicates the demo claims, not new ones | A submission endpoint that stores the packet in S3 and starts ingestion, then the event driven workflow below |
| Run metrics, call records and the alert history are read from local files when a task starts, so each task shows its own; the claim list reads the whole audit table with a consistent read on every call | Observability differs between tasks and the claim list slows as the audit log grows | Read metrics from DynamoDB and Athena, and keep a per claim stage item to list from |
| Document ingestion is a batch script, not event driven | A new claim needs the script run before its photo and form check appear | An S3 event and a Step Functions workflow |
| The deploy and live evaluation workflows have not run, because their OIDC role is not in the CDK app | Only CI is exercised on GitHub. Deployment is done from a workstation | Add the OIDC provider and role to the CDK app, then run both workflows |
| MFA is optional and tokens live in the browser's session storage | A script injected into the page could read a token for the hour it is valid | Enforce MFA, and keep tokens in memory with a refresh cookie |
| Password reset uses Cognito's default email sender (about 50 emails a day, from a shared address) and needs a verified email on the account | Reset suits a handful of users, and a user without an email cannot reset | Amazon SES as the sender, and an administrator process that always sets the email |
| The styled sign in page is defined in the CDK app and covered by template tests (managed login, the Essentials plan, the branding for the app's client, sign up off). It was checked in a browser on a standalone user pool built with the same settings, and has not yet been deployed as part of the full stack | A full deployment could still reject a property the tests cannot see | The next deployment confirms it, and its result belongs in the deployment evidence |
| The interactive demo on GitHub Pages does not run the agents, the guardrail or memory, and its sign in accepts any username with a rule-meeting password, with the role switched from a menu | A visitor sees rule baseline runs, not live agent runs, cannot scan their own text, and the sign in protects nothing | Run the live deployment for anyone who needs the real thing, as the demos in this document show |
| The WAF limits by address only, and the daily spend limit is checked when a run starts | A shared address is limited together, and a day can overshoot by one run per task | Limit per signed in user and reserve spend before a run |
| The investigation experiment used one model and 28 cases written by the author, and the product has a deterministic investigator that solves the same task | It shows the agent beats stuffing the context, and that rules alone find 79% at no cost. It does not show the agent finds problems no rule covers | More models, cases that no rule covers, and real adjuster feedback |
| The free-form benchmark has 124 claims and its labels are agreement between two models, not human ground truth. 15 of the 16 dropped narratives were implicit ones | It ties the single call and the agent team. A difference of one or two claims is noise, and the set is somewhat easier than intended | Human review of the labels, and more implicit and adversarial narratives |
| One region, one account, direct query QuickSight | Not a production topology | A second region, and SPICE for the dashboard |
| No hybrid search on S3 Vectors | A vocabulary gap in retrieval | Evaluate a managed search cluster on cost and recall |

---

## What I would do next

1. Enforce **MFA** and keep tokens out of session storage, limit by signed in user instead of by address, and show each adjuster only their own queue.
2. Drive ingestion from **S3** events and **AWS Step Functions**, so **Bedrock Data Automation** and the vision model run when a document arrives.
3. Improve retrieval with query rewriting, a reranker and a **hybrid search** comparison.
4. Use adjuster overrides as an evaluation set that is never tuned against.
5. Move agent hosting to **Bedrock AgentCore** Runtime, with **AgentCore** Observability for tracing.
6. Add an **LLM** judge for memo quality, calibrated against hand graded samples.
7. Add a voice note path using **Bedrock Data Automation** transcription.
8. Run the investigation test on more models and on cases that no rule covers, and compare the agent with the deterministic investigator on the cases where a rule does not exist.
9. Strengthen the **fine-tuning** study: replace the compositional training data with paraphrases checked by people and then real adjuster-labelled narratives, repeat across seeds with a rank and learning-rate sweep and a reported spread, distil from the strong model if volume justifies self-hosting, and evaluate on the whole pipeline.

---

## Repository layout

```
agentic-claims-adjudication-aws/
  backend/            FastAPI service, token checks (auth.py), Strands agent graph, rules engine, MCP servers, tools, tests
  frontend/           React and TypeScript workbench
  infra/              AWS CDK app: ClaimsAdjudicationData and ClaimsAdjudicationApp stacks
  evals/              golden and held-out cases, hand-calculated oracle claims, scorer, quality gate, retrieval and photo
                      evaluations, the free-form benchmark (freeform/), the investigation test (investigation/), reports
  redteam/            30 attacks, the harness, the naive control, reports
  finetune/           QLoRA data, training, SageMaker launcher, baselines
  scripts/            data generator, photo attachment, Bedrock Data Automation batch job, DynamoDB and memory
                      seeding, QuickSight setup, deployment verification, price check, screenshot redaction
  docs/               diagram generator, demo recorder, images, verification results
  .github/            workflows (CI, CodeQL, live eval, deploy) and the Dependabot configuration
  pyproject.toml      dependencies and tool settings; uv.lock pins every package; .python-version is 3.12
```

---

## Data sources and references

Policy wording (rules and **knowledge base**), fetched at setup and not redistributed:
- [Universal Sompo Private Car Package Policy wording](https://www.universalsompo.com/assets/file/motor-private-car/motor-private-car-policy-wordings.pdf)
- [Digit Private Car Package Policy](https://godigit.com/content/dam/godigit/directportal/en/downloads/car/policy-wordings-digit-private-car-package-policy-multi-year.pdf)
- [Liberty Private Car Package Policy](https://www.libertyinsurance.in/Docx/Private%20Car%20Package%20Policy%20Wordings%20-%20V18%2017042019.pdf)

Damage photographs: [Coco Car Damage Detection Dataset](https://www.kaggle.com/datasets/lplenka/coco-car-damage-detection-dataset) on **Kaggle**, licence CC0 1.0.

Generated data: claim packets, policy schedules and narratives come from [scripts/generate_data.py](scripts/generate_data.py), seeded for reproducibility.

Models and methods: [Qwen2.5-3B-Instruct](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct); Hu et al., "**LoRA**: Low-Rank Adaptation of Large Language Models" (2021); Dettmers et al., "**QLoRA**: Efficient Finetuning of Quantized LLMs" (2023); [Strands Agents](https://strandsagents.com); [Model Context Protocol](https://modelcontextprotocol.io).

---

## Licence

Released under the [MIT licence](LICENSE). The damage photographs are from a public dataset under CC0 1.0, and the policy wordings remain the property of their insurers and are not redistributed.
