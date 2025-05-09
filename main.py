import tkinter as tk
from tkinter import filedialog, ttk, scrolledtext, messagebox
import os
# We will still load .env initially, but prefer the saved key if it exists
from dotenv import load_dotenv
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from pydub import AudioSegment
import threading
import re
import time
import webbrowser
import sys # Import sys to potentially handle exit more gracefully if needed
import subprocess # Import subprocess for FFmpeg check

# --- Configuration File for API Key ---
# Use a simple file in the user's home directory
API_KEY_FILE = os.path.join(os.path.expanduser("~"), ".gemini_srt_key")

def save_api_key(api_key):
    """Saves the API key to a file in the user's home directory."""
    try:
        # Ensure the directory exists (especially for first run)
        api_key_dir = os.path.dirname(API_KEY_FILE)
        if not os.path.exists(api_key_dir):
            os.makedirs(api_key_dir)
            print(f"Created directory for API key file: {api_key_dir}")

        with open(API_KEY_FILE, "w", encoding="utf-8") as f:
            f.write(api_key.strip()) # Save without leading/trailing whitespace
        print(f"API Key saved to {API_KEY_FILE}")
        return True
    except Exception as e:
        messagebox.showerror("Save Error", f"Could not save API Key to {API_KEY_FILE}.\nError: {e}")
        print(f"Error saving API key: {e}")
        return False

def load_api_key():
    """Loads the API key from the file in the user's home directory."""
    # First, try loading from the saved file
    if os.path.exists(API_KEY_FILE):
        try:
            with open(API_KEY_FILE, "r", encoding="utf-8") as f:
                key = f.read().strip()
                if key:
                    print(f"API Key loaded from {API_KEY_FILE}")
                    return key
        except Exception as e:
            print(f"Error reading API Key from {API_KEY_FILE}: {e}")
            # Continue to try .env if file read fails

    # If not found or failed from file, try .env (existing behavior)
    load_dotenv()
    env_key = os.getenv("GEMINI_API_KEY")
    if env_key:
        print("API Key loaded from .env file")
        # Optionally save this to the new file for future use if it's the first time
        # save_api_key(env_key) # Decide if you want to auto-migrate from .env
        return env_key

    print("No API Key found in saved file or .env")
    return "" # Return empty string if no key is found

# --- Initial API Key Handling ---
# Load key on startup but don't configure genai globally yet.
# Configuration will happen just before the first API call in the task thread.
INITIAL_API_KEY = load_api_key()

# --- Model Configuration ---
# Use a model capable of processing audio/video and generating text
# Check the changelog for the latest models: https://ai.google.dev/gemini-api/docs/models
DEFAULT_MODEL_NAME = "gemini-2.5-pro-exp-03-25"
MODEL_CHANGELOG_URL = "https://ai.google.dev/gemini-api/docs/models"

# --- Prompt Templates (Updated and Translated to English) ---

# Prompt for Step 1: Direct Translation from Audio/Video to SRT
# Model receives Audio/Video + Prompt + Glossary + Tone instruction, outputs SRT
DEFAULT_DIRECT_TRANSLATE_PROMPT_TEMPLATE = """Translate the speech in the provided audio/video file into {target_lang} and output the translation strictly in SubRip (.srt) format.
Each subtitle entry should represent a short, natural speech segment or sentence.
Timestamps MUST be in the format HH:MM:SS,MMM --> HH:MM:SS,MMM and must accurately reflect the audio's timing.
Ensure timestamps are sequential and do not overlap.
{glossary_instructions_direct_translate}
{tone_instructions_direct_translate}
Do NOT include any explanatory text before or after the SRT content, or any markdown like ```srt. Only output the raw SRT data.
If there is a term that needs to be explained, put it in brackets {{}} right after the translated sentence.

Example of expected SRT format:
1
00:00:01,123 --> 00:00:03,456
This is the first line of dialogue.

2
00:00:04,000 --> 00:00:06,789
And this is the second.

Begin {target_lang} SRT output now:
"""

# Prompt for Step 2: Validate and Correct SRT based on Original Audio/Video
# Model receives Audio/Video + Prompt + SRT to validate, outputs corrected SRT
DEFAULT_VALIDATE_SRT_PROMPT_TEMPLATE = """Review the provided SRT content in conjunction with the audio/video file.
Your task is to identify and correct any errors in the SRT based on the audio/video.
Specifically, check for:
- Accuracy of timestamps (start and end times) - ensure they match the speech in the audio/video.
- Correct SRT formatting (sequential numbering, time format HH:MM:SS,MMM --> HH:MM:SS,MMM, correct line breaks between entries).
- Overlapping or non-sequential timestamps.

Provided SRT content to review and correct:
{srt_content_to_validate}

Based on the audio/video and the provided SRT, output the CORRECTED and FINAL SRT content.
Do NOT include any explanatory text before or after the SRT content, or any markdown like ```srt. Only output the corrected SRT data.

Begin corrected SRT output now:
"""


SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# --- SRT Handling Functions (Kept mostly same, improved parsing robustness) ---
def parse_srt_time(time_str):
    """Parses an SRT time string into seconds (float), handling variations in millisecond digits."""
    # Prioritize the standard 3-digit millisecond format
    match = re.match(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})', time_str)
    if match:
        h, m, s, ms = map(int, match.groups())
        return h * 3600 + m * 60 + s + ms / 1000.0

    # Try formats with fewer milliseconds digits for robustness, assuming trailing zeros are implied
    # e.g., ,1 -> ,100; ,12 -> ,120
    match = re.match(r'(\d{2}):(\d{2}):(\d{2}),(\d{1,2})', time_str)
    if match:
        h, m, s, ms_part = match.groups()
        ms = int(ms_part)
        # Pad milliseconds to 3 digits with trailing zeros
        if len(ms_part) == 1: ms *= 100
        elif len(ms_part) == 2: ms *= 10
        return int(h) * 3600 + int(m) * 60 + int(s) + ms / 1000.0


    raise ValueError(f"Invalid time format: {time_str}")

def format_srt_time(total_seconds):
    """Formats a total number of seconds (float) into an SRT time string HH:MM:SS,MMM."""
    if not isinstance(total_seconds, (int, float)) or total_seconds < 0:
        return "00:00:00,000"
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    milliseconds = int(round((total_seconds - int(total_seconds)) * 1000))
    # Ensure milliseconds are exactly 3 digits
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

def parse_srt(srt_content):
    """Parses a string containing SRT content into a list of segment dictionaries."""
    segments = []
    if not srt_content or not srt_content.strip():
        return segments

    # Handle potential BOM at the start of the file
    content = srt_content.lstrip('\ufeff')

    # Regex to find entries: index, start_time, end_time, text block.
    # Uses non-greedy match for text block and looks for double newline or end of string as separator.
    # Allows for different line endings (\r\n, \n, \r).
    # Handles 1-3 digit milliseconds in times.
    # Added check for at least one non-space character in the text block to avoid empty segments from malformed files
    pattern = re.compile(
        r'(\d+)\s*[\r\n]+'                 # Index (one or more digits) followed by newline(s)
        r'(\d{2}:\d{2}:\d{2},\d{1,3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{1,3})\s*[\r\n]+' # Timestamps line
        r'([\s\S]*?)'                     # Text block (non-greedy, includes any char including newlines)
        r'(?:\s*[\r\n]{2,}|\Z)',          # Separator: two or more newlines OR end of string
        re.MULTILINE
    )
    matches = pattern.findall(content)

    for match in matches:
        try:
            index = int(match[0])
            start_time_str = match[1]
            end_time_str = match[2]
            text = match[3].strip() # Strip leading/trailing whitespace from text block

            # Skip empty segments after stripping text
            if not text:
                 # print(f"Skipping empty text segment originally at index {match[0]} between {start_time_str} and {end_time_str}")
                 continue

            segments.append({
                "index": index,
                "start_str": start_time_str, # Store original string for robustness
                "end_str": end_time_str,   # Store original string for robustness
                "start_sec": parse_srt_time(start_time_str),
                "end_sec": parse_srt_time(end_time_str),
                "text": text
            })
        except ValueError as e:
            print(f"Error parsing SRT time string in entry starting with index {match[0]}: {e}. Skipping entry.")
            # Decide how to handle errors: skip, add error segment, etc.
            # For now, we print the error and skip the malformed segment.
            continue
        except Exception as e:
            print(f"Unknown error parsing SRT entry starting with index {match[0]}: {e}. Skipping entry.")
            continue

    # After parsing, re-index and sort by start time for robustness
    # This handles cases where SRT files are out of order or have duplicate indices
    segments.sort(key=lambda x: x.get("start_sec", 0))
    for i, seg in enumerate(segments):
        seg["index"] = i + 1 # Assign new sequential index

    return segments

def build_srt(segments):
    """Builds an SRT string from a list of segment dictionaries."""
    srt_output = []
    for i, seg in enumerate(segments):
        # Use normalized index after parse and sort
        srt_output.append(str(seg.get("index", i + 1)))
        # Use original start_str/end_str if available and valid, otherwise format from seconds
        # Simple validation: check if original string seems valid HH:MM:SS,MMM format
        start_t = seg.get("start_str") if re.match(r'\d{2}:\d{2}:\d{2},\d{3}', seg.get("start_str", "")) else format_srt_time(seg.get("start_sec", 0))
        end_t = seg.get("end_str") if re.match(r'\d{2}:\d{2}:\d{2},\d{3}', seg.get("end_str", "")) else format_srt_time(seg.get("end_sec", 0))

        srt_output.append(f"{start_t} --> {end_t}")
        srt_output.append(seg["text"])
        srt_output.append("") # Blank line separator
    # Add a final newline if there are segments, for proper file ending
    if srt_output:
        return "\n".join(srt_output).strip() + "\n"
    return ""

