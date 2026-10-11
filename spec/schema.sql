-- =====================================================================
-- Household ledger — v1 baseline schema (PostgreSQL 14+)
--
-- Conventions
--   * Money is bigint in MINOR UNITS of its own currency (cents for EUR,
--     none for JPY; see `currency`), signed in ledger convention: positive
--     increases the account's balance. Never float. Sums are exact and the
--     split invariant is checkable without rounding tolerance. Exchange
--     rates are exact numerics, not money. See spec §3.3, §3.8.
--   * Enumerated values are text + CHECK, not PG enums: adding/removing a
--     value is a plain constraint change instead of ALTER TYPE surgery.
--   * Dates the source reports are `date`. Who and when are recorded only on
--     event records (import runs); mutable state carries neither. Spec §3.2.
--   * There is ONE ledger per deployment. Users exist for login only;
--     nothing is scoped by user. See spec §3.2.
--   * Join tables are named parent_a_parent_b (ledger_entry_tag).
--     `account_source` is the deliberate
--     exception: it is a named concept carrying its own fields, not a
--     mechanical join.
--   * Invariants are cited by their stable spec ids (spec §2.1, I<n>).
-- =====================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------------------------------------------------------------------
-- 1. Identity (session only — the ledger itself is shared)
-- ---------------------------------------------------------------------

-- `user` is reserved in PostgreSQL, hence the prefix.
CREATE TABLE app_user (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    login         text        NOT NULL UNIQUE,
    pw_hash       text        NOT NULL,
    display_name  text        NOT NULL,
    disabled      boolean     NOT NULL DEFAULT false
);

-- A login session. The cookie holds the opaque id, not a token that carries
-- claims, so revoking a session is deleting its row. `method` is the seam for
-- adding OIDC later: a new method, not a rewrite. A session is an event
-- record, so it may carry when (spec §3.2).
CREATE TABLE session (
    id          text        PRIMARY KEY,
    user_id     bigint      NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    method      text        NOT NULL CHECK (method IN ('password','oidc')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    CONSTRAINT ck_session_expiry CHECK (expires_at > created_at)
);

CREATE INDEX ix_session_user ON session (user_id);

-- ---------------------------------------------------------------------
-- 2. Reference data: currencies and the ledger's base currency
-- ---------------------------------------------------------------------

-- ISO code and minor-unit exponent. Every amount in the schema is an
-- integer in the minor units of its own currency. Spec §3.8.
CREATE TABLE currency (
    code        char(3)  PRIMARY KEY CHECK (code ~ '^[A-Z]{3}$'),
    minor_units smallint NOT NULL CHECK (minor_units BETWEEN 0 AND 4)
);

-- seeded by the initial migration with the active ISO 4217 currencies (precious
-- metals and test codes left out), so no currency ever needs a migration of its own
INSERT INTO currency (code, minor_units) VALUES
    ('AED', 2), ('AFN', 2), ('ALL', 2), ('AMD', 2), ('ANG', 2),
    ('AOA', 2), ('ARS', 2), ('AUD', 2), ('AWG', 2), ('AZN', 2),
    ('BAM', 2), ('BBD', 2), ('BDT', 2), ('BGN', 2), ('BHD', 3),
    ('BIF', 0), ('BMD', 2), ('BND', 2), ('BOB', 2), ('BRL', 2),
    ('BSD', 2), ('BTN', 2), ('BWP', 2), ('BYN', 2), ('BZD', 2),
    ('CAD', 2), ('CDF', 2), ('CHF', 2), ('CLF', 4), ('CLP', 0),
    ('CNY', 2), ('COP', 2), ('CRC', 2), ('CUP', 2), ('CVE', 2),
    ('CZK', 2), ('DJF', 0), ('DKK', 2), ('DOP', 2), ('DZD', 2),
    ('EGP', 2), ('ERN', 2), ('ETB', 2), ('EUR', 2), ('FJD', 2),
    ('FKP', 2), ('GBP', 2), ('GEL', 2), ('GHS', 2), ('GIP', 2),
    ('GMD', 2), ('GNF', 0), ('GTQ', 2), ('GYD', 2), ('HKD', 2),
    ('HNL', 2), ('HTG', 2), ('HUF', 2), ('IDR', 2), ('ILS', 2),
    ('INR', 2), ('IQD', 3), ('IRR', 2), ('ISK', 0), ('JMD', 2),
    ('JOD', 3), ('JPY', 0), ('KES', 2), ('KGS', 2), ('KHR', 2),
    ('KMF', 0), ('KPW', 2), ('KRW', 0), ('KWD', 3), ('KYD', 2),
    ('KZT', 2), ('LAK', 2), ('LBP', 2), ('LKR', 2), ('LRD', 2),
    ('LSL', 2), ('LYD', 3), ('MAD', 2), ('MDL', 2), ('MGA', 2),
    ('MKD', 2), ('MMK', 2), ('MNT', 2), ('MOP', 2), ('MRU', 2),
    ('MUR', 2), ('MVR', 2), ('MWK', 2), ('MXN', 2), ('MYR', 2),
    ('MZN', 2), ('NAD', 2), ('NGN', 2), ('NIO', 2), ('NOK', 2),
    ('NPR', 2), ('NZD', 2), ('OMR', 3), ('PAB', 2), ('PEN', 2),
    ('PGK', 2), ('PHP', 2), ('PKR', 2), ('PLN', 2), ('PYG', 0),
    ('QAR', 2), ('RON', 2), ('RSD', 2), ('RUB', 2), ('RWF', 0),
    ('SAR', 2), ('SBD', 2), ('SCR', 2), ('SDG', 2), ('SEK', 2),
    ('SGD', 2), ('SHP', 2), ('SLE', 2), ('SOS', 2), ('SRD', 2),
    ('SSP', 2), ('STN', 2), ('SVC', 2), ('SYP', 2), ('SZL', 2),
    ('THB', 2), ('TJS', 2), ('TMT', 2), ('TND', 3), ('TOP', 2),
    ('TRY', 2), ('TTD', 2), ('TWD', 2), ('TZS', 2), ('UAH', 2),
    ('UGX', 0), ('USD', 2), ('UYI', 0), ('UYU', 2), ('UYW', 4),
    ('UZS', 2), ('VES', 2), ('VND', 0), ('VUV', 0), ('WST', 2),
    ('XAF', 0), ('XCD', 2), ('XOF', 0), ('XPF', 0), ('YER', 2),
    ('ZAR', 2), ('ZMW', 2), ('ZWG', 2);

-- Exactly one row, written when the ledger is first started: the base
-- currency every report is expressed in. It is not a property of any entry; no
-- entry stores a base value. It never changes, because fx_rate is stored
-- against it (trigger 8.7), and the application refuses to start when its
-- configured base currency differs from this row. Every other ledger-wide
-- setting — the maximum rate age (spec §3.8), the matching window (§5.7), the
-- document window (§5.8) — is deployment configuration, not data. The maximum
-- rate age reaches SQL as the connection setting ledger.max_rate_age, set by
-- the application on every connection (like ledger.settling, trigger 8.6).
-- Spec §3.8.
CREATE TABLE ledger_setting (
    singleton           boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    base_currency       char(3)  NOT NULL REFERENCES currency(code)
);

-- ---------------------------------------------------------------------
-- 3. Dimensions
-- ---------------------------------------------------------------------

-- Every account holds ONE currency, permanently. A multi-currency provider
-- (PayPal, Wise) is one account per currency pocket; a conversion between
-- pockets is a cross-currency transfer. An account is SYNCED while it is open
-- and has at least one account_source row, unsynced otherwise
-- (v_account_synced); that decides what is fetched, whether a transfer leg
-- pointing at it may wait for an import (spec §5.7) and what its data age is
-- read from (spec §3.11), and where rows may be made by hand: user-authored
-- source transactions, counter-legs included, only on unsynced accounts
-- (I40, trg_user_source_unsynced). Depots and assets are INVESTMENT accounts: their later balance
-- records derive valuations, any other account's reconciliations; whether an
-- account is one is fixed at creation (trigger 8.5, I38). Spec §3.3, §3.8, I5.
CREATE TABLE account (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name           text NOT NULL,
    kind           text NOT NULL CHECK (kind IN (
                       'checking','savings','card','cash',
                       'paypal','depot','loan','asset')),
    currency       char(3) NOT NULL REFERENCES currency(code),
    -- opaque identifier at the remote side: IBAN, PayPal account and pocket,
    -- whatever the importer uses. STORED CANONICALISED (spec §5.2), by the
    -- same function that canonicalises counterparty_ref, so the unique index
    -- below holds for what pass 0 compares. Never
    -- interpreted: pass 0 of resolution matches counterparty_ref against it
    -- (spec §5.9).
    external_ref   text,
    -- No synced_through column: how far the data is complete is DERIVED from
    -- the coverage of the account's non-reverted runs (v_account_coverage,
    -- spec §5.4).
    -- May lie in the future. Closing changes the account's state at once (it
    -- is unsynced, v_account_synced); the date only matters where an entry's
    -- date is judged, by rules and history (spec §3.3, §5.9).
    -- A closed account is unsynced and no longer offered by discovery;
    -- pickers list it after the open accounts. No balance is required to
    -- close, and entries dated after it are still accepted. Its links stay,
    -- so clearing the column reopens it. Spec §3.3.
    closed_on      date,
    sort_order     integer NOT NULL DEFAULT 0,
    note           text
);

CREATE UNIQUE INDEX ux_account_external_ref
    ON account (external_ref) WHERE external_ref IS NOT NULL;
-- supports the composite FKs from source_transaction and ledger_entry: a
-- row's currency is its account's currency, enforced rather than intended.
ALTER TABLE account ADD CONSTRAINT uq_account_id_currency UNIQUE (id, currency);

