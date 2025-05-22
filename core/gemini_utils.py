# EasyAISubbing/core/gemini_utils.py
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold, GenerationConfig
from google.generativeai.types.content_types import to_part

import logging
import time
# import os # os import not used in this file

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 15 # Increased base delay

def configure_api(api_key):
    if not api_key:
        logger.error("API key missing for Gemini configuration.")
        return False
    try:
        genai.configure(api_key=api_key)
        # Test the configuration by listing models (lightweight check)
        # This might raise an exception if key is bad or network issue
        # list(genai.list_models()) # Can be time-consuming or fail if network is flaky
        # A more direct check might be to try a very small, non-billed operation if available,
        # or simply assume configuration worked if no immediate exception.
        # For now, the configure() call itself is the primary check.
        # A subsequent genai.get_model() or list_models() will reveal issues.
        logger.info("Gemini API configured (key set). Validity will be checked on first use.")
        return True
    except Exception as e:
        logger.error(f"Failed to configure Gemini API: {e}")
        return False

def list_available_models():
    """Lists available models, with a fallback list if API call fails."""
    try:
        models_info = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                is_multimodal_hint = "pro" in m.name.lower() and \
                                   any(ver in m.name.lower() for ver in ["1.5", "2.5", "next", "-latest", "flash"])
                user_facing_name = m.name.replace("models/", "")
                models_info.append({
                    "name": user_facing_name,
                    "display_name": m.display_name,
                    "multimodal_hint": is_multimodal_hint
                })
        models_info.sort(key=lambda x: (not x['multimodal_hint'], "pro" not in x['name'].lower(), x['name']))
        if not models_info: # If API returns empty list for some reason
            logger.warning("genai.list_models() returned an empty list. Using fallback models.")
            raise Exception("Empty model list from API") # Trigger fallback
        return models_info
    except Exception as e:
        logger.error(f"Error listing Gemini models: {e}. Using fallback list.")
        return [
            {"name": "gemini-1.5-pro-latest", "display_name": "Gemini 1.5 Pro (Latest) - Multimodal", "multimodal_hint": True},
            {"name": "gemini-1.5-flash-latest", "display_name": "Gemini 1.5 Flash (Latest) - Multimodal", "multimodal_hint": True},
            {"name": "gemini-pro", "display_name": "Gemini Pro (Text/Older Multimodal)", "multimodal_hint": False} # Simplified display name
        ]

def start_gemini_chat(model_name_from_user, initial_history=None):
    """
    Initializes and returns a Gemini chat session.
    """
    api_model_name_format = model_name_from_user if model_name_from_user.startswith("models/") else f"models/{model_name_from_user}"

    try:
        logger.info(f"Attempting to initialize Gemini chat with model: {model_name_from_user} (API format: {api_model_name_format})")
        # Check model existence and capabilities using the API format
        model_info = genai.get_model(api_model_name_format) # This can raise if model not found

        if 'generateContent' not in model_info.supported_generation_methods:
            logger.error(f"Model {model_name_from_user} (API: {api_model_name_format}) does not support 'generateContent', required for chat.")
            raise ValueError(f"Model {model_name_from_user} not suitable for chat functionality.")

        # Use the user-provided name (which might not have "models/") for GenerativeModel instance
        # The SDK internally prefixes with "models/" if not present.
        model_instance = genai.GenerativeModel(model_name_from_user)
        chat_session = model_instance.start_chat(history=initial_history if initial_history else [])
        logger.info(f"Gemini chat session started successfully with model '{model_name_from_user}'.")
        return chat_session
    except Exception as e:
        logger.error(f"Failed to start Gemini chat session with model {model_name_from_user} (API: {api_model_name_format}): {e}", exc_info=True)
        return None