# --- API Call Function (Modified to take API key and configure genai) ---
def generate_content_with_retry(api_key, model_name_str, prompt_parts, generation_config, max_retries=3, delay_seconds=30):
    """Calls the generative model API with retry logic. Configures genai with the provided key."""
    # Configure genai right before the call using the provided key
    # This is a safeguard, primary configuration happens before upload
    try:
        genai.configure(api_key=api_key)
    except Exception as e:
        # Pass the error back to the calling thread function via a result queue or similar
        # For simplicity in this example, we'll rely on the caller handling None return
        # and generate_content_with_retry showing a messagebox (which is okay for simple GUIs)
        messagebox.showerror("API Configuration Error", f"Could not configure API with the provided key.\nError: {e}")
        print(f"API configuration error inside generate_content_with_retry: {e}")
        return None # Indicate critical failure

    retries = 0
    if not model_name_str or not model_name_str.strip():
        messagebox.showerror("Model Error", "API Model name cannot be empty.")
        return None # Indicate failure
    try:
        model_instance = genai.GenerativeModel(model_name_str)
    except Exception as e:
        # Pass the error back to the calling thread function
        messagebox.showerror("Model Initialization Error", f"Could not initialize model '{model_name_str}'.\nError: {e}\nPlease check the model name and access permissions.")
        print(f"Model initialization error: {e}")
        return None # Indicate critical failure

    while retries < max_retries:
        try:
            response = model_instance.generate_content(
                prompt_parts,
                generation_config=generation_config,
                safety_settings=SAFETY_SETTINGS # Apply safety settings
            )
            # Check for safety blocks (still need to handle this as API might return empty candidates)
            if not response.candidates:
                 safety_feedback = response.prompt_feedback.safety_ratings
                 messagebox.showwarning("API Blocked", f"API response was blocked due to safety concerns.\nDetails: {safety_feedback}")
                 print(f"API response blocked: {safety_feedback}")
                 return None # Indicate failure due to block

            return response
        except Exception as e:
            error_message = str(e).lower()
            if "401" in error_message or "authentication" in error_message or "api key" in error_message:
                 messagebox.showerror("API Authentication Error", f"Invalid API Key or Authentication Failed.\nDetails: {e}\nPlease check your API Key.")
                 print(f"Authentication error: {e}")
                 return None # Indicate immediate failure on auth error
            elif "429" in error_message or "quota" in error_message or "rate limit" in error_message:
                retries += 1
                if retries < max_retries:
                    print(f"Quota/Rate Limit error (429) with model {model_name_str}. Retrying {retries}/{max_retries} in {delay_seconds} seconds...")
                    # Update status via a thread-safe mechanism if needed, but direct gui updates are complex from here
                    # status_var.set(f"Quota/Rate Limit error. Retrying in {delay_seconds}s ({retries}/{max_retries})") # Not thread safe
                    # app.update_idletasks() # Not thread safe
                    time.sleep(delay_seconds)
                    delay_seconds *= 2 # Exponential backoff
                else:
                    print(f"Max retries exhausted for quota/rate limit error with model {model_name_str}. Error: {e}")
                    messagebox.showerror("API Error (Quota/Rate Limit)", f"Max retries exhausted due to quota or rate limit error.\nDetails: {e}")
                    return None
            elif ("model" in error_message and "not found" in error_message) or \
                 ("user location is not supported" in error_message) or \
                 ("permission denied" in error_message) or \
                 ("access" in error_message):
                 messagebox.showerror("Model/Access Error", f"Model '{model_name_str}' not found, you don't have access, or your location is not supported for this model.\nError: {e}\nPlease check the model name and project settings.")
                 return None
            else:
                print(f"Unknown API error with model {model_name_str}: {e}")
                messagebox.showerror("Unknown API Error", f"An unexpected error occurred calling the API.\nDetails: {e}")
                return None
    return None # Should not be reached if max_retries is positive and no exception is raised

# --- File and API Processing Functions (Updated to pass API key) ---
def extract_audio_from_video(media_path, audio_output_path):
    """Extracts audio from video or converts audio to MP3 if necessary."""
    # Status updates here are not thread-safe if called from the task thread directly
    # Use a queue or post messages back to the main thread's event loop for proper updates
    # For now, we'll keep them but be aware they might not work reliably in all environments
    # status_var.set("Extracting audio from video / Converting audio format...")
    # app.update_idletasks()
    print(f"Attempting audio extraction/conversion for {media_path}...")
    try:
        file_extension = os.path.splitext(media_path)[1].lower()
        # List of file extensions pydub should be able to read directly
        supported_formats = ["mp4", "mkv", "avi", "mov", "webm", "wmv", "flv", "mp3", "wav", "ogg", "flac", "aac", "wma"]
        if file_extension.lstrip('.') not in supported_formats:
             print(f"Warning: Attempting to process potentially unsupported format: {media_path}")

        # If it's already MP3 and we want MP3 output, just use the original path
        # This skips unnecessary re-encoding for standard MP3s
        if file_extension == ".mp3" and audio_output_path.lower().endswith(".mp3"):
             print(f"File is already MP3: {media_path}. No extraction needed.")
             # status_var.set("Using original MP3 audio file.")
             return media_path # Return the original path

        # Otherwise, use pydub to process (extract from video or convert other audio formats)
        print(f"Processing file {media_path} using pydub...")
        # Attempt to read the file
        try:
             # Attempt to read with FFmpeg first, then other backends if pydub supports them
             audio = AudioSegment.from_file(media_path)
        except FileNotFoundError:
             # Specific error for FFmpeg not found
             messagebox.showerror("FFmpeg Not Found", "FFmpeg is required for audio processing of many formats but was not found. Please install FFmpeg and ensure it's in your system's PATH.")
             # status_var.set("FFmpeg not found.")
             return None
        except Exception as e:
             # General pydub read error
             messagebox.showerror("Audio Read Error", f"Could not read media file with pydub. Ensure FFmpeg is installed and accessible in your system's PATH, or that the format is supported.\nError: {e}")
             print(f"pydub read error: {e}")
             return None


        # Ensure bitrate is suitable for speech recognition models (e.g., 64k or higher)
        # Check API docs for recommended bitrates. 64k is a common balance.
        # Use 128k for potentially better quality if needed, but increases file size.
        # Export with fixed sample rate (e.g., 16000 Hz) can also help some models.
        # Set common SR and mono BEFORE exporting
        audio = audio.set_frame_rate(16000).set_channels(1)
        audio.export(audio_output_path, format="mp3", bitrate="64k") # Export as MP3
        print(f"Audio processed and saved to {audio_output_path}")
        # status_var.set("Audio extraction/conversion successful.")
        return audio_output_path
    except Exception as e:
        # Catch any other unexpected errors during processing/export
        messagebox.showerror("Audio Processing Error", f"An unexpected error occurred during audio processing: {e}")
        # status_var.set("Audio processing failed.")
        return None

def upload_file_for_api(file_path):
    """Uploads a file to the API and returns the file object once processed.
       Assumes genai has been configured with the API key already."""
    if not os.path.exists(file_path):
        # messagebox.showerror("File Not Found", f"Cannot upload file: {file_path} does not exist.") # Not thread safe
        print(f"Upload failed: File not found at {file_path}")
        return None, None # Indicate failure
    # status_var.set(f"Uploading file '{os.path.basename(file_path)}'...") # Not thread safe
    # app.update_idletasks() # Not thread safe
    print(f"Uploading file '{os.path.basename(file_path)}' to API...")
    file_object = None
    try:
        # Check file size limit (currently 2GB for Gemini 1.5 Pro)
        file_size_bytes = os.path.getsize(file_path)
        file_size_gb = file_size_bytes / (1024**3) # 1024^3 for GiB
        # Official limit is 2GB (2 * 1024^3 bytes or 2 GiB). Let's use a safe margin.
        MAX_FILE_SIZE_BYTES = 2 * 1024**3

        if file_size_bytes > MAX_FILE_SIZE_BYTES:
             messagebox.showwarning("File Too Large", f"File size ({file_size_gb:.2f} GiB) exceeds the {MAX_FILE_SIZE_BYTES/(1024**3):.0f} GiB limit for direct upload to Gemini API. Audio extraction might reduce size if it's video, but large audio files might still be too big.")
             return None, None


        file_object = genai.upload_file(path=file_path)
        print(f"Uploaded file '{file_object.display_name}' as: {file_object.uri}")
        # Wait for the file to be processed server-side
        # Add timeout
        timeout_seconds = 600 # 10 minutes timeout for processing (adjust if needed for very large files)
        start_time = time.time()
        while file_object.state.name == "PROCESSING" and (time.time() - start_time) < timeout_seconds:
            # status_var.set(f"Processing file on server... ({file_object.state.name})") # Not thread safe
            # app.update_idletasks() # Not thread safe
            print(f"Server processing file... ({file_object.state.name}) - {int(time.time() - start_time)}s elapsed")
            time.sleep(5) # Wait a bit longer between checks (increased from 3)
            try:
                file_object = genai.get_file(name=file_object.name) # Refresh state
            except Exception as e_get:
                 print(f"Error refreshing file state for {file_object.name}: {e_get}. Assuming processing might continue.")
                 # Continue loop, the timeout will eventually catch it if it's stuck

        if file_object.state.name == "FAILED":
            messagebox.showerror("Upload Failed", f"File upload or server-side processing failed with state: {file_object.state.name}")
            print(f"Server-side processing failed for {file_path}: {file_object.state.name}")
            return None, file_object # Return None for success, return file_object for cleanup (even failed ones can sometimes be deleted)
        elif file_object.state.name == "PROCESSING": # Still processing after timeout
             messagebox.showerror("Upload Timeout", f"Server-side processing timed out after {timeout_seconds} seconds. File state is still {file_object.state.name}.")
             print(f"Server-side processing timed out for {file_path}")
             return None, file_object # Return None for success, return file_object for cleanup
        elif file_object.state.name == "ACTIVE":
             print("File state is ACTIVE. Ready for use.")
        else:
             # Handle other unexpected states
             print(f"File state is unexpected: {file_object.state.name}")
             messagebox.showwarning("Unexpected File State", f"Uploaded file is in unexpected state: {file_object.state.name}")


        # status_var.set("File ready on server.") # Not thread safe
        print("File ready on server.")
        return file_object, None # Return file_object on success, None on failure

    except Exception as e:
        messagebox.showerror("Upload Error", f"Could not upload file: {e}")
        print(f"Upload file API error: {e}")
        # If file_object was created before error, it might need cleanup
        return None, file_object