-- Categories are orthogonal to payees. Each has a KIND — which side of the
-- income statement its flows fall on — fixed at creation, and a child has its
-- parent's kind, enforced by the composite FK below. The kind does NOT
-- constrain the sign: a refund is a positive flow in an expense category. The
-- tree's two roots, Income and Expense, are the kinds themselves, not rows: a
-- top-level category has parent_id NULL. There is no archived state; a
-- category without entries, rules or children can be deleted (the RESTRICT
-- below enforces the last), and one in use is merged
-- into another OF THE SAME KIND like a payee — entries and rules repointed,
-- children moved under the target (which the composite FK below requires to
-- share its kind), then deleted. A child whose name the target's children
-- already use is merged into that child the same way, recursively, which is
-- what keeps ux_category_name satisfied: those collisions are merged first,
-- deepest first, the remaining children moved after, the merged category
-- deleted last (the index is checked row by row). Merging into one's own
-- descendant is refused. Repointed values keep their keys. The tree has no
-- cycles (trigger 8.4b). Spec §3.5, I9.
CREATE TABLE category (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       text NOT NULL,
    kind       text NOT NULL CHECK (kind IN ('income','expense')),
    parent_id  bigint,
    sort_order integer NOT NULL DEFAULT 0,
    CONSTRAINT uq_category_id_kind UNIQUE (id, kind),
    CHECK (parent_id IS NULL OR parent_id <> id)
);

ALTER TABLE category ADD CONSTRAINT fk_category_parent_same_kind
    FOREIGN KEY (parent_id, kind) REFERENCES category (id, kind)
    ON DELETE RESTRICT;

