#!/usr/bin/env python3
"""Read-only detector for temporal edge identity drift in MemoryGraph exports."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from emg_common_types import Classification
from emg_memory_graph import EdgeDirection, MemoryEdge, MemoryGraph, TemporalValidity
from pydantic import BaseModel, ConfigDict, ValidationError

EXIT_CLEAN = 0
EXIT_CONFIRMED_DRIFT = 1
EXIT_INSUFFICIENT_EVIDENCE = 2
EXIT_OPERATIONAL_ERROR = 3

_EXIT_THREE = {"malformed_snapshot", "content_hash_mismatch"}
_EXIT_ONE = {
    "confirmed_evidence_association_mismatch",
    "confirmed_mixed_identity",
    "confirmed_missing_relationship_edge",
    "confirmed_interval_mismatch",
    "confirmed_relationship_definition_mismatch",
    "graph_edge_absent_from_source",
}
_EXIT_TWO = {
    "suspected_collapsed_evidence",
    "legacy_id_without_source_inventory",
    "insufficient_evidence",
}


class RelationshipInventoryItem(BaseModel):
    """Authoritative relationship fields needed for read-only comparison."""

    model_config = ConfigDict(extra="forbid")

    relationship_id: str
    relationship_type: str
    from_entity_id: str
    to_entity_id: str
    direction: EdgeDirection = EdgeDirection.DIRECTED
    effective_from: datetime
    effective_to: datetime | None = None
    classification: Classification
    evidence_identities: tuple[str, ...] = ()
    provenance_identity: str | None = None
    supersedes: str | None = None
    superseded_by: str | None = None

    @property
    def evidence_keys(self) -> frozenset[str]:
        keys = set(self.evidence_identities)
        if self.provenance_identity:
            keys.add(self.provenance_identity)
        return frozenset(keys)

    @property
    def validity(self) -> TemporalValidity:
        return TemporalValidity(
            valid_from=self.effective_from,
            valid_until=self.effective_to,
        )


@dataclass(frozen=True)
class LogicalShape:
    edge_type: str
    direction: str
    endpoints: tuple[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "edge_type": self.edge_type,
            "direction": self.direction,
            "endpoints": list(self.endpoints),
        }


@dataclass(frozen=True)
class Finding:
    classification: str
    severity: str
    tenant_id: str | None
    revision_identifier: str | int | None
    edge_id: str | None
    relationship_id: str | None
    logical_shape: dict[str, Any] | None
    evidence: tuple[str, ...]
    explanation: str
    remediation: str
    confirmed: bool

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["evidence"] = list(self.evidence)
        return value


@dataclass(frozen=True)
class RevisionAnalysis:
    source: str
    tenant_id: str | None
    revision_identifier: str | int | None
    calculated_content_hash: str | None
    stored_content_hash: str | None
    findings: tuple[Finding, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "tenant_id": self.tenant_id,
            "revision_identifier": self.revision_identifier,
            "calculated_content_hash": self.calculated_content_hash,
            "stored_content_hash": self.stored_content_hash,
            "findings": [finding.as_dict() for finding in self.findings],
        }


def logical_shape(
    edge_type: str,
    direction: EdgeDirection,
    source_id: str,
    target_id: str,
) -> LogicalShape:
    endpoints = (source_id, target_id)
    if direction is EdgeDirection.UNDIRECTED:
        endpoints = tuple(sorted(endpoints))
    return LogicalShape(edge_type=edge_type, direction=direction.value, endpoints=endpoints)


def edge_shape(edge: MemoryEdge) -> LogicalShape:
    return logical_shape(edge.edge_type, edge.direction, edge.source_id, edge.target_id)


def relationship_shape(relationship: RelationshipInventoryItem) -> LogicalShape:
    return logical_shape(
        relationship.relationship_type,
        relationship.direction,
        relationship.from_entity_id,
        relationship.to_entity_id,
    )


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_relationship_inventory(path: Path) -> tuple[RelationshipInventoryItem, ...]:
    raw = _read_json(path)
    items = raw.get("relationships") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError("relationship inventory must be a list or contain a relationships list")
    relationships = tuple(RelationshipInventoryItem.model_validate(item) for item in items)
    ids = [relationship.relationship_id for relationship in relationships]
    if len(ids) != len(set(ids)):
        raise ValueError("relationship inventory contains duplicate relationship_id values")
    return tuple(sorted(relationships, key=lambda relationship: relationship.relationship_id))


def _snapshot_parts(raw: Any) -> tuple[Any, str | None, str | None, str | int | None]:
    if not isinstance(raw, dict):
        raise ValueError("revision export must be a JSON object")
    graph_json = raw.get("graph_json")
    if graph_json is None:
        graph_json = {"nodes": raw.get("nodes", ()), "edges": raw.get("edges", ())}
    if not isinstance(graph_json, dict):
        raise ValueError("graph_json must be a JSON object")
    tenant = raw.get("tenant_id") or raw.get("tenant")
    if isinstance(tenant, dict):
        tenant = tenant.get("value")
    revision = raw.get("revision_id", raw.get("revision_number"))
    return graph_json, raw.get("content_hash"), tenant, revision


def _finding(
    classification: str,
    *,
    severity: str,
    tenant_id: str | None,
    revision: str | int | None,
    edge_id: str | None = None,
    relationship_id: str | None = None,
    shape: LogicalShape | None = None,
    evidence: Iterable[str] = (),
    explanation: str,
    remediation: str,
    confirmed: bool,
) -> Finding:
    return Finding(
        classification=classification,
        severity=severity,
        tenant_id=tenant_id,
        revision_identifier=revision,
        edge_id=edge_id,
        relationship_id=relationship_id,
        logical_shape=None if shape is None else shape.as_dict(),
        evidence=tuple(sorted(set(evidence))),
        explanation=explanation,
        remediation=remediation,
        confirmed=confirmed,
    )


def _edge_relationship_mismatches(
    edge: MemoryEdge, relationship: RelationshipInventoryItem
) -> tuple[str, ...]:
    mismatches: list[str] = []
    if edge.edge_type != relationship.relationship_type:
        mismatches.append("edge_type")
    if edge.direction != relationship.direction:
        mismatches.append("direction")
    if edge_shape(edge).endpoints != relationship_shape(relationship).endpoints:
        mismatches.append("endpoints")
    if edge.validity != relationship.validity:
        mismatches.append("validity")
    if edge.classification != relationship.classification:
        mismatches.append("classification")
    return tuple(mismatches)


def _check_canonical_evidence(
    edge: MemoryEdge,
    relationship: RelationshipInventoryItem,
    by_id: Mapping[str, RelationshipInventoryItem],
    findings: list[Finding],
    tenant_id: str | None,
    revision: str | int | None,
) -> None:
    observed = {value for item in edge.evidence for value in (item.evidence_id, item.locator)}
    foreign = sorted(
        other.relationship_id
        for other in by_id.values()
        if other.relationship_id != relationship.relationship_id
        and observed.intersection(other.evidence_keys)
    )
    if foreign:
        findings.append(
            _finding(
                "confirmed_evidence_association_mismatch",
                severity="high",
                tenant_id=tenant_id,
                revision=revision,
                edge_id=edge.edge_id,
                relationship_id=relationship.relationship_id,
                shape=edge_shape(edge),
                evidence=foreign,
                explanation=(
                    "Edge evidence belongs to a different authoritative relationship version."
                ),
                remediation="Rebuild a new revision from version-specific source evidence.",
                confirmed=True,
            )
        )
    elif observed and not relationship.evidence_keys:
        findings.append(
            _finding(
                "insufficient_evidence",
                severity="low",
                tenant_id=tenant_id,
                revision=revision,
                edge_id=edge.edge_id,
                relationship_id=relationship.relationship_id,
                shape=edge_shape(edge),
                evidence=observed,
                explanation="Inventory has no evidence identity for validating edge evidence.",
                remediation="Supply evidence identities in the authoritative inventory.",
                confirmed=False,
            )
        )
    elif relationship.evidence_keys and not observed.intersection(relationship.evidence_keys):
        findings.append(
            _finding(
                "insufficient_evidence",
                severity="medium",
                tenant_id=tenant_id,
                revision=revision,
                edge_id=edge.edge_id,
                relationship_id=relationship.relationship_id,
                shape=edge_shape(edge),
                evidence=observed,
                explanation="Edge evidence does not match a known inventory evidence identity.",
                remediation="Verify evidence locator mapping before classifying the edge.",
                confirmed=False,
            )
        )


def _check_legacy_evidence(
    graph: MemoryGraph,
    relationships: Sequence[RelationshipInventoryItem],
    findings: list[Finding],
    tenant_id: str | None,
    revision: str | int | None,
) -> None:
    by_shape: dict[LogicalShape, list[RelationshipInventoryItem]] = defaultdict(list)
    for relationship in relationships:
        by_shape[relationship_shape(relationship)].append(relationship)
    for edge in graph.edges:
        if not edge.edge_id.startswith("me-"):
            continue
        observed = {value for item in edge.evidence for value in (item.evidence_id, item.locator)}
        matched = [
            relationship
            for relationship in by_shape.get(edge_shape(edge), [])
            if observed.intersection(relationship.evidence_keys)
        ]
        intervals = {relationship.validity.model_dump_json() for relationship in matched}
        if len(matched) > 1 and len(intervals) > 1:
            findings.append(
                _finding(
                    "suspected_collapsed_evidence",
                    severity="high",
                    tenant_id=tenant_id,
                    revision=revision,
                    edge_id=edge.edge_id,
                    shape=edge_shape(edge),
                    evidence=(relationship.relationship_id for relationship in matched),
                    explanation=(
                        "Legacy edge contains evidence for multiple relationship versions "
                        "with different validity intervals."
                    ),
                    remediation="Recover the full source and inspect before a controlled rebuild.",
                    confirmed=False,
                )
            )
        elif observed and not matched:
            findings.append(
                _finding(
                    "insufficient_evidence",
                    severity="medium",
                    tenant_id=tenant_id,
                    revision=revision,
                    edge_id=edge.edge_id,
                    shape=edge_shape(edge),
                    evidence=observed,
                    explanation="Legacy edge evidence cannot be mapped to the source inventory.",
                    remediation="Recover or enrich the authoritative evidence inventory.",
                    confirmed=False,
                )
            )


def _inventory_findings(
    graph: MemoryGraph,
    relationships: Sequence[RelationshipInventoryItem],
    *,
    tenant_id: str | None,
    revision: str | int | None,
) -> list[Finding]:
    findings: list[Finding] = []
    by_id = {relationship.relationship_id: relationship for relationship in relationships}
    for relationship in relationships:
        edge = graph.edge(relationship.relationship_id)
        if edge is None:
            findings.append(
                _finding(
                    "confirmed_missing_relationship_edge",
                    severity="high",
                    tenant_id=tenant_id,
                    revision=revision,
                    relationship_id=relationship.relationship_id,
                    shape=relationship_shape(relationship),
                    explanation="Authoritative relationship has no edge with its canonical ID.",
                    remediation="Rebuild a new revision from the complete authoritative source.",
                    confirmed=True,
                )
            )
            continue
        mismatches = _edge_relationship_mismatches(edge, relationship)
        if "validity" in mismatches:
            findings.append(
                _finding(
                    "confirmed_interval_mismatch",
                    severity="high",
                    tenant_id=tenant_id,
                    revision=revision,
                    edge_id=edge.edge_id,
                    relationship_id=relationship.relationship_id,
                    shape=edge_shape(edge),
                    evidence=("validity",),
                    explanation=(
                        "Graph edge validity disagrees with the authoritative relationship."
                    ),
                    remediation="Investigate source/export consistency before any rebuild.",
                    confirmed=True,
                )
            )
        definition_mismatches = tuple(field for field in mismatches if field != "validity")
        if definition_mismatches:
            findings.append(
                _finding(
                    "confirmed_relationship_definition_mismatch",
                    severity="high",
                    tenant_id=tenant_id,
                    revision=revision,
                    edge_id=edge.edge_id,
                    relationship_id=relationship.relationship_id,
                    shape=edge_shape(edge),
                    evidence=definition_mismatches,
                    explanation=(
                        "Graph edge definition disagrees with the authoritative relationship: "
                        + ", ".join(definition_mismatches)
                        + "."
                    ),
                    remediation="Investigate source/export consistency before any rebuild.",
                    confirmed=True,
                )
            )
        _check_canonical_evidence(edge, relationship, by_id, findings, tenant_id, revision)
    for edge in graph.edges:
        if edge.edge_id.startswith("me-") or edge.edge_id in by_id:
            continue
        findings.append(
            _finding(
                "graph_edge_absent_from_source",
                severity="high",
                tenant_id=tenant_id,
                revision=revision,
                edge_id=edge.edge_id,
                shape=edge_shape(edge),
                explanation="Canonical graph edge ID is absent from the source inventory.",
                remediation="Verify inventory completeness before approving a rebuild.",
                confirmed=True,
            )
        )
    _check_legacy_evidence(graph, relationships, findings, tenant_id, revision)
    return findings


def analyze_revision(
    path: Path,
    relationships: Sequence[RelationshipInventoryItem] | None = None,
    *,
    tenant_override: str | None = None,
) -> RevisionAnalysis:
    tenant: str | None = tenant_override
    revision: str | int | None = None
    stored_hash: str | None = None
    try:
        graph_json, stored_hash, snapshot_tenant, revision = _snapshot_parts(_read_json(path))
        tenant = tenant_override or snapshot_tenant
        graph = MemoryGraph.model_validate(graph_json)
    except (OSError, json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
        finding = _finding(
            "malformed_snapshot",
            severity="high",
            tenant_id=tenant,
            revision=revision,
            evidence=(str(exc),),
            explanation="Export could not be parsed and validated as a MemoryGraph.",
            remediation="Escalate for source/export investigation; do not repair automatically.",
            confirmed=True,
        )
        return RevisionAnalysis(str(path), tenant, revision, None, stored_hash, (finding,))

    calculated_hash = graph.content_hash()
    findings: list[Finding] = []
    if stored_hash is None:
        findings.append(
            _finding(
                "insufficient_evidence",
                severity="medium",
                tenant_id=tenant,
                revision=revision,
                explanation="Revision export does not include a stored content_hash.",
                remediation="Export the persisted envelope including content_hash.",
                confirmed=False,
            )
        )
    elif stored_hash != calculated_hash:
        findings.append(
            _finding(
                "content_hash_mismatch",
                severity="high",
                tenant_id=tenant,
                revision=revision,
                evidence=(f"stored={stored_hash}", f"calculated={calculated_hash}"),
                explanation="Stored content hash does not match the validated graph.",
                remediation="Escalate as an integrity incident; do not repair automatically.",
                confirmed=True,
            )
        )

    grouped: dict[LogicalShape, list[MemoryEdge]] = defaultdict(list)
    for edge in graph.edges:
        grouped[edge_shape(edge)].append(edge)
    for shape, edges in sorted(grouped.items(), key=lambda item: repr(item[0])):
        legacy = sorted(edge.edge_id for edge in edges if edge.edge_id.startswith("me-"))
        canonical = sorted(edge.edge_id for edge in edges if not edge.edge_id.startswith("me-"))
        if legacy and canonical:
            findings.append(
                _finding(
                    "confirmed_mixed_identity",
                    severity="high",
                    tenant_id=tenant,
                    revision=revision,
                    shape=shape,
                    evidence=(*legacy, *canonical),
                    explanation="Shape contains both legacy and canonical identities.",
                    remediation="Investigate and rebuild a new revision from the full source.",
                    confirmed=True,
                )
            )
        elif legacy and relationships is None:
            for edge_id in legacy:
                findings.append(
                    _finding(
                        "legacy_id_without_source_inventory",
                        severity="medium",
                        tenant_id=tenant,
                        revision=revision,
                        edge_id=edge_id,
                        shape=shape,
                        explanation="Legacy edge cannot be assessed without source relationships.",
                        remediation="Supply the complete authoritative relationship inventory.",
                        confirmed=False,
                    )
                )
    if relationships is not None:
        findings.extend(
            _inventory_findings(graph, relationships, tenant_id=tenant, revision=revision)
        )
    if not findings:
        findings.append(
            _finding(
                "clean",
                severity="informational",
                tenant_id=tenant,
                revision=revision,
                explanation="No temporal edge identity drift was detected.",
                remediation="No action required.",
                confirmed=True,
            )
        )
    return RevisionAnalysis(
        str(path),
        tenant,
        revision,
        calculated_hash,
        stored_hash,
        tuple(sorted(findings, key=_finding_sort_key)),
    )


def _finding_sort_key(finding: Finding) -> tuple[str, str, str, str]:
    shape = (
        "" if finding.logical_shape is None else json.dumps(finding.logical_shape, sort_keys=True)
    )
    return (
        finding.classification,
        finding.edge_id or "",
        finding.relationship_id or "",
        shape,
    )


def exit_code_for(analyses: Sequence[RevisionAnalysis]) -> int:
    classifications = {
        finding.classification for analysis in analyses for finding in analysis.findings
    }
    if classifications.intersection(_EXIT_THREE):
        return EXIT_OPERATIONAL_ERROR
    if classifications.intersection(_EXIT_ONE):
        return EXIT_CONFIRMED_DRIFT
    if classifications.intersection(_EXIT_TWO):
        return EXIT_INSUFFICIENT_EVIDENCE
    return EXIT_CLEAN


def render_json(analyses: Sequence[RevisionAnalysis]) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "exit_code": exit_code_for(analyses),
            "revisions": [analysis.as_dict() for analysis in analyses],
        },
        indent=2,
        sort_keys=True,
    )


def render_human(analyses: Sequence[RevisionAnalysis]) -> str:
    lines = ["Temporal Edge Identity Drift Report", f"Exit code: {exit_code_for(analyses)}"]
    for analysis in analyses:
        tenant = "unknown" if analysis.tenant_id is None else analysis.tenant_id
        revision = (
            "unknown" if analysis.revision_identifier is None else str(analysis.revision_identifier)
        )
        lines.extend(
            [
                "",
                f"Source: {analysis.source}",
                f"Tenant: {tenant}",
                f"Revision: {revision}",
            ]
        )
        for finding in analysis.findings:
            subject = finding.edge_id or finding.relationship_id or "-"
            lines.append(
                f"- [{finding.severity}] {finding.classification} "
                f"(subject: {subject}, confirmed: {str(finding.confirmed).lower()})"
            )
            lines.append(f"  {finding.explanation}")
            lines.append(f"  Guidance: {finding.remediation}")
    return "\n".join(lines)


def _revision_paths(values: Sequence[Path]) -> tuple[Path, ...]:
    paths: list[Path] = []
    for value in values:
        paths.extend(sorted(value.glob("*.json")) if value.is_dir() else (value,))
    if not paths:
        raise ValueError("no revision JSON files found")
    return tuple(sorted(paths, key=str))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--revision-json",
        action="append",
        required=True,
        type=Path,
        help="Revision JSON file or directory; may be repeated.",
    )
    parser.add_argument("--relationships-json", type=Path)
    parser.add_argument("--tenant-id")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        relationships = (
            load_relationship_inventory(args.relationships_json)
            if args.relationships_json
            else None
        )
        analyses = tuple(
            analyze_revision(path, relationships, tenant_override=args.tenant_id)
            for path in _revision_paths(args.revision_json)
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
        print(f"operational error: {exc}", file=sys.stderr)
        return EXIT_OPERATIONAL_ERROR
    print(render_json(analyses) if args.format == "json" else render_human(analyses))
    return exit_code_for(analyses)


if __name__ == "__main__":
    raise SystemExit(main())
