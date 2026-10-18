from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="finance_index"),
    path("trial-balance/", views.trial_balance, name="finance_trial_balance"),
    path("ledger/", views.ledger, name="finance_ledger"),
    path("income-statement/", views.income_statement, name="finance_income_statement"),
    path("balance-sheet/", views.balance_sheet, name="finance_balance_sheet"),
    path("funds/", views.funds, name="finance_funds"),
]