-- names are unique among siblings; the kind keeps the two roots apart, so
-- "Other" may exist under both Income and Expense (a child's kind is its
-- parent's, so below the top level it changes nothing)
CREATE UNIQUE INDEX ux_category_name
    ON category (kind, COALESCE(parent_id, 0), lower(name));

-- A payee is a CURATED reporting dimension: it exists because someone wants
-- to report on that merchant, not because a counterparty appeared. Most
-- counterparties never become payees. Spec §3.6.
--
-- Merging two payees repoints entries and moves rules, then deletes the
-- loser outright. ON DELETE RESTRICT below makes the FK enforce that order.
-- A payee no entry references can be deleted directly, its rules with it.
CREATE TABLE payee (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name              text NOT NULL,
    -- the external_document.provider whose documents describe this payee's
    -- charges ('paypal', 'amazon'). Drives document matching and waiting for
    -- a document (spec §5.8).
    document_provider text,
    note              text
);

CREATE UNIQUE INDEX ux_payee_name ON payee (lower(name));

-- Rules are pass 1 (spec §5.9) and are HAND-WRITTEN ONLY: nothing creates
-- them automatically. A rule declares intent that overrides observation;
-- recurring classification is otherwise handled by pass 2 reading history,
-- not by materialising a rule per correction. Rule values are STANDING: a
-- unit decided entirely by pass 0 and rules is confirmed without review.
--
-- ONE table: a rule SETS one thing — a counter-account (which types the
-- entry a transfer), a payee or a category — named by `sets`, with exactly
-- that target column filled, so a key's {rule_id} always names one row. The
-- UI groups rules by what they set. Rules are evaluated by what they set:
-- counter-account rules, then payee rules, then category rules (a category
-- rule may read the payee a payee rule set); within each, lower priority
-- first, the id breaking a tie, so resolution stays deterministic. The type
-- follows the first rule in that order that matches. Rules are few and
-- resolution reads them whole, so there is no lookup index.
--
-- CONDITIONS, all of which must hold; NULL means no condition on that field,
-- and at least one is required. The payee condition is for category rules
-- only, since it reads the output of payee rules.
--
-- A counter-account rule obeys the currency rule (spec §5.7): a rule whose
-- account is in the wrong currency for an entry does not match it, nor does a
-- rule whose account is not open on the booking date (spec §3.3, §5.9) — a
-- card payoff from the issuer's collection account, told apart from another
-- card's by its mandate, or a withdrawal to the cash account.
--
-- A category a rule references cannot be deleted (spec §3.5); a merge
-- repoints its rules. Deleting a payee deletes the rules that set it or name
-- it as a condition; a merge repoints both (spec §3.6).
CREATE TABLE rule (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sets               text NOT NULL CHECK (sets IN ('counter_account','payee','category')),
    -- the value it sets: exactly the column `sets` names
    counter_account_id bigint REFERENCES account(id)  ON DELETE RESTRICT,
    payee_id           bigint REFERENCES payee(id)    ON DELETE CASCADE,
    category_id        bigint REFERENCES category(id) ON DELETE RESTRICT,
    -- conditions
    condition_payee_id bigint REFERENCES payee(id)    ON DELETE CASCADE,
    counterparty_ref   text,
    mandate_ref        text,
    name_exact         text,
    name_prefix        text,
    purpose_regex      text,
    booking_text       text,
    priority           integer NOT NULL DEFAULT 100,
    CONSTRAINT ck_rule_sets CHECK (
            (sets = 'counter_account') = (counter_account_id IS NOT NULL)
        AND (sets = 'payee')           = (payee_id IS NOT NULL)
        AND (sets = 'category')        = (category_id IS NOT NULL)),
    CONSTRAINT ck_rule_payee_condition
        CHECK (condition_payee_id IS NULL OR sets = 'category'),
    CONSTRAINT ck_rule_condition
        CHECK (num_nonnulls(condition_payee_id, counterparty_ref, mandate_ref,
                            name_exact, name_prefix, purpose_regex,
                            booking_text) > 0)
);

-- Spans (a holiday, a project) are DERIVED from min/max booked_on over the
-- tagged entries, not stored. Spec §3.7.
CREATE TABLE tag (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       text NOT NULL,
    color      text
);

CREATE UNIQUE INDEX ux_tag_name ON tag (lower(name));

-- ---------------------------------------------------------------------
-- 4. Importer instances, account links and import runs
-- ---------------------------------------------------------------------

-- One row per CREDENTIAL, not per account: a single FinTS login reaches
-- several accounts, and a shared account is reachable from several logins.
-- Document and rate sources use this same table. No PIN column, by design —
-- the PIN is typed per session.
CREATE TABLE importer_instance (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    importer     text    NOT NULL,        -- 'fints' | 'paypal' | 'amazon' | ...
    label        text    NOT NULL,        -- 'Sparkasse — Anna'
    -- the kinds this instance produces. After one authentication per sync it
    -- is asked for each linked account, and for each accountless kind, each
    -- logged as its own run; ingest routes by the run's kind without loading
    -- importer code (spec §5.1).
    emits        text[]  NOT NULL DEFAULT ARRAY['transactions']::text[]
                 CHECK (cardinality(emits) > 0
                        AND emits <@ ARRAY['transactions','documents','rates']::text[]),
    -- WHO MAY AUTHENTICATE this credential — never who may see the resulting
    -- data. Every source transaction lands in the one shared ledger regardless
    -- (spec §5.11). 'shared' is for credentials either spouse legitimately
    -- uses, such as a minor child's account both parents manage, and always
    -- for instances holding no credential at all (CSV profiles, public rate
    -- sources).
    owner_id     bigint REFERENCES app_user(id) ON DELETE RESTRICT,
    access       text    NOT NULL DEFAULT 'owner'
                 CHECK (access IN ('owner','shared')),
    -- the one thing worth constraining: stops two instances pointing at the
    -- same remote login and importing it twice. Leave NULL for a second
    -- instance against the same login (the index is partial).
    external_id  text,
    -- what the user configured: FinTS URL, BLZ, login, TAN method/medium,
    -- CSV profile and column mapping (including an optional running-balance
    -- column and the sign-inversion settings for amounts and balance).
    -- Validated in app code against a per-importer schema. The ledger side has
    -- no opinion on its contents.
    settings     jsonb   NOT NULL DEFAULT '{}'::jsonb,
    -- what the importer wrote back and owns: system_id, TAN medium, and a
    -- session token ONLY where that token is verifiably read-only and cannot
    -- authorise a payment (spec §7). Coverage is not here: it is recorded per
    -- run (import_run.covered_through). PINs, passwords and TANs are never
    -- stored here. Split from settings so "reset this connection" can clear one and
    -- keep the other. CREDENTIAL state only. When the credential last ran is
    -- read from its runs (v_importer_last_run).
    state        jsonb   NOT NULL DEFAULT '{}'::jsonb,
    -- a disabled instance is not run by "sync everything" (spec §5.11)
    disabled     boolean NOT NULL DEFAULT false,

    CONSTRAINT ck_owner_iff_owned
        CHECK ((access = 'owner') = (owner_id IS NOT NULL))
);

CREATE UNIQUE INDEX ux_importer_instance_ext
    ON importer_instance (importer, external_id) WHERE external_id IS NOT NULL;

-- Many-to-many: which credentials can fetch which accounts. A shared checking
-- account has one row per spouse's login. There is deliberately no "primary",
-- no "enabled" and no coverage range: all credentials are equal, an account
-- you do not track simply has no row, coverage is recorded per run, and
-- duplicates between sources are settled row by row at import (spec §5.2,
-- §5.4).
-- Instances emitting only documents or rates have no rows here.
CREATE TABLE account_source (
    account_id           bigint NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    importer_instance_id bigint NOT NULL REFERENCES importer_instance(id) ON DELETE CASCADE,
    external_ref         text   NOT NULL,   -- this account's id at that login; for a file importer, which has no login, acct-<account id>, read by nothing
    -- No resume cursor: where a fetch starts is derived when the run starts —
    -- from synced_through minus the overlap, or, without coverage, after the
    -- account's latest entry (spec §5.4).
    PRIMARY KEY (account_id, importer_instance_id)
);

CREATE UNIQUE INDEX ux_account_source_ref
    ON account_source (importer_instance_id, external_ref);

-- One run per (instance, ACCOUNT, sync) for transactions — the orchestrator
-- asks the importer for one account at a time — and one per (instance, kind,
-- sync) for documents and rates. Runs are never deleted — a reverted run is
-- kept and marked — because they are the provenance and the arrival time of
-- every source transaction. Runs are the event records that carry who and
-- when. A run succeeds as a whole or fails, and a failed run wrote nothing
-- (spec §5.1): ingest sets it 'ok', with finished_at, its coverage and stats,
-- in the transaction that writes its rows, under the account's lock —
-- finished_at from clock_timestamp() read after the lock is taken, since now()
-- is the transaction's start — so finished_at orders an account's runs as ingest wrote them. A run left
-- 'running' by a crash is marked 'failed' at start. Only a transaction run is
-- reverted, and only while it is the latest successful, non-reverted run on
-- its account by finished_at (spec §5.6, I30); document and rate runs never
-- are. Checked by the revert operation.
CREATE TABLE import_run (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    importer             text NOT NULL,     -- denormalised for convenience
    importer_instance_id bigint REFERENCES importer_instance(id) ON DELETE SET NULL,
    emits                text NOT NULL CHECK (emits IN ('transactions','documents','rates')),
    -- the one account a transaction run fetched; NULL for accountless kinds
    account_id           bigint REFERENCES account(id) ON DELETE RESTRICT,
    started_at           timestamptz NOT NULL DEFAULT now(),
    finished_at          timestamptz,
    status               text NOT NULL CHECK (status IN
                             ('running','ok','failed','reverted')),
    error_text           text,
    -- the date the run covered THROUGH, as the importer reported it, by the
    -- rules of spec §5.1: a fetch through the day before the fetch, whether or
    -- not it returned rows; a file through its period end or last booking,
    -- never through its export day; a document run through the provider's
    -- completeness date (spec §5.1). NULL for a run that did not succeed.
    -- synced_through and document coverage are derived from it
    -- (v_account_coverage, v_document_coverage). covered_from is where the
    -- run's data starts, for the import log only: nothing in the domain
    -- reads it.
    covered_from         date,
    covered_through      date,
    -- ingest-reported facts about the run, for the run summary: counts (inserted,
    -- skipped by identity, inserted as duplicates), the importer's own counts
    -- (`importer`: zero bookings it dropped, a statement payment it did not emit),
    -- the balance record the run wrote, and the unexplained difference before and
    -- after it, with the reported records since the sum was last zero. A breach
    -- of the importer's contract is not a statistic: the run fails (spec §5.1).
    -- Reported balances themselves are balance_record rows. Spec §5.2, §5.3, §5.10.
    stats                jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_by           bigint REFERENCES app_user(id) ON DELETE SET NULL,
    reverted_at          timestamptz,
    reverted_by          bigint REFERENCES app_user(id) ON DELETE SET NULL,
    CONSTRAINT ck_reverted CHECK ((status = 'reverted') = (reverted_at IS NOT NULL)),
    CONSTRAINT ck_reverted_transactions
        CHECK (status <> 'reverted' OR emits = 'transactions'),
    CONSTRAINT ck_run_account_iff_transactions
        CHECK ((emits = 'transactions') = (account_id IS NOT NULL)),
    CONSTRAINT ck_run_coverage
        CHECK (covered_from IS NULL OR covered_through IS NULL
               OR covered_from <= covered_through),
    -- only a run that succeeded has coverage; a finished run says when
    CONSTRAINT ck_run_coverage_succeeded
        CHECK (status IN ('ok','reverted')
               OR (covered_from IS NULL AND covered_through IS NULL)),
    -- every successful transaction or document run says how far it covers
    -- (spec §5.1)
    CONSTRAINT ck_run_coverage_reported
        CHECK (status NOT IN ('ok','reverted') OR emits = 'rates'
               OR covered_through IS NOT NULL),
    CONSTRAINT ck_run_finished
        CHECK (status = 'running' OR finished_at IS NOT NULL),
    -- supports the composite FKs from source_transaction and balance_record:
    -- a row belongs to the account of its run
    CONSTRAINT uq_import_run_id_account UNIQUE (id, account_id)
);

CREATE INDEX ix_import_run_recent ON import_run (started_at DESC);
CREATE INDEX ix_import_run_account ON import_run (account_id, finished_at DESC)
    WHERE account_id IS NOT NULL;

-- Reference exchange rates: units of `currency` per 1 unit of the base
-- currency (the ECB convention), one per currency per day. The base currency
-- itself has no rows. Delivered by an importer emitting 'rates'. Lookup is
-- the latest rate on or before a date and no older than the maximum rate age;
-- no usable rate means unvalued, never zero. Spec §3.8.
CREATE TABLE fx_rate (
    currency      char(3) NOT NULL REFERENCES currency(code),
    rate_date     date    NOT NULL,
    per_base      numeric(20,10) NOT NULL CHECK (per_base > 0),
    import_run_id bigint REFERENCES import_run(id) ON DELETE RESTRICT,
    PRIMARY KEY (currency, rate_date)
);

-- A stated balance: "account X held B at the end of D", in the account's
-- currency and ledger sign convention. A fact about a balance, never part of
-- a sum. Every record RECONCILES: each record owns at most one derived entry
-- explaining its interval — the anchor's is the opening, a later record's a
-- valuation (investment account) or a reconciliation. The kind only says where the
-- number came from:
--   reported = an importer's booked closing balance of the last day before
--              the fetch, at most one per run, on the run's account, never
--              dated after the run's coverage (spec §5.1, I36)
--   manual   = entered by a user ("set balance"), on any account
-- Any record may be deleted, reported ones included; manual ones may also be
-- edited. Deleting merges the record's interval into the next one; its
-- derived entry goes with it (ON DELETE CASCADE on
-- ledger_entry.balance_record_id) and the account is recomputed. The
-- reconciliations of an account's reported records are summed into its
-- unexplained difference (v_unexplained_difference).
-- The account's earliest counting record is its ANCHOR; the derived entries
-- (ledger_entries with a balance_record_id) are computed from these rows. Records of
-- a reverted run do not count (v_balance_record).
-- Records on the same date are ordered by id. Spec §3.10, §5.10.
CREATE TABLE balance_record (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id    bigint  NOT NULL REFERENCES account(id) ON DELETE RESTRICT,
    kind          text    NOT NULL CHECK (kind IN ('reported','manual')),
    import_run_id bigint  REFERENCES import_run(id) ON DELETE RESTRICT,
    balance       bigint  NOT NULL,
    currency      char(3) NOT NULL,
    balance_on    date    NOT NULL,
    CONSTRAINT fk_balance_record_account_currency
        FOREIGN KEY (account_id, currency) REFERENCES account (id, currency),
    CONSTRAINT ck_balance_record_run
        CHECK ((kind = 'manual') = (import_run_id IS NULL)),
    -- a reported record is on its run's account (NULL run: manual, unchecked)
    CONSTRAINT fk_balance_record_run_account
        FOREIGN KEY (import_run_id, account_id) REFERENCES import_run (id, account_id)
);

CREATE UNIQUE INDEX ux_balance_record_reported
    ON balance_record (import_run_id) WHERE kind = 'reported';
CREATE UNIQUE INDEX ux_balance_record_manual_date
    ON balance_record (account_id, balance_on) WHERE kind = 'manual';
CREATE INDEX ix_balance_record_account_date
    ON balance_record (account_id, balance_on);

-- ---------------------------------------------------------------------
-- 5. Provenance layer — immutable record of what the source actually said
-- ---------------------------------------------------------------------

CREATE TABLE source_transaction (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    -- NULL for a USER-AUTHORED row, entered through the entry form on an
    -- unsynced account (spec §3.9, §5.6, I1, I40). Otherwise denormalised:
    -- decides which provenance widget renders, must survive the instance
    -- being deleted.
    importer      text,
    importer_instance_id bigint REFERENCES importer_instance(id) ON DELETE SET NULL,
    -- RESTRICT: an imported row's run is its provenance and carries its
    -- arrival time, so this table has no created_at. A user-authored row
    -- belongs to no run (ck_user_row).
    import_run_id bigint REFERENCES import_run(id) ON DELETE RESTRICT,
    account_id    bigint NOT NULL REFERENCES account(id) ON DELETE RESTRICT,

    -- ONE identity per row (spec §5.2, I4), in exactly one of two columns:
    --   source_id    = the id the SOURCE assigns (camt AcctSvcrRef, PayPal
    --                  transaction id). Emitted when the source has one, NULL
    --                  when it does not. A fact, never a decision. For a
    --                  user-authored row, a random id the entry form generates
    --                  before submitting, so a repeated submission is skipped.
    --   content_hash = computed by INGEST, only where there is no source_id,
    --                  from canonicalised amount, currency, booked_on,
    --                  counterparty_ref, purpose and the row's ordinal.
    --                  Field-tagged encoding. Importers never hash.
    source_id     text,
    content_hash  text,
    -- the statement format this record came from ('mt940', 'camt053', a CSV
    -- profile); NULL for a user-authored row. Provenance only; not a hash
    -- input.
    source_format text,

    -- signed minor units, as booked. Never zero: a booking that moves nothing
    -- is not a movement, importers do not emit it (spec §5.1), and an entry
    -- cannot carry zero.
    amount        bigint  NOT NULL CHECK (amount <> 0),
    currency      char(3) NOT NULL,
    booked_on     date    NOT NULL,
    value_on      date,                -- stored, NOT a hash input (spec §5.2)

    -- where the payment was made in another currency: the original amount as
    -- the source reported it, signed like `amount`. Used for cross-currency
    -- counter-legs, exact cross-currency pairing and document matching; never
    -- for valuation, never a hash input. Spec §3.8.
    instructed_amount   bigint,
    instructed_currency char(3) REFERENCES currency(code),

    -- counterparty as the source gave it. `ref` is an opaque string: IBAN for
    -- SEPA, an email or merchant id for PayPal. Compared, never interpreted.
    counterparty_ref  text,
    counterparty_bic  text,
    counterparty_name text,
    purpose           text,            -- remittance text only, free of format
                                       -- artefacts (spec §5.1)
    end_to_end_id     text,
    -- SEPA mandate reference (camt MndtId, MT940 MREF+). Not a hash input;
    -- a rule condition and a refinement of history key 1 (spec §5.2, §5.9).
    mandate_ref       text,
    booking_text      text,            -- 'LASTSCHRIFT', 'KARTENZAHLUNG', 'GUTSCHRIFT'

    -- importer-typed payload, rendered by the UI widget. MUST include the
    -- original, unparsed source data so columns can be re-derived and rows
    -- rehashed should normalisation ever change (spec §5.1). For a
    -- user-authored row, what the entry form submitted.
    raw           jsonb  NOT NULL,

    -- DUPLICATE: kept, interpreted as nothing — no ledger entries, exempt
    -- from the split invariant, but still blocking its identity so the next
    -- fetch cannot re-import it. Names the row on the SAME account reporting
    -- the same movement (composite FK below), never another duplicate
    -- (trg_duplicate_state). Set by ingest only on rows it is inserting
    -- (spec §5.2), or by a user's "mark as duplicate of"; cleared by "not a
    -- duplicate". When a revert deletes its original, the lowest-id row
    -- pointing at that original is cleared and the others repointed to it,
    -- before the delete. NO ACTION rather than RESTRICT, so one statement can delete a
    -- run's rows that point at each other. The only permitted change to a row
    -- after insert. Spec §5.6, I2, I32.
    duplicate_of  bigint,

    CONSTRAINT ck_one_identity
        CHECK ((source_id IS NULL) = (content_hash IS NOT NULL)),
    -- a user-authored row has no importer, run or format, and is never a
    -- duplicate: deduplication compares imported rows only (spec §5.2)
    CONSTRAINT ck_user_row
        CHECK ((importer IS NULL) = (import_run_id IS NULL)
               AND (importer IS NULL) = (source_format IS NULL)
               AND (importer IS NOT NULL OR duplicate_of IS NULL)),
    CONSTRAINT uq_source_id_account UNIQUE (id, account_id),
    CONSTRAINT fk_duplicate_same_account
        FOREIGN KEY (duplicate_of, account_id)
        REFERENCES source_transaction (id, account_id) ON DELETE NO ACTION,
    CONSTRAINT ck_duplicate_not_self
        CHECK (duplicate_of IS NULL OR duplicate_of <> id),
    CONSTRAINT fk_source_account_currency
        FOREIGN KEY (account_id, currency) REFERENCES account (id, currency),
    -- a row belongs to the account of its run (one account per transaction run)
    CONSTRAINT fk_source_run_account
        FOREIGN KEY (import_run_id, account_id) REFERENCES import_run (id, account_id),
    CONSTRAINT ck_instructed_pair
        CHECK ((instructed_amount IS NULL) = (instructed_currency IS NULL)),
    CONSTRAINT ck_instructed_foreign
        CHECK (instructed_currency IS NULL OR instructed_currency <> currency),
    CONSTRAINT ck_instructed_sign
        CHECK (instructed_amount IS NULL OR sign(instructed_amount) = sign(amount))
);

-- The identity is unique per ACCOUNT over ALL rows, duplicates included — a
-- duplicate must keep blocking it. Per account and not per credential is what
-- makes the shared account work: whoever syncs second finds the same
-- identities and skips them; where the credentials render a row differently,
-- deduplication by amount inserts the second delivery as a duplicate, and its
-- identity then accounts for the original too (spec §5.2).
-- Reverted rows are deleted, so their identities are free again. A conflict
-- on either index is a concurrent identical insert and is skipped. I4.
CREATE UNIQUE INDEX ux_source_content_hash
    ON source_transaction (account_id, content_hash)
    WHERE content_hash IS NOT NULL;
CREATE UNIQUE INDEX ux_source_source_id
    ON source_transaction (account_id, source_id)
    WHERE source_id IS NOT NULL;
-- deduplication compares per account and booking day (spec §5.2)
CREATE INDEX ix_source_account_date
    ON source_transaction (account_id, booked_on DESC);
CREATE INDEX ix_source_counterparty
    ON source_transaction (counterparty_ref) WHERE counterparty_ref IS NOT NULL;
CREATE INDEX ix_source_purpose_trgm
    ON source_transaction USING gin (purpose gin_trgm_ops);
CREATE INDEX ix_source_run ON source_transaction (import_run_id);

-- ---------------------------------------------------------------------
-- 6. Ledger layer — the interpretation you see, edit and report on
-- ---------------------------------------------------------------------

CREATE TABLE ledger_entry (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id            bigint NOT NULL REFERENCES account(id) ON DELETE RESTRICT,
    -- An entry is one of two kinds (spec §3.9), told apart by which of these
    -- two references it sets — exactly one (ck_entry_kind):
    --   source_transaction_id = a MOVEMENT: the interpretation of a source
    --     transaction, imported or user-authored (entered through the form,
    --     or created as a counter-leg, spec §5.7). Split invariant, resolution,
    --     review. Whether it was imported is the source's importer, not a
    --     property of the entry. The original entry stays as the residual
    --     child of a split; split ordering is by id. Spec §5.9, I3.
    --   balance_record_id = a DERIVED entry: the opening, a valuation or a
    --     reconciliation of that record (spec §3.10). Recomputed, never
    --     edited, tagged or annotated, never resolved or reviewed (I13).
    source_transaction_id bigint REFERENCES source_transaction(id) ON DELETE RESTRICT,
    balance_record_id bigint REFERENCES balance_record(id) ON DELETE CASCADE,

    -- NULL while a movement is not yet interpreted (spec §3.4).
    -- income vs expense is the CATEGORY's kind, not a type.
    type       text   CHECK (type IN ('flow','transfer','opening','valuation',
                                      'reconciliation')),
    -- signed minor units. The sign is NOT constrained: a refund is a positive
    -- flow in an expense category.
    amount     bigint NOT NULL CHECK (amount <> 0),
    -- copied from the account, never editable (spec §5.9)
    currency   char(3) NOT NULL,
    booked_on  date   NOT NULL,
    value_on   date,

    category_id bigint REFERENCES category(id) ON DELETE RESTRICT,
    payee_id    bigint REFERENCES payee(id) ON DELETE RESTRICT,
    -- the other leg of a transfer; NULL while unpaired. A transfer is
    -- confirmed only as a pair (I22, checked by the commit).
    counterpart_entry_id bigint REFERENCES ledger_entry(id) ON DELETE SET NULL,
    -- a transfer leg's COUNTER-ACCOUNT, keyed 'counter_account': where the
    -- money went or came from. NULL while not yet known; once paired, the
    -- partner's account (I10, trg_transfer_pair) — set by the pairing itself
    -- where the leg had none, in the same write, and then part of the pair:
    -- cleared with it (spec §5.7). It is what a waiting leg
    -- waits on and what candidates are filtered by (spec §5.7). The currency
    -- rule (I11) is applied by the one core function that proposes and checks
    -- it, not here.
    counter_account_id   bigint REFERENCES account(id) ON DELETE RESTRICT,
    -- the transaction's DOCUMENT (spec §5.8), on its original entry only, so a
    -- split carries it once. Derived like a field, keyed 'document'. Its
    -- foreign key and the I35 indexes follow external_document, below.
    document_id          bigint,

    description text,
    note        text,

    -- How each derived value was arrived at, keyed by what it explains: type,
    -- payee, category, counter_account, counterpart, and on a transaction's
    -- original entry its document link. Every derived value carries a key.
    -- Keys of passes 'history', 'llm' and 'matcher_proposal' (settling's link
    -- to a document of several lines) are PROPOSALS and stay until a user
    -- confirms the value. Keys of passes 'own_account', 'rule',
    -- 'matcher_decision' (made by settling: a pair, a one-line document link,
    -- or the "none" it records when it confirms a unit without a document) and 'user' (decided in a commit) are STANDING: they do
    -- not hold up review and are not rederived
    -- unless the entry's input changes or an earlier field in field order does.
    -- A commit keeps unchanged standing keys; an accepted proposal becomes
    -- 'user' with the proposal's key as its basis; a value set by hand becomes
    -- 'user' without one. NOT provenance (that is source_transaction.raw) and
    -- NOT audit. Spec §5.9.
    derivation  jsonb NOT NULL DEFAULT '{}'::jsonb,

    -- Review state is DERIVED, per unit: a unit (the entries of a source
    -- transaction, and of a transfer pair, joined transitively) is reviewed
    -- when it meets every requirement of
    -- confirming and carries no keys but standing ones (spec §6).
    -- `review_flags` presents that state and is rewritten wholesale by
    -- settling; never append or strip tokens at call sites (I23).
    review_flags text[] NOT NULL DEFAULT '{}'::text[],

    -- Optimistic concurrency token. Bumped by user-meaningful change (see
    -- trg_le_version below) — deliberately NOT by settling's rederivation of
    -- unconfirmed entries, nor by flags or derivation bookkeeping: a commit
    -- writes the state the user saw and is refused only where the unit
    -- changed underneath it, never because a proposal was recomputed
    -- (spec §6). Structural columns — account, amount, counterpart,
    -- document — bump it whoever writes them, settling included.
    -- No created_by / created_at / updated_at: attribution and timestamps
    -- are audit questions (spec §3.2). An imported entry's arrival time is its
    -- source transaction's run.
    version    integer NOT NULL DEFAULT 1,

    -- a movement or a derived entry, never both, never neither
    CONSTRAINT ck_entry_kind
        CHECK (num_nonnulls(source_transaction_id, balance_record_id) = 1),
    -- only a movement explains a document
    CONSTRAINT ck_document_on_movement
        CHECK (document_id IS NULL OR source_transaction_id IS NOT NULL),
    -- derived entries are exactly the openings, valuations and
    -- reconciliations, each tied to the record it is derived from
    CONSTRAINT ck_balance_types
        CHECK ((balance_record_id IS NOT NULL)
               = COALESCE(type IN ('opening','valuation','reconciliation'), false)),
    -- only movements may be incomplete; derived entries are complete at
    -- creation. Confirming requires completeness, derived by settling (spec
    -- §3.4, §6, I8).
    CONSTRAINT ck_complete_unless_movement
        CHECK (source_transaction_id IS NOT NULL OR type IS NOT NULL),
    -- a category implies a flow
    CONSTRAINT ck_category_only_flow
        CHECK (category_id IS NULL OR type IS NOT DISTINCT FROM 'flow'),
    -- only transfers may be paired
    CONSTRAINT ck_counterpart_only_transfer
        CHECK (counterpart_entry_id IS NULL OR type IS NOT DISTINCT FROM 'transfer'),
    -- only transfers have a counter-account, never their own account
    CONSTRAINT ck_counter_account_only_transfer
        CHECK (counter_account_id IS NULL OR type IS NOT DISTINCT FROM 'transfer'),
    CONSTRAINT ck_counter_account_not_own
        CHECK (counter_account_id IS NULL OR counter_account_id <> account_id),
    -- payees apply to flows only; a pass proposing a payee thereby proposes
    -- the type flow (spec §5.9, I9)
    CONSTRAINT ck_payee_only_flow
        CHECK (payee_id IS NULL OR type IS NOT DISTINCT FROM 'flow'),
    CONSTRAINT ck_not_self_counterpart
        CHECK (counterpart_entry_id IS NULL OR counterpart_entry_id <> id),
    CONSTRAINT ck_review_flags_known
        CHECK (review_flags <@ ARRAY['unconfirmed','unclassified',
                                     'document_suggested','waiting',
                                     'unmatched_transfer']::text[]),
    -- an entry is denominated in its account's currency
    CONSTRAINT fk_entry_account_currency
        FOREIGN KEY (account_id, currency) REFERENCES account (id, currency)
);

-- structurally prevents two entries claiming the same partner (3-leg transfers)
CREATE UNIQUE INDEX ux_le_counterpart ON ledger_entry (counterpart_entry_id)
    WHERE counterpart_entry_id IS NOT NULL;
-- at most one opening per account: the anchor's derived entry (spec §3.10, I13)
CREATE UNIQUE INDEX ux_le_one_opening ON ledger_entry (account_id)
    WHERE type = 'opening';
-- one derived entry per balance record
CREATE UNIQUE INDEX ux_le_balance_record ON ledger_entry (balance_record_id)
    WHERE balance_record_id IS NOT NULL;

CREATE INDEX ix_le_account_date ON ledger_entry (account_id, booked_on DESC);
CREATE INDEX ix_le_date         ON ledger_entry (booked_on DESC);
CREATE INDEX ix_le_source       ON ledger_entry (source_transaction_id);
CREATE INDEX ix_le_category     ON ledger_entry (category_id);
CREATE INDEX ix_le_payee        ON ledger_entry (payee_id);
-- the review queue: one cheap indexed predicate
CREATE INDEX ix_le_review_open  ON ledger_entry (booked_on DESC)
    WHERE cardinality(review_flags) > 0;
-- containment lookups on derivation keys: the entries carrying a rule's key
-- (a rule's preview, spec §5.9), or those without a 'user' key (confirmed by
-- passes alone). Every derived value carries a key (spec §5.9), so no partial
-- clause; jsonb_path_ops keeps the index small despite nested 'user' bases.
CREATE INDEX ix_le_derivation ON ledger_entry
    USING gin (derivation jsonb_path_ops);
-- unpaired transfer legs, for the matcher and read-time offers
CREATE INDEX ix_le_open_transfer ON ledger_entry (booked_on)
    WHERE type = 'transfer' AND counterpart_entry_id IS NULL;
-- legs waiting on an account, for waiting and the needs-an-account grouping
CREATE INDEX ix_le_counter_account ON ledger_entry (counter_account_id)
    WHERE counter_account_id IS NOT NULL AND counterpart_entry_id IS NULL;
-- at most one transfer entry per source transaction: a split produces only
-- additional flows (spec §5.9, I31)
CREATE UNIQUE INDEX ux_le_one_transfer_per_source ON ledger_entry (source_transaction_id)
    WHERE type = 'transfer' AND source_transaction_id IS NOT NULL;

-- Derived entries (with a balance_record_id) take no tags: they are deleted and
-- recreated as their records change (spec §3.7, I13). Enforced by the
-- operations that tag, not here. Tags are not part of review and bump no
-- version: a commit writes the tags of the entries it creates and never
-- those of existing ones, so it cannot overwrite a tag change made elsewhere.
CREATE TABLE ledger_entry_tag (
    ledger_entry_id bigint NOT NULL REFERENCES ledger_entry(id) ON DELETE CASCADE,
    tag_id          bigint NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
    PRIMARY KEY (ledger_entry_id, tag_id)
);

CREATE INDEX ix_ledger_entry_tag_tag ON ledger_entry_tag (tag_id);

-- ---------------------------------------------------------------------
-- 7. Enrichment layer — documents that DESCRIBE money but don't move it
-- ---------------------------------------------------------------------

-- Updated in place when re-fetched: a document moves no money, so it needs no
-- immutability, and keeping the first version would drop cancellations and
-- partial shipments. One document per charge where the provider exposes
-- charges. In v1, fed by a test importer until real document importers
-- exist. Spec §5.5, §5.8.
CREATE TABLE external_document (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider             text NOT NULL,     -- 'amazon' | 'paypal' | 'receipt' | ...
    external_id          text NOT NULL,     -- order id, invoice no
    importer_instance_id bigint REFERENCES importer_instance(id) ON DELETE SET NULL,
    -- nullable, unlike source_transaction: a receipt may one day be added by
    -- hand rather than fetched.
    import_run_id        bigint REFERENCES import_run(id) ON DELETE RESTRICT,
    occurred_on          date NOT NULL,     -- the charge date
    -- minor units of `currency`, signed in ledger convention: negative for a
    -- charge, positive for a refund or credit note. Matched with its sign.
    total                bigint NOT NULL CHECK (total <> 0),
    currency             char(3) NOT NULL REFERENCES currency(code),
    merchant_name        text,              -- input to resolution (§5.8)
    title                text,
    raw                  jsonb NOT NULL,
    -- incremented by ingest whenever what resolution reads of the document
    -- changes — total, currency, merchant, lines — so a commit made on an
    -- older version is refused (spec §5.5, §6). Not bumped by a re-fetch
    -- that changes nothing resolution reads.
    version              integer NOT NULL DEFAULT 1,
    UNIQUE (provider, external_id)
);

CREATE INDEX ix_document_date ON external_document (occurred_on DESC);

CREATE TABLE external_document_line (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id bigint NOT NULL REFERENCES external_document(id) ON DELETE CASCADE,
    line_no     integer NOT NULL,
    description text NOT NULL,
    -- signed like the document's total: a charge's lines are negative
    -- (spec §5.5)
    amount      bigint NOT NULL,
    qty         integer,
    UNIQUE (document_id, line_no)
);

-- The link from a transaction to its document is ledger_entry.document_id, a
-- derived field keyed like any other (spec §5.8, §5.9): 'matcher_decision'
-- where settling linked a document of one line, 'matcher_proposal' one of
-- several, 'user' where a commit picked it or decided "none" (key without a
-- value; a commit with no document picked decides "none"). Suggestions are computed when read and never stored.
-- RESTRICT: a document is never deleted while an entry carries it.
ALTER TABLE ledger_entry
    ADD CONSTRAINT fk_le_document
    FOREIGN KEY (document_id) REFERENCES external_document(id) ON DELETE RESTRICT;

-- I35, enforced on the entries: a document is carried by at most one entry,
-- and a transaction has at most one entry carrying a document — the original
-- entry, which keeps its id through splits.
CREATE UNIQUE INDEX ux_le_document
    ON ledger_entry (document_id) WHERE document_id IS NOT NULL;
CREATE UNIQUE INDEX ux_le_document_per_transaction
    ON ledger_entry (source_transaction_id) WHERE document_id IS NOT NULL;

-- Every entry's document, read through its transaction's carrier: one join
-- instead of a copy on each entry of a split.
CREATE VIEW v_entry_document AS
SELECT e.id AS ledger_entry_id, c.document_id
  FROM ledger_entry e
  JOIN ledger_entry c
    ON c.source_transaction_id = e.source_transaction_id
   AND c.document_id IS NOT NULL;

-- Every document with the entry carrying it, NULL where none does: the
-- document list and its "not linked" filter (spec §5.8).
CREATE VIEW v_document_link AS
SELECT d.id AS document_id, e.id AS ledger_entry_id,
       e.source_transaction_id
  FROM external_document d
  LEFT JOIN ledger_entry e ON e.document_id = d.id;

-- ---------------------------------------------------------------------
-- 8. Invariants that DDL cannot express
-- ---------------------------------------------------------------------

-- 8.1 source transactions are immutable: after insert, the only permitted
-- change is whether the row is a duplicate (duplicate_of set or cleared).
CREATE OR REPLACE FUNCTION assert_source_immutable() RETURNS trigger AS $$
BEGIN
    -- a user-authored row is the user's to edit — amount, date, purpose — but
    -- stays user-authored, on its account and in its currency (spec §5.6)
    IF OLD.importer IS NULL AND NEW.importer IS NULL
       AND NEW.account_id = OLD.account_id AND NEW.currency = OLD.currency THEN
        RETURN NEW;
    END IF;
    IF OLD.importer IS NULL THEN
        RAISE EXCEPTION 'user-authored source_transaction % keeps its account and currency', OLD.id;
    END IF;
    -- besides duplicate_of, only the instance link may go, to NULL: the FK's
    -- ON DELETE SET NULL runs as an UPDATE, and `importer` keeps the provenance
    IF (to_jsonb(NEW) - 'duplicate_of' - 'importer_instance_id')
           = (to_jsonb(OLD) - 'duplicate_of' - 'importer_instance_id')
       AND (NEW.importer_instance_id IS NULL
            OR NEW.importer_instance_id = OLD.importer_instance_id) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'source_transaction % is immutable; only duplicate_of, and its instance link to NULL, may change', OLD.id;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_source_immutable BEFORE UPDATE ON source_transaction
    FOR EACH ROW EXECUTE FUNCTION assert_source_immutable();

-- 8.2 split allocation (I3): the entries of a source transaction carry its
-- account, currency and dates and sum to its amount; a duplicate has none.
-- Checked when entries change, and when a source's copied columns change — a
-- user-authored row is editable (spec §5.6). DEFERRED so an import, a commit,
-- an edit through the entry form or clearing a duplicate can write the row
-- and its entries in one tx.
CREATE OR REPLACE FUNCTION check_source_entries(st_id bigint) RETURNS void AS $$
DECLARE
    st        source_transaction%ROWTYPE;
    kid_sum   bigint;
    kid_count bigint;
BEGIN
    SELECT * INTO st FROM source_transaction WHERE id = st_id;
    IF NOT FOUND THEN
        RETURN;                           -- source removed in the same tx (revert)
    END IF;
    SELECT COALESCE(sum(amount), 0), count(*) INTO kid_sum, kid_count
      FROM ledger_entry WHERE source_transaction_id = st_id;
    IF st.duplicate_of IS NOT NULL THEN
        IF kid_count > 0 THEN
            RAISE EXCEPTION 'duplicate source_transaction % still has % entries', st_id, kid_count;
        END IF;
        RETURN;
    END IF;
    IF kid_sum <> st.amount THEN
        RAISE EXCEPTION
            'split allocation mismatch for source_transaction %: entries sum to %, source is %',
            st_id, kid_sum, st.amount;
    END IF;
    IF EXISTS (SELECT 1 FROM ledger_entry e
                WHERE e.source_transaction_id = st_id
                  AND (e.account_id <> st.account_id OR e.currency <> st.currency
                       OR e.booked_on <> st.booked_on
                       OR e.value_on IS DISTINCT FROM st.value_on)) THEN
        RAISE EXCEPTION
            'entries of source_transaction % must carry its account, currency and dates', st_id;
    END IF;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION assert_split_sum() RETURNS trigger AS $$
DECLARE
    st_id bigint;
BEGIN
    st_id := COALESCE(NEW.source_transaction_id, OLD.source_transaction_id);
    IF st_id IS NOT NULL THEN
        PERFORM check_source_entries(st_id);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- fires only on the columns it checks, so settling's rewrite of flags and
-- derivation queues nothing; an entry's source never changes (8.5c)
CREATE CONSTRAINT TRIGGER trg_split_sum
    AFTER INSERT OR DELETE
       OR UPDATE OF amount, account_id, currency, booked_on, value_on
    ON ledger_entry
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION assert_split_sum();

CREATE OR REPLACE FUNCTION assert_source_entries() RETURNS trigger AS $$
BEGIN
    PERFORM check_source_entries(NEW.id);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_source_entries
    AFTER UPDATE OF amount, account_id, currency, booked_on, value_on
    ON source_transaction
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION assert_source_entries();

-- 8.2b inserting rows, marking and clearing duplicates. 8.2 fires on entries
-- only, so a new row and a change of duplicate_of are checked here: a
-- duplicate has no entries, a row that is not one — newly inserted, or no
-- longer a duplicate — has entries summing to its amount (so a source row
-- inserted without its entry is refused, I7), and duplicates are
-- never chained — a duplicate points at a row that is not one, and a row
-- others point at is not a duplicate. DEFERRED so one tx can delete or create
-- the entries and repoint the rows pointing at a newly marked one (spec §5.6).
CREATE OR REPLACE FUNCTION assert_duplicate_state() RETURNS trigger AS $$
DECLARE
    cur       source_transaction%ROWTYPE;
    kid_sum   bigint;
    kid_count bigint;
BEGIN
    -- the row as it is now, not as it was when this deferred event was queued:
    -- one transaction may insert or mark a row and change it again
    SELECT * INTO cur FROM source_transaction WHERE id = NEW.id;
    IF NOT FOUND THEN
        RETURN NULL;                      -- removed in the same tx (revert)
    END IF;
    SELECT COALESCE(sum(amount), 0), count(*) INTO kid_sum, kid_count
      FROM ledger_entry WHERE source_transaction_id = cur.id;
    IF cur.duplicate_of IS NULL THEN
        IF kid_sum <> cur.amount THEN
            RAISE EXCEPTION 'source_transaction % is not a duplicate but its entries sum to %, not %',
                cur.id, kid_sum, cur.amount;
        END IF;
        RETURN NULL;
    END IF;
    IF kid_count > 0 THEN
        RAISE EXCEPTION 'duplicate source_transaction % still has % entries', cur.id, kid_count;
    END IF;
    IF EXISTS (SELECT 1 FROM source_transaction
                WHERE id = cur.duplicate_of AND importer IS NULL) THEN
        RAISE EXCEPTION 'source_transaction % cannot duplicate user-authored row %',
            cur.id, cur.duplicate_of;
    END IF;
    IF EXISTS (SELECT 1 FROM source_transaction
                WHERE id = cur.duplicate_of AND duplicate_of IS NOT NULL) THEN
        RAISE EXCEPTION 'source_transaction % duplicates %, which is itself a duplicate',
            cur.id, cur.duplicate_of;
    END IF;
    IF EXISTS (SELECT 1 FROM source_transaction WHERE duplicate_of = cur.id) THEN
        RAISE EXCEPTION 'source_transaction % is a duplicate but others still point at it',
            cur.id;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_duplicate_state
    AFTER INSERT OR UPDATE OF duplicate_of ON source_transaction
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION assert_duplicate_state();

-- 8.2c user-authored source transactions are entered only on unsynced
-- accounts (I40). Their account never changes (trg_source_immutable), so
-- entry is the only moment to check.
CREATE OR REPLACE FUNCTION assert_user_source_unsynced() RETURNS trigger AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM account a
                WHERE a.id = NEW.account_id AND a.closed_on IS NULL
                  AND EXISTS (SELECT 1 FROM account_source s WHERE s.account_id = a.id)) THEN
        RAISE EXCEPTION 'account % is synced: user-authored transactions are entered only on unsynced accounts',
            NEW.account_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_user_source_unsynced
    BEFORE INSERT ON source_transaction
    FOR EACH ROW WHEN (NEW.importer IS NULL)
    EXECUTE FUNCTION assert_user_source_unsynced();

