"""SQLite-backed repository for SegmentAttempt entities."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from transrealm.domain.segment_attempt import SegmentAttempt, SegmentAttemptError
from transrealm.domain.translation_revision import TranslationRevision
from transrealm.infrastructure.database import DatabaseConnection, create_database, transaction

_ATTEMPT_COLUMNS = (
    "id, run_id, segment_id, claim_version, lease_owner, idempotency_key, "
    "model_profile_id, profile_snapshot, prompt_hash, context_summary, "
    "validator_summary, request_id, status, retryable, input_tokens, output_tokens, "
    "latency_ms, error_type, error_message, created_at, finished_at"
)


class SegmentAttemptRepository:
    """SQLite-backed repository for SegmentAttempt entities."""

    def __init__(self, db: DatabaseConnection) -> None:
        self._db = db

    @classmethod
    def open(cls, path: Path) -> SegmentAttemptRepository:
        """Open a repository for the database at ``path``."""
        return cls(create_database(path))

    def create_after_claim(
        self,
        *,
        run_id: int,
        segment_id: int,
        expected_version: int,
        lease_owner: str,
        lease_expires_at: datetime,
        idempotency_key: str,
        model_profile_id: int,
        profile_snapshot: dict[str, object],
        prompt_hash: str,
        context_summary: dict[str, object],
        validator_summary: dict[str, object],
        now: datetime,
    ) -> SegmentAttempt:
        """Atomically claim a segment and persist an attempt.

        The claim only succeeds when the segment is ``pending`` with the expected
        version and its lease is empty or already expired. If an attempt with the
        same ``idempotency_key`` already exists, it is returned without modifying
        the segment or creating a second attempt.

        This guarantees that duplicate submissions of the same logical request do
        not result in a second external model call.
        """
        now_iso = now.isoformat()

        with transaction(self._db):
            existing = self.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                if existing.run_id != run_id or existing.segment_id != segment_id:
                    raise SegmentAttemptError(
                        "idempotency_key belongs to a different run/segment.",
                    )
                return existing

            cursor = self._db.execute(
                "UPDATE segments SET status = ?, version = version + 1, lease_owner = ?, "
                "lease_expires_at = ?, updated_at = ? WHERE id = ? AND status = ? "
                "AND version = ? AND (lease_owner IS NULL OR lease_expires_at <= ?)",
                (
                    "processing",
                    lease_owner,
                    lease_expires_at.isoformat(),
                    now_iso,
                    segment_id,
                    "pending",
                    expected_version,
                    now_iso,
                ),
            )
            if cursor.rowcount == 0:
                self._raise_claim_failure(segment_id, expected_version, now)

            # Read back the newly assigned claim generation.
            row = self._db.execute(
                "SELECT version FROM segments WHERE id = ?",
                (segment_id,),
            ).fetchone()
            assert row is not None
            claim_version = int(str(row[0]))

            cursor = self._db.execute(
                "INSERT INTO segment_attempts "
                "(run_id, segment_id, claim_version, lease_owner, idempotency_key, "
                "model_profile_id, profile_snapshot, prompt_hash, context_summary, "
                "validator_summary, status, retryable, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    segment_id,
                    claim_version,
                    lease_owner,
                    idempotency_key,
                    model_profile_id,
                    json.dumps(profile_snapshot),
                    prompt_hash,
                    json.dumps(context_summary),
                    json.dumps(validator_summary),
                    "created",
                    0,
                    now_iso,
                ),
            )
            new_id = cursor.lastrowid

        assert new_id is not None
        loaded = self.get_by_id(new_id)
        assert loaded is not None
        return loaded

    def _raise_claim_failure(
        self,
        segment_id: int,
        expected_version: int,
        now: datetime,
    ) -> None:
        """Inspect the segment and raise a precise claim failure."""
        row = self._db.execute(
            "SELECT status, version, lease_owner, lease_expires_at FROM segments WHERE id = ?",
            (segment_id,),
        ).fetchone()
        if row is None:
            raise SegmentAttemptError(f"Segment with id {segment_id} does not exist.")

        status = str(row[0])
        version = int(str(row[1]))
        lease_owner = row[2]
        lease_expires_at = row[3]

        if status != "pending":
            raise SegmentAttemptError(
                f"Cannot claim segment {segment_id}: status is {status!r}, expected 'pending'.",
            )

        if version != expected_version:
            raise SegmentAttemptError(
                f"Cannot claim segment {segment_id}: stale version "
                f"(expected {expected_version}, got {version}).",
            )

        if lease_owner is not None and lease_expires_at is not None:
            expires = datetime.fromisoformat(str(lease_expires_at))
            if expires > now:
                raise SegmentAttemptError(
                    f"Cannot claim segment {segment_id}: lease held by {lease_owner} "
                    f"until {lease_expires_at}.",
                )

        raise SegmentAttemptError(
            f"Cannot claim segment {segment_id}: claim condition not met.",
        )

    def get_by_id(self, attempt_id: int) -> SegmentAttempt | None:
        """Fetch an attempt by id, or None if not found."""
        cursor = self._db.execute(
            f"SELECT {_ATTEMPT_COLUMNS} FROM segment_attempts WHERE id = ?",
            (attempt_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_attempt(row)

    def get_by_idempotency_key(self, idempotency_key: str) -> SegmentAttempt | None:
        """Fetch an attempt by idempotency key, or None if not found."""
        cursor = self._db.execute(
            f"SELECT {_ATTEMPT_COLUMNS} FROM segment_attempts WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_attempt(row)

    def get_by_segment_and_claim_version(
        self,
        segment_id: int,
        claim_version: int,
    ) -> SegmentAttempt | None:
        """Fetch the attempt for a segment at a specific claim generation."""
        cursor = self._db.execute(
            f"SELECT {_ATTEMPT_COLUMNS} FROM segment_attempts "
            "WHERE segment_id = ? AND claim_version = ?",
            (segment_id, claim_version),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_attempt(row)

    def list_by_run(self, run_id: int) -> list[SegmentAttempt]:
        """Return all attempts for a run ordered by id."""
        cursor = self._db.execute(
            f"SELECT {_ATTEMPT_COLUMNS} FROM segment_attempts WHERE run_id = ? ORDER BY id",
            (run_id,),
        )
        return [self._row_to_attempt(row) for row in cursor.fetchall()]

    def finalize_success(
        self,
        *,
        attempt_id: int,
        translated_text: str,
        expected_current_revision_id: int | None,
        request_id: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        now: datetime,
    ) -> tuple[SegmentAttempt, TranslationRevision]:
        """Atomically finalize a successful attempt.

        Persists the response audit, appends an AI ``TranslationRevision``,
        updates ``segments.current_revision_id`` to the new revision and marks
        the segment ``completed`` and the attempt ``succeeded``.

        The operation only succeeds when the segment is still ``processing``,
        the lease has not expired, and the lease owner and claim version match
        the attempt.  The current revision must not have changed since the
        claim and must not be a locked revision.

        All writes happen inside a single transaction; any failure rolls back
        and leaves the segment in a recoverable ``processing`` state.
        """
        now_iso = now.isoformat()

        with transaction(self._db):
            attempt = self.get_by_id(attempt_id)
            if attempt is None:
                raise SegmentAttemptError(
                    f"SegmentAttempt with id {attempt_id} does not exist.",
                )
            if attempt.status != "created":
                raise SegmentAttemptError(
                    f"Cannot finalize attempt {attempt_id}: status is {attempt.status!r}.",
                )

            segment_row = self._db.execute(
                "SELECT status, version, lease_owner, lease_expires_at, "
                "current_revision_id FROM segments WHERE id = ?",
                (attempt.segment_id,),
            ).fetchone()
            if segment_row is None:
                raise SegmentAttemptError(
                    f"Segment with id {attempt.segment_id} does not exist.",
                )

            status = str(segment_row[0])
            version = int(str(segment_row[1]))
            lease_owner = segment_row[2]
            lease_expires_at = segment_row[3]
            current_revision_id = segment_row[4]

            if status != "processing":
                raise SegmentAttemptError(
                    f"Cannot finalize segment {attempt.segment_id}: "
                    f"status is {status!r}, expected 'processing'.",
                )
            if lease_owner != attempt.lease_owner:
                raise SegmentAttemptError(
                    f"Cannot finalize segment {attempt.segment_id}: "
                    "lease owner does not match the attempt.",
                )
            if version != attempt.claim_version:
                raise SegmentAttemptError(
                    f"Cannot finalize segment {attempt.segment_id}: "
                    f"claim version mismatch (expected {attempt.claim_version}, got {version}).",
                )
            if lease_expires_at is None:
                raise SegmentAttemptError(
                    f"Cannot finalize segment {attempt.segment_id}: lease has no expiry.",
                )
            if datetime.fromisoformat(str(lease_expires_at)) <= now:
                raise SegmentAttemptError(
                    f"Cannot finalize segment {attempt.segment_id}: lease has expired.",
                )

            if (current_revision_id is None) != (expected_current_revision_id is None):
                raise SegmentAttemptError(
                    f"Cannot finalize segment {attempt.segment_id}: "
                    "current revision has changed since claim.",
                )
            if expected_current_revision_id is not None:
                if int(str(current_revision_id)) != expected_current_revision_id:
                    raise SegmentAttemptError(
                        f"Cannot finalize segment {attempt.segment_id}: "
                        "current revision has changed since claim.",
                    )
                locked_row = self._db.execute(
                    "SELECT is_locked FROM translation_revisions WHERE id = ?",
                    (expected_current_revision_id,),
                ).fetchone()
                if locked_row is None:
                    raise SegmentAttemptError(
                        f"Cannot finalize segment {attempt.segment_id}: "
                        "expected current revision no longer exists.",
                    )
                if bool(locked_row[0]):
                    raise SegmentAttemptError(
                        f"Cannot finalize segment {attempt.segment_id}: "
                        "current revision is locked.",
                    )

            # Build the conditional segment update.  The WHERE clause encodes
            # all fencing checks so a concurrent mutation fails atomically.
            if expected_current_revision_id is None:
                current_clause = "current_revision_id IS NULL"
                segment_params: tuple[object, ...] = (
                    attempt.segment_id,
                    attempt.lease_owner,
                    attempt.claim_version,
                    now_iso,
                )
            else:
                current_clause = "current_revision_id = ?"
                segment_params = (
                    attempt.segment_id,
                    attempt.lease_owner,
                    attempt.claim_version,
                    expected_current_revision_id,
                    now_iso,
                )

            cursor = self._db.execute(
                "INSERT INTO translation_revisions "
                "(segment_id, text, origin, attempt_id, is_locked, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    attempt.segment_id,
                    translated_text,
                    "ai",
                    attempt.id,
                    0,
                    now_iso,
                ),
            )
            revision_id = cursor.lastrowid
            assert revision_id is not None

            cursor = self._db.execute(
                f"UPDATE segments SET status = ?, current_revision_id = ?, "
                f"version = version + 1, lease_owner = NULL, "
                f"lease_expires_at = NULL, updated_at = ? "
                f"WHERE id = ? AND status = 'processing' AND lease_owner = ? "
                f"AND version = ? AND {current_clause} "
                f"AND lease_expires_at > ?",
                (
                    "completed",
                    revision_id,
                    now_iso,
                    *segment_params,
                ),
            )
            if cursor.rowcount == 0:
                raise SegmentAttemptError(
                    f"Cannot finalize segment {attempt.segment_id}: "
                    "fencing check failed (concurrent change or expired lease).",
                )

            cursor = self._db.execute(
                "UPDATE segment_attempts SET status = ?, request_id = ?, "
                "input_tokens = ?, output_tokens = ?, latency_ms = ?, finished_at = ? "
                "WHERE id = ? AND status = 'created'",
                (
                    "succeeded",
                    request_id,
                    input_tokens,
                    output_tokens,
                    latency_ms,
                    now_iso,
                    attempt_id,
                ),
            )
            if cursor.rowcount == 0:
                raise SegmentAttemptError(
                    f"Cannot finalize attempt {attempt_id}: "
                    "fencing check failed (attempt no longer in 'created' state).",
                )

        loaded_attempt = self.get_by_id(attempt_id)
        loaded_revision = self._load_revision(revision_id)
        assert loaded_attempt is not None
        assert loaded_revision is not None
        return loaded_attempt, loaded_revision

    def finalize_failure(
        self,
        *,
        attempt_id: int,
        error_type: str,
        error_message: str,
        retryable: bool,
        now: datetime,
    ) -> SegmentAttempt:
        """Atomically record a failed model call for an attempt.

        Moves the segment from ``processing`` to ``failed`` and the attempt from
        ``created`` to ``failed`` with the error details and retryable flag.
        The write only succeeds while the segment is still owned by this claim
        and the lease has not expired, so a late worker cannot overwrite a newer
        owner. Existing revisions and the segment's current revision are left
        untouched.
        """
        now_iso = now.isoformat()

        with transaction(self._db):
            attempt = self.get_by_id(attempt_id)
            if attempt is None:
                raise SegmentAttemptError(
                    f"SegmentAttempt with id {attempt_id} does not exist.",
                )
            if attempt.status != "created":
                raise SegmentAttemptError(
                    f"Cannot finalize failure for attempt {attempt_id}: "
                    f"status is {attempt.status!r}.",
                )

            segment_row = self._db.execute(
                "SELECT status, version, lease_owner, lease_expires_at "
                "FROM segments WHERE id = ?",
                (attempt.segment_id,),
            ).fetchone()
            if segment_row is None:
                raise SegmentAttemptError(
                    f"Segment with id {attempt.segment_id} does not exist.",
                )
            self._require_valid_claim(
                attempt,
                segment_row,
                now=now,
                operation="finalize failure for",
            )

            cursor = self._db.execute(
                "UPDATE segments SET status = ?, version = version + 1, "
                "lease_owner = NULL, lease_expires_at = NULL, updated_at = ? "
                "WHERE id = ? AND status = 'processing' AND lease_owner = ? "
                "AND version = ? AND lease_expires_at > ?",
                (
                    "failed",
                    now_iso,
                    attempt.segment_id,
                    attempt.lease_owner,
                    attempt.claim_version,
                    now_iso,
                ),
            )
            if cursor.rowcount == 0:
                raise SegmentAttemptError(
                    f"Cannot finalize failure for segment {attempt.segment_id}: "
                    "fencing check failed (concurrent change or expired lease).",
                )

            cursor = self._db.execute(
                "UPDATE segment_attempts SET status = ?, retryable = ?, "
                "error_type = ?, error_message = ?, finished_at = ? "
                "WHERE id = ? AND status = 'created'",
                (
                    "failed",
                    1 if retryable else 0,
                    error_type,
                    error_message,
                    now_iso,
                    attempt_id,
                ),
            )
            if cursor.rowcount == 0:
                raise SegmentAttemptError(
                    f"Cannot finalize failure for attempt {attempt_id}: "
                    "attempt no longer in 'created' state.",
                )

        loaded = self.get_by_id(attempt_id)
        assert loaded is not None
        return loaded

    def cancel(
        self,
        *,
        attempt_id: int,
        reason: str,
        now: datetime,
    ) -> SegmentAttempt:
        """Atomically cancel an attempt that still holds a valid lease.

        Marks the attempt ``cancelled`` with the given reason and returns the
        segment to ``pending`` with its lease released so it can be claimed
        again. Existing revisions and the segment's current revision are
        preserved. A claim whose lease has already expired cannot be cancelled;
        it must instead be recovered at startup.
        """
        now_iso = now.isoformat()

        with transaction(self._db):
            attempt = self.get_by_id(attempt_id)
            if attempt is None:
                raise SegmentAttemptError(
                    f"SegmentAttempt with id {attempt_id} does not exist.",
                )
            if attempt.status != "created":
                raise SegmentAttemptError(
                    f"Cannot cancel attempt {attempt_id}: status is {attempt.status!r}.",
                )

            segment_row = self._db.execute(
                "SELECT status, version, lease_owner, lease_expires_at "
                "FROM segments WHERE id = ?",
                (attempt.segment_id,),
            ).fetchone()
            if segment_row is None:
                raise SegmentAttemptError(
                    f"Segment with id {attempt.segment_id} does not exist.",
                )
            self._require_valid_claim(
                attempt,
                segment_row,
                now=now,
                operation="cancel",
            )

            cursor = self._db.execute(
                "UPDATE segments SET status = ?, version = version + 1, "
                "lease_owner = NULL, lease_expires_at = NULL, updated_at = ? "
                "WHERE id = ? AND status = 'processing' AND lease_owner = ? "
                "AND version = ? AND lease_expires_at > ?",
                (
                    "pending",
                    now_iso,
                    attempt.segment_id,
                    attempt.lease_owner,
                    attempt.claim_version,
                    now_iso,
                ),
            )
            if cursor.rowcount == 0:
                raise SegmentAttemptError(
                    f"Cannot cancel segment {attempt.segment_id}: "
                    "fencing check failed (concurrent change or expired lease).",
                )

            cursor = self._db.execute(
                "UPDATE segment_attempts SET status = ?, error_type = ?, "
                "error_message = ?, finished_at = ? "
                "WHERE id = ? AND status = 'created'",
                (
                    "cancelled",
                    "cancelled",
                    reason,
                    now_iso,
                    attempt_id,
                ),
            )
            if cursor.rowcount == 0:
                raise SegmentAttemptError(
                    f"Cannot cancel attempt {attempt_id}: "
                    "attempt no longer in 'created' state.",
                )

        loaded = self.get_by_id(attempt_id)
        assert loaded is not None
        return loaded

    def recover_expired_leases(self, *, now: datetime) -> int:
        """Converge processing segments whose leases have expired.

        Stale attempts are cancelled and their leases released. Segments without
        a locked current revision return to ``pending``. A locked current
        revision is already the protected final translation, so its segment
        becomes ``completed`` without creating or replacing any revision.
        Returns the number of converged segments.
        """
        now_iso = now.isoformat()

        with transaction(self._db):
            rows = self._db.execute(
                "SELECT s.id, r.is_locked FROM segments s "
                "LEFT JOIN translation_revisions r ON r.id = s.current_revision_id "
                "WHERE s.status = 'processing' AND s.lease_expires_at IS NOT NULL "
                "AND s.lease_expires_at <= ?",
                (now_iso,),
            ).fetchall()
            if not rows:
                return 0

            pending_ids = [int(str(row[0])) for row in rows if not bool(row[1])]
            completed_ids = [int(str(row[0])) for row in rows if bool(row[1])]
            segment_ids = pending_ids + completed_ids
            placeholders = ",".join("?" for _ in segment_ids)
            self._db.execute(
                f"UPDATE segment_attempts SET status = 'cancelled', "
                f"error_type = 'lease_expired', "
                f"error_message = 'recovered after lease expiry', finished_at = ? "
                f"WHERE segment_id IN ({placeholders}) AND status = 'created'",
                (now_iso, *segment_ids),
            )
            if pending_ids:
                pending_placeholders = ",".join("?" for _ in pending_ids)
                self._db.execute(
                    f"UPDATE segments SET status = 'pending', version = version + 1, "
                    f"lease_owner = NULL, lease_expires_at = NULL, updated_at = ? "
                    f"WHERE id IN ({pending_placeholders})",
                    (now_iso, *pending_ids),
                )
            if completed_ids:
                completed_placeholders = ",".join("?" for _ in completed_ids)
                self._db.execute(
                    f"UPDATE segments SET status = 'completed', version = version + 1, "
                    f"lease_owner = NULL, lease_expires_at = NULL, updated_at = ? "
                    f"WHERE id IN ({completed_placeholders})",
                    (now_iso, *completed_ids),
                )
            return len(segment_ids)

    def requeue_failed(self, *, segment_id: int, now: datetime) -> None:
        """Transition a failed segment back to pending atomically.

        The service validates that the last effective attempt is a retryable
        failure before calling this. The atomic status guard prevents two
        workers from requeueing the same segment.
        """
        now_iso = now.isoformat()

        with transaction(self._db):
            cursor = self._db.execute(
                "UPDATE segments SET status = 'pending', version = version + 1, "
                "updated_at = ? WHERE id = ? AND status = 'failed'",
                (now_iso, segment_id),
            )
            if cursor.rowcount == 0:
                raise SegmentAttemptError(
                    f"Cannot requeue segment {segment_id}: status is no longer 'failed'.",
                )

    def _require_valid_claim(
        self,
        attempt: SegmentAttempt,
        segment_row: tuple[object, ...],
        *,
        now: datetime,
        operation: str,
    ) -> None:
        """Verify the segment is still processing under this attempt's claim.

        Shared fencing for the terminal writes (failure, cancel): the segment
        must be ``processing``, owned by the same lease owner, at the attempt's
        claim version, with a lease that has not expired.
        """
        status = str(segment_row[0])
        version = int(str(segment_row[1]))
        lease_owner = segment_row[2]
        lease_expires_at = segment_row[3]

        if status != "processing":
            raise SegmentAttemptError(
                f"Cannot {operation} segment {attempt.segment_id}: "
                f"status is {status!r}, expected 'processing'.",
            )
        if lease_owner != attempt.lease_owner:
            raise SegmentAttemptError(
                f"Cannot {operation} segment {attempt.segment_id}: "
                "lease owner does not match the attempt.",
            )
        if version != attempt.claim_version:
            raise SegmentAttemptError(
                f"Cannot {operation} segment {attempt.segment_id}: "
                f"claim version mismatch (expected {attempt.claim_version}, got {version}).",
            )
        if lease_expires_at is None:
            raise SegmentAttemptError(
                f"Cannot {operation} segment {attempt.segment_id}: lease has no expiry.",
            )
        if datetime.fromisoformat(str(lease_expires_at)) <= now:
            raise SegmentAttemptError(
                f"Cannot {operation} segment {attempt.segment_id}: lease has expired.",
            )

    def _load_revision(self, revision_id: int) -> TranslationRevision | None:
        """Fetch a revision by id inside the repository connection."""
        cursor = self._db.execute(
            "SELECT id, segment_id, text, origin, attempt_id, is_locked, created_at "
            "FROM translation_revisions WHERE id = ?",
            (revision_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return TranslationRevision(
            id=int(str(row[0])),
            segment_id=int(str(row[1])),
            text=str(row[2]),
            origin=str(row[3]),
            attempt_id=int(str(row[4])) if row[4] is not None else None,
            is_locked=bool(row[5]),
            created_at=datetime.fromisoformat(str(row[6])),
        )

    @staticmethod
    def _row_to_attempt(row: tuple[object, ...]) -> SegmentAttempt:
        return SegmentAttempt(
            id=int(str(row[0])),
            run_id=int(str(row[1])),
            segment_id=int(str(row[2])),
            claim_version=int(str(row[3])),
            lease_owner=str(row[4]),
            idempotency_key=str(row[5]),
            model_profile_id=int(str(row[6])),
            profile_snapshot=json.loads(str(row[7])),
            prompt_hash=str(row[8]),
            context_summary=json.loads(str(row[9])),
            validator_summary=json.loads(str(row[10])),
            request_id=str(row[11]) if row[11] is not None else None,
            status=str(row[12]),
            retryable=bool(row[13]),
            input_tokens=int(str(row[14])) if row[14] is not None else None,
            output_tokens=int(str(row[15])) if row[15] is not None else None,
            latency_ms=int(str(row[16])) if row[16] is not None else None,
            error_type=str(row[17]) if row[17] is not None else None,
            error_message=str(row[18]) if row[18] is not None else None,
            created_at=datetime.fromisoformat(str(row[19])),
            finished_at=datetime.fromisoformat(str(row[20])) if row[20] is not None else None,
        )

    def close(self) -> None:
        """Close the underlying database connection."""
        self._db.close()
