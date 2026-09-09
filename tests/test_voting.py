import pytest, asyncio
from uuid import uuid4

from sqlalchemy import text

from app.database import SessionLocal, engine
from app.voting import cast_vote
from app.exceptions import (
    AlreadyVotedError,
    BallotIdConflictError,
    InvalidOptionError,
)


@pytest.mark.anyio
async def test_cast_vote_success(voting_setup):
    session, user_id, poll_id, option_id = voting_setup

    # Act
    ballot_id = await cast_vote(
        session=session,
        user_id=user_id,
        poll_id=poll_id,
        option_id=option_id,
    )

    # Assert
    ballot = (
        await session.execute(
            text("""
                SELECT id, poll_id, option_id, prev_hash, record_hash
                FROM ballots
                WHERE id = :ballot_id
            """),
            {"ballot_id": ballot_id},
        )
    ).mappings().one()

    assert ballot["poll_id"] == poll_id
    assert ballot["option_id"] == option_id
    assert ballot["prev_hash"] is None
    assert ballot["record_hash"]

    eligibility = (
        await session.execute(
            text("""
                SELECT has_voted, voted_at
                FROM eligibility
                WHERE user_id = :user_id
                  AND poll_id = :poll_id
            """),
            {
                "user_id": user_id,
                "poll_id": poll_id,
            },
        )
    ).mappings().one()

    assert eligibility["has_voted"] is True
    assert eligibility["voted_at"] is not None

    state = (
        await session.execute(
            text("""
                SELECT latest_hash
                FROM poll_ballot_state
                WHERE poll_id = :poll_id
            """),
            {"poll_id": poll_id},
        )
    ).scalar_one()

    assert state == ballot["record_hash"]

@pytest.mark.anyio
async def test_cast_vote_rejects_duplicate_vote(voting_setup):
    session, user_id, poll_id, option_id = voting_setup

    # First vote
    await cast_vote(
        session=session,
        user_id=user_id,
        poll_id=poll_id,
        option_id=option_id,
    )

    # Second vote
    with pytest.raises(
        AlreadyVotedError,
        match="already voted or is not eligible",
    ):
        await cast_vote(
            session=session,
            user_id=user_id,
            poll_id=poll_id,
            option_id=option_id,
        )

@pytest.mark.anyio
async def test_cast_vote_rejects_option_from_different_poll(voting_setup):
    session, user_id, poll_id, option_id = voting_setup

    # Create another poll
    other_poll_id = (
        await session.execute(
            text("""
                INSERT INTO polls (
                    title,
                    start_time,
                    end_time,
                    status,
                    created_by
                )
                VALUES (
                    'Other Poll',
                    now() - interval '1 hour',
                    now() + interval '1 hour',
                    'open',
                    :user_id
                )
                RETURNING id
            """),
            {"user_id": user_id},
        )
    ).scalar_one()

    # Create an option belonging to the other poll
    other_option_id = (
        await session.execute(
            text("""
                INSERT INTO options (
                    poll_id,
                    label
                )
                VALUES (
                    :poll_id,
                    'Other Option'
                )
                RETURNING id
            """),
            {"poll_id": other_poll_id},
        )
    ).scalar_one()

    await session.commit()

    # Try to vote in the original poll using the other poll's option
    with pytest.raises(
        InvalidOptionError,
        match="Option does not belong to poll",
    ):
        await cast_vote(
            session=session,
            user_id=user_id,
            poll_id=poll_id,
            option_id=other_option_id,
        )

@pytest.mark.anyio
async def test_cast_vote_rolls_back_on_ballot_insert_failure(
    voting_setup,
    monkeypatch,
):
    session, user_id, poll_id, option_id = voting_setup

    original_execute = session.execute

    async def failing_execute(statement, *args, **kwargs):
        statement_text = str(statement)

        if "INSERT INTO ballots" in statement_text:
            raise RuntimeError("simulated ballot insert failure")

        return await original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(session, "execute", failing_execute)

    with pytest.raises(
        RuntimeError,
        match="simulated ballot insert failure",
    ):
        await cast_vote(
            session=session,
            user_id=user_id,
            poll_id=poll_id,
            option_id=option_id,
        )

    # The eligibility update must have rolled back.
    eligibility = (
        await session.execute(
            text("""
                SELECT has_voted, voted_at
                FROM eligibility
                WHERE user_id = :user_id
                  AND poll_id = :poll_id
            """),
            {
                "user_id": user_id,
                "poll_id": poll_id,
            },
        )
    ).mappings().one()

    assert eligibility["has_voted"] is False
    assert eligibility["voted_at"] is None

    # No ballot should have been created.
    ballot_count = (
        await session.execute(
            text("""
                SELECT COUNT(*)
                FROM ballots
                WHERE poll_id = :poll_id
            """),
            {"poll_id": poll_id},
        )
    ).scalar_one()

    assert ballot_count == 0


