"""Approval limits for project budgets are PLACEHOLDERS until the board sets them."""
from decimal import Decimal

from core.seeding import policy

POLICIES = [
    ("projects.budget", Decimal(0), ["finance_manager"]),
    ("projects.budget", Decimal(250000), ["finance_manager", "executive"]),
]


def run(stdout):
    for doc_type, amount, roles in POLICIES:
        policy(doc_type, amount, roles)