-- 8.3 transfer pairing: mutual, two distinct accounts, opposing signs, and for
-- a same-currency pair exactly equal and opposite amounts. Cross-currency legs
-- need only opposing signs: their amounts legitimately differ. A paired leg's
-- counter-account is its partner's account. Spec §5.7, I10.
--
-- Checked for the row written AND for the partner it pointed at before, so a
-- pair half-broken — one leg cleared or retyped while the other still points
-- at it — is refused at commit, not only reported by /check.
CREATE OR REPLACE FUNCTION check_transfer_pair(e_id bigint) RETURNS void AS $$
DECLARE
    e     ledger_entry%ROWTYPE;
    other ledger_entry%ROWTYPE;
BEGIN
    SELECT * INTO e FROM ledger_entry WHERE id = e_id;
    IF NOT FOUND THEN
        RETURN;                           -- deleted in the same tx
    END IF;

    IF e.counterpart_entry_id IS NULL THEN
        IF EXISTS (SELECT 1 FROM ledger_entry WHERE counterpart_entry_id = e_id) THEN
            RAISE EXCEPTION 'entry %: another entry still points at it as its counterpart', e_id;
        END IF;
        RETURN;
    END IF;

    SELECT * INTO other FROM ledger_entry WHERE id = e.counterpart_entry_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'entry %: counterpart % does not exist', e_id, e.counterpart_entry_id;
    END IF;

    IF other.counterpart_entry_id IS DISTINCT FROM e_id THEN
        RAISE EXCEPTION 'entry %: counterpart link is not mutual (% points at %)',
            e_id, other.id, other.counterpart_entry_id;
    END IF;
    IF other.type IS DISTINCT FROM 'transfer' THEN
        RAISE EXCEPTION 'entry %: counterpart % is not a transfer', e_id, other.id;
    END IF;
    IF other.account_id = e.account_id THEN
        RAISE EXCEPTION 'entry %: both transfer legs are on account %', e_id, e.account_id;
    END IF;
    IF e.counter_account_id IS DISTINCT FROM other.account_id THEN
        RAISE EXCEPTION 'entry %: counter-account % is not its partner''s account %',
            e_id, e.counter_account_id, other.account_id;
    END IF;
    IF sign(other.amount) = sign(e.amount) THEN
        RAISE EXCEPTION 'entry %: transfer legs must have opposing signs', e_id;
    END IF;
    IF other.currency = e.currency AND other.amount <> -e.amount THEN
        RAISE EXCEPTION 'entry %: same-currency transfer legs must be equal and opposite (% vs %)',
            e_id, e.amount, other.amount;
    END IF;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION assert_transfer_pair() RETURNS trigger AS $$
