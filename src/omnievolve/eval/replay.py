"""Canonical fingerprints for deterministic evaluation replay."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any


def canonical_fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ReplayRecord:
    candidate_hash: str
    evaluator_version_id: str
    environment_version_id: str
    seed: int
    split_name: str
    score: float
    metrics: dict[str, Any]
    passed: bool

    @property
    def input_fingerprint(self) -> str:
        return canonical_fingerprint(
            {
                "candidate_hash": self.candidate_hash,
                "evaluator_version_id": self.evaluator_version_id,
                "environment_version_id": self.environment_version_id,
                "seed": self.seed,
                "split_name": self.split_name,
            }
        )

    @property
    def output_fingerprint(self) -> str:
        return canonical_fingerprint(
            {
                "score": self.score,
                "metrics": self.metrics,
                "passed": self.passed,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "input_fingerprint": self.input_fingerprint,
            "output_fingerprint": self.output_fingerprint,
        }


def assert_deterministic_replay(expected: ReplayRecord, actual: ReplayRecord) -> None:
    if expected.input_fingerprint != actual.input_fingerprint:
        raise ValueError("replay inputs do not match")
    if expected.output_fingerprint != actual.output_fingerprint:
        raise RuntimeError(
            "non-deterministic evaluation output for identical candidate/evaluator/seed/split"
        )
