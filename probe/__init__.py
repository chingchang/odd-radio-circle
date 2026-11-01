"""Send labelled items to Muse Wonder with a fixed prompt and score the answers (docs/probes.md).

``guard`` adds this project's identifiers to the landers leak guard, ``harness`` runs a probe through the landers
Ledger and writes every request, answer, label and cost under ``out/``, ``score`` gives accuracy, the 95 percent Wilson
interval and the confusion table, and ``promptcheck`` checks the prompts in code.
"""
