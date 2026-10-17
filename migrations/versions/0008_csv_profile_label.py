"""A CSV profile has no name of its own: strip `label` from csv instances' settings (step 10).

`source_format` of a CSV row is `csv:` and the instance's label at the time of the run
(`plugins/importers/csv.md` §3), so the profile no longer carries a `label` key, and the importer rejects
unknown keys. Instances stored before then may still hold one. Data only, no schema change; idempotent
(an instance without the key is left alone). The key is not restored on downgrade.

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_STRIP = """
UPDATE importer_instance
   SET settings = settings - 'label'
 WHERE importer = 'csv' AND jsonb_exists(settings, 'label')
"""


def upgrade() -> None:
    op.execute(_STRIP)


def downgrade() -> None:
    pass
