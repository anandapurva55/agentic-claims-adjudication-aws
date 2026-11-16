"""Runtime configuration. Everything comes from environment variables so the same image runs anywhere."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CLAIMS_", env_file=".env", extra="ignore")

    region: str = "us-east-1"
    # "live" calls Bedrock. "replay" runs the deterministic rule baseline and needs no AWS access.
    mode: str = "replay"
    # Model ids are configuration, never code. Swap in whichever your account can invoke.
    orchestrator_model: str = "global.anthropic.claude-sonnet-4-6"
    fast_model: str = "global.amazon.nova-2-lite-v1:0"
    # A third model for the coverage agent. Bedrock quotas are per model, so spreading agents across models multiplies throughput.
    policy_model: str = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
    guardrail_id: str = ""
    guardrail_version: str = "1"
    knowledge_base_id: str = ""
    memory_id: str = ""  # Amazon Bedrock AgentCore Memory
    # Ablation switches: the evals measure the system with each of these on and off.
    memory_enabled: bool = True
    # Cost and latency switches, measured by evals/optimise.py. Off by default so the baseline stays the baseline.
    prompt_cache: bool = False  # Bedrock prompt caching of system prompt and tool definitions, Claude models only
    parallel_tools: bool = False  # tell agents to request independent tools together, so fewer model round trips
    collab_rounds: int = 1  # rounds of agent to agent questions after the first pass. 0 turns collaboration off.
    claims_table: str = ""  # DynamoDB: one record per claim holding what Bedrock Data Automation extracted
    policies_table: str = ""  # DynamoDB: policy schedules
    audit_table: str = ""
    metrics_table: str = ""
    bda_project_arn: str = ""  # Amazon Bedrock Data Automation project (claim form blueprint and damage photo blueprint)
    claims_bucket: str = ""  # BDA inputs and outputs
    calls_bucket: str = ""  # per call records land here as JSON partitioned by date, for Athena and QuickSight
    replay_pace: float = 1.0  # offline replay only: 1 keeps the animation pauses, 0 removes them (tests and evals)
    # Runs are serialised per task (tool state is per process). A request waiting its turn sends a queued event this often, which also keeps the connection alive
    # through CloudFront's 60 second origin timeout, and a queue longer than max_queue is refused up front with a clear message.
    queue_keepalive_s: float = 10.0
    max_queue: int = 5
    daily_budget_usd: float = 5.0  # alert when one day's model spend passes this
    # Sign-in. When a user pool is configured every endpoint except the health check needs a valid Amazon Cognito token. With none configured the API is for
    # local development only and live mode refuses to start.
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    # Browsers allowed to call the API from another origin. In AWS the site and the API share one CloudFront domain, so nothing else is needed there.
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    data_dir: Path = ROOT / "data"
    # Audit log, review decisions and run metrics. DynamoDB replaces this in AWS.
    runtime_dir: Path = ROOT / "data" / "runtime"
    # Spend guard: an agent run is aborted if it exceeds this many model calls.
    max_model_calls: int = 40


settings = Settings()
