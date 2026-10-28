"""Persist structured discovery milestones without credentials or command output."""
from psycopg.types.json import Jsonb

from db import database


def save_progress(job_id, progress):
    with database() as conn:
        conn.execute("""UPDATE discoveries SET progress=%s,progress_updated_at=now()
                        WHERE id=%s AND status='running'""", (Jsonb(progress), job_id))
