from datetime import datetime

from pydantic import BaseModel, Field


class UserProfile(BaseModel):
    """Structured profile ProfileService builds from a user's memories."""

    name: str | None = Field(None, description="The user's name, if stated")
    education: str | None = Field(None, description="Current school/degree, if stated")
    work: str | None = Field(None, description="Current job/employer, if stated")
    location: str | None = Field(None, description="Where the user lives, if stated")
    skills: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list, description="Likes, dislikes, habits")
    # Required (no default) so structured output always fills it.
    summary: str = Field(description="Two or three sentences describing the user")


class ProfileResponse(BaseModel):
    profile: UserProfile | None
    updated_at: datetime | None
    stale: bool
