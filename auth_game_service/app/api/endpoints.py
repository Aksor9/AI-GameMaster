# File: backend/auth_game_service/app/api/endpoints.py

import logging
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import BaseModel

from ..services import message_queue, crud
from ..services.database_service import get_db_session
from ..models.schemas import GameState
from .connection_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter()

# --- HTTP ENDPOINT ---

class LanguageUpdateRequest(BaseModel):
    """Pydantic model for the language update request body."""
    language: str

@router.post("/users/{username}/language", status_code=200, tags=["User Management"])
def update_user_language(username: str, request: LanguageUpdateRequest):
    """
    Updates the language preference for a given user.
    Creates the user if they do not exist.
    """
    # Validate the language code to prevent arbitrary data in the DB.
    if request.language not in ["en", "es", "ca"]:
        raise HTTPException(status_code=400, detail="Invalid language code. Use 'en', 'es', or 'ca'.")
    
    with get_db_session() as db:
        # get_or_create_user ensures the user exists before we try to update them.
        user = crud.get_or_create_user(db, username=username)
        
        user.language = request.language
        db.add(user) # Stage the change
        db.commit() # Commit the change to the database
        db.refresh(user) # Refresh the user object with the data from the DB
        
        logger.info(f"Updated language for user '{user.username}' (ID: {user.id}) to '{user.language}'.")
        return {"message": f"Language for user '{username}' updated to '{request.language}'."}

# --- WEBSOCKET ENDPOINT ---

@router.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """
    Handles WebSocket connections, game state loading, and action dispatching.
    """
    await manager.connect(websocket, client_id)
    try:
        # --- Database Interaction on Connect ---
        with get_db_session() as db:
            user = crud.get_or_create_user(db, username=client_id)
            session_data = crud.get_or_create_session(db, user_id=user.id)
            game_state = GameState.model_validate(session_data.game_state)
            logger.info(f"Loaded session for user {user.id} ({client_id}). Language: {user.language}. Phase: {game_state.game_phase}")

        # Send the current game state to the client upon connection
        await manager.send_personal_message(
            {"event": "game_state_update", "data": game_state.model_dump(mode='json')},
            client_id
        )

        # --- Main Message Loop ---
        while True:
            data = await websocket.receive_text()
            client_message = json.loads(data)
            
            # --- FIX 2: ALWAYS read the latest state from the DB (Single Source of Truth) ---
            with get_db_session() as db:
                user = crud.get_or_create_user(db, username=client_id)
                current_session = crud.get_latest_session(db, user_id=user.id)
                if not current_session: 
                    logger.error(f"Could not find session for user {user.id} inside loop.")
                    await manager.send_personal_message({"error": "Session not found."}, client_id)
                    continue # Wait for next message
                current_game_state = GameState.model_validate(current_session.game_state)

            task_payload = {
                "session_id": str(current_game_state.session_id),  # --- AÑADIDO: session_id ---
                "client_id": client_id,
                "game_state": current_game_state.model_dump(mode='json'),
                "client_action": client_message,
                "language": user.language
            }

            success = message_queue.publish_task(
                queue_name='gm_tasks',
                task_name='app.tasks.game_logic.process_game_action_task',
                task_payload=task_payload
            )
            if success:
                await manager.send_personal_message({"event": "action_acknowledged"}, client_id)
            else:
                await manager.send_personal_message({"error": "Could not process request."}, client_id)

    except WebSocketDisconnect:
        logger.info(f"Client {client_id} disconnected.")
    except Exception as e:
        logger.error(f"An unexpected error occurred for client {client_id}: {e}", exc_info=True)
    finally:
        manager.disconnect(client_id)