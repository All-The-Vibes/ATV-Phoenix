# Bug: round_money loses cents to float error

`round_money(amount)` should round a float dollar amount to 2 decimal places, returning a value equal
to the correct cents. It uses naive `round(amount, 2)`, which produces float-representation errors on
common values (e.g. `round(2.675, 2)` → `2.67`, not `2.68`), so monetary rounding is wrong.

Fix `solution.py` so rounding is correct to the nearest cent (round half up) for values like 2.675 and
0.125. Return a float equal to the expected cents value. Keep the `round_money` signature.