BEGIN
    PERFORM check_transfer_pair(NEW.id);
    IF TG_OP = 'UPDATE' AND OLD.counterpart_entry_id IS NOT NULL
       AND OLD.counterpart_entry_id IS DISTINCT FROM NEW.counterpart_entry_id THEN
        PERFORM check_transfer_pair(OLD.counterpart_entry_id);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_transfer_pair
    AFTER INSERT
       OR UPDATE OF counterpart_entry_id, type, counter_account_id, amount,
                    account_id, currency
    ON ledger_entry
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION assert_transfer_pair();

-- 8.4 a category's kind is fixed at creation (spec §3.5, I9).
CREATE OR REPLACE FUNCTION assert_category_kind_fixed() RETURNS trigger AS $$
BEGIN
    IF NEW.kind IS DISTINCT FROM OLD.kind THEN
        RAISE EXCEPTION 'category %: kind is fixed at creation', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_category_kind_fixed BEFORE UPDATE OF kind ON category
    FOR EACH ROW EXECUTE FUNCTION assert_category_kind_fixed();

-- 8.4b the category tree has no cycles (spec §3.5, I9): a category is never
-- moved under itself or one of its descendants. Self-parenting is already a
-- CHECK; this catches the longer loops.
CREATE OR REPLACE FUNCTION assert_category_acyclic() RETURNS trigger AS $$
BEGIN
    IF NEW.parent_id IS NOT NULL AND EXISTS (
        WITH RECURSIVE up(id) AS (
            SELECT NEW.parent_id
            UNION
            SELECT c.parent_id FROM category c JOIN up ON c.id = up.id
             WHERE c.parent_id IS NOT NULL)
        SELECT 1 FROM up WHERE id = NEW.id) THEN
        RAISE EXCEPTION 'category %: moving it under % would create a cycle',
            NEW.id, NEW.parent_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_category_acyclic BEFORE UPDATE OF parent_id ON category
    FOR EACH ROW EXECUTE FUNCTION assert_category_acyclic();

