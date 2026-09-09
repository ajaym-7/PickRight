import pytest
from sqlalchemy import text

from app.database import SessionLocal
from app.hashing import compute_record_hash
from app.verification import verify_ballot_chain
from app.voting import cast_vote
from uuid import uuid4


@pytest.mark.anyio
async def test_empty_ballot_chain_is_valid(voting_setup):
    session, _, poll_id, _ = voting_setup

    assert await verify_ballot_chain(session, poll_id) is True


@pytest.mark.anyio
async def test_valid_ballot_chain_is_valid(voting_setup):
    session, user_id, poll_id, option_id = voting_setup

    await cast_vote(
        session=session,
        user_id=user_id,
        poll_id=poll_id,
        option_id=option_id,
    )

    assert await verify_ballot_chain(session, poll_id) is True


@pytest.mark.anyio
async def test_tampered_record_hash_invalidates_chain(voting_setup):
    session, user_id, poll_id, option_id = voting_setup

    await cast_vote(
        session=session,
        user_id=user_id,
        poll_id=poll_id,
        option_id=option_id,
    )

    await session.execute(
        text("""
            UPDATE ballots
            SET record_hash = 'tampered'
            WHERE poll_id = :poll_id
        """),
        {"poll_id": poll_id},
    )
    await session.commit()

    assert await verify_ballot_chain(session, poll_id) is False


@pytest.mark.anyio
async def test_tampered_option_invalidates_chain(voting_setup):
    session, user_id, poll_id, option_id = voting_setup

    other_option_id = (
        await session.execute(
            text("""
                INSERT INTO options (poll_id, label)
                VALUES (:poll_id, 'Option B')
                RETURNING id
            """),
            {"poll_id": poll_id},
        )
    ).scalar_one()

    await session.commit()

    await cast_vote(
        session=session,
        user_id=user_id,
        poll_id=poll_id,
        option_id=option_id,
    )

    await session.execute(
        text("""
            UPDATE ballots
            SET option_id = :option_id
            WHERE poll_id = :poll_id
        """),
        {
            "poll_id": poll_id,
            "option_id": other_option_id,
        },
    )
    await session.commit()

    assert await verify_ballot_chain(session, poll_id) is False


@pytest.mark.anyio
async def test_broken_previous_hash_invalidates_chain(voting_setup):
    session, user_id, poll_id, option_id = voting_setup

    await cast_vote(
        session=session,
        user_id=user_id,
        poll_id=poll_id,
        option_id=option_id,
    )

    # Create a second eligible user.
    suffix = uuid4()

    second_user_id = (
    await session.execute(
        text("""
            INSERT INTO users (
                email,
                oauth_provider,
                provider_user_id
            )
            VALUES (
                :email,
                'test',
                :provider_user_id
            )
            RETURNING id
        """),
        {
            "email": f"verification-second-{suffix}@example.com",
            "provider_user_id": f"verification-second-{suffix}",
        },
    )
).scalar_one()

    await session.execute(
        text("""
            INSERT INTO eligibility (user_id, poll_id)
            VALUES (:user_id, :poll_id)
        """),
        {
            "user_id": second_user_id,
            "poll_id": poll_id,
        },
    )

    await session.commit()

    await cast_vote(
        session=session,
        user_id=second_user_id,
        poll_id=poll_id,
        option_id=option_id,
    )

    await session.execute(
        text("""
            UPDATE ballots
            SET prev_hash = 'broken'
            WHERE poll_id = :poll_id
              AND prev_hash IS NOT NULL
        """),
        {"poll_id": poll_id},
    )
    await session.commit()

    assert await verify_ballot_chain(session, poll_id) is False


@pytest.mark.anyio
async def test_incorrect_latest_hash_invalidates_chain(voting_setup):
    session, user_id, poll_id, option_id = voting_setup

    await cast_vote(
        session=session,
        user_id=user_id,
        poll_id=poll_id,
        option_id=option_id,
    )

    await session.execute(
        text("""
            UPDATE poll_ballot_state
            SET latest_hash = 'incorrect'
            WHERE poll_id = :poll_id
        """),
        {"poll_id": poll_id},
    )
    await session.commit()

    assert await verify_ballot_chain(session, poll_id) is False