@pytest.mark.anyio
async def test_cast_vote_is_idempotent(voting_setup):
    session, user_id, poll_id, option_id = voting_setup

    ballot_id = uuid4()

    first_result = await cast_vote(
        session=session,
        user_id=user_id,
        poll_id=poll_id,
        option_id=option_id,
        ballot_id=ballot_id,
    )

    second_result = await cast_vote(
        session=session,
        user_id=user_id,
        poll_id=poll_id,
        option_id=option_id,
        ballot_id=ballot_id,
    )

    assert first_result == ballot_id
    assert second_result == ballot_id

    ballot_count = (
        await session.execute(
            text("""
                SELECT COUNT(*)
                FROM ballots
                WHERE id = :ballot_id
            """),
            {"ballot_id": ballot_id},
        )
    ).scalar_one()

    assert ballot_count == 1


@pytest.mark.anyio
async def test_cast_vote_rejects_idempotency_conflict(voting_setup):
    session, user_id, poll_id, option_id = voting_setup

    ballot_id = uuid4()

    # Create another option in the same poll.
    other_option_id = (
        await session.execute(
            text("""
                INSERT INTO options (
                    poll_id,
                    label
                )
                VALUES (
                    :poll_id,
                    'Option B'
                )
                RETURNING id
            """),
            {"poll_id": poll_id},
        )
    ).scalar_one()

    await session.commit()

    # First request.
    await cast_vote(
        session=session,
        user_id=user_id,
        poll_id=poll_id,
        option_id=option_id,
        ballot_id=ballot_id,
    )

    # Same id, but different option.
    with pytest.raises(
        BallotIdConflictError,
        match="Ballot ID already used with different payload",
    ):
        await cast_vote(
            session=session,
            user_id=user_id,
            poll_id=poll_id,
            option_id=other_option_id,
            ballot_id=ballot_id,
        )

    ballot_count = (
        await session.execute(
            text("""
                SELECT COUNT(*)
                FROM ballots
                WHERE id = :ballot_id
            """),
            {"ballot_id": ballot_id},
        )
    ).scalar_one()

    assert ballot_count == 1


@pytest.mark.anyio
async def test_concurrent_votes_from_same_user_allow_only_one(voting_setup):
    _, user_id, poll_id, option_id = voting_setup

    ballot_id_1 = uuid4()
    ballot_id_2 = uuid4()

    async def submit_vote(ballot_id):
        async with SessionLocal() as session:
            try:
                result = await cast_vote(
                    session=session,
                    user_id=user_id,
                    poll_id=poll_id,
                    option_id=option_id,
                    ballot_id=ballot_id,
                )
                return ("success", result)
            except AlreadyVotedError as exc:
                return ("rejected", str(exc))

    results = await asyncio.gather(
        submit_vote(ballot_id_1),
        submit_vote(ballot_id_2),
    )

    successes = [
        result
        for result in results
        if result[0] == "success"
    ]

    rejections = [
        result
        for result in results
        if result[0] == "rejected"
    ]

    assert len(successes) == 1
    assert len(rejections) == 1

    assert "already voted or is not eligible" in rejections[0][1]

    async with SessionLocal() as session:
        ballot_count = (
            await session.execute(
                text("""
                    SELECT COUNT(*)
                    FROM ballots
                    WHERE poll_id = :poll_id
                """),
                {"poll_id": poll_id},
            )
        ).scalar_one()

        assert ballot_count == 1


@pytest.mark.anyio
async def test_concurrent_votes_from_different_users_preserve_hash_chain(
    voting_setup,
):
    session, user_id, poll_id, option_id = voting_setup

    # Create a second user.
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
                "email": f"second-{uuid4()}@example.com",
                "provider_user_id": f"second-user-{uuid4()}",
            },
        )
    ).scalar_one()

    # Make the second user eligible for the same poll.
    await session.execute(
        text("""
            INSERT INTO eligibility (
                user_id,
                poll_id
            )
            VALUES (
                :user_id,
                :poll_id
            )
        """),
        {
            "user_id": second_user_id,
            "poll_id": poll_id,
        },
    )

    await session.commit()

    ballot_id_1 = uuid4()
    ballot_id_2 = uuid4()

    async def submit_vote(user_id, ballot_id):
        async with SessionLocal() as vote_session:
            return await cast_vote(
                session=vote_session,
                user_id=user_id,
                poll_id=poll_id,
                option_id=option_id,
                ballot_id=ballot_id,
            )

    results = await asyncio.gather(
        submit_vote(user_id, ballot_id_1),
        submit_vote(second_user_id, ballot_id_2),
    )

    assert set(results) == {ballot_id_1, ballot_id_2}

    async with SessionLocal() as verify_session:
        ballots = (
            await verify_session.execute(
                text("""
                    SELECT
                        id,
                        prev_hash,
                        record_hash,
                        created_at
                    FROM ballots
                    WHERE poll_id = :poll_id
                    ORDER BY created_at, id
                """),
                {"poll_id": poll_id},
            )
        ).mappings().all()

        assert len(ballots) == 2

        # The first ballot starts the chain.
        assert ballots[0]["prev_hash"] is None

        # The second ballot must point to the first ballot.
        assert ballots[1]["prev_hash"] == ballots[0]["record_hash"]

        # poll_ballot_state must point to the final ballot.
        latest_hash = (
            await verify_session.execute(
                text("""
                    SELECT latest_hash
                    FROM poll_ballot_state
                    WHERE poll_id = :poll_id
                """),
                {"poll_id": poll_id},
            )
        ).scalar_one()

        assert latest_hash == ballots[1]["record_hash"]