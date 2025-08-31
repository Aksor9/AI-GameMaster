# File: backend/gm_worker/app/tasks/game_logic.py
import random
import logging
import json
import uuid
import pika
import re
from ..worker import celery_app
from ..services.gemini_service import get_gemini_service
from ..services.rag_service import get_rag_service
from ..services.database_service import update_game_state_in_db, get_db_session
from ..services import gameplay_rules, crud
from ..core.config import settings
from ..models.schemas import *


logger = logging.getLogger(__name__)

# --- Helper Function (No changes) ---
def publish_result_to_queue(client_id: str, result: dict):
    """Publishes the result to the gm_results queue using a direct pika connection."""
    connection = None
    try:
        def json_serializer(o):
            if isinstance(o, uuid.UUID):
                return str(o)
            raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")

        message_body = json.dumps({"client_id": client_id, "result": result}, default=json_serializer)
        
        connection = pika.BlockingConnection(pika.URLParameters(settings.RABBITMQ_URL))
        channel = connection.channel()
        channel.queue_declare(queue='gm_results', durable=True)
        
        channel.basic_publish(
            exchange='',
            routing_key='gm_results',
            body=message_body,
            properties=pika.BasicProperties(delivery_mode=2)
        )
        logger.info(f"Published event for client {client_id} to queue 'gm_results' via Pika producer.")
    except Exception as e:
        logger.error(f"Failed to publish result via Pika producer: {e}", exc_info=True)
    finally:
        if connection and connection.is_open:
            connection.close()

# --- NEW: AI-Powered Helper Functions ---
def _get_natural_language_choice(gemini_service, action_text: str, num_options: int) -> int:
    """Uses the LLM to parse a natural language choice into a number."""
    prompt = f"""
    The user was presented with {num_options} options, numbered 1 to {num_options}.
    The user's input was: "{action_text}"
    Analyze the input and determine which number the user chose.
    If the input is ambiguous or does not seem to be a choice, respond with 0.
    Your response must be a single integer.
    """
    try:
        response_text = gemini_service.generate_narrative(prompt)
        match = re.search(r'\d+', response_text)
        if match:
            choice = int(match.group(0))
            if 1 <= choice <= num_options:
                return choice
    except Exception:
        pass
    
    match = re.search(r'\d+', action_text)
    if match:
        choice = int(match.group(0))
        if 1 <= choice <= num_options:
            return choice
            
    return 0

def _determine_narrative_focus(game_state: GameState) -> str:
    """Analyzes the game state to provide a narrative focus for the GM."""
    active_quests = [q for q in game_state.quest_log if q.status == 'active']
    if active_quests:
        current_objective = active_quests[0].objectives[0] if active_quests[0].objectives else "an unknown task"
        return f"Focus on advancing the active quest: '{active_quests[0].title}'. The next objective is: '{current_objective}'."
    if game_state.main_plot and game_state.main_plot.get('key_milestones'):
        current_milestone = game_state.main_plot['key_milestones'][0]
        return f"Focus on guiding the players towards the next main plot milestone: '{current_milestone}'."
    return "The players are exploring. Your goal is to introduce a new conflict, mystery, or a hook for a new quest to drive the story forward."

def _classify_intent(gemini_service, action_text: str) -> PlayerIntent:
    """Calls the LLM to classify the player's intent."""
    logger.info(f"--- Classifying Intent for action: '{action_text}' ---")
    intent_prompt = f"""
    You are a Dungeons & Dragons Dungeon Master's assistant. Your task is to analyze a player's action and classify its primary intent.

    Player's action: "{action_text}"

    **Priority Rule:** If the action describes a state-changing action (ATTACK, SKILL_CHECK, MANAGE_INVENTORY), that intent ALWAYS takes priority over passive ones (OBSERVE, SOCIAL).

    **Instructions & Examples:**
    1.  **Classify the intent_type:** Choose ONE from the list below based on the action's core verb.
        - 'ATTACK': For any direct physical or magical assault.
            - Examples: "I swing my sword at the goblin", "I shoot an arrow", "Attack the scout"
        - 'SKILL_CHECK': For actions requiring skill where the outcome is uncertain.
            - Examples: "I try to sneak past the guards", "I attempt to persuade the merchant", "I jump across the chasm"
        - 'MANAGE_INVENTORY': For interacting with items.
            - Examples: "I pick up the sword", "I drink the potion"
        - 'SOCIAL': For non-persuasive dialogue.
            - Examples: "I ask the bartender for rumors"
        - 'OBSERVE': ONLY if no other intent applies.
            - Examples: "I look around the room", "I examine the markings on the wall"

    2.  **For SKILL_CHECK intents, determine:**
        - `relevant_stat`: Choose from 'strength', 'dexterity', 'constitution', 'intelligence', 'wisdom', 'charisma'.
        - `required_dc`: Estimate a DC (5-25).

    3.  **Extract `target` and `item_name` where applicable.**

    Your response MUST be a valid JSON object matching the PlayerIntent schema.
    """
    try:
        player_intent = gemini_service.generate_structured_narrative(prompt=intent_prompt, response_model=PlayerIntent)
        logger.info(f"Intent Classified: {player_intent}")
        return player_intent
    except Exception as e:
        logger.error(f"Intent classification failed: {e}. Defaulting to OBSERVE.", exc_info=True)
        return PlayerIntent(intent_type="OBSERVE", action_description="look around", target=None)

