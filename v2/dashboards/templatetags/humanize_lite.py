from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def money(value):
    """12345.5 -> '12,345.50' (Western digits, as on receipts)."""
    try:
        return f"{Decimal(value):,.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return value


@register.filter
def plain(value):
    """10.00 -> '10', 2.50 -> '2.5'."""
    try:
        return format(Decimal(value or 0).normalize(), "f")
    except (InvalidOperation, TypeError, ValueError):
        return value
