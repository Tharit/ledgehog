"""A failed run says whether running it again can help: `import_run.retryable`.

The error class of the importer taxonomy decides it (architecture §5.5); NULL unless the run
failed. Runs that failed before are backfilled from the class prefix of `error_text`
(`<Class>: message`): the retryable taxonomy classes and a run interrupted by a restart are
true, every other failed run is false.

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_BACKFILL = """
UPDATE import_run
   SET retryable = (
       error_text ~ '^(AuthRejected|ChallengeExpired|ChallengeAbandoned|SourceUnavailable|interrupted):'
   )
 WHERE status = 'failed'
"""


def upgrade() -> None:
    op.execute("ALTER TABLE import_run ADD COLUMN retryable boolean")
    op.execute(_BACKFILL)


def downgrade() -> None:
    op.execute("ALTER TABLE import_run DROP COLUMN retryable")
