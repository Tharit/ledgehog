"""Structural snapshot of a database, for comparing two ways of building the same schema."""

from __future__ import annotations

from typing import Any

import psycopg

_SKIP = "alembic_version"

QUERIES: dict[str, str] = {
    "extensions": "SELECT extname FROM pg_extension ORDER BY 1",
    "relations": f"""
        SELECT c.relkind::text, c.relname FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname NOT LIKE '{_SKIP}%'
          AND c.relkind IN ('r','v','m','S','p') ORDER BY 1, 2""",
    "columns": f"""
        SELECT table_name, column_name, ordinal_position, data_type, udt_name,
               character_maximum_length, numeric_precision, numeric_scale, is_nullable,
               column_default, is_identity, identity_generation, is_generated,
               generation_expression
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name <> '{_SKIP}'
        ORDER BY table_name, ordinal_position""",
    "constraints": f"""
        SELECT conrelid::regclass::text, conname, contype::text,
               pg_get_constraintdef(oid), condeferrable, condeferred
        FROM pg_constraint
        WHERE connamespace = 'public'::regnamespace AND conrelid::regclass::text <> '{_SKIP}'
        ORDER BY 1, 2""",
    "indexes": f"""
        SELECT tablename, indexname, indexdef FROM pg_indexes
        WHERE schemaname = 'public' AND tablename <> '{_SKIP}' ORDER BY 1, 2""",
    "triggers": f"""
        SELECT tgrelid::regclass::text, tgname, pg_get_triggerdef(oid), tgenabled::text
        FROM pg_trigger
        WHERE NOT tgisinternal AND tgrelid::regclass::text <> '{_SKIP}' ORDER BY 1, 2""",
    "functions": """
        SELECT p.proname, pg_get_functiondef(p.oid) FROM pg_proc p
        WHERE p.pronamespace = 'public'::regnamespace
          AND NOT EXISTS (SELECT 1 FROM pg_depend d
                          WHERE d.objid = p.oid AND d.deptype = 'e')
        ORDER BY 1, 2""",
    "views": """
        SELECT viewname, definition FROM pg_views WHERE schemaname = 'public' ORDER BY 1""",
    "comments": f"""
        SELECT c.relname, a.attname, d.description
        FROM pg_description d
        JOIN pg_class c ON c.oid = d.objoid AND d.classoid = 'pg_class'::regclass
        LEFT JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = d.objsubid AND d.objsubid > 0
        WHERE c.relnamespace = 'public'::regnamespace AND c.relname NOT LIKE '{_SKIP}%'
        ORDER BY 1, 2 NULLS FIRST""",
}


def snapshot(conn: psycopg.Connection[Any]) -> dict[str, list[tuple[Any, ...]]]:
    snap = {name: [tuple(r) for r in conn.execute(q).fetchall()] for name, q in QUERIES.items()}
    tables = [r[1] for r in snap["relations"] if r[0] in ("r", "p")]
    for table in tables:
        snap[f"data:{table}"] = [
            tuple(r)
            for r in conn.execute(
                f'SELECT row_to_json(t)::text FROM "{table}" t ORDER BY 1'  # noqa: S608
            ).fetchall()
        ]
    return snap


def diff(a: dict[str, list[tuple[Any, ...]]], b: dict[str, list[tuple[Any, ...]]]) -> list[str]:
    problems: list[str] = []
    for key in sorted(set(a) | set(b)):
        ra, rb = a.get(key, []), b.get(key, [])
        if ra == rb:
            continue
        only_a = [r for r in ra if r not in rb]
        only_b = [r for r in rb if r not in ra]
        problems.append(f"[{key}] only in migrations: {only_a[:3]!r} | only in schema.sql: {only_b[:3]!r}")
    return problems
