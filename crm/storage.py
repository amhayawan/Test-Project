"""Database location, schema upgrades, backups and copying between databases."""

import configparser
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import MetaData, create_engine, inspect, select, text
from sqlalchemy.engine import make_url

LOCAL_HOSTS = {None, "", "localhost", "127.0.0.1", "::1"}


def resolve_database_url(data_dir, explicit=None):
    """Pick the database: explicit value > HAZ_CRM_DATABASE_URL > settings.ini > local SQLite file."""
    url = explicit or os.environ.get("HAZ_CRM_DATABASE_URL")
    if not url:
        ini = Path(data_dir) / "settings.ini"
        if ini.exists():
            cfg = configparser.ConfigParser(interpolation=None)
            cfg.read(ini, encoding="utf-8")
            url = cfg.get("database", "url", fallback="").strip() or None
    if not url:
        return f"sqlite:///{Path(data_dir) / 'crm.db'}"
    return normalize_url(url)


def normalize_url(url):
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    parsed = make_url(url)
    if parsed.drivername in ("postgresql", "postgres"):
        parsed = parsed.set(drivername="postgresql+psycopg")
    if parsed.get_backend_name() == "postgresql":
        # Never send passwords and personal data over the internet unencrypted.
        if parsed.host not in LOCAL_HOSTS and "sslmode" not in parsed.query:
            parsed = parsed.update_query_dict({"sslmode": "require"})
    return parsed.render_as_string(hide_password=False)


def masked(url):
    return make_url(url).render_as_string(hide_password=True)


def is_sqlite(url):
    return make_url(url).get_backend_name() == "sqlite"


def sqlite_path(url):
    return make_url(url).database


def upgrade_schema(engine, added_columns):
    """Add columns introduced after the first release (create_all never alters tables)."""
    insp = inspect(engine)
    quote = engine.dialect.identifier_preparer.quote
    with engine.begin() as conn:
        for table, columns in added_columns.items():
            if not insp.has_table(table):
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {quote(table)} ADD COLUMN {quote(name)} {ddl}"))


# ---------------------------------------------------------------- copying

def copy_database(src_url, dst_url, metadata):
    """Copy every table from one database to another (e.g. local SQLite -> cloud PostgreSQL).

    The target must be empty. Returns {table: row_count}.
    """
    src = create_engine(src_url)
    dst = create_engine(dst_url)
    try:
        metadata.create_all(dst)
        counts = {}
        with src.connect() as s, dst.begin() as d:
            for table in metadata.sorted_tables:
                if d.execute(select(table).limit(1)).first() is not None:
                    raise RuntimeError(f"Target database is not empty (table '{table.name}' has data).")
            for table in metadata.sorted_tables:
                rows = [dict(r._mapping) for r in s.execute(select(table))]
                if rows:
                    d.execute(table.insert(), rows)
                counts[table.name] = len(rows)
            if dst.dialect.name == "postgresql":
                q = dst.dialect.identifier_preparer.quote
                for table in metadata.sorted_tables:
                    if "id" in table.c:
                        d.execute(text(
                            f"SELECT setval(pg_get_serial_sequence('{q(table.name)}', 'id'), "
                            f"COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {q(table.name)}"))
        return counts
    finally:
        src.dispose()
        dst.dispose()


# ---------------------------------------------------------------- backups

def backup_bytes(db_url, metadata):
    """A complete backup as a portable SQLite file, whatever database is in use."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "backup.db"
        if is_sqlite(db_url):
            _sqlite_copy(sqlite_path(db_url), out)
        else:
            copy_database(db_url, f"sqlite:///{out}", metadata)
        return out.read_bytes()


def _sqlite_copy(src_path, dst_path):
    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(dst_path)
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close()
        dst.close()


def auto_backup(db_url, backup_dir, metadata, keep=30, min_age=timedelta(hours=20)):
    """Write a dated backup if the newest one is older than `min_age`; keep the last `keep`.

    Returns the new file path, or None when no backup was needed.
    """
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(backup_dir.glob("haz-crm-*.db"))
    if existing and datetime.now() - datetime.fromtimestamp(existing[-1].stat().st_mtime) < min_age:
        return None
    path = backup_dir / f"haz-crm-{datetime.now():%Y%m%d-%H%M%S}.db"
    path.write_bytes(backup_bytes(db_url, metadata))
    for old in sorted(backup_dir.glob("haz-crm-*.db"))[:-keep]:
        old.unlink()
    return path