-- 8.5 whether an account is an investment account (depot, asset) is fixed at
-- creation: it decides whether later balance records derive valuations or
-- reconciliations (spec §3.3, I38).
CREATE OR REPLACE FUNCTION assert_account_investment_fixed() RETURNS trigger AS $$
BEGIN
    IF (OLD.kind IN ('depot','asset')) IS DISTINCT FROM (NEW.kind IN ('depot','asset')) THEN
        RAISE EXCEPTION 'account %: whether it is an investment account is fixed at creation', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_account_investment_fixed BEFORE UPDATE OF kind ON account
    FOR EACH ROW EXECUTE FUNCTION assert_account_investment_fixed();

-- 8.5b an account's currency is fixed, permanently, even while it holds
-- nothing (spec §3.3, I5); the composite FKs alone would allow it on an
-- empty account.
CREATE OR REPLACE FUNCTION assert_account_currency_fixed() RETURNS trigger AS $$
BEGIN
    IF NEW.currency IS DISTINCT FROM OLD.currency THEN
        RAISE EXCEPTION 'account %: its currency is fixed', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_account_currency_fixed BEFORE UPDATE OF currency ON account
    FOR EACH ROW EXECUTE FUNCTION assert_account_currency_fixed();

-- 8.5c an entry's source transaction is structurally fixed (spec §5.9): an
-- entry is never moved between sources, so the split check (8.2) need only
-- look at the source an entry belongs to.
CREATE OR REPLACE FUNCTION assert_entry_source_fixed() RETURNS trigger AS $$
BEGIN
    IF NEW.source_transaction_id IS DISTINCT FROM OLD.source_transaction_id THEN
        RAISE EXCEPTION 'entry %: its source transaction is fixed', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_entry_source_fixed
    BEFORE UPDATE OF source_transaction_id ON ledger_entry
    FOR EACH ROW EXECUTE FUNCTION assert_entry_source_fixed();

