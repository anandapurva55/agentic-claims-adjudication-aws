# Security policy

This is a portfolio project with one maintainer, not a product with customers. This page says what is covered and how to report a problem.

## Supported versions

Only the latest commit on `main`. The AWS deployment is created to demonstrate the system and then torn down, and the interactive demo on GitHub Pages is a static site.

## Reporting a vulnerability

Please report privately and not in a public issue or pull request.

Use GitHub's private vulnerability reporting: open the **Security** tab of this repository and choose **Report a vulnerability**, or go straight to
[the report form](https://github.com/anandapurva55/agentic-claims-adjudication-aws/security/advisories/new).

A useful report says what was found, how to reproduce it, and what an attacker gains. The maintainer aims to reply within seven days and to fix a confirmed problem before it is discussed in public. Reporters who want credit are named in the fix.

## In scope

- The API: the sign-in token checks, the human review gate (one decision per claim, four eyes above the authority limit, a review bound to the run it looked at), input limits, the daily spend limit and the run queue.
- Prompt injection through a claim narrative or a reviewer's reason, and anything that lets customer text change a decision, a payable amount or the audit log.
- The CDK app: network exposure, IAM scope, the web ACL and how secrets are handled.
- Secrets or personal data committed to the repository or its history.

## Out of scope

- The sign-in on the interactive demo. It accepts any username by design, protects nothing and holds no secrets, and the page says so.
- Problems that can only be shown against a deployed stack that does not exist right now, unless they can be shown from the code or the synthesised template.
- Volume attacks on a static site, social engineering, and weaknesses in third-party services.

## How security is built in

The layers, the threat model and the 30 attacks used to test them are described in [Security and red team testing](README.md#security-and-red-team-testing). Dependencies are watched by Dependabot, the code is scanned by CodeQL on every push, and the Python code is linted with the security rules of ruff.
