"""Affiliate redirect builder. Stub — implementation lands with click tracking."""
from __future__ import annotations


def build_affiliate_url(template: str, **substitutions: str) -> str:
    """Naive template substitution. Real impl will sign + log clicks."""
    url = template
    for key, value in substitutions.items():
        url = url.replace("{" + key + "}", value)
    return url
