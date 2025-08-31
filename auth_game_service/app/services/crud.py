# File: backend/auth_game_service/app/services/crud.py

from sqlalchemy.orm import Session
import uuid

from ..models import database as db_models
from ..models import schemas as pydantic_schemas

def get_user_by_username(db: Session, username: str) -> db_models.User | None:
    """Fetches a user by their username."""
    return db.query(db_models.User).filter(db_models.User.username == username).first()

def create_user(db: Session, username: str, password: str) -> db_models.User:
    """Creates a new user."""
    db_user = db_models.User(username=username, hashed_password=password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def get_or_create_user(db: Session, username: str) -> db_models.User:
    """Gets a user, or creates one if it doesn't exist."""
    db_user = get_user_by_username(db, username)
    if not db_user:
        db_user = create_user(db, username, "dummy_password")
    return db_user

def get_latest_session(db: Session, user_id: int) -> db_models.GameSession | None:
    """Fetches the most recent game session for a user."""
    return db.query(db_models.GameSession).filter(db_models.GameSession.user_id == user_id).order_by(db_models.GameSession.updated_at.desc()).first()

def create_game_session(db: Session, user_id: int) -> db_models.GameSession:
    """
    Creates a new, initial game session for a user in a single, atomic transaction.
    """
    # Create the session object in Python first. The session_id will be generated
    # by the database upon commit.
    new_session = db_models.GameSession(user_id=user_id)
    
    # Create the initial GameState. We need a placeholder UUID for now,
    # as the final one will be set by the database.
    # We will immediately refresh the object to get the real one.
    placeholder_uuid = uuid.uuid4()
    initial_game_state = pydantic_schemas.GameState(
        session_id=placeholder_uuid,
        game_id=str(uuid.uuid4()),
        game_phase="NEW_GAME",
        players={},
        story_summary="A new story is about to unfold..."
    )
    
    # Assign the state to the session object *before* committing.
    new_session.game_state = initial_game_state.model_dump(mode='json')
    
    # Add to the session and commit. SQLAlchemy handles the INSERT in one go.
    db.add(new_session)
    db.commit()
    
    # After the commit, the `new_session` object is automatically updated by SQLAlchemy
    # with the actual values from the database, including the generated `session_id`.
    db.refresh(new_session)
    
    # Now, we ensure the GameState JSON also has the *correct* final session_id.
    final_game_state = pydantic_schemas.GameState.model_validate(new_session.game_state)
    final_game_state.session_id = new_session.session_id
    new_session.game_state = final_game_state.model_dump(mode='json')
    db.commit() # Commit this final correction
    db.refresh(new_session)
    
    return new_session

def get_or_create_session(db: Session, user_id: int) -> db_models.GameSession:
    """Gets the latest session for a user, or creates one if none exist."""
    session = get_latest_session(db, user_id)
    if not session:
        session = create_game_session(db, user_id)
    return session


def get_session_by_id(db: Session, session_id: uuid.UUID) -> db_models.GameSession | None:
    """Fetches a game session by its unique UUID."""
    return db.query(db_models.GameSession).filter(db_models.GameSession.session_id == session_id).first()