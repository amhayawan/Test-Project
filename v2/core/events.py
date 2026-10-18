"""Business events shared between modules.

A module announces that something happened (a donation was received, aid was delivered, payroll
was approved...). Other modules listen: finance turns events into journal entries, so no module
has to import finance and finance problems never block the work of another department.

    emit("aid.delivered", aid)

Listeners: business_event.connect(handler)  →  handler(sender, event, document, **kwargs)
"""
from django.dispatch import Signal

business_event = Signal()


def emit(event, document, **extra):
    business_event.send(sender=type(document), event=event, document=document, **extra)