def direct_translate_audio_to_srt_gemini(api_key, model_name, original_file_path, target_lang, prompt_template_from_gui, temperature, glossary_text, tone_text):
    """
    Directly translates speech from audio/video to SRT using Gemini.
    Processes original_file_path to get a suitable audio file for upload.
    Requires api_key parameter now.
    """
    uploaded_file_obj = None
    temp_audio_file_path = None
    raw_srt_output = None # Initialize output variable
    temp_audio_created = False # Flag to know if we created a temp file
    final_status = "Ready." # Default status

    try:
        # Step 1: Prepare the audio file for API upload
        # Create a temporary path for the audio file if needed
        file_extension = os.path.splitext(original_file_path)[1].lower()
        # List of file extensions pydub should be able to read directly
        supported_formats = [".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".flv", ".mp3", ".wav", ".ogg", ".flac", ".aac", ".wma"]

        audio_to_process_path = original_file_path # Start assuming original path is fine


        # Basic check if FFmpeg is available before attempting audio processing
        # Moved the check inside the is_media_file block where it's relevant
        # Check if it's an audio/video file type that likely needs processing
        is_media_file_type = file_extension in [".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".flv", ".wav", ".ogg", ".flac", ".aac", ".wma"] or file_extension == ".mp3"

        if is_media_file_type:
             try:
                 # Use a simple command that should return quickly if FFmpeg exists
                 subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                 print("FFmpeg check successful.")
             except FileNotFoundError:
                  messagebox.showerror("FFmpeg Not Found", "FFmpeg is required for audio processing of many formats but was not found. Please install FFmpeg and ensure it's in your system's PATH.")
                  final_status = "Failed: FFmpeg not found."
                  return "" # Indicate critical failure
             except Exception as e:
                  print(f"Warning: Could not verify FFmpeg availability completely: {e}. Proceeding, but audio processing might fail.")
                  # Don't stop here, let extract_audio handle the actual failure if it occurs

        if is_media_file_type: # Process if not standard MP3 or if in list (handles edge cases)
             # If video or audio format needs conversion, create a temp file path
             temp_audio_file_path = f"temp_audio_for_translate_{int(time.time())}.mp3"
             audio_to_process_path = extract_audio_from_video(original_file_path, temp_audio_file_path)
             if audio_to_process_path and audio_to_process_path != original_file_path:
                temp_audio_created = True
             if not audio_to_process_path or not os.path.exists(audio_to_process_path):
                 # extract_audio_from_video already showed specific error messages
                 final_status = "Failed: Audio preparation failed."
                 return "" # Stop if audio preparation failed
        elif original_file_path.lower().endswith(".srt"):
            # Direct translate doesn't use SRT as input media
            messagebox.showwarning("Invalid File Type", "Direct Translate requires an audio or video file, not an SRT file. Please select a media file.")
            final_status = "Failed: Invalid file type for Direct Translate."
            return ""
        else:
             # Should not happen if initial file selection validation is correct
             messagebox.showwarning("Invalid File", "Please select a valid media file (.mp4, .mp3, etc.) for direct translation.")
             final_status = "Failed: No valid media file selected."
             return ""


        # Step 2: Upload audio file to the API
        # Check if audio_to_process_path is valid before uploading
        if audio_to_process_path and os.path.exists(audio_to_process_path):
            # --- API Configuration happens BEFORE upload ---
            # This is handled in the task thread function caller *before* calling this function
            # --------------------------------------------------

            uploaded_file_obj, failed_file_obj_on_upload = upload_file_for_api(audio_to_process_path)
            if not uploaded_file_obj:
                 # Upload failed, clean up the failed file object on server if returned
                 if failed_file_obj_on_upload:
                     try: genai.delete_file(failed_file_obj_on_upload.name); print(f"Deleted failed server file: {failed_file_obj_on_upload.name}")
                     except Exception as e_del: print(f"Could not delete failed server file {failed_file_obj_on_upload.name}: {e_del}")
                 # upload_file_for_api already shows error/status
                 final_status = "Failed: File upload failed."
                 return "" # Stop if upload failed
        else:
            # This case should theoretically not happen if extract_audio_from_video succeeded or wasn't needed
            messagebox.showerror("Audio File Missing", f"Prepared audio file path is invalid: {audio_to_process_path}. Cannot proceed with direct translation.")
            final_status = "Failed: Prepared audio file missing."
            return "" # Return empty string on unexpected file path issue


        # Step 3: Prepare prompt parts and call API
        # status_var.set(f"Translating directly to SRT (Model: {model_name})...") # Not thread safe
        # app.update_idletasks() # Not thread safe
        print(f"Calling API for direct translation using model {model_name}...")

        glossary_instructions_str = ""
        if glossary_text and glossary_text.strip():
            # Provide clear instructions on how to use the glossary
            glossary_instructions_str = f"""
            Adhere strictly to the following glossary and character names for translation. If a term or name from this list appears in the audio, you MUST use its specified translation if provided (format: SourceTerm:TargetTranslation). If only a name or term is provided without a specific translation, keep the name/term as is (transliterate if necessary for the target language).

            Glossary/Character Names:
            {glossary_text.strip()}
            ---
            """
        else:
             glossary_instructions_str = "\n" # Ensure separation even if empty

        tone_instructions_str = ""
        if tone_text and tone_text.strip():
             tone_instructions_str = f"Please ensure the translation adopts a '{tone_text.strip()}' tone/style."
        else:
             tone_instructions_str = "Use a natural, easy-to-understand, and appropriate tone for the content." # Default tone instruction


        try:
            # Format the prompt template with actual values
            current_prompt = prompt_template_from_gui.format(
                target_lang=target_lang,
                glossary_instructions_direct_translate=glossary_instructions_str,
                tone_instructions_direct_translate=tone_instructions_str
            )
        except KeyError as e:
            messagebox.showerror("Prompt Error (Direct Translate)", f"Custom direct translate prompt template is missing a required placeholder: {e}. Please check the prompt input box (needs {{target_lang}}, {{glossary_instructions_direct_translate}}, {{tone_instructions_direct_translate}}).")
            final_status = f"Failed: Prompt error ({e})."
            return "" # Return empty string on prompt error

        # Prompt parts list includes the text prompt and the uploaded file object
        full_prompt_parts = [current_prompt, uploaded_file_obj]
        generation_config = genai.types.GenerationConfig(temperature=temperature)

        # Call the API using the provided api_key parameter
        # genai.configure is also called inside generate_content_with_retry as a safeguard
        response = generate_content_with_retry(api_key, model_name, full_prompt_parts, generation_config)

        # Step 4: Process the result
        if response and response.candidates and response.candidates[0].content.parts:
            raw_srt_output = response.candidates[0].content.parts[0].text
        elif response and hasattr(response, 'text') and response.text: # Fallback for simpler responses
             raw_srt_output = response.text

        # Clean up potential markdown wrappers from the API output and normalize
        if raw_srt_output is not None:
            raw_srt_output = raw_srt_output.strip()
            raw_srt_output = re.sub(r'^```srt\s*', '', raw_srt_output, flags=re.IGNORECASE | re.MULTILINE)
            raw_srt_output = re.sub(r'\s*```$', '', raw_srt_output)
            raw_srt_output = raw_srt_output.replace('\r\n', '\n').replace('\r', '\n') # Normalize line endings
            raw_srt_output = re.sub(r'\n{3,}', '\n\n', raw_srt_output) # Reduce multiple blank lines to just one
            print(f"Raw API output (first 500 chars):\n{raw_srt_output[:500]}{'...' if len(raw_srt_output)>500 else ''}") # Print snippet

            # Basic validation after cleaning
            try:
                parsed_segments = parse_srt(raw_srt_output)
                if not parsed_segments and raw_srt_output.strip():
                     print(f"Warning (Model: {model_name}): Direct translate API returned content but it may not be standard SRT.")
                     final_status = f"Warning: Output might not be standard SRT."
                elif segments:
                    final_status = f"Direct translation successful. {len(segments)} segments."
                else:
                    final_status = "Direct translation yielded no content."
            except Exception as e_parse:
                 print(f"Warning (Model: {model_name}): Direct translation result may not be valid SRT format: {e_parse}")
                 final_status = f"Warning: Error parsing output SRT. Check manually."


            return raw_srt_output.strip() # Return the cleaned output
        else:
            print(f"Model {model_name}: Did not receive SRT content from API after retries or response was empty.")
            # Check if a safety block occurred - generate_content_with_retry already handles message
            if response and response.prompt_feedback and response.prompt_feedback.safety_ratings:
                 final_status = "Failed: API response blocked." # Status already set by generate_content_with_retry
                 return "" # Blocked, return empty
            elif response is None:
                 final_status = status_var.get() # Keep status from generate_content_with_retry errors
                 return ""
            else:
                 # Empty response for other reasons
                 final_status = "Failed: API returned no content."
                 return "" # Return empty string on no content


    except Exception as e:
        # This catches errors not caught by generate_content_with_retry, upload_file_for_api, or audio processing
        print(f"Unexpected Error during Direct Translate with model {model_name}: {e}")
        messagebox.showerror("Processing Error", f"An unexpected error occurred during direct translation processing.\nDetails: {e}")
        final_status = f"Failed: Unexpected error ({e})."
        return "" # Indicate failure by returning empty string
    finally:
        # Step 5: Clean up temporary files (server-side upload and local audio file)
        if uploaded_file_obj:
            try:
                genai.delete_file(uploaded_file_obj.name)
                print(f"Deleted temporary server file: {uploaded_file_obj.name}")
            except Exception as e_del:
                print(f"Error deleting temporary server file {uploaded_file_obj.name}: {e_del}")

        # Only delete the temp audio file if it was actually created (i.e., original wasn't standard MP3)
        if temp_audio_created and temp_audio_file_path and os.path.exists(temp_audio_file_path):
            try:
                os.remove(temp_audio_file_path)
                print(f"Deleted temporary audio file: {temp_audio_file_path}")
            except Exception as e:
                print(f"Could not delete temporary audio file {temp_audio_file_path}: {e}")

        # Update status_var in the main thread
        app.after(0, status_var.set, final_status)
        # app.update_idletasks() # Not needed with app.after


def validate_and_correct_srt_gemini(api_key, model_name, original_file_path, srt_content_to_validate, prompt_template_from_gui, temperature):
    """
    Validates and corrects SRT based on the original audio/video and prompt.
    Processes original_file_path to get a suitable audio file for upload (if it's a media file).
    Requires api_key parameter now.
    """
    uploaded_file_obj = None
    temp_audio_file_path = None
    raw_srt_output = None # Initialize output variable
    temp_audio_created = False # Flag to know if we created a temp file
    final_status = "Ready." # Default status


    try:
        # Step 1: Prepare the original media file (as audio) for API upload
        # Only attempt to process and upload if the original file is a media file (not SRT)
        is_media_file = not original_file_path.lower().endswith(".srt")
        audio_to_process_path = None # Path to the audio file that will be uploaded


        if is_media_file:
             # Basic check if FFmpeg is available before attempting audio processing
            try:
                # Use a simple command that should return quickly if FFmpeg exists
                subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                print("FFmpeg check successful for validation.")
            except FileNotFoundError:
                 messagebox.showerror("FFmpeg Not Found", "FFmpeg is required for audio processing of many formats but was not found. Please install FFmpeg and ensure it's in your system's PATH.")
                 final_status = "Failed: FFmpeg not found. Cannot use media for validation."
                 # Continue validation attempt without audio, but warn
                 messagebox.showwarning("Audio Preparation Failed", "Could not prepare audio for validation due to FFmpeg error. The model will attempt to validate only the SRT text and format.")
                 # uploaded_file_obj remains None
            except Exception as e:
                 print(f"Warning: Could not verify FFmpeg availability completely for validation: {e}. Proceeding with audio processing attempt.")


            # Check if it's a media file type that likely needs processing or upload
            file_extension = os.path.splitext(original_file_path)[1].lower()
            media_formats_to_process = [".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".flv", ".wav", ".ogg", ".flac", ".aac", ".wma"]

            if file_extension in media_formats_to_process or file_extension == ".mp3": # Process if not standard MP3 or if in list
                 temp_audio_file_path = f"temp_audio_for_validation_{int(time.time())}.mp3"
                 audio_to_process_path = extract_audio_from_video(original_file_path, temp_audio_file_path)
                 if audio_to_process_path and audio_to_process_path != original_file_path:
                    temp_audio_created = True
                 if not audio_to_process_path or not os.path.exists(audio_to_process_path):
                     # extract_audio_from_video already shows error/status (including FFmpeg error)
                     # If extract failed, audio_to_process_path might be None or invalid
                     # Continue validation attempt without audio, but warn (if FFmpeg error wasn't already shown)
                     if not final_status.startswith("Failed: FFmpeg"):
                         messagebox.showwarning("Audio Preparation Failed", "Could not prepare audio for validation. The model will attempt to validate only the SRT text and format without timing correction based on audio.")
                     # uploaded_file_obj remains None, final_status is not set to failed critically yet

            elif is_media_file and not audio_to_process_path: # If it's a media file but audio_to_process_path wasn't set (e.g., unrecognized format)
                 messagebox.showwarning("Audio Processing Skipped", "Audio processing was skipped for the selected file type. Validation will proceed without audio context.")
                 # uploaded_file_obj remains None


            # If audio_to_process_path is set (meaning it's a media file, potentially converted), upload it
            if audio_to_process_path and os.path.exists(audio_to_process_path):
                 # --- API Configuration happens BEFORE upload ---
                 # This is handled in the task thread function caller *before* calling this function
                 # --------------------------------------------------

                 uploaded_file_obj, failed_file_obj_on_upload = upload_file_for_api(audio_to_process_path)
                 if not uploaded_file_obj:
                     # Upload failed, clean up the failed file object on server if returned
                     if failed_file_obj_on_upload:
                         try: genai.delete_file(failed_file_obj_on_upload.name); print(f"Deleted failed server file: {failed_file_obj_on_upload.name}")
                         except Exception as e_del: print(f"Could not delete failed server file {failed_file_obj_on_upload.name}: {e_del}")
                     # upload_file_for_api already shows error/status
                     # Audio file upload failed, model might still be able to validate format/text without audio
                     messagebox.showwarning("Audio Upload Failed", "Could not upload audio for validation. The model will attempt to validate only the SRT text and format without timing correction.")
                     # uploaded_file_obj remains None, final_status is not set to failed critically yet

        elif original_file_path.lower().endswith(".srt"):
            # If the original file is an SRT, there's no media to upload for validation
            print("Original file is SRT. Validation will proceed without audio/video context.")
            messagebox.showinfo("SRT Validation Context", "Original file is an SRT. Validation will be based on the SRT text and format only, without audio/video timing verification using the original file.")
            # uploaded_file_obj remains None
        # else: FilePath is empty or doesn't exist, browse_file or the caller should handle this. Initial check before threading should prevent this.


        # Step 2: Prepare prompt parts and call API
        # status_var.set(f"Validating and correcting SRT (Model: {model_name})...") # Not thread safe
        # app.update_idletasks() # Not thread safe
        print(f"Calling API for SRT validation/correction using model {model_name}...")


        if not srt_content_to_validate or not srt_content_to_validate.strip():
             messagebox.showwarning("Empty SRT Content", "No SRT content in the 'Direct Translate Output (SRT)' box to validate/correct.")
             final_status = "Ready." # Reset status
             return "" # Return empty string if no content to validate

        try:
             # Format the prompt template
             current_prompt = prompt_template_from_gui.format(
                 srt_content_to_validate=srt_content_to_validate.strip() # Pass stripped content
             )
        except KeyError as e:
            messagebox.showerror("Prompt Error (Validate)", f"Custom validate prompt template is missing a required placeholder: {e}. Please check the prompt input box (needs {{srt_content_to_validate}}).")
            final_status = f"Failed: Prompt error ({e})."
            return srt_content_to_validate # Return original SRT on prompt error


        # Prompt parts includes the text prompt. If audio was uploaded successfully, add the file object.
        full_prompt_parts = [current_prompt]
        if uploaded_file_obj:
             full_prompt_parts.append(uploaded_file_obj) # Add the file object if successfully uploaded
             print(f"Calling validation API with file: {uploaded_file_obj.uri}")
        else:
             print("Calling validation API without a file object (using SRT content only).")


        generation_config = genai.types.GenerationConfig(temperature=temperature)

        # Call the API using the provided api_key parameter
        # genai.configure is also called inside generate_content_with_retry as a safeguard
        response = generate_content_with_retry(api_key, model_name, full_prompt_parts, generation_config)

        # Step 3: Process the result
        if response and response.candidates and response.candidates[0].content.parts:
            raw_srt_output = response.candidates[0].content.parts[0].text
        elif response and hasattr(response, 'text') and response.text:
             raw_srt_output = response.text

        # Clean up potential markdown wrappers and normalize format
        if raw_srt_output is not None:
            raw_srt_output = raw_srt_output.strip()
            raw_srt_output = re.sub(r'^```srt\s*', '', raw_srt_output, flags=re.IGNORECASE | re.MULTILINE)
            raw_srt_output = re.sub(r'\s*```$', '', raw_srt_output)
            raw_srt_output = raw_srt_output.replace('\r\n', '\n').replace('\r', '\n') # Normalize line endings
            raw_srt_output = re.sub(r'\n{3,}', '\n\n', raw_srt_output) # Reduce multiple blank lines to just one

            print(f"Raw API output (first 500 chars):\n{raw_srt_output[:500]}{'...' if len(raw_srt_output)>500 else ''}") # Print snippet

            # Basic validation of the *output* structure
            try:
                segments = parse_srt(raw_srt_output)
                if not segments and raw_srt_output.strip():
                    print(f"Warning (Model: {model_name}): Validation API returned content that doesn't parse as standard SRT.")
                    final_status = f"Warning: Validation output might not be standard SRT. Check manually."
                elif segments:
                    final_status = f"SRT validation & correction successful. {len(segments)} segments."
                else:
                    final_status = "SRT validation & correction yielded no content."
            except Exception as e_parse:
                 print(f"Warning (Model: {model_name}): Could not parse validation API output as SRT: {e_parse}")
                 final_status = f"Warning: Error parsing validated output SRT. Check manually."

            return raw_srt_output.strip() # Return the cleaned output

        else:
            print(f"Model {model_name}: Did not receive corrected SRT content from API after retries or response was empty.")
            # messagebox.showwarning("No Corrected Output", "The API did not return any corrected SRT content. Please check the model or try again.") # Not thread safe
            # Check if a safety block occurred or other error message was shown by generate_content_with_retry
            if response and response.prompt_feedback and response.prompt_feedback.safety_ratings:
                 final_status = "Failed: API response blocked." # Status already set by generate_content_with_retry
            elif response is None:
                 final_status = status_var.get() # Keep status from generate_content_with_retry errors
            else:
                 final_status = "Failed: API returned no content for validation."
                 messagebox.showwarning("No Corrected Output", "The API did not return any corrected SRT content.") # Now safe to show message box after thread finishes


            return srt_content_to_validate # Return original content if API gives nothing back

    except Exception as e:
        # This catches errors not caught by generate_content_with_retry, upload_file_for_api, or audio processing
        print(f"Unexpected Error during Validate/Correct with model {model_name}: {e}")
        messagebox.showerror("Processing Error", f"An unexpected error occurred during validation/correction processing.\nDetails: {e}")
        final_status = f"Failed: Unexpected error ({e})."
        return srt_content_to_validate # Return original content on error
    finally:
        # Step 4: Clean up temporary files (server-side upload and local audio file)
        if uploaded_file_obj:
            try:
                genai.delete_file(uploaded_file_obj.name)
                print(f"Deleted temporary server file: {uploaded_file_obj.name}")
            except Exception as e_del:
                print(f"Error deleting temporary server file {uploaded_file_obj.name}: {e_del}")

        # Only delete the temp audio file if it was actually created
        if temp_audio_created and temp_audio_file_path and os.path.exists(temp_audio_file_path):
            try:
                os.remove(temp_audio_file_path)
                print(f"Deleted temporary audio file: {temp_audio_file_path}")
            except Exception as e:
                print(f"Could not delete temporary audio file {temp_audio_file_path}: {e}")

        # Update status_var in the main thread
        app.after(0, status_var.set, final_status)
        # app.update_idletasks() # Not needed with app.after


# --- GUI Event Handlers (Updated and Translated) ---

# --- Define handle_save_api_key BEFORE GUI Setup ---
def handle_save_api_key():
    """Handles the button click to save the API key from the entry field."""
    api_key = api_key_var.get().strip()
    if not api_key:
        messagebox.showwarning("Warning", "API Key field is empty.")
        return
    if save_api_key(api_key):
        messagebox.showinfo("Success", "API Key saved successfully.")
    else:
         messagebox.showerror("Error", "Failed to save API Key.") # save_api_key already shows specific error


def browse_file():
    filepath = filedialog.askopenfilename(title="Select Video/Audio/SRT File", filetypes=(("Media files", "*.mp4 *.mkv *.avi *.mov *.webm *.wmv *.flv *.mp3 *.wav *.ogg *.flac *.aac *.wma"), ("SRT files", "*.srt"), ("All files", "*.*")))
    if filepath:
        file_path_var.set(filepath)
        # Clear previous results
        direct_translate_output_area.delete(1.0, tk.END)
        validated_srt_output_area.delete(1.0, tk.END)
        if filepath.lower().endswith(".srt"):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    # Load SRT content into the Direct Translate Output area for potential validation
                    srt_content = f.read()
                    direct_translate_output_area.insert(tk.END, srt_content)
                status_var.set(f"Loaded SRT file: {os.path.basename(filepath)}")
                messagebox.showinfo("Info", "SRT file loaded into the 'Direct Translate Output' area. You can edit it and then click 'Validate & Correct', or run 'Direct Translate' (requires a media file) to overwrite it with a new translation from the original media.")
            except Exception as e:
                messagebox.showerror("File Read Error", f"Could not read SRT file: {e}")
                status_var.set("Ready.") # Reset status on error
        else:
             status_var.set(f"Selected media file: {os.path.basename(filepath)}")


def open_model_changelog(event=None):
    webbrowser.open_new_tab(MODEL_CHANGELOG_URL)

def update_window_title(*args):
    selected_model = model_name_var.get()
    # Đổi tên ứng dụng ở đây
    app.title(f"Easy AI Subbing - Model: {selected_model if selected_model else 'Not Selected'}")

# --- Hàm hiển thị cửa sổ About (Đã cập nhật thông tin của bạn) ---
def show_about_window():
    about_window = tk.Toplevel(app)
    about_window.title("About Easy AI Subbing")
    about_window.transient(app) # Keep about window on top of the main window
    about_window.grab_set() # Make it modal (block interaction with main window)

    # Thông tin credit của bạn được đưa vào đây
    about_text = """
    Easy AI Subbing

    Version: 1.0.0
    Developed by: GioChieu@KiOZ

    Website: https://gsga.moe/
    Facebook: https://www.facebook.com/tranthanhkioz

    Powered by Google Gemini API and FFmpeg
    """

    about_label = ttk.Label(
        about_window,
        text=about_text.strip(), # Sử dụng text đã cập nhật
        padding="10",
        justify=tk.LEFT # Căn trái cho đoạn text có nhiều dòng hơn
    )
    about_label.pack(padx=20, pady=20)

    close_button = ttk.Button(about_window, text="Close", command=about_window.destroy)
    close_button.pack(pady=(0, 10))

    # Center the about window relative to the main window (optional but nice)
    app_x = app.winfo_x()
    app_y = app.winfo_y()
    app_width = app.winfo_width()
    app_height = app.winfo_height()

    about_window.update_idletasks() # Get actual size of about window
    about_width = about_window.winfo_width()
    about_height = about_window.winfo_height()

    new_x = app_x + (app_width // 2) - (about_width // 2)
    new_y = app_y + (app_height // 2) - (about_height // 2)

    # Ensure the window stays on screen
    screen_width = app.winfo_screenwidth()
    screen_height = app.winfo_screenheight()
    new_x = max(0, min(new_x, screen_width - about_width))
    new_y = max(0, min(new_y, screen_height - about_height))


    about_window.geometry(f"+{new_x}+{new_y}")


def run_direct_translate_task_thread():
    # Get API key from the GUI entry field just before starting the task
    api_key = api_key_var.get().strip()
    if not api_key:
        messagebox.showerror("API Key Missing", "Please enter your Gemini API key before running a translation.")
        status_var.set("Ready.") # Reset status
        return

    # --- Configure genai *before* doing anything that uses the API (like upload_file) ---
    try:
        genai.configure(api_key=api_key)
        print("genai configured successfully in direct translate task thread.")
    except Exception as e:
        messagebox.showerror("API Configuration Error", f"Could not configure API with the provided key.\nError: {e}")
        status_var.set("API Configuration failed.")
        return # Stop the task if configuration fails
    # ---------------------------------------------------------------------------------


    filepath = file_path_var.get()
    selected_model = model_name_var.get().strip()
    target_lang = target_lang_var.get().strip()

    if not selected_model:
        messagebox.showerror("Missing Model", "Please enter the API model name.")
        status_var.set("Ready.") # Reset status
        return
    # Check if the selected file is a media file (not SRT) and exists for direct translation
    if not filepath or not os.path.exists(filepath) or filepath.lower().endswith(".srt"):
        messagebox.showwarning("Missing/Invalid File", "Please select a valid audio/video file for direct translation.")
        status_var.set("Ready.") # Reset status
        return
    if not target_lang:
         messagebox.showwarning("Missing Language", "Please select the target language for translation.")
         status_var.set("Ready.") # Reset status
         return

    direct_translate_prompt_template_from_gui = direct_translate_prompt_entry.get("1.0", tk.END).strip()
    if not direct_translate_prompt_template_from_gui:
        messagebox.showwarning("Missing Translate Prompt", "The prompt for Direct Translate cannot be empty.")
        status_var.set("Ready.") # Reset status
        return

    required_placeholders = ["{target_lang}", "{glossary_instructions_direct_translate}", "{tone_instructions_direct_translate}"]
    for ph in required_placeholders:
        if ph not in direct_translate_prompt_template_from_gui:
            messagebox.showwarning("Prompt Error (Direct Translate)", f"Custom direct translate prompt template is missing a required placeholder: {ph}. Please check the prompt input box.")
            status_var.set("Ready.") # Reset status
            return

    glossary_text = glossary_direct_translate_entry.get("1.0", tk.END).strip()
    tone_text = tone_var.get().strip() # Get from the new tone entry (using the StringVar)


    try:
        temperature = float(direct_translate_temp_var.get())
        if not (0.0 <= temperature <= 1.0): # Standard temperature range
            raise ValueError("Temperature must be between 0.0 and 1.0")
    except ValueError as e:
        messagebox.showerror("Invalid Value", f"Invalid Temperature for Direct Translate: {e}")
        status_var.set("Ready.") # Reset status
        return

    # Disable buttons and clear output areas
    direct_translate_button.config(state=tk.DISABLED)
    validate_button.config(state=tk.DISABLED)
    save_direct_translate_button.config(state=tk.DISABLED) # Disable save during processing
    save_validated_button.config(state=tk.DISABLED) # Disable other save too
    direct_translate_output_area.delete(1.0, tk.END)
    validated_srt_output_area.delete(1.0, tk.END)
    status_var.set("Starting direct translation...")
    app.update_idletasks()


    def task():
        # Call the direct translation function, passing the api_key
        # genai is already configured by the outer function
        srt_result = direct_translate_audio_to_srt_gemini(
            api_key, # Pass the API key (redundant for configure but good practice)
            selected_model,
            filepath, # Pass the original filepath
            target_lang,
            direct_translate_prompt_template_from_gui,
            temperature,
            glossary_text,
            tone_text # Pass the tone text
        )

        # Update GUI with results - must be done in the main thread using app.after
        def update_gui():
            direct_translate_output_area.insert(tk.END, srt_result)
            # Status variable is updated inside direct_translate_audio_to_srt_gemini using app.after
            # Attempt parsing for segment count and basic format check (can be done here in main thread)
            if srt_result is not None and srt_result.strip(): # Only parse if there's content
                try:
                    segments = parse_srt(srt_result)
                    if segments:
                         # If status wasn't already set to warning/error by the task function
                         current_status = status_var.get()
                         if not (current_status.startswith("Warning") or current_status.startswith("Failed")):
                             status_var.set(f"Direct translation successful. {len(segments)} segments.")
                    elif srt_result.strip() and not status_var.get().startswith("Warning"): # Content but no segments parsed
                         status_var.set(f"Warning: Output might not be standard SRT.")

                except Exception as e_parse:
                     print(f"Error parsing final Direct Translate output in main thread: {e_parse}")
                     if not status_var.get().startswith("Warning"):
                          status_var.set(f"Warning: Error parsing output SRT. Check manually.")
            elif srt_result == "" and not status_var.get().startswith("Failed"): # No content returned
                 status_var.set("Direct translation yielded no content.")


            # Re-enable buttons
            direct_translate_button.config(state=tk.NORMAL)
            validate_button.config(state=tk.NORMAL)
            save_direct_translate_button.config(state=tk.NORMAL) # Re-enable save
            save_validated_button.config(state=tk.NORMAL) # Re-enable other save

        # Schedule the GUI update function to run in the main thread
        app.after(0, update_gui)


    # Run the task in a separate thread
    threading.Thread(target=task, daemon=True).start()


def run_validate_task_thread():
    # Get API key from the GUI entry field just before starting the task
    api_key = api_key_var.get().strip()
    if not api_key:
        messagebox.showerror("API Key Missing", "Please enter your Gemini API key before running a validation.")
        status_var.set("Ready.") # Reset status
        return

    # --- Configure genai *before* doing anything that uses the API (like upload_file) ---
    try:
        genai.configure(api_key=api_key)
        print("genai configured successfully in validate task thread.")
    except Exception as e:
        messagebox.showerror("API Configuration Error", f"Could not configure API with the provided key.\nError: {e}")
        status_var.set("API Configuration failed.")
        return # Stop the task if configuration fails
    # ---------------------------------------------------------------------------------


    original_file_path = file_path_var.get() # Need the original file path for re-processing audio
    srt_content_to_validate = direct_translate_output_area.get("1.0", tk.END).strip() # Get content from the first output box
    selected_model = model_name_var.get().strip()

    if not selected_model: messagebox.showerror("Missing Model", "Please enter the API model name."); status_var.set("Ready."); return
    # Original file path is needed for context, even if it's an SRT
    if not original_file_path or not os.path.exists(original_file_path): messagebox.showwarning("Missing Original File", "Please select the original audio/video/SRT file to validate against."); status_var.set("Ready."); return
    if not srt_content_to_validate: messagebox.showwarning("Missing SRT Content", "No SRT content in the 'Direct Translate Output (SRT)' box to validate/correct."); status_var.set("Ready."); return

    validate_prompt_template_from_gui = validate_prompt_entry.get("1.0", tk.END).strip()
    if not validate_prompt_template_from_gui: messagebox.showwarning("Missing Validate Prompt", "The prompt for Validate & Correct cannot be empty."); status_var.set("Ready."); return

    required_placeholders = ["{srt_content_to_validate}"]
    for ph in required_placeholders:
        if ph not in validate_prompt_template_from_gui:
            messagebox.showwarning("Prompt Error (Validate)", f"Custom validate prompt template is missing a required placeholder: {ph}. Please check the prompt input box.")
            status_var.set("Ready."); return

    try:
        temperature = float(validate_temp_var.get())
        # A lower temperature (0.0-0.5) is generally better for validation/correction
        if not (0.0 <= temperature <= 0.5):
             # Adjust bounds slightly for user flexibility but recommend lower
             # messagebox.showwarning("Temperature Suggestion", "Temperature for validation is typically best between 0.0 and 0.5 for higher precision.") # Avoid modal here
             print("Note: Temperature for validation is typically best between 0.0 and 0.5 for higher precision.")
        if not (0.0 <= temperature <= 1.0): # Still enforce the 0-1 range
             raise ValueError("Temperature must be between 0.0 and 1.0")

    except ValueError as e: messagebox.showerror("Invalid Value", f"Invalid Temperature for Validate/Correct: {e}"); status_var.set("Ready."); return


    # Disable buttons and clear output area
    direct_translate_button.config(state=tk.DISABLED)
    validate_button.config(state=tk.DISABLED)
    save_direct_translate_button.config(state=tk.DISABLED) # Disable save during processing
    save_validated_button.config(state=tk.DISABLED) # Disable other save too
    validated_srt_output_area.delete(1.0, tk.END)
    status_var.set("Starting validation & correction...")
    app.update_idletasks()


    def task():
        # Call the validation function, passing the api_key
        # genai is already configured by the outer function
        validated_srt_result = validate_and_correct_srt_gemini(
            api_key, # Pass the API key (redundant for configure but good practice)
            selected_model,
            original_file_path, # Pass the original file path
            srt_content_to_validate,
            validate_prompt_template_from_gui,
            temperature
        )

        # Update GUI with results - must be done in the main thread using app.after
        def update_gui():
            if validated_srt_result is not None: # API function returns None on critical failure *before* getting content
                 validated_srt_output_area.insert(tk.END, validated_srt_result)
                 # Status variable is updated inside validate_and_correct_srt_gemini using app.after
                 # Attempt parsing for segment count and basic format check (can be done here in main thread)
                 if validated_srt_result.strip(): # Only parse if there's content
                     try:
                        segments = parse_srt(validated_srt_result)
                        if segments:
                            # If status wasn't already set to warning/error by the task function
                            current_status = status_var.get()
                            if not (current_status.startswith("Warning") or current_status.startswith("Failed")):
                                status_var.set(f"SRT validation & correction successful. {len(segments)} segments.")
                        elif validated_srt_result.strip() and not status_var.get().startswith("Warning"): # Content but no segments parsed
                            status_var.set(f"Warning: Validation output might not be standard SRT.")
                     except Exception as e_parse:
                        print(f"Error parsing final Validation output in main thread: {e_parse}")
                        if not status_var.get().startswith("Warning"):
                            status_var.set(f"Warning: Error parsing validated output SRT. Check manually.")
                 elif not status_var.get().startswith("Failed"): # No content returned
                     status_var.set("SRT validation & correction yielded no content.")

            # Re-enable buttons
            direct_translate_button.config(state=tk.NORMAL)
            validate_button.config(state=tk.NORMAL)
            save_direct_translate_button.config(state=tk.NORMAL) # Re-enable save
            save_validated_button.config(state=tk.NORMAL) # Re-enable other save

        # Schedule the GUI update function to run in the main thread
        app.after(0, update_gui)


    # Run the task in a separate thread
    threading.Thread(target=task, daemon=True).start()

# --- Function to get default save path ---
def get_default_save_path(output_type):
    """
    Calculates the default save path based on the original file path and output type.
    Returns (initial_dir, initial_file) tuple.
    """
    original_file_path = file_path_var.get()
    suffix = "_translated" if output_type == 'translated' else "_validated"
    default_dir = "." # Default to current directory
    default_filename = f"output{suffix}.srt"

    if original_file_path and os.path.exists(original_file_path):
        try:
            original_dir = os.path.dirname(original_file_path)
            # Get the base name without any extension (handle multiple dots)
            original_base = os.path.basename(original_file_path)
            if '.' in original_base:
                 original_base = original_base.rsplit('.', 1)[0] # Split only on the last dot

            default_dir = original_dir
            default_filename = f"{original_base}{suffix}.srt"
        except Exception as e:
            print(f"Warning: Could not derive default save path from original file '{original_file_path}': {e}. Using fallback defaults.")
            # Fallback to default_dir = "." and default_filename already set

    return default_dir, default_filename


# --- Modified save_srt_file function ---
def save_srt_file(content_area, output_type):
    """
    Prompts user to save SRT content using a file dialog,
    suggesting a default path/name based on the original file and output type.
    """
    content = content_area.get("1.0", tk.END).strip()
    if not content:
        messagebox.showwarning("Empty Content", "There is no content to save.")
        return

    initial_dir, initial_file = get_default_save_path(output_type)

    filepath = filedialog.asksaveasfilename(
        defaultextension=".srt",
        filetypes=[("SubRip Subtitle files", "*.srt"), ("All files", "*.*")],
        initialdir=initial_dir,
        initialfile=initial_file,
        title=f"Save {output_type.replace('_', ' ').capitalize()} SRT File"
    )

    if filepath:
        try:
            # Clean up common markdown/formatting issues before saving
            content = re.sub(r'^```srt\s*', '', content, flags=re.IGNORECASE | re.MULTILINE)
            content = re.sub(r'\s*```$', '', content)
            content = content.replace('\r\n', '\n').replace('\r', '\n') # Normalize line endings
            content = re.sub(r'\n{3,}', '\n\n', content) # Reduce multiple blank lines to just one
            content = content.strip() # Remove leading/trailing whitespace after cleaning

            # Optional: Add basic validation before saving
            try:
                segments = parse_srt(content)
                if not segments and content.strip():
                    print("Warning: Saving content that does not appear to be standard SRT.")
                    # messagebox.showwarning("Save Warning", "The content doesn't appear to be valid SRT format, but it will be saved as is.") # Avoid modal inside save
            except Exception as e_parse:
                 print(f"Warning: Could not parse content before saving as SRT: {e_parse}. Saving anyway.")
                 # messagebox.showwarning("Save Warning", f"Could not parse content as SRT before saving: {e_parse}. The content will be saved as is.") # Avoid modal inside save


            with open(filepath, 'w', encoding='utf-8') as f: # Always save with UTF-8
                f.write(content)
            messagebox.showinfo("Success", f"File saved successfully: {filepath}")
        except Exception as e:
            messagebox.showerror("File Save Error", f"Could not save file: {e}")


# --- GUI Setup (Translated to English) ---
app = tk.Tk()
# Đổi tên ứng dụng ở dòng này
app.title("Easy AI Subbing") # Initial title

# --- Code để đặt icon cho cửa sổ ứng dụng ---
# Đây là đoạn mã mới được thêm vào
# Xác định đường dẫn cơ sở tùy thuộc vào việc chạy từ script hay PyInstaller bundle
if getattr(sys, 'frozen', False):
    # Đang chạy từ PyInstaller bundle, sử dụng thư mục tạm _MEIPASS
    base_path = sys._MEIPASS
else:
    # Đang chạy script Python trực tiếp, sử dụng thư mục chứa script
    base_path = os.path.dirname(__file__)

icon_path = os.path.join(base_path, 'app_icon.ico')

try:
    # iconbitmap chỉ hỗ trợ định dạng .ico trên Windows. Dùng .iconphoto nếu cần đa nền tảng với .png
    app.iconbitmap(icon_path)
    print(f"Window icon set from: {icon_path}")
except tk.TclError as e:
    print(f"Warning: Could not load window icon from {icon_path}: {e}")
    # Nếu không load được icon, ứng dụng sẽ dùng icon mặc định của hệ thống/Tkinter

# -------------------------------------------

main_frame = ttk.Frame(app, padding="10")
main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

# Configure the main window and main_frame to expand
app.columnconfigure(0, weight=1)
app.rowconfigure(0, weight=1)
main_frame.columnconfigure(0, weight=1) # Column 0 spans both processing frames
main_frame.columnconfigure(1, weight=1) # Added weight to column 1 for the second processing frame
main_frame.rowconfigure(0, weight=0) # Config frame (fixed height)
main_frame.rowconfigure(1, weight=1) # Processing frame (expands vertically)
main_frame.rowconfigure(2, weight=0) # Status bar (fixed height)

# --- Menu Bar (Đã thêm vào đây) ---
menubar = tk.Menu(app)
app.config(menu=menubar)

# Help Menu (Đã thêm vào đây)
helpmenu = tk.Menu(menubar, tearoff=0)
menubar.add_cascade(label="Help", menu=helpmenu)
helpmenu.add_command(label="About Easy AI Subbing", command=show_about_window) # Gọi hàm hiển thị About
helpmenu.add_command(label="Gemini Models Info", command=open_model_changelog) # Link to existing function
helpmenu.add_command(label="Get API Key", command=lambda: webbrowser.open_new_tab("https://aistudio.google.com/apikey")) # Direct link

# --- Top Config Area ---
config_frame = ttk.Frame(main_frame)
config_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
# Configure config_frame columns to share horizontal space
config_frame.columnconfigure(0, weight=1) # API Key frame
config_frame.columnconfigure(1, weight=3) # File frame gets more space
config_frame.columnconfigure(2, weight=1) # Model frame gets some space
config_frame.columnconfigure(3, weight=2) # Language frame gets some space
config_frame.columnconfigure(4, weight=2) # Tone frame gets some space


# API Key Frame (New)
api_key_frame = ttk.LabelFrame(config_frame, text="Gemini API Key", padding="5")
api_key_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0,5), pady=5)
api_key_frame.columnconfigure(1, weight=1) # Entry column expands

api_key_label = ttk.Label(api_key_frame, text="Key:")
api_key_label.grid(row=0, column=0, sticky=tk.W, padx=2)
api_key_var = tk.StringVar(value=INITIAL_API_KEY) # Load initial key here
api_key_entry = ttk.Entry(api_key_frame, textvariable=api_key_var, show='*') # Use show='*' to hide key
api_key_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=2, pady=2)

save_key_button = ttk.Button(api_key_frame, text="Save Key", command=handle_save_api_key)
save_key_button.grid(row=0, column=2, sticky=tk.E, padx=2)

# Add a help label for API Key
api_key_help_label = ttk.Label(api_key_frame, text="Get your API key from: https://aistudio.google.com/apikey", foreground="gray", wraplength=250)
api_key_help_label.grid(row=1, column=0, columnspan=3, sticky=tk.W, padx=2)
# Make the help label clickable
api_key_help_label.bind("<Button-1>", lambda e: webbrowser.open_new_tab("https://aistudio.google.com/apikey"))
api_key_help_label.configure(cursor="hand2")


# File Selection Frame - Adjusted column index
file_frame = ttk.LabelFrame(config_frame, text="Select Original File (Video/Audio/SRT)", padding="5")
file_frame.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0,5), pady=5) # Changed column to 1
file_frame.columnconfigure(1, weight=1) # Make path entry expandable
file_path_var = tk.StringVar()
file_label = ttk.Label(file_frame, text="Path:")
file_label.grid(row=0, column=0, sticky=tk.W, padx=2)
file_entry = ttk.Entry(file_frame, textvariable=file_path_var) # Removed width hint
file_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=2)
browse_button = ttk.Button(file_frame, text="Browse...", command=browse_file)
browse_button.grid(row=0, column=2, sticky=tk.E, padx=2)

