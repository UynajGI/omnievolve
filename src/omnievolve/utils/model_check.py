"""模型可用性检查.

从 ShinkaEvolve model_availability.py 精简移植。
启动前验证 LLM API key/endpoint 可用性。
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

PROVIDER_ENV_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "azure": ("AZURE_OPENAI_API_KEY", "AZURE_API_ENDPOINT"),
    "bedrock": ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION_NAME"),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "google": ("GEMINI_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
}


def _resolve_provider(model_name: str) -> str:
    """从模型名推断 provider."""
    model_lower = model_name.lower()
    if "deepseek" in model_lower:
        return "deepseek"
    if "claude" in model_lower or "anthropic" in model_lower:
        return "anthropic"
    if "gemini" in model_lower or "google" in model_lower:
        return "google"
    if "azure" in model_lower:
        return "azure"
    if "openrouter" in model_lower:
        return "openrouter"
    if "bedrock" in model_lower:
        return "bedrock"
    return "openai"


def check_model_availability(models: list[str]) -> list[dict]:
    """检查模型的环境变量配置.

    Returns:
        list of {"model": str, "provider": str, "missing_env_vars": list[str], "available": bool}
    """
    results: list[dict] = []
    for model in models:
        provider = _resolve_provider(model)
        env_vars = PROVIDER_ENV_REQUIREMENTS.get(provider, ())
        missing = [v for v in env_vars if not os.getenv(v, "").strip()]
        results.append(
            {
                "model": model,
                "provider": provider,
                "required_env_vars": list(env_vars),
                "missing_env_vars": missing,
                "available": len(missing) == 0,
            }
        )
    return results


def validate_models(
    models: list[str],
    mode: str = "warn",
) -> bool:
    """验证模型可用性.

    Args:
        models: 要检查的模型列表
        mode: "warn" 打印警告, "required" 抛出 RuntimeError

    Returns:
        True if all models available
    """
    results = check_model_availability(models)
    unavailable = [r for r in results if not r["available"]]

    if not unavailable:
        logger.info("All %d models have required environment variables", len(models))
        return True

    for r in unavailable:
        logger.warning(
            "Model '%s' (provider: %s) missing env vars: %s",
            r["model"],
            r["provider"],
            ", ".join(r["missing_env_vars"]),
        )

    if mode == "required":
        details = "; ".join(
            f"{r['model']}: missing {r['missing_env_vars']}" for r in unavailable
        )
        raise RuntimeError(f"Required models unavailable — {details}")

    return False


def print_availability_report(models: list[str]) -> None:
    """打印可读的可用性报告."""
    results = check_model_availability(models)
    print("\n=== Model Availability Report ===")
    print(f"{'Model':<40} {'Provider':<12} {'Status':<10} Missing Env Vars")
    print("-" * 90)
    for r in results:
        status = "✅ OK" if r["available"] else "❌ FAIL"
        missing = ", ".join(r["missing_env_vars"]) if r["missing_env_vars"] else "-"
        print(f"{r['model']:<40} {r['provider']:<12} {status:<10} {missing}")
    print()
