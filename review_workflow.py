"""SQLite persistence for student course reviews."""

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator


REVIEW_STATUSES = {"Pending", "Approved", "Rejected"}


def _normalize_header(value: str) -> str:
    value = str(value or "").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return re.sub(r"\s+", " ", value).strip()


def validate_review(review: dict) -> dict:
    """Validate and normalize a student review before it is stored."""
    cleaned = {
        "course": str(review.get("course", "")).strip(),
        "course_name": str(review.get("course_name", "")).strip(),
        "assignments": str(review.get("assignments", "")).strip(),
        "instructor": str(review.get("instructor", "")).strip(),
        "term": str(review.get("term", "")).strip(),
        "year": review.get("year"),
        "difficulty_rating": review.get("difficulty_rating"),
        "usefulness_rating": review.get("usefulness_rating"),
        "liked": review.get("liked"),
        "review": str(review.get("review", "")).strip(),
    }
    for field in ("course", "instructor", "term", "assignments", "review"):
        if not cleaned[field]:
            raise ValueError(f"{field.replace('_', ' ').title()} is required.")
    if cleaned["course"].casefold() == "other" and not cleaned["course_name"]:
        raise ValueError("Enter the course name for Other.")
    if len(cleaned["course_name"]) > 200:
        raise ValueError("Course name must be 200 characters or fewer.")
    if len(cleaned["assignments"]) > 1000:
        raise ValueError("Assignments / assessments must be 1,000 characters or fewer.")

    if cleaned["term"] not in {"Fall", "Spring"}:
        raise ValueError("Term must be Fall or Spring.")
    if (
        not isinstance(cleaned["year"], int)
        or not 2000 <= cleaned["year"] <= datetime.now().year + 1
    ):
        raise ValueError("Select a valid course year.")
    for field in ("difficulty_rating", "usefulness_rating"):
        value = cleaned[field]
        if not isinstance(value, int) or not 1 <= value <= 10:
            raise ValueError(f"{field.replace('_', ' ').title()} must be from 1 to 10.")
    if not isinstance(cleaned["liked"], bool):
        raise ValueError("Select whether you liked the class.")
    if len(cleaned["review"]) > 3000:
        raise ValueError("Review must be 3,000 characters or fewer.")
    return cleaned


@contextmanager
def _connect(database_path: str | Path) -> Iterator[sqlite3.Connection]:
    path = Path(database_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(database_path: str | Path) -> None:
    """Create the review table if it does not exist."""
    with _connect(database_path) as connection:
        existing = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'reviews'"
        ).fetchone()
        if existing:
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(reviews)").fetchall()
            }
            for name, definition in (
                ("difficulty_rating", "INTEGER"),
                ("usefulness_rating", "INTEGER"),
                ("liked", "INTEGER"),
                ("course_name", "TEXT NOT NULL DEFAULT ''"),
                ("assignments", "TEXT NOT NULL DEFAULT ''"),
            ):
                if name not in columns:
                    connection.execute(f"ALTER TABLE reviews ADD COLUMN {name} {definition}")
            return

        connection.execute(_create_reviews_table_sql())


def _create_reviews_table_sql() -> str:
    return """
        CREATE TABLE IF NOT EXISTS reviews (
            review_id TEXT PRIMARY KEY,
            submitted_at TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('Pending', 'Approved', 'Rejected')),
            course TEXT NOT NULL,
            instructor TEXT NOT NULL,
            term TEXT NOT NULL CHECK (term IN ('Fall', 'Spring')),
            year INTEGER NOT NULL,
            difficulty_rating INTEGER CHECK (difficulty_rating BETWEEN 1 AND 10),
            usefulness_rating INTEGER CHECK (usefulness_rating BETWEEN 1 AND 10),
            liked INTEGER CHECK (liked IN (0, 1)),
            course_name TEXT NOT NULL DEFAULT '',
            assignments TEXT NOT NULL,
            review TEXT NOT NULL CHECK (length(review) <= 3000)
        )
    """