def send_message_to_chat(chat_session, list_of_parts, temperature, safety_level=HarmBlockThreshold.BLOCK_NONE):
    """
    Sends a message (composed of one or more parts) to an active chat session and returns the text response.
    Handles retries for API errors.
    `list_of_parts` should be a list where each element is a Part (e.g., created by `to_part()`).
    `safety_level` controls the HarmBlockThreshold for all categories.
    """
    if not chat_session:
        logger.error("Chat session is not initialized.")
        return "[Error] Chat session not initialized."

    processed_parts = []
    for p_idx, p_item in enumerate(list_of_parts):
        if hasattr(p_item, 'inline_data') or hasattr(p_item, 'text'): # Already a Part object
            processed_parts.append(p_item)
        elif isinstance(p_item, str): # Simple text part
            processed_parts.append(to_part(p_item))
        elif isinstance(p_item, dict) and "mime_type" in p_item and "data" in p_item: # Blob for media
             try:
                # Ensure data is bytes if it's for media like audio/image
                if "audio/" in p_item["mime_type"] or "image/" in p_item["mime_type"]:
                    if not isinstance(p_item["data"], bytes):
                        logger.error(f"Data for media part at index {p_idx} (mime: {p_item['mime_type']}) is not bytes. Type: {type(p_item['data'])}")
                        return f"[Error] Invalid data type for media part at index {p_idx}."
                processed_parts.append(to_part(p_item))
             except Exception as e_to_part:
                logger.error(f"Failed to convert item at index {p_idx} to Part: {p_item}. Error: {e_to_part}")
                return f"[Error] Invalid part at index {p_idx} for chat message."
        else:
            logger.error(f"Invalid item type at index {p_idx} in list_of_parts: {type(p_item)}. Must be Part, str, or media blob dict.")
            return f"[Error] Invalid part type at index {p_idx} for chat message."

    if not processed_parts:
        logger.error("No valid parts to send in the message.")
        return "[Error] No content to send."

    last_exception = None
    for attempt in range(MAX_RETRIES):
        try:
            generation_config = GenerationConfig(temperature=temperature)
            safety_settings_map = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: safety_level,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: safety_level,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: safety_level,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: safety_level
            }

            log_prompt_preview = []
            for p in processed_parts:
                if hasattr(p, 'text'):
                    log_prompt_preview.append(f"<TextPart: {p.text[:100]}...>")
                elif hasattr(p, 'inline_data') and hasattr(p.inline_data, 'mime_type'):
                    log_prompt_preview.append(f"<MediaPart: {p.inline_data.mime_type}, Size: {len(p.inline_data.data)/1024:.2f}KB>")
                else:
                    log_prompt_preview.append("<UnknownPartType>") # More specific
            logger.debug(f"Sending to Gemini Chat (attempt {attempt+1}/{MAX_RETRIES}): {', '.join(log_prompt_preview)}")

            response = chat_session.send_message(
                processed_parts,
                generation_config=generation_config,
                safety_settings=safety_settings_map,
                stream=False
            )

            # Check for blocking first
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
                block_reason_msg = response.prompt_feedback.block_reason_message or str(response.prompt_feedback.block_reason)
                logger.warning(f"Gemini chat response (attempt {attempt+1}) blocked. Reason: {block_reason_msg}")
                return f"[Blocked] Gemini Chat: {block_reason_msg}"

            # Check if response has text and is not empty
            if not hasattr(response, 'text') or not response.text:
                finish_reason_val = "N/A"
                if response.candidates and response.candidates[0].finish_reason:
                    finish_reason_val = str(response.candidates[0].finish_reason.name) # Use enum name
                logger.warning(f"Gemini chat response (attempt {attempt+1}) empty or finished unexpectedly. Finish Reason: {finish_reason_val}")

                # If finish reason is not STOP (or OK, or 1), it might be an issue.
                # FinishReason enum: 0: UNSPECIFIED, 1: STOP, 2: MAX_TOKENS, 3: SAFETY, 4: RECITATION, 5: OTHER
                # Typically 1 (STOP) is a successful completion.
                if response.candidates and response.candidates[0].finish_reason != genai.types. candidats.FinishReason.STOP:
                     # Check if it's not explicitly blocked by safety in candidates (though prompt_feedback is better)
                    if response.candidates[0].finish_reason == genai.types. candidats.FinishReason.SAFETY:
                        safety_ratings_info = str(response.candidates[0].safety_ratings)
                        return f"[Blocked] Gemini Chat: Finished due to SAFETY. Ratings: {safety_ratings_info}"
                    return f"[Error] Gemini Chat: Finished with reason '{finish_reason_val}'. Potential issue."

                if attempt == MAX_RETRIES - 1:
                    return f"[Error] Gemini Chat: Empty response after {MAX_RETRIES} retries. Finish Reason: {finish_reason_val}"
                # Fallthrough to retry with delay for empty responses if not explicitly an error finish reason
            else: # Successful response with text
                generated_text_full = response.text.strip()
                logger.debug(f"Gemini Chat Raw Output (Attempt {attempt+1}): '{generated_text_full[:300]}...'")
                return generated_text_full

        except Exception as e:
            last_exception = e
            logger.error(f"Exception during Gemini chat API call (attempt {attempt+1}): {e}", exc_info=True)
            if "API key not valid" in str(e) or "PermissionDenied" in str(e): # More robust check for API key issues
                 return f"[Error] Gemini Chat: API key not valid or permission denied. Please check your API key."
            if "resource has been exhausted" in str(e).lower() or "quota" in str(e).lower() or "429" in str(e): # 429 is Too Many Requests
                 logger.warning(f"Gemini API rate limit or quota likely hit: {e}")
                 # Fallthrough to retry with delay for quota issues
            # Add more specific error handling if needed (e.g., model compatibility, input validation from API)
            elif "DeadlineExceeded" in str(e) or "504" in str(e): # Gateway timeout or deadline exceeded
                logger.warning(f"Gemini API timeout or deadline exceeded: {e}")
                # Fallthrough to retry

        if attempt < MAX_RETRIES - 1:
            # Implement exponential backoff with jitter for retries
            current_delay = (RETRY_DELAY_SECONDS * (2 ** attempt)) + (time.time_ns() % 1000 / 1000.0) # Add jitter
            logger.info(f"Retrying Gemini chat message in {current_delay:.2f}s...")
            time.sleep(current_delay)
        else:
            error_msg = f"[Error] Gemini Chat: Failed after {MAX_RETRIES} retries."
            if last_exception:
                error_msg += f" Last error: {str(last_exception)}"
            logger.error(error_msg)
            return error_msg

    logger.error("Unexpected: Gemini chat send_message_to_chat loop completed without returning.")
    return f"[Error] Unexpected Gemini chat logic failure in send_message_to_chat."