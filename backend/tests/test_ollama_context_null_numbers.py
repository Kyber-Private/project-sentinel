"""Live Ollama regression: extracted text observations can have no numeric value.

These are valid documented observations, but must not be formatted with :,.0f or :g.
"""
from domain import ExtractionResult, Fact, SourceRef
from finance.types import CompanyForecast, MetricForecast, ProjectForecast, SeriesPoint
from agents.context import company_context, project_context


def _fact(metric, value=None, period='2026-10'):
    return Fact(entity_type='company', entity='Nova Industries', metric=metric,
                period=period, dimension='Payroll', value=value,
                text_value='Unconfirmed observation', extraction_method='agent',
                source=SourceRef(file_id='n', file_name='notes.txt'))


def _ex(facts):
    # Construct only declared ExtractionResult fields to avoid assuming another schema.
    return ExtractionResult(company_name='Nova Industries', currency='USD',
                            as_of_period='2026-10', facts=facts)


def test_emily_context_does_not_format_non_numeric_opex_observation():
    ex = _ex([_fact('expense_category'), _fact('expense_category', 1200),
              _fact('supplier_price_change_pct'), _fact('supplier_price_change_pct', 5)])
    mf = MetricForecast(id='company.revenue',metric='revenue',label='Revenue',horizon_months=6,
                        history=[SeriesPoint(period='2026-10',value=1000)])
    ctx = company_context(ex, CompanyForecast(horizon_months=6, metrics=[mf]), [], [])
    assert len(ctx['expense_categories']['Payroll']) == 1
    assert len(ctx['supplier_price_changes']) == 1
    assert '5%' in ctx['supplier_price_changes'][0]


def test_emily_context_keeps_numeric_opex_observations():
    ex = _ex([_fact('expense_category', 1200)])
    ctx = company_context(ex, CompanyForecast(horizon_months=6), [], [])
    assert '1,200' in ctx['expense_categories']['Payroll'][0]

def test_real_nova_documents_survive_text_only_agent_facts_through_agent_contexts(extraction):
    """Real spreadsheet/PDF-derived forecasts, with text-only Ollama facts added."""
    from agents.orchestrator import compute_core
    ex = extraction.model_copy(deep=True)
    ex.facts.extend([_fact('expense_category'), _fact('supplier_price_change_pct')])
    projects, cf, company_drvs, project_drvs = compute_core(ex, {}, 6)
    assert len(projects) >= 2
    emily = company_context(ex, cf, company_drvs, [])
    sebas = project_context(ex, projects, project_drvs, [])
    assert emily['forecasts']
    assert sebas['projects']