-- 8.6 version: user-meaningful changes only.
--
-- A timestamp is not usable as a concurrency token: timestamps can collide
-- within a transaction, and a check that silently passes on collision is
-- worse than no check because it invites trust. A monotonic integer is
-- unambiguous.
--
-- The WHEN clause is the substance. review_flags and derivation are
-- deliberately EXCLUDED, and so is everything settling writes while it
-- rederives unconfirmed entries (it sets the transaction-local setting
-- ledger.settling = 'on'): a commit writes the state the user saw, so a
-- proposal recomputed underneath an open review panel must not refuse it.
-- STRUCTURAL changes bump the version whoever makes them — account, amount,
-- counterpart and document (an entry's source never changes, 8.5c) —
-- because a commit must be refused when the unit's structure moved (spec §6). A recomputed derived amount is such a change.
CREATE OR REPLACE FUNCTION bump_version() RETURNS trigger AS $$
BEGIN
    NEW.version := OLD.version + 1;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_le_version BEFORE UPDATE ON ledger_entry
    FOR EACH ROW WHEN (
            OLD.account_id            IS DISTINCT FROM NEW.account_id
         OR OLD.amount                IS DISTINCT FROM NEW.amount
         OR OLD.counterpart_entry_id  IS DISTINCT FROM NEW.counterpart_entry_id
         OR OLD.document_id           IS DISTINCT FROM NEW.document_id
         OR (current_setting('ledger.settling', true) IS DISTINCT FROM 'on'
             AND (   OLD.type         IS DISTINCT FROM NEW.type
                  OR OLD.counter_account_id IS DISTINCT FROM NEW.counter_account_id
                  OR OLD.currency     IS DISTINCT FROM NEW.currency
                  OR OLD.booked_on    IS DISTINCT FROM NEW.booked_on
                  OR OLD.value_on     IS DISTINCT FROM NEW.value_on
                  OR OLD.category_id  IS DISTINCT FROM NEW.category_id
                  OR OLD.payee_id     IS DISTINCT FROM NEW.payee_id
                  OR OLD.description  IS DISTINCT FROM NEW.description
                  OR OLD.note         IS DISTINCT FROM NEW.note)))
    EXECUTE FUNCTION bump_version();

-- 8.7 the base currency is fixed once written: fx_rate.per_base is stored against
-- it, so changing it would silently misvalue every foreign amount (spec §3.8).
CREATE OR REPLACE FUNCTION assert_base_currency_fixed() RETURNS trigger AS $$
BEGIN
    IF NEW.base_currency IS DISTINCT FROM OLD.base_currency THEN
        RAISE EXCEPTION 'the base currency is fixed once the ledger is started';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_base_currency_fixed
    BEFORE UPDATE OF base_currency ON ledger_setting
    FOR EACH ROW EXECUTE FUNCTION assert_base_currency_fixed();

-- ---------------------------------------------------------------------
-- 9. Integrity views — back the /check page. All should return zero rows.
-- ---------------------------------------------------------------------

CREATE VIEW v_check_split_sum AS
SELECT s.id AS source_transaction_id, s.amount AS source_amount,
       COALESCE(sum(e.amount), 0) AS entries_sum
  FROM source_transaction s
  LEFT JOIN ledger_entry e ON e.source_transaction_id = s.id
 WHERE s.duplicate_of IS NULL
 GROUP BY s.id, s.amount
HAVING COALESCE(sum(e.amount), 0) <> s.amount;

CREATE VIEW v_check_duplicate_with_entries AS
SELECT s.id AS source_transaction_id, count(e.id) AS entries
  FROM source_transaction s
  JOIN ledger_entry e ON e.source_transaction_id = s.id
 WHERE s.duplicate_of IS NOT NULL
 GROUP BY s.id;

CREATE VIEW v_check_duplicate_chain AS
SELECT d.id AS source_transaction_id, d.duplicate_of
  FROM source_transaction d
  JOIN source_transaction o ON o.id = d.duplicate_of
 WHERE o.duplicate_of IS NOT NULL;

CREATE VIEW v_check_transfer_asymmetry AS
SELECT a.id AS entry_id, a.counterpart_entry_id, b.counterpart_entry_id AS back_ref
  FROM ledger_entry a
  LEFT JOIN ledger_entry b ON b.id = a.counterpart_entry_id
 WHERE a.counterpart_entry_id IS NOT NULL
   AND (b.id IS NULL OR b.counterpart_entry_id IS DISTINCT FROM a.id);

-- an opening must be dated before every other entry on its account
CREATE VIEW v_check_opening_not_first AS
SELECT o.id AS opening_entry_id, o.account_id, o.booked_on,
       min(e.booked_on) AS earliest_other
  FROM ledger_entry o
  JOIN ledger_entry e ON e.account_id = o.account_id AND e.id <> o.id
 WHERE o.type = 'opening'
 GROUP BY o.id, o.account_id, o.booked_on
HAVING min(e.booked_on) <= o.booked_on;

-- a reported balance record is never dated after its run's coverage (I36)
CREATE VIEW v_check_reported_after_coverage AS
SELECT b.id AS balance_record_id, b.balance_on, r.id AS import_run_id,
       r.covered_through
  FROM balance_record b
  JOIN import_run r ON r.id = b.import_run_id
 WHERE b.kind = 'reported'
   AND (r.covered_through IS NULL OR b.balance_on > r.covered_through);

-- the derived entry's type follows the account: a later record on an
-- investment account derives a valuation, on any other a reconciliation
CREATE VIEW v_check_derived_type AS
SELECT e.id AS entry_id, e.account_id, e.type, a.kind
  FROM ledger_entry e
  JOIN account a ON a.id = e.account_id
 WHERE (e.type = 'valuation'      AND a.kind NOT IN ('depot','asset'))
    OR (e.type = 'reconciliation' AND a.kind IN ('depot','asset'));

-- ---------------------------------------------------------------------
-- 9b. Derived read models
-- ---------------------------------------------------------------------

-- balance records that count: manual ones, and those of non-reverted runs
CREATE VIEW v_balance_record AS
SELECT b.*
  FROM balance_record b
  LEFT JOIN import_run r ON r.id = b.import_run_id
 WHERE r.id IS NULL OR r.status <> 'reverted';

-- integrity views that need v_balance_record (section 9): a derived entry
-- whose record no longer counts, an opening not owned by the anchor, and an
-- anchor whose derived entry is not the opening
CREATE VIEW v_check_derived_on_uncounted AS
SELECT e.id AS entry_id, e.balance_record_id
  FROM ledger_entry e
 WHERE e.balance_record_id IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM v_balance_record b
                    WHERE b.id = e.balance_record_id);

