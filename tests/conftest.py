import pytest
from uuid import uuid4

from sqlalchemy import text

from app.database import SessionLocal, engine


@pytest.fixture
async def voting_setup():
    async with SessionLocal() as session:
        test_id = uuid4()

        user_id = (
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
                    "email": f"test-{test_id}@example.com",
                    "provider_user_id": f"test-user-{test_id}",
                },
            )
        ).scalar_one()

        poll_id = (
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
                        'Test Poll',
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

        option_id = (
            await session.execute(
                text("""
                    INSERT INTO options (
                        poll_id,
                        label
                    )
                    VALUES (
                        :poll_id,
                        'Option A'
                    )
                    RETURNING id
                """),
                {"poll_id": poll_id},
            )
        ).scalar_one()

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
                "user_id": user_id,
                "poll_id": poll_id,
            },
        )

        await session.execute(
            text("""
                INSERT INTO poll_ballot_state (
                    poll_id
                )
                VALUES (
                    :poll_id
                )
            """),
            {"poll_id": poll_id},
        )

        await session.commit()

        try:
            yield session, user_id, poll_id, option_id
        finally:
            await engine.dispose()