def add_pending_review(
    database_path: str | Path,
    review_id: str,
    submitted_at: str,
    review: dict,
) -> None:
    """Save a validated review awaiting moderation."""
    cleaned = validate_review(review)
    initialize_database(database_path)
    with _connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO reviews (
                review_id, submitted_at, status, course, course_name, assignments,
                instructor, term, year, difficulty_rating, usefulness_rating, liked, review
            ) VALUES (?, ?, 'Pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review_id,
                submitted_at,
                cleaned["course"],
                cleaned["course_name"],
                cleaned["assignments"],
                cleaned["instructor"],
                cleaned["term"],
                cleaned["year"],
                cleaned["difficulty_rating"],
                cleaned["usefulness_rating"],
                int(cleaned["liked"]),
                cleaned["review"],
            ),
        )


def get_reviews(database_path: str | Path, status: str | None = None) -> list[dict]:
    """Return reviews, optionally filtered by moderation status."""
    initialize_database(database_path)
    with _connect(database_path) as connection:
        if status is None:
            rows = connection.execute(
                "SELECT * FROM reviews ORDER BY submitted_at DESC"
            ).fetchall()
        else:
            if status not in REVIEW_STATUSES:
                raise ValueError("Unknown review status.")
            rows = connection.execute(
                "SELECT * FROM reviews WHERE status = ? ORDER BY submitted_at DESC",
                (status,),
            ).fetchall()
    return [dict(row) for row in rows]


def set_review_status(database_path: str | Path, review_id: str, status: str) -> None:
    """Approve or reject a review that is still pending."""
    if status not in {"Approved", "Rejected"}:
        raise ValueError("Review status must be Approved or Rejected.")
    initialize_database(database_path)
    with _connect(database_path) as connection:
        cursor = connection.execute(
            """
            UPDATE reviews
            SET status = ?
            WHERE review_id = ? AND status = 'Pending'
            """,
            (status, review_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Pending review was not found or was already processed.")


def append_approved_review_to_worksheet(
    worksheet,
    review: dict,
    source_columns: dict[str, str],
) -> bool:
    """Append an approved review using only the existing course-response columns.

    Returns False if the exact review row already exists in the sheet.
    """
    values = worksheet.get_all_values()
    if not values:
        raise ValueError("The course-response worksheet must have a header row.")

    original_headers = [str(header) for header in values[0]]
    headers = [_normalize_header(header) for header in original_headers]
    required_fields = (
        "timestamp", "course", "course_name", "assignments", "instructor", "semester",
        "difficulty", "usefulness", "liked", "comments",
    )
    normalized_source_columns = {
        field: _normalize_header(column)
        for field, column in source_columns.items()
    }
    missing = [
        source_columns[field]
        for field in required_fields
        if normalized_source_columns[field] not in headers
    ]
    if missing:
        raise ValueError(
            "The course-response worksheet is missing required columns: "
            + ", ".join(missing)
        )

    indexes = {header: index for index, header in enumerate(headers)}
    row = [""] * len(headers)
    row[indexes[normalized_source_columns["timestamp"]]] = review["submitted_at"]
    row[indexes[normalized_source_columns["course"]]] = review["course"]
    row[indexes[normalized_source_columns["course_name"]]] = review["course_name"]
    row[indexes[normalized_source_columns["assignments"]]] = review["assignments"]
    row[indexes[normalized_source_columns["instructor"]]] = review["instructor"]
    row[indexes[normalized_source_columns["semester"]]] = f'{review["term"]} {review["year"]}'
    row[indexes[normalized_source_columns["difficulty"]]] = review["difficulty_rating"]
    row[indexes[normalized_source_columns["usefulness"]]] = review["usefulness_rating"]
    row[indexes[normalized_source_columns["liked"]]] = "Yes" if review["liked"] else "No"
    row[indexes[normalized_source_columns["comments"]]] = review["review"]

    expected_row = [str(value) for value in row]
    if any(
        [str(value) for value in existing_row[:len(headers)]]
        + [""] * max(0, len(headers) - len(existing_row))
        == expected_row
        for existing_row in values[1:]
    ):
        return False

    worksheet.append_row(row, value_input_option="RAW")
    return True
