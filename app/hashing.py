import hashlib
from datetime import datetime
from uuid import UUID


def compute_record_hash(
    prev_hash: str | None,
    poll_id: UUID,
    option_id: UUID,
    created_at: datetime,
) -> str:
    canonical = "|".join(
        [
            prev_hash or "",
            str(poll_id),
            str(option_id),
            created_at.isoformat(),
        ]
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()