# Model Frame - Adjusted column index
model_frame = ttk.LabelFrame(config_frame, text="API Model", padding="5")
model_frame.grid(row=0, column=2, sticky=(tk.W, tk.E), padx=5, pady=5) # Changed column to 2
model_name_var = tk.StringVar(value=DEFAULT_MODEL_NAME)
model_name_var.trace_add("write", update_window_title)
model_entry = ttk.Entry(model_frame, textvariable=model_name_var) # Removed width hint
model_entry.pack(side=tk.LEFT, padx=(0,5), fill=tk.X, expand=True) # Use pack inside frame, let entry expand
model_info_label = ttk.Label(model_frame, text="(Info)", cursor="hand2", foreground="blue")
model_info_label.pack(side=tk.LEFT)
model_info_label.bind("<Button-1>", open_model_changelog)
tooltip_model = tk.Label(model_frame, text=MODEL_CHANGELOG_URL, relief=tk.SOLID, borderwidth=1, background="lightyellow", wraplength=200)
def show_tooltip_model(event): # Adjusted to place relative to parent frame
    # Position the tooltip relative to the label's position on the screen
    label_x = model_info_label.winfo_rootx()
    label_y = model_info_label.winfo_rooty()
    tooltip_model.place(x=label_x + model_info_label.winfo_width(), y=label_y + model_info_label.winfo_height())

