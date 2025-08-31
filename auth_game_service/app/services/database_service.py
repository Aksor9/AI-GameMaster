import uuid  # <-- AÑADIDO
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from ..core.config import settings
from ..models import database as db_models
from ..models.schemas import GameState

# Create the database engine
engine = create_engine(settings.DATABASE_URL)

# Create a session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Initializes the database and creates tables if they don't exist."""
    db_models.Base.metadata.create_all(bind=engine)

@contextmanager
def get_db_session():
    """Provide a transactional scope around a series of operations."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def update_game_state_in_db(session_id: uuid.UUID, new_game_state: GameState):
    """
    Finds a specific game session by its unique UUID and updates its game_state_json field.
    """
    with get_db_session() as db:
        stmt = (
            update(db_models.GameSession)
            .where(db_models.GameSession.session_id == session_id)  # <-- MODIFICACIÓN CLAVE
            .values(game_state_json=new_game_state.model_dump_json())
        )
        db.execute(stmt)
        db.commit()