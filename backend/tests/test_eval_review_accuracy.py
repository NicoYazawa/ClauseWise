"""Independent labeled evaluation: rule-layer miss (false negative) / false positive / citation accuracy (coverage is only an auxiliary metric).

Data source: tests/data/review_goldset.json (human-labeled samples, independent of the implementation):
- miss: an expected finding was not produced by the rule engine
- false positive: the rule engine produced a finding not in the labels
- citation accuracy: the legal_basis of a hit finding must contain the labeled citation basis
"""
from __future__ import annotations

import json
from pathlib import Path

from app.services import review_service
from tests import helpers

GOLDSET = Path(__file__).parent / "data" / "review_goldset.json"


def _load_samples() -> list[dict]:
    return json.loads(GOLDSET.read_text(encoding="utf-8"))["samples"]


def _matches(produced: dict, expected: dict) -> bool:
    if produced.get("risk_type") != expected.get("risk_type"):
        return False
    issue = produced.get("issue") or ""
    return all(token in issue for token in expected.get("issue_contains", []))


def test_rule_engine_goldset_metrics(db):
    samples = _load_samples()
    owner = helpers.make_user(db)
    db.commit()
    missed: list[str] = []
    false_positives: list[str] = []
    citation_misses: list[str] = []
    total_expected = total_produced = total_citations = 0

    for sample in samples:
        contract = helpers.make_contract(db, owner_id=owner.id, contract_type=sample["contract_type"],
                                         contract_no=f"HT-EVAL-{sample['id']}")
        clauses = [
            helpers.make_clause(db, 1, contract.id, clause_no=cl["clause_no"],
                                clause_type=cl["clause_type"], content=cl["content"])
            for cl in sample["clauses"]
        ]
        db.commit()
        produced = review_service.run_rule_engine(db, contract, clauses)
        total_produced += len(produced)
        expected = sample.get("expect", [])
        total_expected += len(expected)

        for exp in expected:
            hit = next((p for p in produced if _matches(p, exp)), None)
            if hit is None:
                missed.append(f"{sample['id']}: 漏报 {exp['risk_type']} {exp.get('issue_contains')}")
                continue
            for citation in exp.get("legal_basis_contains", []):
                total_citations += 1
                if citation not in (hit.get("legal_basis") or ""):
                    citation_misses.append(f"{sample['id']}: 引用缺失「{citation}」")
        for p in produced:
            if not any(_matches(p, exp) for exp in expected):
                false_positives.append(f"{sample['id']}: 误报 {p['risk_type']} {p['issue'][:40]}")

    recall = 1.0 if total_expected == 0 else (total_expected - len(missed)) / total_expected
    precision = 1.0 if total_produced == 0 else (total_produced - len(false_positives)) / total_produced
    # Auxiliary metric output (coverage is not a correctness metric)
    print(f"\n[eval] 样本 {len(samples)}｜期望发现 {total_expected}｜产出 {total_produced}"
          f"｜召回 {recall:.2%}｜精确 {precision:.2%}｜引用检查 {total_citations}")

    assert not missed, "存在漏报：\n" + "\n".join(missed)
    assert not false_positives, "存在误报：\n" + "\n".join(false_positives)
    assert not citation_misses, "存在引用缺失：\n" + "\n".join(citation_misses)
