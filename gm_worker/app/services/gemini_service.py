import instructor
import google.generativeai as genai
import logging
from typing import Type
from pydantic import BaseModel
from ..core.config import settings

logger = logging.getLogger(__name__)

# Variable global para el Singleton
_gemini_service_instance = None

class GeminiService:
    def __init__(self, api_key: str):
        # The constructor for the service, takes an API key.
        if not api_key or "YOUR_GEMINI_API_KEY" in api_key:
            raise ValueError("GEMINI_API_KEY is not set or is invalid.")
        
        genai.configure(api_key=api_key)
        try:
            # Patch the standard synchronous client with instructor.
            self.client = instructor.from_gemini(
                client=genai.GenerativeModel(model_name="gemini-1.5-flash"),
                mode=instructor.Mode.GEMINI_JSON,
            )
            logger.info("Gemini Service instance created.")
        except Exception as e:
            logger.error(f"Failed to initialize Instructor with Gemini: {e}")
            raise

    # This is a standard, synchronous function. No async/await.
    def generate_structured_narrative(self, prompt: str, response_model: Type[BaseModel]) -> BaseModel:
        # It takes a prompt and a Pydantic model and returns an instance of that model.
        try:
            logger.info(f"Generating structured response for model: {response_model.__name__}")
            # The `instructor` patched client makes a blocking network call here.
            # It is not an awaitable coroutine.
            response = self.client.messages.create(
                messages=[{"role": "user", "content": prompt}],
                response_model=response_model,
            )
            logger.info("Successfully received structured response from Gemini.")
            return response
        except Exception as e:
            logger.error(f"Error calling Gemini API: {e}", exc_info=True)
            raise

def get_gemini_service() -> GeminiService:
    """Factory function to get a GeminiService instance using the Singleton pattern."""
    global _gemini_service_instance
    if _gemini_service_instance is None:
        _gemini_service_instance = GeminiService(api_key=settings.GEMINI_API_KEY)
    return _gemini_service_instance