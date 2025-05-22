# EasyAISubbing/core/config_manager.py
import configparser
import os
import logging
import sys # For determining app root path more reliably

logger = logging.getLogger(__name__) # Should be core.config_manager
CONFIG_FILE_NAME = "app_settings.ini"
CONFIG_SECTION_USER = "UserSettings" # Main section for user-configurable settings
CONFIG_SECTION_INTERNAL = "InternalState" # For app's internal state, less user-facing

def _get_app_root_path():
    """
    Determines the application's root directory.
    This is crucial for placing the config file correctly, especially when frozen.
    """
    if getattr(sys, 'frozen', False):
        # If the application is run as a bundle (e.g., PyInstaller)
        application_path = os.path.dirname(sys.executable)
    else:
        # If run as a normal Python script
        # Assume this file (config_manager.py) is in EasyAISubbing/core/
        # So, app root is two levels up.
        application_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return application_path

_CONFIG_FILE_PATH = os.path.join(_get_app_root_path(), CONFIG_FILE_NAME)
logger.info(f"Application settings file path determined as: {_CONFIG_FILE_PATH}")


def _read_config():
    """Reads the config file and returns the ConfigParser object."""
    config = configparser.ConfigParser()
    if os.path.exists(_CONFIG_FILE_PATH):
        try:
            config.read(_CONFIG_FILE_PATH, encoding='utf-8')
        except configparser.Error as e:
            logger.warning(f"Could not read config file {_CONFIG_FILE_PATH}: {e}. A new one may be created or defaults used.")
    return config

def _write_config(config):
    """Writes the ConfigParser object to the config file."""
    try:
        # Ensure the directory for the config file exists
        config_dir = os.path.dirname(_CONFIG_FILE_PATH)
        if config_dir and not os.path.exists(config_dir): # Check if config_dir is not empty (e.g. saving to current dir)
            os.makedirs(config_dir, exist_ok=True)
            logger.info(f"Created directory for config file: {config_dir}")

        with open(_CONFIG_FILE_PATH, 'w', encoding='utf-8') as configfile:
            config.write(configfile)
    except IOError as e:
        logger.error(f"Error writing config file {_CONFIG_FILE_PATH}: {e}")
    except Exception as e_general:
        logger.error(f"An unexpected error occurred while writing config to {_CONFIG_FILE_PATH}: {e_general}")


# --- Generic Save/Load ---
def save_setting(key, value, section=CONFIG_SECTION_USER):
    """Saves a setting to the specified section (default: UserSettings)."""
    config = _read_config()
    if not config.has_section(section):
        config.add_section(section)
    config.set(section, key, str(value)) # Ensure value is string
    _write_config(config)
    logger.debug(f"Saved setting to [{section}]: {key} = {value}")

def load_setting(key, default=None, section=CONFIG_SECTION_USER):
    """Loads a setting from the specified section (default: UserSettings)."""
    config = _read_config()
    # The fallback mechanism of config.get() is preferred
    return config.get(section, key, fallback=default)


# --- Specific Settings Wrappers ---

# --- API Key (Shared) ---
def save_api_key(api_key):
    save_setting("gemini_api_key", api_key, section=CONFIG_SECTION_INTERNAL) # Store securely or as internal

def load_api_key():
    """
    Loads the Gemini API key, prioritizing the GEMINI_API_KEY environment variable.
    Falls back to the config file if the environment variable is not set.
    If the API key is found in the environment variable, it is removed from the config file.
    """
    env_api_key = os.environ.get('GEMINI_API_KEY')
    if env_api_key:
        logger.info("Using Gemini API key from environment variable GEMINI_API_KEY.")
        
        # If API key is found in environment variable, remove it from config file if it exists
        config = _read_config()
        if config.has_section(CONFIG_SECTION_INTERNAL) and config.has_option(CONFIG_SECTION_INTERNAL, "gemini_api_key"):
            logger.info("Removing API key from config file as it's available via environment variable.")
            config.remove_option(CONFIG_SECTION_INTERNAL, "gemini_api_key")
            _write_config(config)
            
        return env_api_key

    logger.info("GEMINI_API_KEY environment variable not set. Loading API key from config file.")
    return load_setting("gemini_api_key", section=CONFIG_SECTION_INTERNAL)

# --- Common Gemini Settings (Can be used as defaults or for VideoAudioTab) ---
def save_last_gemini_model(model_name): # For VideoAudioTab primarily
    save_setting("video_audio_last_gemini_model", model_name)