# --- Core Game Phase Handlers ---

def _handle_start_new_game(game_state: GameState, language_pref: str) -> tuple[GameState, dict]:
    """Generates world options via LLM and transitions the game to WORLD_SELECTION."""
    logger.info("Handling start new game: Generating worlds.")
    gemini_service = get_gemini_service()
    
    prompt = f"""
    You are a Game Master starting a new fantasy RPG. Your first task is to create 4 unique, detailed fantasy worlds, plus a 5th 'Surprise Me' option.
    For each of the 4 named worlds, you MUST provide:
    - name: A unique, evocative name.
    - description: A rich paragraph describing the world's atmosphere, key locations, and inhabitants.
    - main_plot_hook: A single, intriguing sentence to draw players in.
    - main_plot: A secret JSON object for the GM with 'synopsis', 'key_milestones' (a list of 3-5 major plot points), and a 'final_boss'.
    - initial_bestiary: A list of 3-4 thematically appropriate monster Entities for this world.

    Your final response MUST be a valid JSON object matching the GMWorldCreationResponse model.
    The 'narrative' field should be a welcoming message. The 'updated_summary' should be "The adventure is about to begin.".
    **CRITICAL INSTRUCTION: All text in your response MUST be in {language_pref}.**
    """
    response = gemini_service.generate_structured_narrative(prompt=prompt, response_model=GMWorldCreationResponse)
    
    game_state.game_phase = "WORLD_SELECTION"
    game_state.world_selection_options = response.world_options
    game_state.story_summary = response.updated_summary
    
    return game_state, {
        "event_type": "WORLD_OPTIONS_PRESENTED",
        "narrative": response.narrative,
        "world_options": [world.model_dump() for world in response.world_options],
        "new_game_state": game_state.model_dump(mode='json')
    }

def _handle_world_selection(game_state: GameState, action_text: str, language_pref: str) -> tuple[GameState, dict]:
    gemini_service = get_gemini_service()
    num_options = len(game_state.world_selection_options) if game_state.world_selection_options else 0
    choice_index = _get_natural_language_choice(gemini_service, action_text, num_options) - 1
    
    if 0 <= choice_index < num_options:
        selected_world = game_state.world_selection_options[choice_index]
        game_state.world = selected_world
        game_state.main_plot = selected_world.main_plot
        game_state.bestiary = {entity.name: entity for entity in selected_world.initial_bestiary}
        game_state.game_phase = "CHARACTER_CREATION_NUM_PLAYERS"
        narrative = f"You have chosen the world of {selected_world.name}. {selected_world.main_plot_hook}\nHow many adventurers will be embarking on this journey? (1-4)"
        return game_state, {"event_type": "STATE_UPDATE_PROMPT_USER", "narrative": narrative, "prompt_user_for": "number_of_players"}
    else:
        return game_state, {"event_type": "ERROR", "narrative": f"Invalid choice. Please choose a number from 1 to {num_options}."}

