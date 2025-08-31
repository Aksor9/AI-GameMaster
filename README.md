# AI - Game Master - AI-Powered Narrative RPG Engine 📜🏰🎲

Welcome to Project Narrador, a backend engine for creating dynamic, AI-driven narrative role-playing games. This system uses a microservices architecture to manage game state, player actions, and AI-generated content, providing a flexible and robust foundation for immersive storytelling experiences.

## Core Concepts

*   **AI as the Game Master:** The core of the experience is powered by Gemini's API, which acts as a proactive Game Master. It interprets player actions, generates narrative content, creates worlds, classes, and quests dynamically.
*   **Hybrid Rules Engine:** The system uses a hybrid model. The AI handles creative tasks (narration, classification), while a deterministic Python rules engine (`gameplay_rules.py`) manages the core mechanics (combat resolution, skill checks, inventory), ensuring fairness and preventing players from "tricking" the AI.
*   **Asynchronous & Event-Driven:** Built on FastAPI, Celery, and RabbitMQ, the architecture is fully asynchronous. Player actions are processed as tasks in the background, ensuring a smooth, non-blocking experience for the client.
*   **Stateful & Persistent:** Game state is managed in a structured way using Pydantic models and persisted in a PostgreSQL database, ensuring that player progress is always saved.
*   **Long-Term Memory (RAG):** The GM uses a ChromaDB vector database to remember past events, allowing it to maintain narrative consistency over long play sessions.

## Current Status: Playable Prototype 🎮

The project is currently in a **playable prototype** stage. The core game loop is functional, and a user can play a complete session from start to finish using the interactive playtest client.

**Implemented Features:**
*   Dynamic world generation.
*   Multi-step character creation with AI-generated classes and stats.
*   An interactive skill check system (the "two-phase dice roll").
*   A turn-based combat system with AI-controlled NPCs.
*   A robust inventory system with guardrails against out-of-world items.
*   A dynamic quest and narrative progression system.

### ⚠️ **Project on Hold & Future Gameplay Improvements**

Development on this prototype is **currently paused**. While the technical foundation is solid, the gameplay experience requires further refinement to reach its full potential. Key areas for future improvement include:

*   **Deeper Mechanical Integration:** Expanding the rules engine to handle more complex abilities, status effects, and tactical combat options.
*   **Enhanced AI Directing:** Further refining the AI prompts to create more complex plotlines, meaningful NPC interactions, and better pacing.
*   **Multi-Character Interaction:** Improving the turn management system to allow for more complex interactions between multiple player characters in the same party.
*   **UI/UX Integration:** The backend is ready to be connected to a proper game client (like Godot or Unity) to create a graphical user experience.

## Getting Started: Running the Playtest ▶️

To play the current version of the game, you need Docker and Python installed.

### 1. Prerequisites

*   Docker & Docker Compose
*   Python 3.11+
*   A Python virtual environment (`venv`)

### 2. Configuration

1.  Navigate to the `backend/` directory.
2.  Create a copy of the environment file template:
    ```bash
    cp .env.example .env
    ```
3.  Edit the `.env` file and fill in your unique values, especially your `GEMINI_API_KEY`.

### 3. Running the Backend

From the `backend/` directory, run the following command to build and start all the microservices:

```bash
docker-compose up --build
```


### 4. Running the Interactive Playtest Client


In a new terminal, navigate to the project root (narrador_project/).

Create and activate a virtual environment:

```bash
python -m venv venv
source venv/bin/activate
```

Install the required packages for the playtest client:

```
pip install -r backend/requirements-playtest.txt
```

Run the client to start playing:

```bash
python backend/interactive_playtest.py
```

Wirte ```START``` and follow the on-screen prompts to start a new game, create your world and characters, and begin your adventure!
