# Security

## Reporting a vulnerability

Please report security problems privately through GitHub's private vulnerability reporting (the Security tab of this repository, "Report a vulnerability"). Do not open a public issue for a vulnerability. Expect an acknowledgement within a few days.

## What this project defends

This is a portfolio system for adjudicating motor insurance claims with AI agents. The controls below are implemented and tested in this repository:

- **Money and outcomes are never decided by a language model.** A deterministic rules engine produces every payable amount and decision, tested against 20 hand-calculated claims and property tests over thousands of random claims.
- **Prompt injection.** Claim narratives are scanned by Amazon Bedrock Guardrails before agents read them, agents treat narrative text as data, and a red team suite measures attack success with and without the defences.
- **Memory poisoning.** Agents can only read long-term memory. The only way to write a lesson is a human review, after a guardrail scan.
- **One human decision per claim.** A conditional DynamoDB write enforces it under concurrent reviewers, and payouts above the authority limit need a senior adjuster.
- **Sign-in.** Every API route except the health check needs a valid Amazon Cognito ID token. The reviewer's name and role come from the token, never from the request body.
- **Network.** The load balancer is internal and reachable only through a CloudFront VPC origin. AWS WAF rate limits each address, and a daily spend limit stops live runs.
- **Least privilege.** The task role names the models, guardrail and resources it uses.

## Known limits

- The deployed demo is torn down between uses, so the cloud controls are verified by `scripts/verify_deployment.py` in a deploy window and by CDK synthesis tests in CI, not continuously.
- Prices in `backend/app/pricing.py` are for estimating cost, not for billing.
- The repository contains no secrets. If you find one, report it as above.
