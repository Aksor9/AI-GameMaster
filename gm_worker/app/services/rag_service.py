import chromadb
import uuid
import logging
from chromadb.utils import embedding_functions
from ..core.config import settings

# Get a logger for this module
logger = logging.getLogger(__name__)

# Variable global para el Singleton
_rag_service_instance = None

# --- MODIFICATION: Define the embedding model explicitly ---
# This gives us control and ensures it's loaded predictably.
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

# Create a single instance of the embedding function.
# This will handle the download (if needed) and caching of the model.
embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=EMBEDDING_MODEL_NAME
)

class RAGService:
    """
    A service to manage interactions with a ChromaDB vector store for
    Retrieval-Augmented Generation (RAG).
    """
    def __init__(self, host: str, port: int):
        """
        The constructor for the RAG service. It connects to ChromaDB and
        initializes the collection using an explicit embedding function.
        """
        self.collection = None
        collection_name = "game_history"
        try:
            self.client = chromadb.HttpClient(host=host, port=port)

            # --- MODIFICATION: Use get_or_create_collection ---
            # This is a more concise and robust way to get or create a collection.
            # We pass the pre-defined embedding function to ensure all documents
            # are processed by the same model.
            self.collection = self.client.get_or_create_collection(
                name=collection_name,
                embedding_function=embedding_function
            )
            logger.info(f"RAG Service connected and using collection '{collection_name}'.")

        except Exception as e:
            # Add exc_info=True to log the full stack trace for better debugging.
            logger.error(f"Failed to connect or setup collection in ChromaDB: {e}", exc_info=True)
            self.client = None
            self.collection = None

    def add_narrative_turn(self, game_id: str, player_action: str, gm_narrative: str):
        """
        Adds a completed game turn (player action and GM response) to the vector memory.
        """
        if not self.collection:
            logger.error("Cannot add turn: ChromaDB collection not available.")
            return

        try:
            document_text = f"Player action: {player_action}\nGM response: {gm_narrative}"
            # Use a UUID for a unique, stable document ID.
            document_id = str(uuid.uuid4())

            self.collection.add(
                documents=[document_text],
                metadatas=[{"game_id": game_id}],
                ids=[document_id]
            )
            logger.info(f"Added narrative turn to RAG memory for game {game_id}.")
        except Exception as e:
            logger.error(f"Failed to add document to ChromaDB: {e}", exc_info=True)

    def query_relevant_history(self, game_id: str, query_text: str, n_results: int = 3) -> list[str]:
        """
        Queries the vector memory for past events from a specific game
        that are semantically similar to the query text.
        """
        if not self.collection:
            logger.error("Cannot query history: ChromaDB collection not available.")
            return []

        try:
            # To prevent errors, only query if the collection has items.
            collection_count = self.collection.count()
            if collection_count == 0:
                logger.warning("Query attempted on an empty collection.")
                return []

            # Ensure n_results does not exceed the number of items in the collection.
            results = self.collection.query(
                query_texts=[query_text],
                n_results=min(n_results, collection_count),
                where={"game_id": game_id} # Filter results for the specific game
            )
            # Safely extract the documents from the results.
            return results.get('documents', [[]])[0]
        except Exception as e:
            logger.error(f"Failed to query ChromaDB: {e}", exc_info=True)
            return []

def get_rag_service() -> RAGService:
    """Factory function for RAGService using the Singleton pattern."""
    global _rag_service_instance
    if _rag_service_instance is None:
        _rag_service_instance = RAGService(host=settings.CHROMADB_HOST, port=settings.CHROMADB_PORT)
    return _rag_service_instance

# --- NEW: Warm-up function ---
def warm_up_rag_service():
    """
    A "warm-up" function to be called at worker/application startup.

    It creates an instance of the RAGService, which forces the download and
    initialization of the embedding model before any tasks are processed.
    This prevents a "cold start" delay on the first request.
    """
    logger.info("Warming up RAG Service: Initializing embedding model...")
    try:
        # Instantiating the service triggers the model download/loading.
        get_rag_service()
        logger.info("RAG Service warmed up successfully. Model is ready.")
    except Exception as e:
        # Log the full traceback if the warm-up fails.
        logger.error(f"Failed to warm up RAG Service: {e}", exc_info=True)