def hide_tooltip_model(event): tooltip_model.place_forget()
model_info_label.bind("<Enter>", show_tooltip_model)
model_info_label.bind("<Leave>", hide_tooltip_model)


# Language Frame (Updated with more languages and Auto Detect) - Adjusted column index
lang_frame = ttk.LabelFrame(config_frame, text="Language Options", padding="5")
lang_frame.grid(row=0, column=3, sticky=(tk.W, tk.E), padx=5, pady=5) # Changed column to 3
languages = sorted(["English", "Vietnamese", "Japanese", "Korean", "Chinese", "French", "German", "Spanish", "Thai", "Indonesian", "Russian", "Portuguese", "Arabic", "Hindi"]) # Added more languages and sorted
source_lang_label = ttk.Label(lang_frame, text="Source:")
source_lang_label.grid(row=0, column=0, sticky=tk.W, padx=2)
source_lang_var = tk.StringVar(value="Auto Detect") # Default to Auto Detect
# Source language combobox including "Auto Detect"
source_lang_combo = ttk.Combobox(lang_frame, textvariable=source_lang_var, values=["Auto Detect"] + languages, state="readonly") # Removed width hint
source_lang_combo.grid(row=0, column=1, padx=2, sticky=(tk.W, tk.E))

target_lang_label = ttk.Label(lang_frame, text="Target:")
target_lang_label.grid(row=1, column=0, sticky=tk.W, padx=2)
target_lang_var = tk.StringVar(value="Vietnamese") # Default target language
target_lang_combo = ttk.Combobox(lang_frame, textvariable=target_lang_var, values=languages, state="readonly") # Removed width hint
target_lang_combo.grid(row=1, column=1, padx=2, sticky=(tk.W, tk.E))
lang_frame.columnconfigure(1, weight=1) # Make language combobox column expandable

