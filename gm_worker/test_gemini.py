import os
import sys
import asyncio
import logging

# This adds the 'backend/gm_worker' directory to the Python path
# so that imports like `from app.services...` work.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'gm_worker')))

from dotenv import load_dotenv

# --- Instructions ---
# 1. Make sure you have run `pip install -r backend/gm_worker/requirements.txt` in your local venv.
# 2. Make sure your `backend/.env` file has a valid GEMINI_API_KEY.
# 3. Run this script from the project root: `python backend/gm_worker/test_gemini.py`
# --------------------

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')

# The main function does not need to be async anymore since our service is now sync.
def main():
    """
    Main function to run the isolated Gemini service test.
    """
    print("--- Starting Isolated Gemini Service Test ---")
    
    dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    if not os.path.exists(dotenv_path):
        print(f"ERROR: .env file not found at {dotenv_path}")
        return
        
    load_dotenv(dotenv_path=dotenv_path)
    print("Loaded environment variables from .env file.")

    try:
        # CORRECTED: Import the factory function, not the old instance name.
        from app.services.gemini_service import get_gemini_service
        from app.models.schemas import GMStructuredResponse

        # CORRECTED: Call the factory to get an instance of the service.
        gemini_service = get_gemini_service()

        prompt = "A lone adventurer discovers a glowing sword embedded in a stone in the middle of a sun-dappled clearing. Describe the scene."
        print(f"\nPrompt: '{prompt}'")
        
        print("\nCalling Gemini Service...")
        
        # Call the synchronous method on the new instance.
        structured_response = gemini_service.generate_structured_narrative(
            prompt=prompt,
            response_model=GMStructuredResponse
        )
        
        print("\n--- TEST SUCCESSFUL ---")
        print("Received structured response:")
        print(structured_response)
        print("------------------------")

    except Exception as e:
        print(f"\n--- TEST FAILED ---")
        logging.error("An error occurred during the test:", exc_info=True)
        print("--------------------")

if __name__ == "__main__":
    # We no longer need asyncio to run this test.
    main()