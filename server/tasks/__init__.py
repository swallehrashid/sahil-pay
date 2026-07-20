"""
SahilPay — tasks/
==================
Celery tasks for work routes dispatch via .delay() rather than running
inline: bulk invoice generation, bulk reminders, backup generation, and
bank-statement parsing. Every module here imports `celery` from
celery_app.py at module level so @celery.task can decorate its functions.
"""
