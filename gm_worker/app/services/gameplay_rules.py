# File: backend/gm_worker/app/services/gameplay_rules.py

import logging
import random
from typing import List, Tuple
from ..models.schemas import GameState, PlayerIntent, Item, PlayerCharacter, QuestRewards, Effect, PendingAction

logger = logging.getLogger(__name__)

INCOHERENT_ITEM_KEYWORDS = ["laser", "pistol", "spaceship", "computer", "phone", "gun"]

def initiate_combat(game_state: GameState) -> GameState:
    """
    Sets up the game state for turn-based combat.
    """
    logger.info(f"--- INITIATING COMBAT for game {game_state.game_id} ---")
    game_state.game_phase = "IN_COMBAT"
    
    combatants = list(game_state.players.values()) + [
        entity for entity in game_state.scene_context.entities if entity.is_hostile
    ]
    
    initiative_rolls = []
    for combatant in combatants:
        dex_modifier = (combatant.stats.get("dexterity", 10) - 10) // 2
        roll = random.randint(1, 20) + dex_modifier
        entity_id = getattr(combatant, 'character_id', getattr(combatant, 'instance_id', None))
        if entity_id:
            initiative_rolls.append((entity_id, roll))
            
    initiative_rolls.sort(key=lambda x: x[1], reverse=True)
    game_state.initiative_order = [entity_id for entity_id, roll in initiative_rolls]
    
    if game_state.initiative_order:
        game_state.current_turn_entity_id = game_state.initiative_order[0]
        logger.info(f"Initiative order: {game_state.initiative_order}. Turn starts with {game_state.current_turn_entity_id}.")
        
    return game_state

# --- Core Rule Engine Sub-Systems ---

def _apply_effects(acting_player: PlayerCharacter, relevant_stat: str = None) -> int:
    """Calculates the total modifier from all active conditions on a player."""
    total_modifier = 0
    for effect in acting_player.conditions:
        # Check if the effect applies to the current stat or is a general modifier
        if relevant_stat and effect.modifiers.get(relevant_stat):
            total_modifier += effect.modifiers.get(relevant_stat, 0)
        if effect.modifiers.get("all"):
            total_modifier += effect.modifiers.get("all", 0)
    return total_modifier

def _check_for_level_up(player: PlayerCharacter) -> Tuple[PlayerCharacter, str]:
    """Checks if a player has enough XP to level up and applies changes."""
    level_up_xp_threshold = player.level * 1000
    level_up_message = ""
    if player.xp >= level_up_xp_threshold:
        player.level += 1
        player.max_health += 10
        player.health = player.max_health
        player.xp -= level_up_xp_threshold
        level_up_message = f"{player.name} has reached Level {player.level}! Their health increases."
        logger.info(f"LEVEL UP: {player.name} is now level {player.level}.")
    return player, level_up_message

def _apply_rewards(player: PlayerCharacter, rewards: QuestRewards) -> Tuple[PlayerCharacter, str]:
    """Applies quest rewards to a player and checks for level up."""
    player.xp += rewards.xp
    player.currency += rewards.currency
    player.inventory.extend(rewards.items)
    
    reward_text = f"Received {rewards.xp} XP, {rewards.currency} currency."
    if rewards.items:
        reward_text += " Items: " + ", ".join([item.name for item in rewards.items])
    
    player, level_up_message = _check_for_level_up(player)
    if level_up_message:
        reward_text += f" {level_up_message}"
        
    return player, reward_text

def _check_quest_completion(game_state: GameState) -> Tuple[GameState, List[str]]:
    """
    Checks all active quests to see if their objectives have been met.
    """
    completed_quest_outcomes = []
    # This is a placeholder for more complex logic.
    return game_state, completed_quest_outcomes


# --- Handlers for Player Intents ---

def handle_inventory_intent(intent: PlayerIntent, game_state: GameState, acting_player: PlayerCharacter) -> Tuple[GameState, str]:
    item_name = intent.item_name
    if not item_name: return game_state, "The player specified no item."
    item_name = item_name.title()
    if intent.is_acquisition:
        if any(keyword in item_name.lower() for keyword in INCOHERENT_ITEM_KEYWORDS):
            return game_state, f"The player's attempt to find a '{item_name}' failed because such an object is entirely foreign to this world."
        if not any(item.name.lower() == item_name.lower() for item in acting_player.inventory):
            acting_player.inventory.append(Item(name=item_name, description="A newly found item.", category="misc"))
            return game_state, f"The player successfully acquired the '{item_name}'."
        else:
            return game_state, f"The player already has a '{item_name}'."
    else:
        item_to_remove = next((item for item in acting_player.inventory if item.name.lower() == item_name.lower()), None)
        if item_to_remove:
            acting_player.inventory.remove(item_to_remove)
            return game_state, f"The player has used or discarded the '{item_name}'."
        else:
            return game_state, f"The player tried to use a '{item_name}', but they don't have one."


