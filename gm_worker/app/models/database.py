# File: backend/gm_worker/app/models/database.py

# This file must be an exact copy of the one in `auth_game_service`.

import uuid
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Uuid
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
import json

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    language = Column(String, nullable=False, server_default='en')
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    game_sessions = relationship("GameSession", back_populates="user")

class GameSession(Base):
    __tablename__ = "game_sessions"
    id = Column(Integer, primary_key=True, index=True)
    # The session_id column is now defined here as well.
    session_id = Column(Uuid, default=uuid.uuid4, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    game_state_json = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), default=func.now())
    user = relationship("User", back_populates="game_sessions")

    @property
    def game_state(self):
        return json.loads(self.game_state_json)

    @game_state.setter
    def game_state(self, state_dict: dict):
        self.game_state_json = json.dumps(state_dict)