# Tone/Style Frame (New) - Adjusted column index
tone_frame = ttk.LabelFrame(config_frame, text="Translation Tone/Style", padding="5")
tone_frame.grid(row=0, column=4, sticky=(tk.W, tk.E), padx=(5,0), pady=5) # Changed column to 4
tone_label = ttk.Label(tone_frame, text="Desired Tone:")
tone_label.pack(side=tk.LEFT, padx=(0,5))
tone_var = tk.StringVar()
tone_entry = ttk.Entry(tone_frame, textvariable=tone_var) # Removed width hint
tone_entry.pack(side=tk.LEFT, fill=tk.X, expand=True) # Use pack inside frame, let entry expand
tone_frame.columnconfigure(1, weight=1) # Not strictly needed as using pack, but good practice


# --- Processing Area (Two Columns) ---
processing_frame = ttk.Frame(main_frame)
# Use sticky N+S+E+W to make this frame fill the space allocated by main_frame's row 1 and column 0,1
processing_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))
# Configure processing_frame itself to make its internal row 0 (containing the two label frames) expand vertically
processing_frame.rowconfigure(0, weight=1)
# Configure processing_frame columns (0 and 1) to share horizontal space equally
processing_frame.columnconfigure(0, weight=1)
processing_frame.columnconfigure(1, weight=1)