def _handle_character_creation(game_state: GameState, client_id: str, action_text: str, language_pref: str) -> tuple[GameState, dict]:
    sub_phase = game_state.game_phase
    gemini_service = get_gemini_service()
    language_instruction = f"**CRITICAL INSTRUCTION: All text in your response MUST be in {language_pref}.**"
    player_num = game_state.characters_created + 1
    
    if sub_phase == "CHARACTER_CREATION_NUM_PLAYERS":
        choice = _get_natural_language_choice(gemini_service, action_text, 4)
        if not 1 <= choice <= 4:
            return game_state, {"event_type": "ERROR", "narrative": "Please enter a number from 1 to 4."}
        
        game_state.num_players_to_create = choice
        game_state.game_phase = "CHARACTER_CREATION_CLASSES"
        prompt = f"""
        Based on the world of '{game_state.world.name}' ({game_state.world.description}), generate 4 unique character classes suitable for that world.
        For each class, you MUST provide:
        - name: A unique class name.
        - description: A paragraph describing the class.
        - positive_attribute: A single descriptive word (e.g., 'Brave', 'Cunning').
        - starting_weapon: The name of a low-tier weapon.
        - starting_object: A non-weapon starting item.
        - starting_currency: An integer amount of gold.
        - base_stats: A balanced set of D&D stats (strength, dexterity, constitution, intelligence, wisdom, charisma), each between 8 and 18, with a total sum of around 75.
        - initial_abilities: A list of 1-2 descriptive skill or ability names (e.g., ["Shadow Meld", "Beast Taming"]).
        
        Your response MUST be a valid JSON object matching the GMClassCreationResponse model.
        **CRITICAL INSTRUCTION: All text in your response MUST be in {language_pref}.**
        """
        response = gemini_service.generate_structured_narrative(prompt=prompt, response_model=GMClassCreationResponse)
        game_state.class_selection_options = response.class_options
        return game_state, {"event_type": "CLASS_OPTIONS_PRESENTED", "narrative": f"{response.narrative}\nPlease choose a class for Player {player_num}.", "class_options": [opt.model_dump() for opt in response.class_options]}

    elif sub_phase == "CHARACTER_CREATION_CLASSES":
        num_options = len(game_state.class_selection_options) if game_state.class_selection_options else 0
        choice_index = _get_natural_language_choice(gemini_service, action_text, num_options) - 1
        if not 0 <= choice_index < num_options:
            return game_state, {"event_type": "ERROR", "narrative": f"Invalid choice. Please choose a number from 1 to {num_options}."}
        
        chosen_class = game_state.class_selection_options[choice_index]
        game_state.pending_character_class = chosen_class
        game_state.game_phase = "CHARACTER_CREATION_DETAILS"
        return game_state, {"event_type": "STATE_UPDATE_PROMPT_USER", "narrative": f"Chosen '{chosen_class.name}' for Player {player_num}.\nPlease provide: Name, Age, Gender, Backstory (comma-separated).", "prompt_user_for": f"details_for_player_{player_num}"}

    elif sub_phase == "CHARACTER_CREATION_DETAILS":
        try:
            parts = action_text.rsplit(',', 3)
            if len(parts) != 4: raise ValueError("Input does not have 4 comma-separated parts.")
            name, age_str, gender, backstory = [part.strip() for part in parts]
            
            pending_class = game_state.pending_character_class
            new_char = PlayerCharacter(
                client_id=client_id,
                name=name, age=int(age_str), gender=gender, backstory=backstory,
                character_class=pending_class.name,
                stats=pending_class.base_stats,
                skills=pending_class.initial_abilities,
                currency=pending_class.starting_currency,
                inventory=[
                    Item(name=pending_class.starting_weapon, description="A basic starting weapon.", category="weapon"),
                    Item(name=pending_class.starting_object, description="A curious starting object.", category="misc")
                ]
            )
            game_state.players[new_char.character_id] = new_char
            game_state.characters_created += 1
            game_state.pending_character_class = None

            if game_state.characters_created < game_state.num_players_to_create:
                game_state.game_phase = "CHARACTER_CREATION_CLASSES"
                return game_state, {"event_type": "CLASS_OPTIONS_PRESENTED", "narrative": f"Character '{name}' created! Now, create Player {game_state.characters_created + 1}.", "class_options": [opt.model_dump(mode='json') for opt in game_state.class_selection_options]}
            else:
                # All characters have been created, time to start the game!
                game_state.game_phase = "GAME_IN_PROGRESS"
                # Set the turn to the first character created.
                game_state.current_turn_entity_id = next(iter(game_state.players.keys()))
                
                logger.info("All characters created. Generating adventure introduction.")
                
                characters_summary_list = []
                for char in game_state.players.values():
                    characters_summary_list.append(f"- {char.name}, a {char.character_class} whose backstory is: '{char.backstory}'.")
                characters_summary = "\n".join(characters_summary_list)

                # This is a special, one-time call to the narrator to kick off the story.
                prompt = f"""
                {language_instruction}
                The adventure is about to begin in the world of {game_state.world.name}.
                The party consists of:
                {characters_summary}

                The main plot is: "{game_state.main_plot.get('synopsis', 'An unknown evil stirs.')}"

                **Your Task:** Write a compelling opening scene that introduces the setting and presents the party with their first situation or challenge, leading them toward the first key milestone: "{game_state.main_plot.get('key_milestones', ['an unexpected event'])[0]}".
                Your response MUST be a JSON object matching the GMTurnResponse model, which includes the initial 'updated_scene_context' and an 'active' quest in the 'updated_quest_log'.
                """
                # We use GMTurnResponse here because we want a full scene update.
                narrative_response = gemini_service.generate_structured_narrative(prompt=prompt, response_model=GMTurnResponse)
                
                game_state.story_summary = narrative_response.updated_summary
                game_state.scene_context = narrative_response.updated_scene_context
                game_state.quest_log = narrative_response.updated_quest_log
                
                return game_state, {
                    "event_type": "NARRATIVE_UPDATE",
                    "narrative": narrative_response.narrative,
                    "image_prompt": narrative_response.image_prompt,
                    "new_game_state": game_state.model_dump(mode='json')
                }
        except (ValueError, IndexError):
            return game_state, {"event_type": "ERROR", "narrative": "Invalid format. Please provide: Name, Age, Gender, Backstory."}
    
    return game_state, {"event_type": "ERROR", "narrative": "Unknown character creation state."}