@pytest.mark.anyio
async def test_forked_chain_invalidates_chain(voting_setup):
    session, user_id, poll_id, option_id = voting_setup

    await cast_vote(
        session=session,
        user_id=user_id,
        poll_id=poll_id,
        option_id=option_id,
    )

    # Read the first ballot's hash.
    first_ballot = (
        await session.execute(
            text("""
                SELECT record_hash, created_at
                FROM ballots
                WHERE poll_id = :poll_id
            """),
            {"poll_id": poll_id},
        )
    ).mappings().one()

    # Create a second ballot that incorrectly extends
    # the first ballot's hash.
# Create a second user.
    suffix = uuid4()

    second_user_id = (
        await session.execute(
            text("""
                INSERT INTO users (
                    email,
                    oauth_provider,
                    provider_user_id
                )
                VALUES (
                    :email,
                    'test',
                    :provider_user_id
                )
                RETURNING id
            """),
            {
                "email": f"fork-user-{suffix}@example.com",
                "provider_user_id": f"fork-user-{suffix}",
            },
        )
    ).scalar_one()

    await session.execute(
        text("""
            INSERT INTO eligibility (user_id, poll_id)
            VALUES (:user_id, :poll_id)
        """),
        {
            "user_id": second_user_id,
            "poll_id": poll_id,
        },
    )

    await session.commit()

    # We deliberately bypass cast_vote() here because we're
    # constructing corrupted database state for the test.
    created_at = first_ballot["created_at"]

    fork_hash = compute_record_hash(
        prev_hash=first_ballot["record_hash"],
        poll_id=poll_id,
        option_id=option_id,
        created_at=created_at,
    )

    await session.execute(
        text("""
            INSERT INTO ballots (
                id,
                poll_id,
                option_id,
                prev_hash,
                record_hash,
                created_at
            )
            VALUES (
                :id,
                :poll_id,
                :option_id,
                :prev_hash,
                :record_hash,
                :created_at
            )
        """),
        {
            "id": uuid4(),
            "poll_id": poll_id,
            "option_id": option_id,
            "prev_hash": first_ballot["record_hash"],
            "record_hash": fork_hash,
            "created_at": created_at,
        },
    )

    await session.commit()

    assert await verify_ballot_chain(session, poll_id) is False


@pytest.mark.anyio
async def test_orphaned_ballot_invalidates_chain(voting_setup):
    session, user_id, poll_id, option_id = voting_setup

    await cast_vote(
        session=session,
        user_id=user_id,
        poll_id=poll_id,
        option_id=option_id,
    )

    # Create a ballot whose contents and hash are internally valid,
    # but whose prev_hash points to a nonexistent ballot.
    orphan_prev_hash = "a" * 64
    orphan_created_at = (
        await session.execute(
            text("""
                SELECT created_at
                FROM ballots
                WHERE poll_id = :poll_id
                LIMIT 1
            """),
            {"poll_id": poll_id},
        )
    ).scalar_one()

    orphan_hash = compute_record_hash(
        prev_hash=orphan_prev_hash,
        poll_id=poll_id,
        option_id=option_id,
        created_at=orphan_created_at,
    )

    await session.execute(
        text("""
            INSERT INTO ballots (
                id,
                poll_id,
                option_id,
                prev_hash,
                record_hash,
                created_at
            )
            VALUES (
                :id,
                :poll_id,
                :option_id,
                :prev_hash,
                :record_hash,
                :created_at
            )
        """),
        {
            "id": uuid4(),
            "poll_id": poll_id,
            "option_id": option_id,
            "prev_hash": orphan_prev_hash,
            "record_hash": orphan_hash,
            "created_at": orphan_created_at,
        },
    )

    await session.commit()

    assert await verify_ballot_chain(session, poll_id) is False