# Left Column: Direct Translate
direct_translate_config_frame = ttk.LabelFrame(processing_frame, text="Step 1: Direct Translate from Original File to SRT", padding="10")
# Place in column 0 of processing_frame and make it fill its cell
direct_translate_config_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5, padx=(0,2))
# Configure columns inside this frame
direct_translate_config_frame.columnconfigure(0, weight=1)
direct_translate_config_frame.columnconfigure(1, weight=1) # Column for temperature entry etc.
# Configure rows inside this frame - the text areas should expand
direct_translate_config_frame.rowconfigure(1, weight=1) # Prompt area
direct_translate_config_frame.rowconfigure(4, weight=1) # Glossary area
direct_translate_config_frame.rowconfigure(8, weight=3) # Output area gets more weight for primary result


direct_translate_prompt_label = ttk.Label(direct_translate_config_frame, text="Prompt Template for Direct Translate (Edit, keep placeholders):")
direct_translate_prompt_label.grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0,2))
direct_translate_prompt_entry = scrolledtext.ScrolledText(direct_translate_config_frame, wrap=tk.WORD, height=8) # Height is hint
direct_translate_prompt_entry.insert(tk.END, DEFAULT_DIRECT_TRANSLATE_PROMPT_TEMPLATE)
# Make prompt entry fill its cell
direct_translate_prompt_entry.grid(row=1, column=0, columnspan=2, sticky=(tk.W,tk.E,tk.N,tk.S), pady=(0,5))
direct_translate_prompt_help = ttk.Label(direct_translate_config_frame, text="Placeholders: {target_lang}, {glossary_instructions_direct_translate}, {tone_instructions_direct_translate}", foreground="gray", wraplength=500) # Increased wraplength
direct_translate_prompt_help.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(0,5))


