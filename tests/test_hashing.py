from datetime import datetime, timezone
from uuid import UUID

from app.hashing import compute_record_hash


POLL_ID = UUID("11111111-1111-1111-1111-111111111111")
OPTION_ID = UUID("22222222-2222-2222-2222-222222222222")
CREATED_AT = datetime(
    2026,
    9,
    8,
    12,
    0,
    0,
    tzinfo=timezone.utc,
)


def test_same_inputs_produce_same_hash():
    first = compute_record_hash(
        prev_hash=None,
        poll_id=POLL_ID,
        option_id=OPTION_ID,
        created_at=CREATED_AT,
    )

    second = compute_record_hash(
        prev_hash=None,
        poll_id=POLL_ID,
        option_id=OPTION_ID,
        created_at=CREATED_AT,
    )

    assert first == second


def test_different_option_produces_different_hash():
    first = compute_record_hash(
        prev_hash=None,
        poll_id=POLL_ID,
        option_id=OPTION_ID,
        created_at=CREATED_AT,
    )

    second = compute_record_hash(
        prev_hash=None,
        poll_id=POLL_ID,
        option_id=UUID(
            "33333333-3333-3333-3333-333333333333"
        ),
        created_at=CREATED_AT,
    )

    assert first != second


def test_different_previous_hash_produces_different_hash():
    first = compute_record_hash(
        prev_hash=None,
        poll_id=POLL_ID,
        option_id=OPTION_ID,
        created_at=CREATED_AT,
    )

    second = compute_record_hash(
        prev_hash="previous-hash",
        poll_id=POLL_ID,
        option_id=OPTION_ID,
        created_at=CREATED_AT,
    )

    assert first != second


def test_different_timestamp_produces_different_hash():
    first = compute_record_hash(
        prev_hash=None,
        poll_id=POLL_ID,
        option_id=OPTION_ID,
        created_at=CREATED_AT,
    )

    second = compute_record_hash(
        prev_hash=None,
        poll_id=POLL_ID,
        option_id=OPTION_ID,
        created_at=CREATED_AT.replace(
            second=1,
        ),
    )

    assert first != second


def test_hash_has_expected_sha256_length():
    result = compute_record_hash(
        prev_hash=None,
        poll_id=POLL_ID,
        option_id=OPTION_ID,
        created_at=CREATED_AT,
    )

    assert len(result) == 64