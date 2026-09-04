"""Rendering of prices and alert messages.

``format_price`` is a byte-exact port, including the JavaScript exponent spelling
(``1.000e-5``, not Python's ``1.000e-05``) and the absence of a guard for prices at or
below zero. The alert line keeps the legacy shape, arrow included and minus sign omitted
on downward moves (PLAN.md §6.10).

Any change here shows up in every notification, so this module is covered by tests that
compare against captured legacy output.
"""
