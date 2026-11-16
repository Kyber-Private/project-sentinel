"""Reconcile facts across documents: duplicates, corroboration, and conflicts."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Optional

from domain import Conflict, DataQualityIssue, DuplicateGroup, ExtractionResult, Fact
from finance.formatting import money

# Lower rank = preferred source when the same value appears in several places.
SOURCE_RANK = {"table": 0, "text_pattern": 2, "agent": 3, "user_answer": 0}


def _rank(f: Fact) -> tuple:
    ftype = f.source.file_name.rsplit(".", 1)[-1].lower()
    type_rank = {"xlsx": 0, "xls": 0, "csv": 1, "docx": 2, "pdf": 3, "txt": 4}.get(ftype, 5)
    return (SOURCE_RANK.get(f.extraction_method, 5), type_rank)


def values_match(a: Optional[float], b: Optional[float], rel: float = 0.005, abs_tol: float = 1.0) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= max(abs_tol, rel * max(abs(a), abs(b)))


def assign_ids(facts: list[Fact]) -> None:
    for i, f in enumerate(facts, start=1):
        if not f.id:
            f.id = f"F{i:04d}"


def _months_between(a: str, b: str) -> int:
    ya, ma = int(a[:4]), int(a[5:7])
    yb, mb = int(b[:4]), int(b[5:7])
    return (yb - ya) * 12 + (mb - ma)


def reconcile(facts: list[Fact], issues: list[DataQualityIssue], meta: dict) -> ExtractionResult:
    assign_ids(facts)
    _CURRENCY["code"] = meta.get("currency") or "USD"
    conflicts: list[Conflict] = []
    duplicates: list[DuplicateGroup] = []
    issues = list(issues)

    # 1. Same metric, same entity, same period from several sources.
    groups: dict[tuple, list[Fact]] = defaultdict(list)
    for f in facts:
        if f.metric in ("business_note", "supplier_invoice", "milestone", "open_purchase_order", "currency_statement"):
            continue
        if f.value is None and f.text_value is None:
            continue
        # A local AI may extract a narrative observation for a metric that
        # already has a numeric table value. Keep text-only evidence separate:
        # comparing None with a float would crash numeric conflict detection.
        kind = "numeric" if f.value is not None else "text"
        key = (f.entity_type, f.entity.lower(), f.metric, f.period,
               (f.dimension or "").lower(), f.qualifier or "", kind)
        if f.metric in ("budget_revised",):
            key = key[:-2] + (kind,)  # qualifier text varies across mentions
        groups[key].append(f)

    for key, members in groups.items():
        if len(members) < 2:
            continue
        members.sort(key=_rank)
        kept = members[0]
        same = [m for m in members[1:] if values_match(m.value, kept.value) and m.text_value == kept.text_value]
        diff = [m for m in members[1:] if m not in same]
        for m in same:
            m.superseded = True
            m.attributes["duplicate_of"] = kept.id
            kept.corroborating_sources.append(m.source)
        if same:
            if any(s.source.file_id != kept.source.file_id for s in same):
                duplicates.append(
                    DuplicateGroup(
                        id=f"D{len(duplicates)+1:03d}", kind="exact",
                        description=f"{_label(kept)} appears in {len(same)+1} places with the same value; counted once.",
                        fact_ids=[kept.id] + [s.id for s in same], kept_fact_id=kept.id,
                    )
                )
        if diff:
            # Text-only observations can disagree in wording without
            # constituting a contradictory financial amount. Keep their
            # provenance; do not invent a numeric conflict from null values.
            if kept.value is None:
                issues.append(DataQualityIssue(
                    severity="info",
                    message=f"{_label(kept)} has differing text descriptions; review the cited sources.",
                    fact_ids=[kept.id] + [d.id for d in diff],
                ))
                continue
            vals = [kept.value] + [d.value for d in diff]
            numeric_vals = [v for v in vals if v is not None]
            if len(numeric_vals) != len(vals):
                issues.append(DataQualityIssue(
                    severity="warning",
                    message=f"{_label(kept)} has a numeric/text mismatch; review the cited sources.",
                    fact_ids=[kept.id] + [d.id for d in diff],
                ))
                continue
            spread = (max(numeric_vals) - min(numeric_vals)) / max(1.0, abs(max(numeric_vals, key=abs)))
            conflicts.append(
                Conflict(
                    id=f"C{len(conflicts)+1:03d}", entity=kept.entity, metric=kept.metric, period=kept.period,
                    description=f"{_label(kept)} has different values in different documents.",
                    fact_ids=[kept.id] + [d.id for d in diff], values=vals, material=spread > 0.01,
                )
            )

    # 2. Project budgets: approved budget vs any other budget figure.
    by_project: dict[str, list[Fact]] = defaultdict(list)
    for f in facts:
        if f.metric in ("budget_approved", "budget_revised") and not f.superseded and f.value is not None:
            by_project[f.entity].append(f)
    for project, members in by_project.items():
        distinct: list[Fact] = []
        for m in sorted(members, key=_rank):
            if not any(values_match(m.value, d.value) for d in distinct):
                distinct.append(m)
            else:
                twin = next(d for d in distinct if values_match(m.value, d.value))
                if m.metric == twin.metric and m.id != twin.id and not m.superseded:
                    m.superseded = True
                    m.attributes["duplicate_of"] = twin.id
                    twin.corroborating_sources.append(m.source)
        if len(distinct) > 1 and not any(
            c.entity == project and c.metric == "budget" for c in conflicts
        ):
            approved = [d for d in distinct if d.metric == "budget_approved"]
            other = [d for d in distinct if d.metric != "budget_approved"]
            if approved and other:
                desc = (
                    f"{project}: the approved budget is {_money(approved[0].value)} in {approved[0].source.file_name}, "
                    f"but {other[0].source.file_name} refers to {_money(other[0].value)}"
                    f" ({other[0].qualifier or 'status unclear'})."
                )
            else:
                desc = f"{project}: several different budget figures appear across the documents."
            conflicts.append(
                Conflict(
                    id=f"C{len(conflicts)+1:03d}", entity=project, metric="budget",
                    description=desc, fact_ids=[d.id for d in distinct], values=[d.value for d in distinct],
                    material=True,
                )
            )
    # Remove generic same-key conflicts already covered by the budget conflict.
    conflicts = [
        c for c in conflicts
        if not (c.metric in ("budget_approved", "budget_revised")
                and any(b.metric == "budget" and b.entity == c.entity for b in conflicts))
    ]

    # 3. Supplier invoices: exact duplicates by invoice id, uncertain by supplier/amount/date.
    invoices = [f for f in facts if f.metric == "supplier_invoice" and not f.superseded]
    invoices.sort(key=_rank)
    seen_ids: dict[str, Fact] = {}
    for inv in invoices:
        iid = (inv.attributes.get("invoice_id") or "").strip().lower()
        if iid and iid in seen_ids:
            kept = seen_ids[iid]
            if values_match(inv.value, kept.value):
                inv.superseded = True
                inv.attributes["duplicate_of"] = kept.id
                kept.corroborating_sources.append(inv.source)
                duplicates.append(
                    DuplicateGroup(
                        id=f"D{len(duplicates)+1:03d}", kind="exact",
                        description=f"Invoice {inv.attributes.get('invoice_id')} from {inv.entity} appears in "
                        f"{kept.source.file_name} and {inv.source.file_name}; counted once.",
                        fact_ids=[kept.id, inv.id], kept_fact_id=kept.id,
                    )
                )
            else:
                conflicts.append(
                    Conflict(
                        id=f"C{len(conflicts)+1:03d}", entity=inv.entity, metric="supplier_invoice",
                        description=f"Invoice {inv.attributes.get('invoice_id')} has different amounts in different files.",
                        fact_ids=[kept.id, inv.id], values=[kept.value, inv.value], material=True,
                    )
                )
        elif iid:
            seen_ids[iid] = inv
    active_inv = [f for f in invoices if not f.superseded]
    for i, a in enumerate(active_inv):
        for b in active_inv[i + 1 :]:
            if b.superseded or a.source.file_id == b.source.file_id:
                continue
            if a.entity.lower() != b.entity.lower() or not values_match(a.value, b.value, rel=0, abs_tol=0.01):
                continue
            ida, idb = a.attributes.get("invoice_id"), b.attributes.get("invoice_id")
            if ida and idb:
                continue  # different invoice numbers: different invoices
            da, db = a.attributes.get("date"), b.attributes.get("date")
            close = True
            if da and db:
                close = abs((date.fromisoformat(da) - date.fromisoformat(db)).days) <= 7
            if close:
                keep, drop = (a, b) if _rank(a) <= _rank(b) else (b, a)
                drop.superseded = True
                drop.attributes["duplicate_of"] = keep.id
                drop.attributes["uncertain_match"] = True
                duplicates.append(
                    DuplicateGroup(
                        id=f"D{len(duplicates)+1:03d}", kind="uncertain",
                        description=f"{_money(a.value)} from {a.entity} appears in {a.source.file_name} and "
                        f"{b.source.file_name} without matching invoice numbers. Treated as the same invoice; "
                        "please review.",
                        fact_ids=[keep.id, drop.id], kept_fact_id=keep.id,
                    )
                )

    # 4. Project actual cost vs sum of monthly project costs.
    monthly: dict[str, float] = defaultdict(float)
    for f in facts:
        if f.metric == "project_cost" and not f.superseded and f.value is not None:
            monthly[f.entity] += f.value
    for f in facts:
        if f.metric == "actual_cost" and not f.superseded and f.entity in monthly:
            total = monthly[f.entity]
            if values_match(total, f.value, rel=0.01):
                f.attributes["reconciled_with_monthly_costs"] = round(total, 2)
            else:
                issues.append(
                    DataQualityIssue(
                        severity="warning",
                        message=f"{f.entity}: actual cost to date ({_money(f.value)}) does not equal the sum of "
                        f"monthly project costs ({_money(total)}). The register figure is used.",
                        fact_ids=[f.id],
                    )
                )

    # 5. Missing reporting periods in company series.
    series_periods: dict[str, set[str]] = defaultdict(set)
    for f in facts:
        if f.entity_type == "company" and f.period and f.metric != "expense_category" and not f.superseded:
            series_periods[f.metric].add(f.period)
    for metric, periods in series_periods.items():
        ordered = sorted(periods)
        if len(ordered) >= 2:
            span = _months_between(ordered[0], ordered[-1]) + 1
            if span > len(ordered):
                issues.append(
                    DataQualityIssue(
                        severity="warning",
                        message=f"{metric.replace('_', ' ').title()}: {span - len(ordered)} month(s) missing between "
                        f"{ordered[0]} and {ordered[-1]}.",
                    )
                )

    all_periods = [f.period for f in facts if f.period and f.entity_type in ("company", "project") and not f.superseded]
    as_of = max(all_periods) if all_periods else None

    projects = sorted({f.entity for f in facts if f.entity_type == "project" and not f.entity.startswith("__")})
    return ExtractionResult(
        company_name=meta.get("company_name"),
        currency=meta.get("currency"),
        currency_evidence=meta.get("currency_evidence", []),
        facts=facts,
        conflicts=conflicts,
        duplicates=duplicates,
        issues=issues,
        projects=projects,
        as_of_period=as_of,
    )


def _label(f: Fact) -> str:
    who = "Company" if f.entity == "__company__" else f.entity
    metric = f.metric.replace("_", " ")
    if f.dimension:
        metric = f"{metric} ({f.dimension})"
    return f"{who} {metric}" + (f" for {f.period}" if f.period else "")


_CURRENCY = {"code": "USD"}


def _money(v: Optional[float]) -> str:
    return money(v, _CURRENCY["code"])