def _handle_dice_resolution(game_state: GameState, action_text: str, language_pref: str) -> tuple[GameState, dict]:
    """Handles the resolution of a dice roll and narrates the outcome."""
    try:
        dice_roll = int(action_text.strip())
        if not 1 <= dice_roll <= 20: raise ValueError("Roll out of range")
    except (ValueError, IndexError):
        return game_state, {"event_type": "ERROR", "narrative": "Invalid dice roll. Please enter a number between 1 and 20."}

    game_state, outcome_description = gameplay_rules.resolve_skill_check(game_state, dice_roll)
    
    original_action = game_state.pending_action.action_text if game_state.pending_action else "a resolved skill check"
    acting_char_id = game_state.pending_action.acting_character_id if game_state.pending_action else game_state.current_turn_entity_id
    acting_player = game_state.players.get(acting_char_id)

    # After resolving, we clear the pending action and proceed to narration
    game_state.pending_action = None
    return _narrate_turn(game_state, acting_player, original_action, language_pref, outcome_description, is_danger_event=False)

def _handle_standard_turn(game_state: GameState, acting_char_id: str, action_text: str, language_pref: str) -> tuple[GameState, dict]:
    """
    Handles a standard turn: classify player intent, process it through game rules,
    and then either present a challenge or narrate the outcome.
    """
    gemini_service = get_gemini_service()
    rag_service = get_rag_service() # Ensure rag_service is available if needed by narrate
    
    acting_player = game_state.players.get(acting_char_id)
    if not acting_player:
        return game_state, {"event_type": "ERROR", "narrative": "Acting player not found."}

    # Step 1 & 2: Classify intent and process it through the rules engine.
    player_intent = _classify_intent(gemini_service, action_text)
    game_state, outcome_description, is_danger_event = gameplay_rules.process_turn_events(player_intent, game_state, acting_player)

    # Step 3: Decide whether to pause for player input or narrate.
    # CRITICAL: Check for the new, correct phase name.
    if game_state.game_phase == "AWAITING_DICE_ROLL_CONFIRMATION":
        # The rules engine has presented a challenge. The turn is now paused.
        # We return the challenge description to the player and wait for their confirmation.
        logger.info("Turn is pausing, awaiting dice roll confirmation from the player.")
        return game_state, {
            "event_type": "DICE_ROLL_REQUESTED",
            "narrative": outcome_description,
            "new_game_state": game_state.model_dump(mode='json') # Send the updated state
        }

    # If the game is not paused, proceed to the full narration step as normal.
    return _narrate_turn(game_state, acting_player, action_text, language_pref, outcome_description, is_danger_event)

