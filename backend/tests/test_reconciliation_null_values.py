"""Regressions for Ollama narrative observations alongside numeric facts."""
from domain import Fact, SourceRef
from documents.reconciliation import reconcile


def f(value, text=None, metric='budget_approved', file='sample.xlsx', method='table'):
    return Fact(entity_type='project', entity='Project Alpha', metric=metric,
                value=value, text_value=text, source=SourceRef(file_id=file,file_name=file),
                extraction_method=method)


def test_numeric_and_text_observation_same_metric_does_not_crash():
    ex = reconcile([f(500000), f(None,'The budget is under review.',file='notes.txt',method='agent')], [], {'currency':'USD'})
    assert len(ex.facts) == 2
    assert not ex.conflicts
    assert all(not fact.superseded for fact in ex.facts)


def test_two_different_text_observations_keep_provenance_without_numeric_conflict():
    ex = reconcile([f(None,'Approval pending',file='one.txt',method='agent'),
                    f(None,'Approved in writing',file='two.txt',method='agent')], [], {'currency':'USD'})
    assert not ex.conflicts
    assert all(not fact.superseded for fact in ex.facts)
    assert any('differing text' in issue.message for issue in ex.issues)


def test_same_numeric_amount_deduplicates_and_conflicting_numeric_budget_still_detected():
    ex = reconcile([f(500000),f(500000,file='other.xlsx'),f(550000,file='board.pdf')], [], {'currency':'USD'})
    assert len(ex.duplicates) == 1
    assert ex.conflicts
    assert all(value is not None for conflict in ex.conflicts for value in conflict.values)


def test_multiple_text_nulls_do_not_crash_or_create_money_conflict():
    ex = reconcile([f(None, 'pending',file='one.txt'),f(None,'confirmed',file='two.txt'),
                    f(None, 'confirmed',file='three.txt')], [], {'currency':'USD'})
    assert not ex.conflicts
    assert len(ex.facts)==3