def load_last_gemini_model(): # For VideoAudioTab primarily
    return load_setting("video_audio_last_gemini_model", "gemini-1.5-pro-latest") # Default to a good one

def save_gemini_temperature(temperature): # For VideoAudioTab primarily
    save_setting("video_audio_gemini_temperature", str(temperature))

def load_gemini_temperature(default=0.25): # For VideoAudioTab primarily
    try:
        val_str = load_setting("video_audio_gemini_temperature", str(default))
        return float(val_str)
    except (ValueError, TypeError):
        logger.warning(f"Could not parse video_audio_gemini_temperature, using default {default}")
        return float(default)

def save_translation_style(style_name): # For VideoAudioTab primarily
    save_setting("video_audio_translation_style", style_name)

def load_translation_style(default="Default/Neutral"): # For VideoAudioTab primarily
    return load_setting("video_audio_translation_style", default)

def save_target_translation_language(lang_name): # For VideoAudioTab primarily
     save_setting("video_audio_target_language", lang_name)

def load_target_translation_language(default="English"): # For VideoAudioTab primarily
    return load_setting("video_audio_target_language", default)


# --- yt-dlp specific ---
def save_yt_dlp_audio_only(value: bool): # For VideoAudioTab
    save_setting("yt_dlp_audio_only", str(value))

def load_yt_dlp_audio_only(default=False) -> bool: # For VideoAudioTab
    val_str = load_setting("yt_dlp_audio_only", str(default))
    return val_str.lower() == 'true'

# --- Context Keywords for VideoAudioTab ---
def save_va_context_keywords(keywords_text: str):
    save_setting("video_audio_context_keywords", keywords_text)

def load_va_context_keywords(default=""):
    return load_setting("video_audio_context_keywords", default)


# --- Settings specific to SubtitleTranslateTab ---
# (These were already added in the SubtitleTranslateTab's _load_settings/_save_settings,
# using the generic save_setting/load_setting. This is fine.
# If you want specific wrappers here, you can add them like:)
# def save_subtitle_tab_model(model_name):
#     save_setting("subtitle_gemini_model", model_name)
# def load_subtitle_tab_model(default="gemini-1.5-pro-latest"):
#     return load_setting("subtitle_gemini_model", default)
# ... and so on for subtitle_gemini_temperature, subtitle_translation_style, etc.

# --- Settings specific to VideoProcessingTab ---
# (Similar to SubtitleTranslateTab, these are likely handled by generic
# save_setting/load_setting in VideoProcessingTab._load_settings/_save_settings.
# Add specific wrappers here if desired for better organization or type handling.)

# Example for VideoProcessingTab:
# def save_video_processing_mode(mode: str):
#     save_setting("video_processing_mode", mode)
# def load_video_processing_mode(default="mux"):
#     return load_setting("video_processing_mode", default)

# def save_hardsub_font(font_name: str):
#     save_setting("hardsub_font", font_name)
# def load_hardsub_font(default="Arial"):
#     return load_setting("hardsub_font", default)
# ... and so on for all hardsub options (size, color, outline, shadow, position, crf, resolution)


# --- Function to ensure config file exists with default sections ---
def initialize_config_if_needed():
    """
    Checks if the config file exists. If not, or if it's malformed,
    it can create a new one with default sections.
    This is useful on first run.
    """
    config_needs_writing = False
    config = _read_config() # Reads existing or creates empty if not found/malformed

    if not config.has_section(CONFIG_SECTION_USER):
        config.add_section(CONFIG_SECTION_USER)
        logger.info(f"Added default section [{CONFIG_SECTION_USER}] to config.")
        config_needs_writing = True
    if not config.has_section(CONFIG_SECTION_INTERNAL):
        config.add_section(CONFIG_SECTION_INTERNAL)
        logger.info(f"Added default section [{CONFIG_SECTION_INTERNAL}] to config.")
        config_needs_writing = True

    if config_needs_writing:
        # You could pre-populate with some very basic default keys here if desired
        # For example:
        # if not config.has_option(CONFIG_SECTION_USER, "video_audio_target_language"):
        #     config.set(CONFIG_SECTION_USER, "video_audio_target_language", "English")
        _write_config(config)
        logger.info(f"Initialized or updated config file at: {_CONFIG_FILE_PATH}")

# Call initialize on module load to ensure sections exist
initialize_config_if_needed()