def handle_skill_check_intent(intent: PlayerIntent, game_state: GameState, acting_player: PlayerCharacter) -> Tuple[GameState, str]:
    """
    Handles PHASE 1 of a skill check: Prepares the challenge and pre-calculates the result,
    then sets the game state to await player confirmation.
    """
    dc = intent.required_dc or 12
    stat_name = intent.relevant_stat.lower() if intent.relevant_stat and intent.relevant_stat.lower() in acting_player.stats else "dexterity"
    stat_value = acting_player.stats.get(stat_name, 10)
    stat_modifier = (stat_value - 10) // 2
    effect_modifier = _apply_effects(acting_player, relevant_stat=stat_name)
    total_modifier = stat_modifier + effect_modifier
    
    # --- Backend rolls the dice and determines the outcome IN SECRET ---
    dice_roll = random.randint(1, 20)
    total_roll = dice_roll + total_modifier
    is_success = total_roll >= dc
    
    # --- Change game state to wait for the player's confirmation ---
    game_state.game_phase = "AWAITING_DICE_ROLL_CONFIRMATION"
    
    # Store all context needed to resolve the roll later in the pending_action field
    game_state.pending_action = PendingAction(
        acting_character_id=acting_player.character_id,
        action_text=intent.action_description,
        dc=dc,
        modifier=total_modifier,
        stat_name=stat_name,
        dice_roll=dice_roll,
        is_success=is_success
    )
    
    # The outcome description is the *challenge* presented to the player.
    outcome_description = (
        f"You prepare to '{intent.action_description}'. "
        f"This will require a {stat_name.title()} check against a Difficulty Class (DC) of {dc}. "
        f"(Your character's total modifier for this is {total_modifier:+})."
    )
    logger.info(f"Initiated skill check for {acting_player.name}. Secret roll: {dice_roll} -> Total: {total_roll} vs DC {dc}. Success: {is_success}.")
    return game_state, outcome_description


def handle_attack_intent(intent: PlayerIntent, game_state: GameState, acting_player: PlayerCharacter) -> Tuple[GameState, str]:
    """Applies combat rules by finding a target and dealing damage."""
    target_name = intent.target
    if not target_name: return game_state, "The player wanted to attack, but did not specify a target."
    target_entity = next((e for e in game_state.scene_context.entities if e.name.lower() == target_name.lower()), None)
    if not target_entity: return game_state, f"The player tried to attack '{target_name}', but there is no such target."
    if not target_entity.is_hostile: return game_state, f"The player attacks '{target_name}', but they are not hostile."
    damage = acting_player.stats.get("strength", 10) // 2 + random.randint(1, 6)
    target_entity.health -= damage
    if target_entity.health <= 0:
        outcome_description = f"With a final blow, the player defeats {target_entity.name}!"
    else:
        outcome_description = f"The player attacks {target_entity.name}, dealing {damage} damage. It has {target_entity.health} health remaining."
    return game_state, outcome_description

# --- Main Turn Processing Pipeline ---

def process_turn_events(intent: PlayerIntent, game_state: GameState, acting_player: PlayerCharacter) -> Tuple[GameState, str, bool]:
    """
    The main pipeline for processing a turn's events with corrected random danger logic.
    """
    all_outcomes: List[str] = []
    
    # --- STEP 1: Check for Combat Initiation ---
    # This is the very first thing we check for state-changing actions.
    if intent.intent_type == "ATTACK" and game_state.game_phase != "IN_COMBAT":
        target_name = intent.target
        if target_name:
            target_entity = next((e for e in game_state.scene_context.entities if e.name.lower() == target_name.lower()), None)
            if target_entity and target_entity.is_hostile:
                logger.info(f"Attack on hostile target '{target_name}' is initiating combat.")
                game_state = initiate_combat(game_state)
                # The outcome of THIS turn is the start of the fight. The attack will be the NEXT turn.
                outcome_description = "Combat begins! The air crackles with tension as initiative is rolled."
                # is_danger is explicitly false here, as initiating combat is its own event.
                return game_state, outcome_description, False

    # --- STEP 2: Determine IF a random danger event should occur this turn. ---
    # This check now happens after combat initiation is ruled out.
    is_danger = (random.randint(1, 100) <= 5 and intent.intent_type not in ['OBSERVE', 'SOCIAL'])
    
    # --- STEP 3: Process the player's intended action ---
    action_outcome = ""
    if intent.intent_type == "MANAGE_INVENTORY":
        game_state, action_outcome = handle_inventory_intent(intent, game_state, acting_player)
    elif intent.intent_type == "SKILL_CHECK":
        game_state, action_outcome = handle_skill_check_intent(intent, game_state, acting_player)
    elif intent.intent_type == "ATTACK":
        # This branch is now only reached if we are ALREADY in combat.
        game_state, action_outcome = handle_attack_intent(intent, game_state, acting_player)
    else: # Default for OBSERVE, SOCIAL, etc.
        action_outcome = "The player takes a moment to interact with their surroundings."
    
    all_outcomes.append(action_outcome)
    
    # --- STEP 4: Check for combat end condition (only if in combat) ---
    if game_state.game_phase == "IN_COMBAT":
        remaining_hostiles = any(e.is_hostile and e.health > 0 for e in game_state.scene_context.entities)
        if not remaining_hostiles:
            game_state.game_phase = "GAME_IN_PROGRESS"
            game_state.initiative_order = []
            game_state.current_turn_entity_id = acting_player.character_id
            all_outcomes.append("\n\n**Combat has ended!**")
    
    # --- STEP 5: Concatenate all outcomes for the narrator. ---
    final_outcome_description = " ".join(filter(None, all_outcomes))
    
    # The `is_danger` flag is passed to the narrator, who will describe the event.
    # No mechanical effects are applied here, leaving it to the LLM's creativity.
    return game_state, final_outcome_description, is_danger