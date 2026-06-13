"""PostgreSQL persistence for users, projects, jobs, and revisions."""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.config import get_settings

MIGRATIONS: list[tuple[str, str]] = [
    (
        "001_users_projects_jobs_revisions",
        """
        CREATE TABLE IF NOT EXISTS users (
            email TEXT PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            user_email TEXT NOT NULL REFERENCES users(email) ON DELETE CASCADE,
            readme TEXT NOT NULL,
            readme_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            user_email TEXT NOT NULL REFERENCES users(email) ON DELETE CASCADE,
            thread_id TEXT NOT NULL,
            parent_job_id TEXT NULL REFERENCES jobs(job_id) ON DELETE SET NULL,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            current_step TEXT,
            request_json JSONB NOT NULL,
            result_json JSONB,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS revisions (
            id BIGSERIAL PRIMARY KEY,
            parent_job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
            child_job_id TEXT NOT NULL UNIQUE REFERENCES jobs(job_id) ON DELETE CASCADE,
            instruction TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS jobs_user_created_idx ON jobs(user_email, created_at DESC);
        CREATE INDEX IF NOT EXISTS projects_user_created_idx ON projects(user_email, created_at DESC);
        CREATE INDEX IF NOT EXISTS jobs_thread_created_idx ON jobs(thread_id, created_at ASC);
        CREATE INDEX IF NOT EXISTS jobs_project_created_idx ON jobs(project_id, created_at DESC);
        """,
    ),
    (
        "002_drop_legacy_tone_column",
        """
        ALTER TABLE users DROP COLUMN IF EXISTS tone_md;
        """,
    ),
]


@contextmanager
def connect():
    with psycopg.connect(get_settings().DATABASE_URL, row_factory=dict_row) as conn:
        yield conn


def init_db() -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute("SELECT version FROM schema_migrations")
        applied = {row["version"] for row in cur.fetchall()}
        for version, sql in MIGRATIONS:
            if version in applied:
                continue
            cur.execute(sql)
            cur.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s)",
                (version,),
            )
        conn.commit()


def project_id_for_readme(readme: str) -> str:
    normalized = "\n".join(line.rstrip() for line in readme.strip().splitlines())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def upsert_user(email: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (email)
            VALUES (%s)
            ON CONFLICT (email) DO UPDATE
            SET updated_at = NOW();
            """,
            (email,),
        )
        conn.commit()


def get_user(email: str) -> dict[str, Any] | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT email, created_at, updated_at FROM users WHERE email = %s", (email,))
        return cur.fetchone()


def upsert_project(project_id: str, email: str, readme: str) -> None:
    readme_hash = project_id_for_readme(readme)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, user_email, readme, readme_hash)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
            SET readme = EXCLUDED.readme,
                readme_hash = EXCLUDED.readme_hash,
                updated_at = NOW()
            """,
            (project_id, email, readme, readme_hash),
        )
        conn.commit()


def create_job_record(
    *,
    job_id: str,
    email: str,
    thread_id: str,
    parent_job_id: str | None,
    project_id: str,
    payload: dict[str, Any],
    revision_instruction: str | None = None,
) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO jobs (
                job_id, user_email, thread_id, parent_job_id, project_id,
                status, current_step, request_json
            )
            VALUES (%s, %s, %s, %s, %s, 'queued', 'queued', %s::jsonb)
            """,
            (job_id, email, thread_id, parent_job_id, project_id, json.dumps(payload)),
        )
        if parent_job_id and revision_instruction:
            cur.execute(
                """
                INSERT INTO revisions (parent_job_id, child_job_id, instruction)
                VALUES (%s, %s, %s)
                ON CONFLICT (child_job_id) DO NOTHING
                """,
                (parent_job_id, job_id, revision_instruction),
            )
        conn.commit()


def update_job_progress(job_id: str, status: str, current_step: str | None = None) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs
            SET status = %s,
                current_step = COALESCE(%s, current_step),
                updated_at = NOW()
            WHERE job_id = %s
            """,
            (status, current_step, job_id),
        )
        conn.commit()


def complete_job(job_id: str, result: dict[str, Any]) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs
            SET status = 'completed',
                current_step = 'completed',
                result_json = %s::jsonb,
                error = NULL,
                updated_at = NOW()
            WHERE job_id = %s
            """,
            (json.dumps(result), job_id),
        )
        conn.commit()


def mark_job_awaiting_approval(job_id: str, result: dict[str, Any]) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs
            SET status = 'awaiting_approval',
                current_step = 'awaiting_approval',
                result_json = %s::jsonb,
                error = NULL,
                updated_at = NOW()
            WHERE job_id = %s
            """,
            (json.dumps(result), job_id),
        )
        conn.commit()


def approve_job(email: str, job_id: str) -> bool:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs
            SET status = 'completed',
                current_step = 'completed',
                updated_at = NOW()
            WHERE job_id = %s AND user_email = %s AND status = 'awaiting_approval'
            """,
            (job_id, email),
        )
        approved = cur.rowcount > 0
        conn.commit()
        return approved


def fail_job(job_id: str, error: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs
            SET status = 'failed',
                current_step = 'failed',
                error = %s,
                updated_at = NOW()
            WHERE job_id = %s
            """,
            (error, job_id),
        )
        conn.commit()


def get_job_record(job_id: str) -> dict[str, Any] | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT job_id, user_email, thread_id, parent_job_id, project_id, status,
                   current_step, request_json, result_json, error, created_at, updated_at
            FROM jobs
            WHERE job_id = %s
            """,
            (job_id,),
        )
        return cur.fetchone()


def get_user_history(email: str, limit: int = 20) -> list[dict[str, Any]]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT job_id, thread_id, parent_job_id, status, current_step, request_json,
                   result_json, error, created_at, updated_at
            FROM jobs
            WHERE user_email = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (email, limit),
        )
        return list(cur.fetchall())


def get_user_projects(email: str, limit: int = 20) -> list[dict[str, Any]]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (p.id)
                p.id AS project_id,
                p.readme,
                p.readme_hash,
                p.created_at AS project_created_at,
                p.updated_at AS project_updated_at,
                j.job_id,
                j.thread_id,
                j.parent_job_id,
                j.status,
                j.current_step,
                j.request_json,
                j.result_json,
                j.error,
                j.created_at,
                j.updated_at
            FROM projects p
            LEFT JOIN jobs j ON j.project_id = p.id
            WHERE p.user_email = %s
            ORDER BY p.id, j.created_at DESC NULLS LAST
            LIMIT %s
            """,
            (email, limit),
        )
        return list(cur.fetchall())


def delete_job(email: str, job_id: str) -> dict[str, Any] | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT job_id, project_id, thread_id
            FROM jobs
            WHERE job_id = %s AND user_email = %s
            """,
            (job_id, email),
        )
        row = cur.fetchone()
        if not row:
            return None
        cur.execute("DELETE FROM jobs WHERE job_id = %s AND user_email = %s", (job_id, email))
        conn.commit()
        return row


def delete_project(email: str, project_id: str) -> bool:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM projects WHERE id = %s AND user_email = %s",
            (project_id, email),
        )
        deleted = cur.rowcount > 0
        conn.commit()
        return deleted