def _handle_dice_roll_confirmation(game_state: GameState, language_pref: str) -> tuple[GameState, dict]:
    """
    Handles PHASE 2 of a skill check: Player has confirmed they want to roll.
    We now reveal the pre-calculated outcome and narrate it.
    """
    if not game_state.pending_action:
        return game_state, {"event_type": "ERROR", "narrative": "No skill check was pending for confirmation."}

    pending = game_state.pending_action
    acting_player = game_state.players.get(pending.acting_character_id)
    
    # The outcome was already decided, now we just build the string to describe it.
    if pending.is_success:
        outcome_description = (
            f"The dice roll is a {pending.dice_roll}! With your modifier of {pending.modifier:+}, your total is {pending.dice_roll + pending.modifier}. "
            f"A success against the DC of {pending.dc}!"
        )
    else:
        damage = random.randint(1, 4) # Consequence for failure
        acting_player.health -= damage
        outcome_description = (
            f"The dice roll is a {pending.dice_roll}. With your modifier of {pending.modifier:+}, your total is {pending.dice_roll + pending.modifier}. "
            f"Unfortunately, that's not enough to beat the DC of {pending.dc}. You fail and take {damage} damage."
        )
    
    # Clean up the state
    original_action = pending.action_text
    game_state.pending_action = None
    game_state.game_phase = "GAME_IN_PROGRESS"
    
    # Now, proceed to the narration step with this factual outcome.
    return _narrate_turn(game_state, acting_player, original_action, language_pref, outcome_description, is_danger_event=False)


def _narrate_turn(game_state: GameState, acting_player: PlayerCharacter, action_text: str, language_pref: str, outcome_description: str, is_danger_event: bool) -> tuple[GameState, dict]:
    """Generates the final narrative for a turn, now with enhanced context."""
    gemini_service = get_gemini_service()
    rag_service = get_rag_service()
    
    narrative_focus = _determine_narrative_focus(game_state)
    context_str = "\n".join(rag_service.query_relevant_history(game_id=game_state.game_id, query_text=action_text))

    narration_prompt = f"""
    You are a Proactive DnD Game Master.
    **Core Directives:**
    - Drive the story according to the Narrative Focus.
    - Be consistent with the Factual Outcome.
    - Do not repeat information the player obviously knows (like their inventory contents).
    - Principle of Player Agency: If a player states a fact about the world that isn't game-breaking, accept it as true.
    
    **NARRATIVE FOCUS FOR THIS TURN:** {narrative_focus}

    **CONTEXT:**
    - World: {game_state.world.name}
    - Scene: {game_state.scene_context.location_name} - {game_state.scene_context.description}
    - Character: {acting_player.name}, the {acting_player.character_class}
    - Immediately Previous Turn: {game_state.previous_turn_narrative or "This is the first turn."}
    - Long-Term History (RAG): {context_str or "None"}

    **ACTION & OUTCOME:**
    - Player's Action: '{action_text}'
    - Factual Outcome (from rules): "{outcome_description}"

    **YOUR TASK:**
    Narrate a compelling scene based on all the above. Update the scene context, quest log, and provide a new summary. Respond in GMTurnResponse JSON format in {language_pref}.
    """
    
    narrative_response = gemini_service.generate_structured_narrative(prompt=narration_prompt, response_model=GMTurnResponse)
    
    game_state.story_summary = narrative_response.updated_summary
    game_state.scene_context = narrative_response.updated_scene_context
    game_state.quest_log = narrative_response.updated_quest_log
    game_state.previous_turn_narrative = narrative_response.narrative
    
    rag_service.add_narrative_turn(game_id=game_state.game_id, player_action=action_text, gm_narrative=narrative_response.narrative)
    
    result_payload = {"event_type": "NARRATIVE_UPDATE", "narrative": narrative_response.narrative, "new_game_state": game_state.model_dump(mode='json')}
    return game_state, result_payload

