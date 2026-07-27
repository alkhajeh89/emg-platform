"""ADR-026 Revision 2, Group D12: confirm no scripting/expression capability
or classification-ranking/dominance comparator was introduced into
`emg_policy_engine` anywhere across Phase 2 (D7-D13).

Appendix ADR-026A's governing principle 1 states this package "remains
declarative, no scripting or expression language" — `PolicyRule`'s own
docstring makes the same commitment explicitly for
`required_resource_attributes` ("not an expression language, an ordinal
operator, or a scripting hook"). These tests make that commitment an
executable, repo-wide guarantee rather than prose that could silently
drift, exactly as Group D12 requires: "confirm no scripting/expression
capability was introduced into `PolicyConfig`/`PolicyEngine`."
"""

from __future__ import annotations

import ast
from pathlib import Path

from emg_policy_engine.rules import PolicyRule

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "emg_policy_engine"

# The exact, known field set as of ADR-026 Revision 2 (Amendment 1). Any
# addition here (an "expression", "script", "rank", or "priority" field, for
# instance) would itself be the kind of change ADR-026A principle 1
# forbids without a new, independent ADR.
_EXPECTED_POLICY_RULE_FIELDS = {
    "rule_id",
    "resource_type",
    "action",
    "effect",
    "description",
    "required_roles",
    "required_attributes",
    "required_scopes",
    "required_resource_attributes",
}

# Any of these appearing as a called name anywhere in the package's source
# would indicate a scripting/expression-evaluation capability.
_FORBIDDEN_CALL_NAMES = {"eval", "exec", "compile", "__import__"}

# Any of these appearing as a declared function/method name would indicate
# an ordinal "classification dominance" comparator being introduced as code
# rather than expressed purely as enumerated policy data (ADR-026A
# principle 1 / PolicyRule's own docstring).
_FORBIDDEN_FUNCTION_NAME_FRAGMENTS = ("rank", "dominance", "dominant", "compare_classification")


def _module_paths() -> tuple[Path, ...]:
    return tuple(sorted(SRC_DIR.glob("*.py")))


def test_policy_rule_field_set_is_unchanged() -> None:
    assert set(PolicyRule.model_fields.keys()) == _EXPECTED_POLICY_RULE_FIELDS


def test_no_scripting_or_expression_evaluation_calls_in_package_source() -> None:
    offenders: list[str] = []
    for module_path in _module_paths():
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in _FORBIDDEN_CALL_NAMES
            ):
                offenders.append(f"{module_path.name}: {node.func.id}(...)")
    assert not offenders, f"forbidden scripting/expression-evaluation calls found: {offenders}"


def test_no_classification_ranking_or_dominance_comparator_in_package_source() -> None:
    offenders: list[str] = []
    for module_path in _module_paths():
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                lowered = node.name.lower()
                for fragment in _FORBIDDEN_FUNCTION_NAME_FRAGMENTS:
                    if fragment in lowered:
                        offenders.append(f"{module_path.name}: {node.name}")
    assert not offenders, f"forbidden ranking/dominance comparator functions found: {offenders}"
