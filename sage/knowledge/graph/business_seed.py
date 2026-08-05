"""Business Intelligence seed ontology text and lexicon (v0.3.1)."""

from __future__ import annotations

from sage.knowledge.graph.models import EntityType

BUSINESS_SEED_TYPES: dict[str, EntityType] = {
    "company": EntityType.COMPANY,
    "customer": EntityType.CUSTOMER,
    "customers": EntityType.CUSTOMER,
    "supplier": EntityType.SUPPLIER,
    "product": EntityType.PRODUCT,
    "service": EntityType.SERVICE,
    "employee": EntityType.EMPLOYEE,
    "department": EntityType.DEPARTMENT,
    "market": EntityType.MARKET,
    "competitor": EntityType.COMPETITOR,
    "campaign": EntityType.CAMPAIGN,
    "revenue": EntityType.REVENUE,
    "expense": EntityType.EXPENSE,
    "expenses": EntityType.EXPENSE,
    "asset": EntityType.ASSET,
    "liability": EntityType.LIABILITY,
    "kpi": EntityType.KPI,
    "project": EntityType.PROJECT,
    "goal": EntityType.GOAL,
    "risk": EntityType.RISK,
    "opportunity": EntityType.OPPORTUNITY,
    "brand": EntityType.CONCEPT,
    "pipeline": EntityType.CONCEPT,
    "inventory": EntityType.RESOURCE,
    "margin": EntityType.METRIC,
    "cash flow": EntityType.METRIC,
    "cashflow": EntityType.METRIC,
    "roi": EntityType.METRIC,
    "break-even": EntityType.METRIC,
    "breakeven": EntityType.METRIC,
}

# Avoid tautologies like "Risk is a risk" (self-edges). Prefer distinct type nouns.
BUSINESS_SEED_ONTOLOGY = """
Company is an organization. Customer is a person. Supplier is an organization.
Product is a concept. Service is a concept. Employee is a person.
Department is a concept. Market is a concept. Competitor is an organization.
Campaign is a concept. Revenue is a metric. Expense is a metric.
Asset is a concept. Liability is a concept. KPI is a metric.
Project is a concept. Goal is a concept. Business Risk is a concept. Opportunity is a concept.
Company employs Employee. Company sells to Customer. Company buys from Supplier.
Company competes with Competitor. Campaign targets Customer. Campaign generates Revenue.
Product generates Revenue. Company incurs Expense. Department is part of Company.
Project belongs to Company. KPI measures Goal. Business Risk affects Project.
Opportunity relates to Market. Budget is a metric. Profit is a metric.
"""