# --- Combat and NPC Tasking (Unchanged) ---
def _advance_turn_in_combat(game_state: GameState) -> tuple[GameState, bool]:
    current_turn_id = game_state.current_turn_entity_id
    # ... (code for this function remains the same as your original)
    try:
        current_index = game_state.initiative_order.index(current_turn_id)
        next_index = (current_index + 1) % len(game_state.initiative_order)
        next_entity_id = game_state.initiative_order[next_index]
        game_state.current_turn_entity_id = next_entity_id
        is_npc_turn = next_entity_id not in game_state.players
        logger.info(f"Turn advanced from {current_turn_id} to {next_entity_id} (Is NPC: {is_npc_turn}).")
        return game_state, is_npc_turn
    except (ValueError, IndexError):
        logger.error("Could not advance turn, defaulting to first in initiative.")
        if not game_state.initiative_order: return game_state, False
        first_entity_id = game_state.initiative_order[0]
        game_state.current_turn_entity_id = first_entity_id
        is_npc_turn = first_entity_id not in game_state.players
        return game_state, is_npc_turn


def _handle_npc_turn(game_state: GameState, npc_id: str, language_pref: str) -> tuple[GameState, str]:
    # ... (code for this function remains the same as your original)
    gemini_service = get_gemini_service()
    npc_entity = next((e for e in game_state.scene_context.entities if e.instance_id == npc_id), None)
    if not npc_entity or npc_entity.health <= 0: return game_state, f"{npc_entity.name if npc_entity else npc_id} cannot act."
    player_summaries = [f"{p.name} ({p.health}/{p.max_health} HP)" for p in game_state.players.values() if p.health > 0]
    if not player_summaries: return game_state, "There are no conscious players to target."
    prompt = f"""
    You are a tactical AI for a D&D combat. It's the turn of a '{npc_entity.name}' ({npc_entity.health} HP).
    The available player targets are: {', '.join(player_summaries)}.
    The NPC's personality is: {npc_entity.description}.
    Based on this, decide the NPC's action. Choose an intent ('ATTACK', 'DEFEND', 'USE_ABILITY') and a valid target from the player list.
    Respond in PlayerIntent JSON format in {language_pref}.
    """
    try:
        npc_intent = gemini_service.generate_structured_narrative(prompt, response_model=PlayerIntent)
        npc_as_actor = PlayerCharacter(**npc_entity.model_dump())
        game_state, outcome_description, _ = gameplay_rules.process_turn_events(npc_intent, game_state, npc_as_actor)
        return game_state, outcome_description
    except Exception as e:
        logger.error(f"Failed to handle NPC turn for {npc_id}: {e}", exc_info=True)
        return game_state, f"{npc_entity.name} hesitates, unsure of what to do."

@celery_app.task(name="app.tasks.game_logic.process_npc_turn_task")
def process_npc_turn_task(session_id_str: str, client_id: str):
    session_id = uuid.UUID(session_id_str)
    logger.info(f"NPC Turn Task started for session {session_id} -> client {client_id}")
    with get_db_session() as db:
        session_data = crud.get_session_by_id(db, session_id)
        if not session_data or not session_data.game_state: return
        game_state = GameState.model_validate(session_data.game_state)
    npc_id = game_state.current_turn_entity_id
    language_pref = "en" # Placeholder
    game_state, npc_outcome = _handle_npc_turn(game_state, npc_id, language_pref)
    remaining_hostiles = any(e.is_hostile and e.health > 0 for e in game_state.scene_context.entities)
    final_narrative = npc_outcome
    if not remaining_hostiles:
        game_state.game_phase = "GAME_IN_PROGRESS"
        final_narrative += "\n\n**Combat has ended!**"
    else:
        game_state, is_next_turn_npc = _advance_turn_in_combat(game_state)
        if is_next_turn_npc:
            process_npc_turn_task.delay(session_id_str=session_id_str, client_id=client_id)
    result_payload = {"event_type": "NARRATIVE_UPDATE", "narrative": final_narrative, "new_game_state": game_state.model_dump(mode='json')}
    update_game_state_in_db(session_id=session_id, new_game_state=game_state)
    publish_result_to_queue(client_id, result_payload)