CREATE VIEW v_check_opening_not_anchor AS
SELECT e.id AS opening_entry_id, e.account_id, e.balance_record_id
  FROM ledger_entry e
 WHERE e.type = 'opening'
   AND e.balance_record_id IS DISTINCT FROM (
         SELECT b.id FROM v_balance_record b
          WHERE b.account_id = e.account_id
          ORDER BY b.balance_on, b.id LIMIT 1);

-- the anchor's derived entry, where it has one, is the opening
CREATE VIEW v_check_anchor_not_opening AS
SELECT e.id AS entry_id, e.account_id, e.type
  FROM ledger_entry e
 WHERE e.balance_record_id IS NOT NULL AND e.type <> 'opening'
   AND e.balance_record_id = (
         SELECT b.id FROM v_balance_record b
          WHERE b.account_id = e.account_id
          ORDER BY b.balance_on, b.id LIMIT 1);

-- unexplained difference: per account, the sum of the reconciliations of
-- EVERY record from its first reported record through its latest, in record
-- order (balance_on, then id), manual records included. Derived entries
-- telescope, so a manual record between two reported ones cancels here
-- whatever its error. A booking the bank dated back into a closed day leaves
-- a pair that cancels too; a missing or duplicated row persists. An account
-- shows the status while it has a row here (spec §3.11, §5.10). The anchor's
-- derived entry is the opening, not a difference; the reported records since
-- the running sum was last zero localise it.
CREATE VIEW v_unexplained_difference AS
WITH reported AS (
    SELECT account_id, balance_on, id FROM v_balance_record WHERE kind = 'reported'
), first_reported AS (
    SELECT DISTINCT ON (account_id) account_id, balance_on, id
      FROM reported ORDER BY account_id, balance_on, id
), last_reported AS (
    SELECT DISTINCT ON (account_id) account_id, balance_on, id
      FROM reported ORDER BY account_id, balance_on DESC, id DESC
)
SELECT b.account_id, sum(e.amount)::bigint AS difference
  FROM v_balance_record b
  JOIN first_reported f ON f.account_id = b.account_id
  JOIN last_reported  l ON l.account_id = b.account_id
  JOIN ledger_entry e ON e.balance_record_id = b.id
 WHERE e.type = 'reconciliation'
   AND (b.balance_on, b.id) >= (f.balance_on, f.id)
   AND (b.balance_on, b.id) <= (l.balance_on, l.id)
 GROUP BY b.account_id
HAVING sum(e.amount) <> 0;

-- synced: open, with at least one credential that can fetch it (spec §3.3)
CREATE VIEW v_account_synced AS
SELECT a.id AS account_id,
       (a.closed_on IS NULL
        AND EXISTS (SELECT 1 FROM account_source s WHERE s.account_id = a.id))
           AS synced
  FROM account a;

-- coverage per account, derived from its non-reverted runs (spec §5.4):
-- synced_through is the latest covered_through; NULL = never fetched. It is
-- the only coverage the domain reads.
CREATE VIEW v_account_coverage AS
SELECT a.id AS account_id,
       max(r.covered_through) AS synced_through
  FROM account a
  LEFT JOIN import_run r
         ON r.account_id = a.id AND r.status = 'ok'
        AND r.covered_through IS NOT NULL
 GROUP BY a.id;

-- an instance's document coverage, for waiting for a document (spec §5.5,
-- §5.8). An instance with no row here has never run, and holds the
-- transactions of its providers dated from its start date on.
CREATE VIEW v_document_coverage AS
SELECT importer_instance_id, max(covered_through) AS covered_through
  FROM import_run
 WHERE emits = 'documents' AND status = 'ok'
   AND covered_through IS NOT NULL AND importer_instance_id IS NOT NULL
 GROUP BY importer_instance_id;

-- data age: synced_through for a synced account, the latest counting
-- balance record for an unsynced one; NULL = "never". A manual record on a
-- synced account does not reset it. The UI turns it into days against today
-- (spec §3.11).
CREATE VIEW v_account_data_age AS
SELECT a.account_id,
       CASE WHEN a.synced THEN c.synced_through
            ELSE (SELECT max(b.balance_on) FROM v_balance_record b
                   WHERE b.account_id = a.account_id)
       END AS last_data_on
  FROM v_account_synced a
  JOIN v_account_coverage c ON c.account_id = a.account_id;

-- when each credential last ran, read from its runs (spec §5.4)
CREATE VIEW v_importer_last_run AS
SELECT importer_instance_id, max(started_at) AS last_run_at
  FROM import_run
 WHERE importer_instance_id IS NOT NULL
 GROUP BY importer_instance_id;

-- informational, not an error: a transfer leg whose partner has not arrived
CREATE VIEW v_open_transfer_legs AS
SELECT e.id AS entry_id, e.account_id, e.amount, e.currency, e.booked_on
  FROM ledger_entry e
 WHERE e.type = 'transfer' AND e.counterpart_entry_id IS NULL;

-- ---------------------------------------------------------------------
-- 10. Conversion and reporting helpers
-- ---------------------------------------------------------------------

-- THE conversion to the base currency — the only place an amount is
-- converted, called only by reporting (spec §3.8, §8, I27). Latest rate on or before p_on,
-- no older than the maximum rate age (the connection setting
-- ledger.max_rate_age, an interval; unset is an error, never a default); returns
-- NULL (unvalued) where there is none, never zero. Rounds half-even to the base currency's minor unit.
CREATE OR REPLACE FUNCTION base_value(p_amount bigint, p_currency char(3), p_on date)
RETURNS bigint AS $$
DECLARE
    v_base     char(3);
    v_max_age  interval;
    v_base_mu  smallint;
    v_ccy_mu   smallint;
    v_per_base numeric;
    v_num      numeric;
    v_den      numeric;
    v_q        numeric;
    v_r        numeric;
BEGIN
    v_max_age := current_setting('ledger.max_rate_age')::interval;
    SELECT s.base_currency, c.minor_units
      INTO v_base, v_base_mu
      FROM ledger_setting s JOIN currency c ON c.code = s.base_currency;
    IF p_currency = v_base THEN
        RETURN p_amount;
    END IF;

    SELECT r.per_base INTO v_per_base
      FROM fx_rate r
     WHERE r.currency = p_currency AND r.rate_date <= p_on
       AND r.rate_date >= p_on - v_max_age
     ORDER BY r.rate_date DESC
     LIMIT 1;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    SELECT minor_units INTO v_ccy_mu FROM currency WHERE code = p_currency;
    -- exact: amount · 10^(base mu − ccy mu) / per_base as a ratio of integers
    -- (per_base has scale 10), then half-even on the remainder, no inexact step
    v_num := p_amount::numeric
             * power(10::numeric, greatest(v_base_mu - v_ccy_mu, 0) + 10);
    v_den := trunc(v_per_base * power(10::numeric, 10))
             * power(10::numeric, greatest(v_ccy_mu - v_base_mu, 0));
    v_q := div(v_num, v_den);                       -- truncates toward zero
    v_r := abs(v_num - v_q * v_den);
    IF 2 * v_r > v_den OR (2 * v_r = v_den AND mod(v_q, 2) <> 0) THEN
        v_q := v_q + sign(v_num);
    END IF;
    RETURN v_q::bigint;
END;
$$ LANGUAGE plpgsql STABLE;

-- Balance is ALWAYS the ledger layer only, in the account's own currency.
-- The provenance layer never enters an aggregate, or you double-count.
CREATE VIEW v_account_balance AS
SELECT a.id AS account_id, a.name, a.kind, a.currency,
       COALESCE(sum(e.amount), 0) AS balance
  FROM account a
  LEFT JOIN ledger_entry e ON e.account_id = a.id
 GROUP BY a.id, a.name, a.kind, a.currency;

-- Flows, each converted at its own booked_on rate. Derived entries (openings,
-- valuations, reconciliations) and transfers are excluded; they have their
-- own lines and still count towards net worth. Entries not yet interpreted
-- (type NULL) are included with a NULL category_kind and, with flows without
-- a category, are the "Unclassified" line; they count in savings. Savings
-- also include reconciliations, which are not flows and are summed
-- separately. A NULL base_amount is unvalued, never zero. Spec §8.
CREATE VIEW v_flows AS
SELECT e.*, c.kind AS category_kind,
       base_value(e.amount, e.currency, e.booked_on) AS base_amount
  FROM ledger_entry e
  LEFT JOIN category c ON c.id = e.category_id
 WHERE e.type = 'flow' OR e.type IS NULL;

-- Net worth at a date: every account's balance on that date, converted at
-- that date's rate — the sum of those that can be valued, with the others
-- counted for the unvalued line, never zeroed (spec §8).
CREATE OR REPLACE FUNCTION net_worth_on(p_on date)
RETURNS TABLE (net_worth bigint, unvalued_accounts integer) AS $$
    WITH bal AS (
        SELECT a.currency, COALESCE(sum(e.amount), 0)::bigint AS balance
          FROM account a
          LEFT JOIN ledger_entry e
                 ON e.account_id = a.id AND e.booked_on <= p_on
         GROUP BY a.id, a.currency
    ), val AS (
        SELECT CASE WHEN balance = 0 THEN 0
                    ELSE base_value(balance, currency, p_on) END AS v
          FROM bal
    )
    SELECT COALESCE(sum(v), 0)::bigint,
           (count(*) FILTER (WHERE v IS NULL))::integer
      FROM val;
$$ LANGUAGE sql STABLE;

-- derived tag spans, replacing stored starts_on / ends_on
CREATE VIEW v_tag_span AS
SELECT t.id AS tag_id, t.name,
       min(e.booked_on) AS starts_on, max(e.booked_on) AS ends_on,
       count(*) AS entry_count
  FROM tag t
  JOIN ledger_entry_tag et ON et.tag_id = t.id
  JOIN ledger_entry e ON e.id = et.ledger_entry_id
 GROUP BY t.id, t.name;

COMMIT;
