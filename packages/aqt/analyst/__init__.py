"""AI Analyst: an LLM that reads the lab's results and *proposes* hypotheses.

It never decides or sends orders, never sees broker credentials and never writes risk settings:
this package must not import ``aqt.brokers``, ``aqt.risk`` or the streaming engine (enforced by
``tests/test_analyst.py``). Its proposals are plain DSL rules that the Research Lab examines with
the same statistics as every other hypothesis, counted in the same global FDR.
"""