# Glossary for Direct Translate
glossary_direct_translate_label = ttk.Label(direct_translate_config_frame, text="Glossary/Character Names for Direct Translate (One item per line, e.g. 'Naruto' or 'Hentai'):")
glossary_direct_translate_label.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(5,0))
glossary_direct_translate_entry = scrolledtext.ScrolledText(direct_translate_config_frame, wrap=tk.WORD, height=4) # Height is hint
glossary_direct_translate_entry.grid(row=4, column=0, columnspan=2, sticky=(tk.W,tk.E,tk.N,tk.S), pady=(0,5))

direct_translate_temp_label = ttk.Label(direct_translate_config_frame, text="Temperature (0.0-1.0):")
direct_translate_temp_label.grid(row=5, column=0, sticky=tk.W, pady=(5,0), padx=(0,5))
direct_translate_temp_var = tk.StringVar(value="0.7")
direct_translate_temp_entry_widget = ttk.Entry(direct_translate_config_frame, textvariable=direct_translate_temp_var, width=10) # Width hint
direct_translate_temp_entry_widget.grid(row=5, column=0, sticky=tk.E, pady=(5,0)) # Place in col 0, stick East

direct_translate_button = ttk.Button(direct_translate_config_frame, text="1. Direct Translate to SRT", command=run_direct_translate_task_thread)
# Make button fill horizontally
direct_translate_button.grid(row=6, column=0, columnspan=2, pady=5, sticky=(tk.W, tk.E))

direct_translate_output_label = ttk.Label(direct_translate_config_frame, text="Direct Translate Output (SRT):")
direct_translate_output_label.grid(row=7, column=0, columnspan=2, sticky=tk.W, pady=(5,0))
direct_translate_output_area = scrolledtext.ScrolledText(direct_translate_config_frame, wrap=tk.WORD, height=10) # Height is hint
# Make output area fill its cell
direct_translate_output_area.grid(row=8, column=0, columnspan=2, sticky=(tk.W,tk.E,tk.N,tk.S), pady=(0,5))

# Modified command to use the new save logic
save_direct_translate_button = ttk.Button(direct_translate_config_frame, text="Save Direct Translate SRT...", command=lambda: save_srt_file(direct_translate_output_area, 'translated'))
save_direct_translate_button.grid(row=9, column=0, columnspan=2, pady=5, sticky=(tk.W, tk.E))


# Right Column: Validate and Correct
validate_config_frame = ttk.LabelFrame(processing_frame, text="Step 2: Validate & Correct SRT", padding="10")
# Place in column 1 of processing_frame and make it fill its cell
validate_config_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5, padx=(2,0))
# Configure columns inside this frame
validate_config_frame.columnconfigure(0, weight=1)
validate_config_frame.columnconfigure(1, weight=1) # Column for temperature entry etc.
# Configure rows inside this frame - the text areas should expand
validate_config_frame.rowconfigure(1, weight=1) # Prompt area
validate_config_frame.rowconfigure(6, weight=3) # Output area gets more weight for primary result


validate_prompt_label = ttk.Label(validate_config_frame, text="Prompt Template for Validate & Correct (Edit, keep placeholder):")
validate_prompt_label.grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0,2))
validate_prompt_entry = scrolledtext.ScrolledText(validate_config_frame, wrap=tk.WORD, height=8) # Height is hint
validate_prompt_entry.insert(tk.END, DEFAULT_VALIDATE_SRT_PROMPT_TEMPLATE)
# Make prompt entry fill its cell
validate_prompt_entry.grid(row=1, column=0, columnspan=2, sticky=(tk.W,tk.E,tk.N,tk.S), pady=(0,5))
validate_prompt_help = ttk.Label(validate_config_frame, text="Placeholder: {srt_content_to_validate}. Model will use the selected original file.", foreground="gray", wraplength=500) # Increased wraplength
validate_prompt_help.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(0,5))


validate_temp_label = ttk.Label(validate_config_frame, text="Temperature (0.0-1.0, lower recommended):")
validate_temp_label.grid(row=3, column=0, sticky=tk.W, pady=(5,0), padx=(0,5))
validate_temp_var = tk.StringVar(value="0.1") # Lower temperature for precision
validate_temp_entry_widget = ttk.Entry(validate_config_frame, textvariable=validate_temp_var, width=10) # Width hint
validate_temp_entry_widget.grid(row=3, column=0, sticky=tk.E, pady=(5,0)) # Place in col 0, stick East


validate_button = ttk.Button(validate_config_frame, text="2. Validate & Correct SRT", command=run_validate_task_thread)
# Make button fill horizontally
validate_button.grid(row=4, column=0, columnspan=2, pady=5, sticky=(tk.W, tk.E))


validated_srt_output_label = ttk.Label(validate_config_frame, text="Validated/Corrected SRT Output:")
validated_srt_output_label.grid(row=5, column=0, columnspan=2, sticky=tk.W, pady=(5,0))
validated_srt_output_area = scrolledtext.ScrolledText(validate_config_frame, wrap=tk.WORD, height=10) # Height is hint
# Make output area fill its cell
validated_srt_output_area.grid(row=6, column=0, columnspan=2, sticky=(tk.W,tk.E,tk.N,tk.S), pady=(0,5))

# Modified command to use the new save logic
save_validated_button = ttk.Button(validate_config_frame, text="Save Validated/Corrected SRT...", command=lambda: save_srt_file(validated_srt_output_area, 'validated'))
save_validated_button.grid(row=7, column=0, columnspan=2, pady=5, sticky=(tk.W, tk.E))


# --- Status Bar ---
status_var = tk.StringVar(value="Ready.")
# Place in main_frame row 2, span columns 0 and 1, stick West and East
status_bar = ttk.Label(main_frame, textvariable=status_var, relief=tk.SUNKEN, anchor=tk.W)
status_bar.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10,0))

# --- Initial Checks / Messages ---
def show_initial_message():
    if not api_key_var.get().strip():
        messagebox.showinfo("Welcome", "Welcome to Easy AI Subbing.\n\nPlease enter your Gemini API key above and click 'Save Key'. You can get a key from https://aistudio.google.com/apikey.\n\nAlso, please ensure FFmpeg is installed and added to your system's PATH for audio/video processing.")

# Call the initial message after the GUI is fully set up
app.after(100, show_initial_message)


# Update window title initially
update_window_title()
app.geometry("1600x900") # Keep initial size hint
app.mainloop()