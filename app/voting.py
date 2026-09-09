from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.hashing import compute_record_hash



async def cast_vote(
    session: AsyncSession,
    user_id: UUID,
    poll_id: UUID,
    option_id: UUID,
    ballot_id: UUID | None = None,
) -> UUID:
    if ballot_id is None:
        ballot_id = uuid4()

    async with session.begin():
        # 1. Check whether this ballot_id was already used.
        existing_ballot = (
            await session.execute(
                text("""
                    SELECT poll_id, option_id
                    FROM ballots
                    WHERE id = :ballot_id
                """),
                {"ballot_id": ballot_id},
            )
        ).mappings().one_or_none()

        if existing_ballot is not None:
            if (
                existing_ballot["poll_id"] == poll_id
                and existing_ballot["option_id"] == option_id
            ):
                # Same id + same payload = idempotent success.
                return ballot_id

            raise ValueError("Ballot ID already used with different payload")

        # 2. Verify poll is open and within its voting window.
        poll = (
            await session.execute(
                text("""
                    SELECT id
                    FROM polls
                    WHERE id = :poll_id
                      AND status = 'open'
                      AND start_time <= now()
                      AND end_time > now()
                """),
                {"poll_id": poll_id},
            )
        ).scalar_one_or_none()

        if poll is None:
            raise ValueError("Poll is not open")

        # 3. Verify that the option belongs to this poll.
        option = (
            await session.execute(
                text("""
                    SELECT id
                    FROM options
                    WHERE id = :option_id
                      AND poll_id = :poll_id
                """),
                {
                    "option_id": option_id,
                    "poll_id": poll_id,
                },
            )
        ).scalar_one_or_none()

        if option is None:
            raise ValueError("Option does not belong to poll")

        # 4. Atomically claim user's eligibility.
        eligibility = (
            await session.execute(
                text("""
                    UPDATE eligibility
                    SET
                        has_voted = TRUE,
                        voted_at = now()
                    WHERE user_id = :user_id
                      AND poll_id = :poll_id
                      AND has_voted = FALSE
                    RETURNING id
                """),
                {
                    "user_id": user_id,
                    "poll_id": poll_id,
                },
            )
        ).scalar_one_or_none()

        if eligibility is None:
            raise ValueError("User has already voted or is not eligible")

        # 5. Lock the poll's ballot-chain state.
        state = (
            await session.execute(
                text("""
                    SELECT poll_id, latest_hash
                    FROM poll_ballot_state
                    WHERE poll_id = :poll_id
                    FOR UPDATE
                """),
                {"poll_id": poll_id},
            )
        ).mappings().one_or_none()

        if state is None:
            raise ValueError("Ballot state does not exist")

        # 6. Create the ballot.
        created_at = datetime.now(timezone.utc)
        prev_hash = state["latest_hash"]

        record_hash = compute_record_hash(
            prev_hash=prev_hash,
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
                "id": ballot_id,
                "poll_id": poll_id,
                "option_id": option_id,
                "prev_hash": prev_hash,
                "record_hash": record_hash,
                "created_at": created_at,
            },
        )

        # 7. Advance the chain.
        await session.execute(
            text("""
                UPDATE poll_ballot_state
                SET
                    latest_hash = :latest_hash,
                    updated_at = now()
                WHERE poll_id = :poll_id
            """),
            {
                "poll_id": poll_id,
                "latest_hash": record_hash,
            },
        )

    return ballot_id
