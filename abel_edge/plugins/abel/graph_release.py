"""Frozen graph-release selection and readiness checks for the Abel provider."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from abel_edge.plugins.abel.client import AbelClient
from abel_edge.plugins.abel.credentials import require_api_key

GRAPH_RELEASE_CONTRACT = "abel-edge.graph-release/v1"
GRAPH_RELEASE_DOCTOR_CONTRACT = "abel-edge.graph-release-doctor/v1"
GRAPH_DISCOVERY_CONTRACT = "abel-edge.graph-discovery/v2"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TOP_LEVEL_KEYS = {
    "contract",
    "provider",
    "graph_ref",
    "expected_release_receipt_sha256",
}
_CREDENTIAL_KEYS = {
    "access_key",
    "api_key",
    "authorization",
    "password",
    "secret",
    "secret_key",
    "token",
}


class GraphReleaseContractError(ValueError):
    """Raised when a caller-supplied graph release is unsafe or ambiguous."""


@dataclass(frozen=True)
class GraphReleaseConfig:
    """Validated graph identity supplied to Edge by a consumer."""

    _payload: dict[str, Any]
    sha256: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GraphReleaseConfig":
        if not isinstance(value, Mapping):
            raise GraphReleaseContractError("graph release config must be a mapping.")
        payload = deepcopy(dict(value))
        credential_path = _find_credential_path(payload)
        if credential_path:
            raise GraphReleaseContractError(
                "graph release config must not contain credential field "
                f"'{credential_path}'; use provider environment auth."
            )
        unknown = sorted(set(payload) - _TOP_LEVEL_KEYS)
        if unknown:
            raise GraphReleaseContractError(
                f"graph release config has unknown keys: {unknown}."
            )
        if payload.get("contract") != GRAPH_RELEASE_CONTRACT:
            raise GraphReleaseContractError(
                f"graph release contract must be '{GRAPH_RELEASE_CONTRACT}'."
            )
        if str(payload.get("provider") or "").strip().lower() != "abel":
            raise GraphReleaseContractError("graph release provider must be 'abel'.")
        payload["provider"] = "abel"
        graph_ref = payload.get("graph_ref")
        if not isinstance(graph_ref, dict):
            raise GraphReleaseContractError("graph release graph_ref must be a mapping.")
        unknown_ref = sorted(set(graph_ref) - {"graph_id", "graph_version", "release_id"})
        if unknown_ref:
            raise GraphReleaseContractError(
                f"graph release graph_ref has unknown keys: {unknown_ref}."
            )
        for key in ("graph_id", "graph_version"):
            if not str(graph_ref.get(key) or "").strip():
                raise GraphReleaseContractError(
                    f"graph release graph_ref.{key} must be non-empty."
                )
        graph_ref["graph_id"] = str(graph_ref["graph_id"]).strip()
        graph_ref["graph_version"] = str(graph_ref["graph_version"]).strip()
        if graph_ref.get("release_id") is not None:
            graph_ref["release_id"] = str(graph_ref["release_id"]).strip()
            if not graph_ref["release_id"]:
                raise GraphReleaseContractError(
                    "graph release release id must be non-empty when provided."
                )
        receipt = payload.get("expected_release_receipt_sha256")
        if receipt is not None:
            receipt = str(receipt)
            if not _SHA256_RE.fullmatch(receipt):
                raise GraphReleaseContractError(
                    "graph release receipt must be a lowercase SHA-256."
                )
            payload["expected_release_receipt_sha256"] = receipt
        if graph_ref["graph_version"] == "CausalNodeV4":
            if not graph_ref.get("release_id"):
                raise GraphReleaseContractError(
                    "CausalNodeV4 graph release requires an exact release id."
                )
            if not receipt:
                raise GraphReleaseContractError(
                    "CausalNodeV4 graph release requires an expected release receipt."
                )
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return cls(payload, hashlib.sha256(canonical).hexdigest())

    @classmethod
    def from_path(cls, path: str | Path) -> "GraphReleaseConfig":
        resolved = Path(path)
        if not resolved.is_file():
            raise GraphReleaseContractError(f"graph release config not found: {resolved}")
        try:
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise GraphReleaseContractError(
                f"graph release config is not valid JSON: {resolved}: {exc}"
            ) from exc
        return cls.from_mapping(payload)

    @property
    def payload(self) -> dict[str, Any]:
        return deepcopy(self._payload)

    @property
    def graph_ref(self) -> dict[str, str]:
        return deepcopy(self._payload["graph_ref"])

    @property
    def graph_version(self) -> str:
        return str(self._payload["graph_ref"]["graph_version"])

    @property
    def expected_release_receipt_sha256(self) -> str | None:
        value = self._payload.get("expected_release_receipt_sha256")
        return str(value) if value else None

    @property
    def is_canonical(self) -> bool:
        return self.graph_version == "CausalNodeV4"


def default_v3_graph_release() -> GraphReleaseConfig:
    return GraphReleaseConfig.from_mapping(
        {
            "contract": GRAPH_RELEASE_CONTRACT,
            "provider": "abel",
            "graph_ref": {
                "graph_id": "abel-main",
                "graph_version": "CausalNodeV3",
            },
        }
    )


def resolve_graph_release(
    value: GraphReleaseConfig | Mapping[str, Any] | str | Path | None,
) -> GraphReleaseConfig:
    if value is None:
        return default_v3_graph_release()
    if isinstance(value, GraphReleaseConfig):
        return value
    if isinstance(value, Mapping):
        return GraphReleaseConfig.from_mapping(value)
    return GraphReleaseConfig.from_path(value)


def doctor_graph_release(
    graph_release: GraphReleaseConfig | Mapping[str, Any] | str | Path,
    *,
    ticker: str = "AAPL.price",
    env_path: str = ".env",
    client: AbelClient | None = None,
) -> dict[str, Any]:
    """Check that CAP exposes enough release facts for safe Edge consumption."""

    release = resolve_graph_release(graph_release)
    api_key = require_api_key(env_path=env_path)
    abel = client or AbelClient(env_path=env_path)
    methods = abel.cap_methods(api_key=api_key)
    parents = abel.discover_parents(
        node_id=ticker,
        limit=20,
        api_key=api_key,
        graph_ref=release.graph_ref,
    )
    provenance = abel.graph_provenance()
    observed_version = str(provenance.get("graph_version") or "")
    observed_release = str(provenance.get("release_id") or "")
    observed_receipt = str(
        provenance.get("release_receipt_sha256")
        or provenance.get("release_sha256")
        or ""
    )
    expected_ref = release.graph_ref
    identity_reasons: list[str] = []
    if observed_version != release.graph_version:
        identity_reasons.append(
            f"expected graph_version={release.graph_version}, observed={observed_version or '<missing>'}"
        )
    if release.is_canonical:
        if observed_release != str(expected_ref["release_id"]):
            identity_reasons.append(
                f"expected release_id={expected_ref['release_id']}, "
                f"observed={observed_release or '<missing>'}"
            )
        if observed_receipt != release.expected_release_receipt_sha256:
            identity_reasons.append(
                "expected release receipt was not reproduced by CAP"
            )

    descriptor_rows = [item for item in parents if _has_complete_descriptor(item)]
    descriptor_ready = bool(parents) and len(descriptor_rows) == len(parents)
    descriptor_methods = [
        str(item.get("verb") or "")
        for item in methods
        if "node" in str(item.get("verb") or "").lower()
        and any(
            token in str(item).lower()
            for token in ("series_spec", "node_spec", "transform", "availability")
        )
    ]
    if not release.is_canonical:
        descriptor_ready = True

    checks = {
        "config": {"status": "pass"},
        "cap_methods": {
            "status": "pass" if methods else "blocked",
            "method_count": len(methods),
            "descriptor_methods": descriptor_methods,
        },
        "discovery": {
            "status": "pass" if parents else "blocked",
            "parent_count": len(parents),
        },
        "release_identity": {
            "status": "blocked" if identity_reasons else "pass",
            "reasons": identity_reasons,
            "observed": provenance,
        },
        "canonical_descriptor": {
            "status": "pass" if descriptor_ready else "blocked",
            "complete_parent_count": len(descriptor_rows),
            "parent_count": len(parents),
        },
    }
    blocked = [name for name, check in checks.items() if check["status"] != "pass"]
    status = "blocked" if blocked else "ready"
    summary = (
        "CAP graph release is ready for Edge consumption."
        if status == "ready"
        else "CAP graph release is raw-only or identity-incomplete; canonical consumption is blocked."
    )
    return {
        "contract": GRAPH_RELEASE_DOCTOR_CONTRACT,
        "status": status,
        "summary": summary,
        "graph_release": release.payload,
        "graph_release_sha256": release.sha256,
        "ticker": ticker,
        "checks": checks,
        "blocked_checks": blocked,
    }


def _has_complete_descriptor(item: Mapping[str, Any]) -> bool:
    node_spec = item.get("node_spec")
    if not isinstance(node_spec, Mapping):
        return False
    required = {"contract", "node_id", "family", "source", "alignment", "transform"}
    if not required.issubset(node_spec):
        return False
    source_receipt = str(item.get("source_receipt_sha256") or "")
    return bool(_SHA256_RE.fullmatch(source_receipt))


def _find_credential_path(value: Any, path: str = "") -> str | None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key)
            child = f"{path}.{key_text}" if path else key_text
            normalized = key_text.strip().lower().replace("-", "_")
            if normalized in _CREDENTIAL_KEYS or normalized.endswith("_token"):
                return child
            found = _find_credential_path(nested, child)
            if found:
                return found
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found = _find_credential_path(nested, f"{path}[{index}]")
            if found:
                return found
    return None
