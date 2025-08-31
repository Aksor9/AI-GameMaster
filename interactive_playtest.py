# File location: backend/interactive_playtest.py

import asyncio
import websockets
import json
import httpx
import logging
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout

# Configure logging to hide noisy library messages
logging.basicConfig(level=logging.WARNING)

# Global variable to store the latest game state received from the server
latest_game_state = {}
dice_roll_is_pending = False

def display_game_state(state: dict, client_id: str):
    """Prints a formatted summary of the current game state."""
    print("\n" + "="*20 + " GAME STATE UPDATE " + "="*20)
    phase = state.get('game_phase', 'N/A')
    summary = state.get('story_summary', 'N/A')
    print(f"Phase: {phase}")
    print(f"Summary: {summary}")

    # In our new model, players are in a dict, so we find the player by client_id if needed
    # For now, we'll just display all players.
    players = state.get('players', {})
    if not players:
        print("  No players in the game yet.")
    for player_id, player in players.items():
        print(f"--- Player '{player.get('name')}' (ID: {player_id}) ---")
        print(f"  Health: {player.get('health', 'N/A')}/{player.get('max_health', 'N/A')}")
        inventory = player.get('inventory', [])
        if not inventory:
            print("  Inventory: (empty)")
        else:
            print("  Inventory:")
            for item in inventory:
                print(f"    - {item['name']}")
    print("="*59 + "\n")


async def listen_for_server_messages(websocket, client_id):
    """Waits for structured events from the server and reacts to them."""
    global latest_game_state, dice_roll_is_pending # , user_prompt_request
    try:
        async for message_str in websocket:
            message = json.loads(message_str)
            event_type = message.get("event_type")

            print("\n" + "---" * 5 + f" EVENT: {event_type or message.get('event')} " + "---" * 5)

            # user_prompt_request = None
            dice_roll_is_pending = False 

            if "narrative" in message:
                print(message['narrative'])

            if event_type == "WORLD_OPTIONS_PRESENTED":
                world_options = message.get("world_options", [])
                print("\n[CHOOSE YOUR WORLD]")
                for i, world in enumerate(world_options):
                    print(f"  {i+1}. {world.get('name')}")
                    print(f"     {world.get('description')}")
                print("\n(Type 'select 1', 'select 2', etc. to choose a world)")
            
            elif event_type == "CLASS_OPTIONS_PRESENTED":
                class_options = message.get("class_options", [])
                player_num = message.get('new_game_state', {}).get('characters_created', 0) + 1
                print(f"\n[CHOOSE YOUR CLASS FOR PLAYER {player_num}]")
                for i, char_class in enumerate(class_options):
                    print(f"  {i+1}. {char_class.get('name')}: {char_class.get('description')}")
                    print(f"     - Attribute: {char_class.get('positive_attribute')}")
                    print(f"     - Starts with: {char_class.get('starting_weapon')}, {char_class.get('starting_currency')} gold, and a {char_class.get('starting_object')}.")
                print("\n(Type 'choose class 1', 'choose class 2', etc.)")

            elif event_type == "STATE_UPDATE_PROMPT_USER":
                prompt_for = message.get("prompt_user_for")
                if prompt_for == "number_of_players":
                     print("\n[GM asks: How many players will be joining? (e.g., '1')]")
                elif "details_for_player" in prompt_for:
                     print("\n[GM asks: Please provide your character details (Name, Age, Gender, Backstory)]")
            elif event_type == "DICE_ROLL_REQUESTED":
                # The server is presenting a challenge.
                # The narrative for this event contains the challenge description.
                print("\n[!!!] ACTION REQUIRED: A skill check is needed!")
                dice_roll_is_pending = True # <-- Activa la bandera

            if "new_game_state" in message:
                latest_game_state = message["new_game_state"]
                display_game_state(latest_game_state, client_id)
                # --- AÑADIR ESTE BLOQUE ---
                if latest_game_state.get('game_phase') == "AWAITING_DICE_ROLL":
                    print("\n[!!!] ACTION REQUIRED: A skill check is needed!")

            elif message.get("event") == "game_state_update":
                 latest_game_state = message.get("data", {})
                 display_game_state(latest_game_state, client_id)

            elif message.get("event") == "action_acknowledged":
                 print("... (Your action is being processed by the GM) ...")
            
            elif "error" in message:
                 print(f"\n[SERVER ERROR]: {message['error']}")

    except websockets.exceptions.ConnectionClosed:
        print("\n[Connection to server lost.]")
    except Exception as e:
        print(f"\n[An error occurred in listener]: {e}", exc_info=True)

