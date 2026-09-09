from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.hashing import compute_record_hash


async def verify_ballot_chain(
    session: AsyncSession,
    poll_id: UUID,
) -> bool:
    ballots = (
        await session.execute(
            text("""
                SELECT
                    id,
                    option_id,
                    prev_hash,
                    record_hash,
                    created_at
                FROM ballots
                WHERE poll_id = :poll_id
            """),
            {"poll_id": poll_id},
        )
    ).mappings().all()

    # No ballots: the chain must have no latest hash.
    if not ballots:
        latest_hash = (
            await session.execute(
                text("""
                    SELECT latest_hash
                    FROM poll_ballot_state
                    WHERE poll_id = :poll_id
                """),
                {"poll_id": poll_id},
            )
        ).scalar_one_or_none()

        return latest_hash is None

    # Every ballot must have a valid record hash.
    for ballot in ballots:
        expected_hash = compute_record_hash(
            prev_hash=ballot["prev_hash"],
            poll_id=poll_id,
            option_id=ballot["option_id"],
            created_at=ballot["created_at"],
        )

        if ballot["record_hash"] != expected_hash:
            return False

    # There must be exactly one root.
    roots = [
        ballot
        for ballot in ballots
        if ballot["prev_hash"] is None
    ]

    if len(roots) != 1:
        return False

    # Follow the chain using prev_hash.
    current = roots[0]
    visited = set()

    while True:
        current_hash = current["record_hash"]

        if current_hash in visited:
            return False

        visited.add(current_hash)

        next_ballots = [
            ballot
            for ballot in ballots
            if ballot["prev_hash"] == current_hash
        ]

        if len(next_ballots) > 1:
            # Two ballots extending the same hash means
            # the chain has forked.
            return False

        if not next_ballots:
            break

        current = next_ballots[0]

    # Every ballot must belong to the single chain.
    if len(visited) != len(ballots):
        return False

    # The state row must point to the chain tip.
    latest_hash = (
        await session.execute(
            text("""
                SELECT latest_hash
                FROM poll_ballot_state
                WHERE poll_id = :poll_id
            """),
            {"poll_id": poll_id},
        )
    ).scalar_one_or_none()

    return latest_hash == current["record_hash"]