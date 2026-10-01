"""Bundled fictional reconciliation policy with stable reference IDs."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .models import ChecklistItem, Finding

POLICY_PATH = Path(__file__).resolve().parent.parent / "policies" / "reconciliation_policy.md"


@dataclass(frozen=True)
class PolicyRule:
    ref: str
    title: str
    applies_to: str
    follow_up: str
    blocking: bool


@lru_cache(maxsize=1)
def load_policy() -> tuple[str, dict[str, PolicyRule]]:
    text = POLICY_PATH.read_text(encoding="utf-8")
    version = re.search(r"Policy version:\s*(\S+)", text).group(1)
    rules: dict[str, PolicyRule] = {}
    for block in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
        head, *body = block.strip().splitlines()
        ref, title = (s.strip() for s in head.split("|", 1))
        fields = dict(line.split(":", 1) for line in body if ":" in line)
        rule = PolicyRule(ref, title, fields["Applies to"].strip(), fields["Follow-up"].strip(),
                          fields["Blocking"].strip().lower() == "yes")
        rules[rule.applies_to] = rule
    return version, rules


def known_codes() -> set[str]:
    return set(load_policy()[1]) - {"NO_FINDINGS"}


def lookup(codes: list[str]) -> list[PolicyRule]:
    _, rules = load_policy()
    wanted = sorted({c for c in codes if c in rules and c != "NO_FINDINGS"})
    if not wanted:
        return [rules["NO_FINDINGS"]]
    return [rules[c] for c in wanted]


def build_checklist(findings: list[Finding]) -> list[ChecklistItem]:
    """Templated follow-up assembled from Python findings and policy references."""
    _, rules = load_policy()
    items = []
    if not any(f.blocking for f in findings):
        r = rules["NO_FINDINGS"]
        items.append(ChecklistItem(finding_code="NO_FINDINGS", policy_ref=r.ref, action=r.follow_up))
    for f in findings:
        r = rules.get(f.code) or rules["INCOMPLETE_PROCESSING"]
        action = r.follow_up.replace("{field}", f.field or "the affected value")
        items.append(ChecklistItem(finding_code=f.code, field=f.field, policy_ref=r.ref, action=action))
    return items
