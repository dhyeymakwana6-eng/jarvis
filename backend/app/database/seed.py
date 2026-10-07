from sqlalchemy.orm import Session

from app.core.constants import DEFAULT_USER_ID
from app.models.user import User


def ensure_default_user(db: Session, user_id: int = DEFAULT_USER_ID) -> User:
    """
    Creates the single user every record is attributed to, if missing.
    Without it the first memory insert fails its users.id foreign key.

    The id is set explicitly, which doesn't advance the users id
    sequence; fine while this is the only way users are created.
    Revisit when real multi-user auth exists.
    """
    user = db.get(User, user_id)

    if user is None:
        # Name and profile fields are filled in by ProfileService
        # once the user tells Jarvis about themselves.
        user = User(id=user_id, name="", education="", skills="", preferences="")
        db.add(user)
        db.commit()

    return user