async def handle_user_input(websocket, client_id):
    """
    Waits for the user to type a command and sends it to the server.
    Handles the special case for dice roll confirmations.
    """
    session = PromptSession()
    # This global flag will be set by the listener thread
    global dice_roll_is_pending

    while True:
        try:
            # Use a single, shared prompt_text variable
            prompt_text = "> "
            message_to_send = None

            # --- Check the flag to determine the correct prompt and action ---
            if dice_roll_is_pending:
                prompt_text = "[Press Enter to roll the dice...]"
                # We wait for any input from the user to proceed
                await session.prompt_async(prompt_text) 
                
                # The action we send is always the same confirmation
                message_to_send = {"action_type": "CONFIRM_DICE_ROLL"}
                dice_roll_is_pending = False # Reset the flag immediately after sending

            else:
                # Normal action input
                if latest_game_state: # Ensure state is available
                    char_id = latest_game_state.get('current_turn_character_id')
                    # Find the character name, default to the client_id if not found
                    char_name = latest_game_state.get('players', {}).get(char_id, {}).get('name', client_id)
                    prompt_text = f"Turno de {char_name} > "
                
                action_text = await session.prompt_async(prompt_text)
                
                if not action_text:
                    continue # Don't send empty messages
                
                message_to_send = {"action_type": action_text}
            
            # Send the prepared message
            if message_to_send:
                await websocket.send(json.dumps(message_to_send))

        except (EOFError, KeyboardInterrupt):
            print("\n[Exiting playtest.]")
            return
        except Exception as e:
            print(f"\n[An error occurred in input handler]: {e}", exc_info=True)
            return

async def set_language_preference(username: str, lang_code: str):
    """Calls the HTTP endpoint to set the user's language."""
    url = f"http://localhost:8001/users/{username}/language"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={"language": lang_code})
            response.raise_for_status()
            print(f"[Language set to '{lang_code}' successfully via API.]")
            return True
    except httpx.RequestError:
        print(f"[Error setting language]: Could not connect to API at {url}.")
        print("[Please ensure the backend is running and accessible at localhost:8001.]")
        return False
    except httpx.HTTPStatusError as e:
        print(f"[Error setting language]: API returned an error: {e.response.status_code} - {e.response.text}")
        return False

async def main():
    """Main function to start the interactive client."""
    username = input("Enter your username/session ID: ")
    
    print("Select your language:")
    print("  1: English")
    print("  2: Spanish")
    
    lang_map = {"1": "en", "2": "es"}
    choice = input("Enter choice (1): ")
    lang_code = lang_map.get(choice, "en")
    
    if not await set_language_preference(username, lang_code):
        return

    uri = f"ws://localhost:8001/ws/{username}"
    print(f"\nConnecting to {uri}...")
    try:
        async with websockets.connect(uri) as websocket:
            print("--- Connection successful! Welcome to the Interactive Playtest. ---")
            
            listener_task = asyncio.create_task(listen_for_server_messages(websocket, username))
            input_task = asyncio.create_task(handle_user_input(websocket, username))
            
            done, pending = await asyncio.wait(
                [listener_task, input_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
    except Exception as e:
        print(f"[An unexpected error occurred during WebSocket connection]: {e}")

if __name__ == "__main__":
    print("--- Interactive Playtest Client ---")
    print("Type your actions and press Enter. Use Ctrl+D or Ctrl+C to exit.")
    asyncio.run(main())