# --- MAIN TASK FOR PLAYER ACTIONS (Refactored) ---
@celery_app.task(name="app.tasks.game_logic.process_game_action_task")
def process_game_action_task(payload: dict):
    # 1. Setup
    session_id = uuid.UUID(payload.get("session_id"))
    game_state = GameState.model_validate(payload.get("game_state", {}))
    client_id = payload.get("client_id")
    action_text = payload.get("client_action", {}).get("action_type", "observe")
    language_pref = payload.get("language", "en")
    
    initial_phase = game_state.game_phase
    logger.info(f"Dispatching for phase: {initial_phase}, action: '{action_text}'")

    if action_text == "FORCE_GAME_STATE":
        forced_state_data = payload.get("client_action", {}).get("payload")
        if forced_state_data:
            logger.warning("FORCE_GAME_STATE action received. Overwriting state.")
            final_game_state = GameState.model_validate(forced_state_data)
            final_game_state.session_id = session_id
            result_payload = { "event_type": "STATE_FORCED", "narrative": "State forced for testing." }
            update_game_state_in_db(session_id=session_id, new_game_state=final_game_state)
            if 'new_game_state' not in result_payload:
                 result_payload['new_game_state'] = final_game_state.model_dump(mode='json')
            publish_result_to_queue(client_id, result_payload)
            logger.info("Task for action 'FORCE_GAME_STATE' completed and results published.")
            return {"status": "success"}
        else:
            logger.error("FORCE_GAME_STATE action received without payload.")
            return {"status": "error", "message": "FORCE_GAME_STATE requires a payload."}

    # 2. MAIN DISPATCHER
    final_game_state, result_payload = game_state, {}

    if initial_phase == "NEW_GAME":
        final_game_state, result_payload = _handle_start_new_game(game_state, language_pref)
    
    elif initial_phase == "WORLD_SELECTION":
        final_game_state, result_payload = _handle_world_selection(game_state, action_text, language_pref)
    
    elif initial_phase.startswith("CHARACTER_CREATION"):
        final_game_state, result_payload = _handle_character_creation(game_state, client_id, action_text, language_pref)
    
    elif initial_phase == "AWAITING_DICE_ROLL_CONFIRMATION":
        final_game_state, result_payload = _handle_dice_roll_confirmation(game_state, language_pref)
        
    elif initial_phase == "IN_COMBAT":
        acting_char_id = game_state.current_turn_entity_id
        if not acting_char_id or acting_char_id not in game_state.players:
             return {"status": "error", "reason": "Not a valid player's turn"}
        final_game_state, result_payload = _handle_standard_turn(game_state, acting_char_id, action_text, language_pref)
        
    elif initial_phase == "GAME_IN_PROGRESS":
        acting_char_id = game_state.current_turn_entity_id
        if not acting_char_id or acting_char_id not in game_state.players:
             logger.error(f"GAME_IN_PROGRESS but no valid character has the turn. Defaulting to first player.")
             acting_char_id = next(iter(game_state.players.keys()), None)
             if not acting_char_id:
                 return {"status": "error", "message": "Game is in progress but no players exist."}
             game_state.current_turn_entity_id = acting_char_id
        
        final_game_state, result_payload = _handle_standard_turn(game_state, acting_char_id, action_text, language_pref)

    else:
        logger.error(f"Unhandled game phase: {initial_phase}.")
        final_game_state, result_payload = game_state, {"event_type": "ERROR", "narrative": f"Unhandled state '{initial_phase}'."}

    # 3. PERSIST STATE MID-WAY
    if final_game_state:
        update_game_state_in_db(session_id=session_id, new_game_state=final_game_state)
    
    # 4. PUBLISH the result of the player's turn
    if result_payload:
        if final_game_state and 'new_game_state' not in result_payload:
             result_payload['new_game_state'] = final_game_state.model_dump(mode='json')
        publish_result_to_queue(client_id, result_payload)

    # 5. POST-TURN LOGIC
    if final_game_state and final_game_state.game_phase == "IN_COMBAT":
        if initial_phase == "IN_COMBAT":
            final_game_state, is_npc_turn = _advance_turn_in_combat(final_game_state)
        else: # Combat just started
            is_npc_turn = final_game_state.current_turn_entity_id not in final_game_state.players
            
        if is_npc_turn:
            process_npc_turn_task.delay(session_id_str=str(session_id), client_id=client_id)
            update_game_state_in_db(session_id=session_id, new_game_state=final_game_state)
    
    elif final_game_state and final_game_state.game_phase == "GAME_IN_PROGRESS":
        player_ids = list(final_game_state.players.keys())
        acting_char_id = game_state.current_turn_entity_id
        if len(player_ids) > 1 and acting_char_id in player_ids:
            current_idx = player_ids.index(acting_char_id)
            next_idx = (current_idx + 1) % len(player_ids)
            final_game_state.current_turn_entity_id = player_ids[next_idx]
            update_game_state_in_db(session_id=session_id, new_game_state=final_game_state)

    logger.info(f"Task for action '{action_text}' fully processed.")
    return {"status": "success"}
