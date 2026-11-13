"""Config + endpoint readiness for an eval run.

`config.yaml` is the whole point of the eval: the same case set re-run against
another model by changing this file. Nothing here may hold a secret -- the
endpoint is a URL, and a credential, if one is ever needed, comes from the
environment, never from the file the report is signed against.

Named `evalconfig`, not `config`: inside the agent package a module called
`config` shadows the agent's own `config.py` (`OLLAMA_URL` et al). The eval
must never shadow the thing it is measuring.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

try:
    import yaml
except ImportError:  # pragma: no cover - yaml ships on the agent image
    yaml = None

DEFAULTS = {
    "endpoint": "http://localhost:11434",
    "model": "qwen3-coder:30b",
    "timeout": 120,
    "concurrency": 1,
}


class ConfigError(Exception):
    pass


@dataclass
class Config:
    endpoint: str
    model: str
    timeout: int
    concurrency: int
    path: str
    raw: dict

    def describe(self) -> str:
        """What the report cites: the values actually read, and from where."""
        return f"endpoint={self.endpoint} model={self.model} (from {self.path})"


def load_config(path):
    if yaml is None:
        raise ConfigError("PyYAML is not available")
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise ConfigError(f"config not found: {path}")
    except Exception as e:
        raise ConfigError(f"config unreadable: {e}")
    if not isinstance(raw, dict):
        raise ConfigError("config must be a mapping")

    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in raw.items() if v is not None})
    for key in ("endpoint", "model"):
        if not isinstance(merged[key], str) or not merged[key].strip():
            raise ConfigError(f"config `{key}` must be a non-empty string")
    try:
        merged["timeout"] = int(merged["timeout"])
        merged["concurrency"] = int(merged["concurrency"])
    except (TypeError, ValueError):
        raise ConfigError("config `timeout`/`concurrency` must be integers")
    if merged["timeout"] <= 0:
        raise ConfigError("config `timeout` must be positive")
    if merged["concurrency"] != 1:
        # The local model is shared with the live bots; more than one call at a
        # time slows the fleet down.
        raise ConfigError("config `concurrency` must be 1 (shared local model)")
    return Config(merged["endpoint"].rstrip("/"), merged["model"],
                  merged["timeout"], merged["concurrency"], path, raw)


def check_endpoint(cfg):
    """(ok, detail). Proves the endpoint ANSWERS for the configured model.

    Asking for `/api/tags` and finding the model name there is the cheap real
    check; a DNS success or an open port is not one, because the model may be
    absent on an endpoint that is up.
    """
    url = f"{cfg.endpoint}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=min(30, cfg.timeout)) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return False, f"endpoint answered {e.code} at {url}"
    except Exception as e:
        return False, f"endpoint did not answer at {url}: {e}"
    models = body.get("models") if isinstance(body, dict) else None
    if not isinstance(models, list):
        return False, f"endpoint returned no model list at {url}"
    names = {m.get("name") or m.get("model") for m in models if isinstance(m, dict)}
    base = cfg.model.split(":")[0]
    if cfg.model in names:
        return True, f"{cfg.model} present ({len(names)} models on the endpoint)"
    same_family = sorted(n for n in names if n and n.split(":")[0] == base)
    if same_family:
        return False, (f"{cfg.model} not present; endpoint has {same_family}"
                       " -- tag drift, not a dead endpoint")
    return False, f"{cfg.model} not on the endpoint ({sorted(n for n in names if n)})"


def env_credential_names():
    """Names of credential-ish env vars that are SET, never their values."""
    return sorted(k for k in os.environ
                  if any(t in k.upper() for t in ("TOKEN", "KEY", "SECRET", "PASSWORD")))
