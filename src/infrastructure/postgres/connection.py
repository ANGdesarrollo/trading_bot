from __future__ import annotations

import psycopg


def connect(database_url: str):
    return psycopg.connect(database_url)
