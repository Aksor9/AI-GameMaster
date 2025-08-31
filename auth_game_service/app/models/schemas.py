# File: backend/gm_worker/app/models/schemas.py

import uuid
from pydantic import BaseModel, Field
from typing import List, Dict, Optional

# --- Foundational Models for Game Mechanics & World ---

class Item(BaseModel):
    """Represents a single item."""
    name: str
    description: Optional[str] = None 
    category: str = "misc"

class Effect(BaseModel):
    """Represents a temporary status effect on a character or entity."""
    name: str
    description: str
    duration_turns: int # How many turns the effect lasts. -1 for permanent.
    modifiers: Dict[str, int] = Field(default_factory=dict) 

class QuestRewards(BaseModel):
    """Standardizes rewards for completing quests."""
    xp: int = 0
    currency: int = 0
    items: List[Item] = Field(default_factory=list)

class Quest(BaseModel):
    """Represents a quest or objective for the players."""
    quest_id: str = Field(default_factory=lambda: f"qst_{uuid.uuid4().hex[:8]}")
    title: str
    description: str
    objectives: List[str]
    rewards: QuestRewards
    status: str = "offered" # offered, active, completed, failed, rejected

class Entity(BaseModel):
    """Represents a non-player character (NPC) or monster template for the bestiary."""
    name: str
    description: str
    health: int
    stats: Dict[str, int] = Field(default_factory=dict)
    is_hostile: bool = False
    abilities: List[str] = Field(default_factory=list)

class SceneEntity(Entity):
    """Represents a specific instance of an entity in a scene, with its own ID."""
    instance_id: str = Field(default_factory=lambda: f"ent_inst_{uuid.uuid4().hex[:8]}")

class SceneContext(BaseModel):
    """Describes the current location, atmosphere, and entities present."""
    location_name: str = "An unknown place"
    description: str = "The air is still and the surroundings are shrouded in mystery."
    entities: List[SceneEntity] = Field(default_factory=list)

class PlayerCharacter(BaseModel):
    """Represents the state of a single player character."""
    character_id: str = Field(default_factory=lambda: f"char_{uuid.uuid4().hex[:8]}")
    name: str
    age: int
    gender: str
    backstory: str
    character_class: str
    level: int = 1
    xp: int = 0
    stats: Dict[str, int] = Field(default_factory=dict)
    skills: List[str] = Field(default_factory=list)
    conditions: List[Effect] = Field(default_factory=list)
    health: int = 100
    max_health: int = 100
    inventory: List[Item] = Field(default_factory=list)
    currency: int = 0

# --- Models for Game Setup Flow ---

class ClassOption(BaseModel):
    name: str
    description: str
    positive_attribute: str
    starting_weapon: str
    starting_currency: int
    starting_object: str
    base_stats: Dict[str, int]
    initial_abilities: List[str] = Field(default_factory=list)

class WorldOption(BaseModel):
    name: str
    description: str
    main_plot_hook: str # Visible to the player
    main_plot: Dict # The secret plot, for the GM only
    initial_bestiary: List[Entity] = Field(default_factory=list)

# --- NEW: Model for Pending Actions ---
class PendingAction(BaseModel):
    """
    Stores the complete context of a skill check while awaiting player confirmation.
    """
    acting_character_id: str
    action_text: str  # The original action, e.g., "jump the chasm"
    stat_name: str    # The stat being used, e.g., "dexterity"
    modifier: int     # The character's modifier for this roll
    dc: int           # The difficulty class of the challenge
    
    # --- SECRET, PRE-CALCULATED RESULTS ---
    dice_roll: int    # The d20 roll, already determined by the backend
    is_success: bool  # Whether the roll succeeded or failed

# --- Main GameState Model ---

class GameState(BaseModel):
    """The single source of truth for a game session."""
    session_id: uuid.UUID
    game_id: str
    game_phase: str = Field(..., description="e.g., ..., GAME_IN_PROGRESS, IN_COMBAT, AWAITING_DICE_ROLL, AWAITING_DICE_ROLL_CONFIRMATION")
    
    world: Optional[WorldOption] = None
    players: Dict[str, PlayerCharacter] = Field(default_factory=dict)
    
    # Shared Party Resources
    party_inventory: List[Item] = Field(default_factory=list)
    party_currency: int = 0

    # Contextual Information
    scene_context: SceneContext = Field(default_factory=SceneContext)
    quest_log: List[Quest] = Field(default_factory=list)
    story_summary: str = "The story is just beginning."
    previous_turn_narrative: Optional[str] = None # For short-term memory
    main_plot: Optional[Dict] = None # The secret main plot for the GM
    bestiary: Dict[str, Entity] = Field(default_factory=dict)
    
    # Turn Management
    current_turn_entity_id: Optional[str] = None # Can be a player character_id or an entity instance_id
    initiative_order: List[str] = Field(default_factory=list) # For combat
    pending_action: Optional[PendingAction] = None
    
    # Temporary data for game setup
    world_selection_options: Optional[List[WorldOption]] = None
    class_selection_options: Optional[List[ClassOption]] = None
    num_players_to_create: int = 0
    characters_created: int = 0
    pending_character_class: Optional[ClassOption] = None

# --- Intent and AI Response Models ---

class PlayerIntent(BaseModel):
    intent_type: str
    action_description: str
    item_name: Optional[str] = None
    is_acquisition: bool = False
    target: Optional[str] = None
    relevant_stat: Optional[str] = None
    required_dc: Optional[int] = None

class GMWorldCreationResponse(BaseModel):
    narrative: str
    world_options: List[WorldOption]
    updated_summary: str

class GMClassCreationResponse(BaseModel):
    narrative: str
    class_options: List[ClassOption]

class GMTurnResponse(BaseModel):
    narrative: str
    image_prompt: str
    updated_summary: str
    updated_scene_context: SceneContext
    updated_quest_log: List[Quest]