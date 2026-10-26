"""SQL fragments of an entry's own state (spec §6, I20), over a `ledger_entry` aliased `le`.

Used by the unit CTE (`core/resolution/confirmed.py`). `STANDING` needs the bind `:standing` (the
standing passes).
"""

# a type; for a flow a category (spec §3.4); for a transfer its pair (I22)
COMPLETE = """(le.type IS NOT NULL
                            AND (le.type <> 'flow' OR le.category_id IS NOT NULL)
                            AND (le.type <> 'transfer' OR le.counterpart_entry_id IS NOT NULL))"""

# no derivation key whose pass is not standing (`history`, `llm`, or a key without a pass)
STANDING = """NOT EXISTS (
                               SELECT 1 FROM jsonb_each(le.derivation) AS d
                                WHERE COALESCE(d.value ->> 'pass', '') <> ALL (:standing))"""
