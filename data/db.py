import sqlite3
import os
import time
from typing import List, Dict, Any, Optional, Tuple

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "applications.db")

class JobDatabase:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        """Initialize sqlite database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                company TEXT NOT NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                subcategories TEXT,
                terms TEXT DEFAULT 'Summer 2027',
                location TEXT,
                url TEXT UNIQUE NOT NULL,
                ats_type TEXT DEFAULT 'generic',
                sponsorship TEXT,
                degrees TEXT,
                date_posted TEXT,
                status TEXT DEFAULT 'NEW',
                notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            # Check if terms column exists in older db
            cursor.execute("PRAGMA table_info(jobs)")
            cols = [col[1] for col in cursor.fetchall()]
            if "terms" not in cols:
                cursor.execute("ALTER TABLE jobs ADD COLUMN terms TEXT DEFAULT 'Summer 2027'")

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_category ON jobs (category)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_url ON jobs (url)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_terms ON jobs (terms)")
            conn.commit()

    def upsert_job(self, job: Dict[str, Any]) -> bool:
        """Insert or update a job posting."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, status FROM jobs WHERE url = ?", (job["url"],))
            existing = cursor.fetchone()
            
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            subs = ",".join(job.get("subcategories", [])) if isinstance(job.get("subcategories"), list) else str(job.get("subcategories", ""))
            terms_str = ",".join(job.get("terms", [])) if isinstance(job.get("terms"), list) else str(job.get("terms", "Summer 2027"))

            if existing:
                cursor.execute("""
                UPDATE jobs SET 
                    company = ?,
                    title = ?,
                    category = ?,
                    subcategories = ?,
                    terms = ?,
                    location = ?,
                    ats_type = ?,
                    sponsorship = ?,
                    degrees = ?,
                    date_posted = ?,
                    updated_at = ?
                WHERE url = ?
                """, (
                    job.get("company", ""),
                    job.get("title", ""),
                    job.get("category", "other"),
                    subs,
                    terms_str,
                    job.get("location", ""),
                    job.get("ats_type", "generic"),
                    job.get("sponsorship", ""),
                    job.get("degrees", ""),
                    str(job.get("date_posted", "")),
                    now,
                    job["url"]
                ))
                conn.commit()
                return False
            else:
                cursor.execute("""
                INSERT INTO jobs (
                    id, company, title, category, subcategories, terms, location, 
                    url, ats_type, sponsorship, degrees, date_posted, status, notes, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    job.get("id", str(time.time_ns())),
                    job.get("company", ""),
                    job.get("title", ""),
                    job.get("category", "other"),
                    subs,
                    terms_str,
                    job.get("location", ""),
                    job.get("url", ""),
                    job.get("ats_type", "generic"),
                    job.get("sponsorship", ""),
                    job.get("degrees", ""),
                    str(job.get("date_posted", "")),
                    job.get("status", "NEW"),
                    job.get("notes", ""),
                    now
                ))
                conn.commit()
                return True

    def upsert_jobs_batch(self, jobs: List[Dict[str, Any]]) -> Tuple[int, int]:
        """Batch upsert jobs using a single transaction."""
        new_count = 0
        updated_count = 0
        now = time.strftime("%Y-%m-%d %H:%M:%S")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT url FROM jobs")
            existing_urls = {row[0] for row in cursor.fetchall()}

            to_insert = []
            to_update = []

            for job in jobs:
                url = job.get("url")
                if not url:
                    continue

                subs = ",".join(job.get("subcategories", [])) if isinstance(job.get("subcategories"), list) else str(job.get("subcategories", ""))
                terms_str = ",".join(job.get("terms", [])) if isinstance(job.get("terms"), list) else str(job.get("terms", "Summer 2027"))

                if url in existing_urls:
                    to_update.append((
                        job.get("company", ""),
                        job.get("title", ""),
                        job.get("category", "other"),
                        subs,
                        terms_str,
                        job.get("location", ""),
                        job.get("ats_type", "generic"),
                        job.get("sponsorship", ""),
                        job.get("degrees", ""),
                        str(job.get("date_posted", "")),
                        now,
                        url
                    ))
                else:
                    to_insert.append((
                        job.get("id", str(time.time_ns())),
                        job.get("company", ""),
                        job.get("title", ""),
                        job.get("category", "other"),
                        subs,
                        terms_str,
                        job.get("location", ""),
                        url,
                        job.get("ats_type", "generic"),
                        job.get("sponsorship", ""),
                        job.get("degrees", ""),
                        str(job.get("date_posted", "")),
                        job.get("status", "NEW"),
                        job.get("notes", ""),
                        now,
                        now
                    ))
                    existing_urls.add(url)

            if to_insert:
                cursor.executemany("""
                INSERT OR IGNORE INTO jobs (
                    id, company, title, category, subcategories, terms, location, 
                    url, ats_type, sponsorship, degrees, date_posted, status, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, to_insert)
                new_count = len(to_insert)

            if to_update:
                cursor.executemany("""
                UPDATE jobs SET 
                    company = ?,
                    title = ?,
                    category = ?,
                    subcategories = ?,
                    terms = ?,
                    location = ?,
                    ats_type = ?,
                    sponsorship = ?,
                    degrees = ?,
                    date_posted = ?,
                    updated_at = ?
                WHERE url = ?
                """, to_update)
                updated_count = len(to_update)

            conn.commit()

        return new_count, updated_count

    def get_jobs(
        self,
        category: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        ats_type: Optional[str] = None,
        term: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Query jobs with category, term/season, and status filters."""
        query = "SELECT * FROM jobs WHERE 1=1"
        params = []

        if category and category.lower() != "all":
            query += " AND (category = ? OR subcategories LIKE ?)"
            params.extend([category, f"%{category}%"])

        if status and status.upper() != "ALL":
            query += " AND status = ?"
            params.append(status.upper())

        if ats_type and ats_type.lower() != "all":
            query += " AND ats_type = ?"
            params.append(ats_type.lower())

        if term and term.lower() != "all":
            query += " AND terms LIKE ?"
            params.append(f"%{term}%")

        if search:
            query += " AND (company LIKE ? OR title LIKE ? OR location LIKE ?)"
            term_param = f"%{search}%"
            params.extend([term_param, term_param, term_param])

        query += " ORDER BY updated_at DESC, date_posted DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_job_by_url(self, url: str) -> Optional[Dict[str, Any]]:
        """Retrieve job by URL."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM jobs WHERE url = ?", (url,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_job_status(self, url: str, status: str, notes: Optional[str] = None) -> bool:
        """Update job application status."""
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if notes is not None:
                cursor.execute(
                    "UPDATE jobs SET status = ?, notes = ?, updated_at = ? WHERE url = ?",
                    (status.upper(), notes, now, url)
                )
            else:
                cursor.execute(
                    "UPDATE jobs SET status = ?, updated_at = ? WHERE url = ?",
                    (status.upper(), now, url)
                )
            conn.commit()
            return cursor.rowcount > 0

    def clear_database(self) -> None:
        """Clear all records from database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM jobs")
            conn.commit()

    def get_stats(self, term: Optional[str] = None) -> Dict[str, Any]:
        """Return aggregate statistics about tracked jobs."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            term_clause = ""
            term_params = []
            if term and term.lower() != "all":
                term_clause = " WHERE terms LIKE ?"
                term_params.append(f"%{term}%")

            cursor.execute(f"SELECT COUNT(*) FROM jobs{term_clause}", term_params)
            total = cursor.fetchone()[0]

            cursor.execute(f"SELECT category, COUNT(*) FROM jobs{term_clause} GROUP BY category", term_params)
            categories = dict(cursor.fetchall())

            cursor.execute(f"SELECT status, COUNT(*) FROM jobs{term_clause} GROUP BY status", term_params)
            statuses = dict(cursor.fetchall())

            cursor.execute(f"SELECT ats_type, COUNT(*) FROM jobs{term_clause} GROUP BY ats_type", term_params)
            ats_types = dict(cursor.fetchall())

            return {
                "total": total,
                "categories": categories,
                "statuses": statuses,
                "ats_types": ats_types
            }
