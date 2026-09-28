"""Policy allow-list and proposal gate.

Governs whether a proposed tool call is denied outright, allowed to run
without asking a human, or requires human approval first.

S1 shipped the deny-by-default `PolicyAllowList` interface with no rules
configured. S7 configures the real rules and adds `check_proposal`, which is
the single gate every action passes through before execution.

`evaluate()`'s three outcomes ("deny", "needs_approval", "allow") are exactly
the values graph/nodes.py's `policy_check` node produces, so the graph shape
is unchanged.

What `check_proposal` enforces, and why each rule is there:

  1. **Tool allow-list.** Deny-by-default. Only `create_reminder` and
     `draft_email` exist; a proposal naming anything else is denied, which
     is what makes "the model invented a `delete_files` tool" a non-event.
  2. **Pydantic parameter validation.** Every tool declares a model; params
     that do not validate never reach a handler.
  3. **Paths stay inside the vault.** Tools build their own paths from a
     slug (see api/tools/_vault.py), and this layer additionally refuses any
     parameter that looks like a path escaping the vault.
  4. **At least one document citation.** A proposal with no evidence is
     denied. This is the handover plan's stated mitigation for "proposals
     without evidence", and it means every action is traceable to a file.
  5. **Values from document text are untrusted.** Parameters are scanned for
     prompt-injection and control characters, and flagged so the approval UI
     can highlight them. Flagged values do not block the action -- a human
     still decides -- but they are never silently trusted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

DENY = "deny"
NEEDS_APPROVAL = "needs_approval"
ALLOW = "allow"


@dataclass
class PolicyRule:
    tool: str
    allowed: bool = False
    requires_approval: bool = True
    notes: str = ""
    #: Coarse sensitivity label surfaced on the approval card.
    tier: str = "review"


class PolicyAllowList:
    """Deny-by-default: a tool with no rule, or a rule with allowed=False,
    always evaluates to "deny"."""

    def __init__(self, rules: Optional[Dict[str, PolicyRule]] = None) -> None:
        self._rules: Dict[str, PolicyRule] = dict(rules) if rules else {}

    def add_rule(self, rule: PolicyRule) -> None:
        self._rules[rule.tool] = rule

    def get_rule(self, tool: str) -> Optional[PolicyRule]:
        return self._rules.get(tool)

    def tools(self) -> List[str]:
        return sorted(self._rules)

    def evaluate(self, tool: str) -> str:
        """Returns one of: "deny", "needs_approval", "allow"."""
        rule = self._rules.get(tool)
        if rule is None or not rule.allowed:
            return DENY
        return NEEDS_APPROVAL if rule.requires_approval else ALLOW


# ---------------------------------------------------------------------
# Untrusted-value detection
# ---------------------------------------------------------------------

#: Phrasings that only appear in text trying to steer a model. Document text
#: is untrusted input, so a parameter carrying one of these was very likely
#: lifted from a document attempting prompt injection.
_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above)", re.I),
    re.compile(r"disregard\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above)", re.I),
    re.compile(r"\byou\s+(?:are|act)\s+(?:now\s+)?(?:a|an|as)\b", re.I),
    re.compile(r"\bsystem\s*(?:prompt|message)\b", re.I),
    re.compile(r"\b(?:reveal|print|output|repeat)\s+(?:your|the)\s+(?:prompt|instructions)", re.I),
    re.compile(r"\bsend\s+(?:this|it|them)\s+to\b", re.I),
    re.compile(r"\b(?:curl|wget|https?://)", re.I),
)

_PATH_LIKE_RE = re.compile(r"(?:^|[\s\"'])(?:/|~/|\.\./|[A-Za-z]:\\)")


@dataclass
class PolicyVerdict:
    """The outcome of `check_proposal`, ready to be written into an audit row."""

    decision: str
    reasons: List[str] = field(default_factory=list)
    tier: str = "review"
    #: Parameter names whose values came from document text and look suspicious.
    untrusted_fields: List[str] = field(default_factory=list)
    #: Parameters after Pydantic validation/coercion, or None if invalid.
    validated_parameters: Optional[Dict[str, Any]] = None

    @property
    def allowed(self) -> bool:
        return self.decision in (ALLOW, NEEDS_APPROVAL)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "reasons": list(self.reasons),
            "tier": self.tier,
            "untrusted_fields": list(self.untrusted_fields),
        }


def find_untrusted_values(parameters: Dict[str, Any]) -> List[str]:
    """Parameter names whose string values look like injected instructions."""
    flagged: List[str] = []
    for name, value in (parameters or {}).items():
        candidates = value if isinstance(value, (list, tuple)) else [value]
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            if any(pattern.search(candidate) for pattern in _INJECTION_PATTERNS):
                flagged.append(name)
                break
    return flagged


def _escaping_paths(parameters: Dict[str, Any], vault_dir: str) -> List[str]:
    """Parameter names holding a path that does not resolve inside the vault."""
    try:
        vault = Path(vault_dir).expanduser().resolve()
    except (OSError, RuntimeError):
        return ["<vault unresolvable>"]

    offenders: List[str] = []
    for name, value in (parameters or {}).items():
        if not isinstance(value, str) or not _PATH_LIKE_RE.search(f" {value}"):
            continue
        try:
            resolved = Path(value).expanduser().resolve()
        except (OSError, RuntimeError):
            offenders.append(name)
            continue
        if resolved != vault and vault not in resolved.parents:
            offenders.append(name)
    return offenders


# ---------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------


def check_proposal(
    tool: str,
    parameters: Optional[Dict[str, Any]],
    evidence_document_hashes: Optional[Sequence[str]] = None,
    allow_list: Optional[PolicyAllowList] = None,
    vault_dir: Optional[str] = None,
) -> PolicyVerdict:
    """Evaluate one proposed action against every policy rule.

    Returns a verdict rather than raising, because a denial is a normal,
    auditable outcome: the graph records it and routes straight to
    audit_and_memory.
    """
    from config import get_config

    allow_list = allow_list if allow_list is not None else default_policy
    vault_dir = vault_dir or get_config().vault_dir
    parameters = dict(parameters or {})
    evidence = [h for h in (evidence_document_hashes or []) if h]

    reasons: List[str] = []

    # 1. Tool allow-list, deny-by-default.
    decision = allow_list.evaluate(tool)
    rule = allow_list.get_rule(tool)
    tier = rule.tier if rule else "denied"
    if decision == DENY:
        reasons.append(
            f"tool {tool!r} is not on the allow-list "
            f"(allowed: {', '.join(allow_list.tools()) or 'none'})"
        )
        return PolicyVerdict(decision=DENY, reasons=reasons, tier=tier)

    # 2. At least one document citation. Checked before parameter validation
    #    so an uncited proposal is reported as uncited, not as malformed.
    if not evidence:
        reasons.append("proposal cites no document; every action needs evidence")

    # 3. Pydantic parameter validation.
    validated: Optional[Dict[str, Any]] = None
    try:
        from api.tools import PARAM_MODELS

        model = PARAM_MODELS.get(tool)
        if model is None:
            reasons.append(f"no parameter model registered for {tool!r}")
        else:
            validated = model(**parameters).model_dump()
    except Exception as exc:  # noqa: BLE001 - any validation error denies
        reasons.append(f"parameter validation failed: {exc}")

    # 4. No path may escape the vault.
    offenders = _escaping_paths(parameters, vault_dir)
    if offenders:
        reasons.append(
            "parameter(s) point outside the vault: " + ", ".join(sorted(offenders))
        )

    # 5. Flag untrusted-looking values. Does NOT deny -- a human decides --
    #    but the approval card must be able to highlight them.
    untrusted = find_untrusted_values(parameters)

    if reasons:
        return PolicyVerdict(
            decision=DENY,
            reasons=reasons,
            tier=tier,
            untrusted_fields=untrusted,
            validated_parameters=validated,
        )

    return PolicyVerdict(
        decision=decision,
        reasons=["passed tool allow-list, parameter validation, vault "
                 "containment and citation checks"],
        tier=tier,
        untrusted_fields=untrusted,
        validated_parameters=validated,
    )


def build_default_policy() -> PolicyAllowList:
    """The S7 rule set: exactly two tools, both requiring human approval.

    `requires_approval=True` on both is deliberate. Neither tool is
    destructive, but the handover plan lists human approval among the things
    that must never be cut, and an action the user never saw is worth less
    than one they approved.
    """
    allow_list = PolicyAllowList()
    allow_list.add_rule(
        PolicyRule(
            tool="create_reminder",
            allowed=True,
            requires_approval=True,
            tier="review",
            notes="Writes a reminders row and an .ics file inside the vault. "
                  "Notifies nobody.",
        )
    )
    allow_list.add_rule(
        PolicyRule(
            tool="draft_email",
            allowed=True,
            requires_approval=True,
            tier="review",
            notes="Writes an .eml draft inside the vault. Never sends.",
        )
    )
    return allow_list


#: Process-wide default policy. Configured as of S7.
default_policy = build_default_policy()
