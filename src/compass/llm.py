"""Which model backend Compass talks to.

Strands is deliberately model-agnostic, and Compass leans on that rather than
treating it as trivia. The whole project develops and is tested against a cheap
OpenAI-compatible endpoint, and deploys unchanged to Amazon Bedrock on AgentCore.
The only difference is the object this module returns.

Another reason this is a separate module: in the demo, "which model is running"
is itself part of the story. Compass's behaviour should not depend on the model
being clever, and the fact that the gate produces identical verdicts on a small
local model and on Bedrock is the evidence.

Selection order (first match wins):

1. ``COMPASS_PROVIDER`` if set explicitly — ``bedrock``, ``deepseek`` or ``openai``
2. Bedrock, if AWS credentials look present
3. DeepSeek, if a key can be found (env var, or ``~/lecture-live/.deepseek_key``)
4. OpenAI, if ``OPENAI_API_KEY`` is set

Anything else raises with a message explaining exactly what to set.
"""

from __future__ import annotations

import os
from pathlib import Path

# Sensible defaults, all overridable. Bedrock model IDs change often and vary
# by region, so the deployment path always sets COMPASS_MODEL_ID explicitly.
DEFAULT_BEDROCK_MODEL = "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def _deepseek_key_file() -> Path:
    """Where a file-based DeepSeek key would live, resolved lazily.

    Deliberately not a module-level constant: resolving it touches the home
    directory, and importing this module must stay side-effect-free — a
    sandboxed process (a clean-room test, a minimal container) can lack a
    resolvable home, and an import should never be the thing that finds out.
    """
    return Path.home() / "lecture-live" / ".deepseek_key"


def _deepseek_key() -> str | None:
    if os.environ.get("DEEPSEEK_API_KEY"):
        return os.environ["DEEPSEEK_API_KEY"]
    key_file = _deepseek_key_file()
    if key_file.exists():
        key = key_file.read_text(encoding="utf-8").strip()
        return key or None
    return None


def _has_aws_credentials() -> bool:
    if os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"):
        return True
    if os.environ.get("AWS_PROFILE") or os.environ.get("AWS_DEFAULT_PROFILE"):
        return True
    return (Path.home() / ".aws" / "credentials").exists()


def resolve_provider() -> str:
    explicit = os.environ.get("COMPASS_PROVIDER", "").strip().lower()
    if explicit:
        return explicit
    if _has_aws_credentials():
        return "bedrock"
    if _deepseek_key():
        return "deepseek"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    raise RuntimeError(
        "No model backend available. Compass needs one of:\n"
        "  * COMPASS_PROVIDER=bedrock  + AWS credentials (for deployment), or\n"
        "  * DEEPSEEK_API_KEY          (or ~/lecture-live/.deepseek_key), or\n"
        "  * OPENAI_API_KEY\n"
        "Override the model with COMPASS_MODEL_ID."
    )


def build_model():
    """Return a Strands model instance for the resolved provider."""

    provider = resolve_provider()
    model_id = os.environ.get("COMPASS_MODEL_ID", "").strip()

    if provider == "bedrock":
        from strands.models import BedrockModel

        region = (os.environ.get("AWS_REGION")
                  or os.environ.get("AWS_DEFAULT_REGION")
                  or "eu-west-1")
        return BedrockModel(
            model_id=model_id or DEFAULT_BEDROCK_MODEL,
            region_name=region,
        )

    if provider in ("deepseek", "openai"):
        from strands.models.openai import OpenAIModel

        if provider == "deepseek":
            key = _deepseek_key()
            if not key:
                raise RuntimeError(
                    "COMPASS_PROVIDER=deepseek but no key found. Set "
                    "DEEPSEEK_API_KEY or write the key to "
                    f"{_deepseek_key_file()}."
                )
            base_url = os.environ.get("COMPASS_BASE_URL", DEEPSEEK_BASE_URL)
            default_model = DEFAULT_DEEPSEEK_MODEL
        else:
            key = os.environ["OPENAI_API_KEY"]
            base_url = os.environ.get("COMPASS_BASE_URL", "")
            default_model = DEFAULT_OPENAI_MODEL

        client_args: dict = {"api_key": key}
        if base_url:
            client_args["base_url"] = base_url
        return OpenAIModel(
            client_args=client_args,
            model_id=model_id or default_model,
            # Greedy decoding. The project's claim is that the *gate* is
            # deterministic — given the same finding it always returns the same
            # verdict. Sampling on top of that would reintroduce variance at the
            # layer above, and the recording has to show the same scenario the
            # tests assert on.
            #
            # max_tokens is raised because Sentinel's answer is a structured
            # report of several findings, and the default ceiling is low enough
            # that a thorough sweep gets truncated mid-JSON.
            params={"temperature": 0, "max_tokens": 8192},
        )

    raise RuntimeError(
        f"Unknown COMPASS_PROVIDER {provider!r}. Use 'bedrock', 'deepseek' or 'openai'."
    )


def describe() -> str:
    """One line for the logs: which backend, and why."""
    try:
        provider = resolve_provider()
    except RuntimeError as exc:
        return f"unavailable ({exc})"
    model_id = os.environ.get("COMPASS_MODEL_ID", "").strip()
    defaults = {
        "bedrock": DEFAULT_BEDROCK_MODEL,
        "deepseek": DEFAULT_DEEPSEEK_MODEL,
        "openai": DEFAULT_OPENAI_MODEL,
    }
    return f"{provider}: {model_id or defaults.get(provider, '?')}"
