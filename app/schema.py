from uuid import UUID

from pydantic import BaseModel


class VoteRequest(BaseModel):
    option_id: UUID
    ballot_id: UUID | None = None


class VoteResponse(BaseModel):
    ballot_id: UUID