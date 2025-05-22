# EasyAISubbing/core/subtitle_parser.py
import logging
import os
try:
    import pysubs2
    SUBTITLE_SUPPORTED = True
    # Optional: Reduce pysubs2 log level if it's too verbose
    logger_pysubs = logging.getLogger("pysubs2")
    logger_pysubs.setLevel(logging.WARNING) # Only show WARNING and ERROR from pysubs2
except ImportError:
    SUBTITLE_SUPPORTED = False
    # Critical error logging will be handled by the calling module or main.py

logger = logging.getLogger(__name__) # The logger name will be core.subtitle_parser

if not SUBTITLE_SUPPORTED:
    # Log here for clarity when this module is imported
    logger.critical("CRITICAL DEPENDENCY ERROR: pysubs2 library not found. Subtitle parsing and handling WILL FAIL.")
    logger.critical("Please install it by running: pip install pysubs2")

# --- Function to clean subtitle text ---
def clean_subtitle_text(text: str) -> str:
    """
    Cleans subtitle text by replacing newline characters (\\N, \\n) with spaces,
    collapsing multiple spaces, and stripping leading/trailing spaces.
    """
    if not isinstance(text, str):
        return "" # Return empty string for non-string input

    # Replace ASS/SSA newline and standard newline with space
    cleaned_text = text.replace('\\N', ' ').replace('\n', ' ')

    # Replace multiple spaces with a single space
    import re
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text)

    # Strip leading/trailing spaces
    cleaned_text = cleaned_text.strip()

    return cleaned_text

# --- Main loading function ---
def load_subtitle_file(filepath: str):
    """
    Loads a subtitle file (SRT, VTT, ASS, SSA) using pysubs2.
    Returns a pysubs2.SSAFile object or None if parsing fails or library is not found.
    """
    if not SUBTITLE_SUPPORTED:
        logger.error("Cannot load subtitle: Pysubs2 library is not available.")
        return None

    if not os.path.exists(filepath):
        logger.error(f"File not found for loading: {filepath}")
        return None

    try:
        # pysubs2.load automatically detects format
        # Try common encodings if utf-8 fails, but utf-8 is preferred
        try:
            subs = pysubs2.load(filepath, encoding="utf-8")
        except UnicodeDecodeError:
            logger.warning(f"Failed to decode {os.path.basename(filepath)} with UTF-8, trying system default...")
            subs = pysubs2.load(filepath) # Try with system default encoding
        except pysubs2.exceptions.UnknownFPSError as e_fps: # Handle FPS error if any
            logger.warning(f"Pysubs2 UnknownFPSError for {os.path.basename(filepath)}: {e}. Assuming 25 FPS.")
            subs = pysubs2.load(filepath, encoding="utf-8", fps=25.0)


        logger.info(f"Successfully parsed subtitle file: {os.path.basename(filepath)} ({len(subs)} events found by pysubs2)")
        return subs
    except Exception as e:
        logger.error(f"Error parsing subtitle file {os.path.basename(filepath)} with pysubs2: {e}", exc_info=True)
        return None

# --- Function to extract text for translation ---
def extract_text_and_format_info(subtitle_data: 'pysubs2.SSAFile'):
    """
    Extracts translatable text segments (with placeholders for drawing/empty dialogue)
    and returns them along with the original event objects.
    Returns a tuple: (list of text segments for translation, list of original pysubs2.SSAEvent objects).
    """
    if not SUBTITLE_SUPPORTED:
        logger.error("Cannot extract text: Pysubs2 library is not available.")
        return [], []

    if not isinstance(subtitle_data, pysubs2.SSAFile):
        logger.error(f"Unsupported data structure for text extraction: {type(subtitle_data)}. Expected pysubs2.SSAFile.")
        return [], []

    text_segments_for_translation = []
    original_events = []

    for event in subtitle_data:
        original_events.append(event) # Keep track of original events

        if event.is_drawing: # Use is_drawing to identify drawing events
            # Drawing event - replace with placeholder
            text_segments_for_translation.append("(shape)")
            logger.debug(f"Replacing drawing event at {event.start}-{event.end} ms with '(shape)'.")
        elif event.type == "Dialogue":
            # Dialogue event
            raw_text = event.plaintext # event.plaintext removes all ASS/SSA tags
            cleaned_text = clean_subtitle_text(raw_text) # Clean the text

            if not cleaned_text:
                # Dialogue event with no text after cleaning
                text_segments_for_translation.append("(empty)")
                logger.debug(f"Replacing empty dialogue event at {event.start}-{event.end} ms with '(empty)'.")
            else:
                # Dialogue event with cleaned text
                text_segments_for_translation.append(cleaned_text)
        elif event.type == "Comment":
            # Comment event - do not include in text for translation
            logger.debug(f"Skipping comment event at {event.start}-{event.end} ms for translation.")
            pass # Do not add to text_segments_for_translation
        else:
            # Other event types - do not include in text for translation
            logger.debug(f"Skipping event type '{event.type}' at {event.start}-{event.end} ms for translation.")
            pass # Do not add to text_segments_for_translation


    logger.info(f"Prepared {len(text_segments_for_translation)} segments for translation from {len(original_events)} total events.")
    if not text_segments_for_translation:
        logger.info("No translatable dialogue or placeholder events found in the input subtitle file.")

    return text_segments_for_translation, original_events


# --- Function to reassemble translated text ---
def reassemble_subtitle(original_timing_info: list, translated_text_segments: list):
    """
    Reassembles translated text segments with original timing into a new pysubs2.SSAFile object.
    original_timing_info: List of dicts [{'start': ms, 'end': ms}].
    translated_text_segments: List of translated text strings.
    Returns the reassembled pysubs2.SSAFile object, or None on error.
    """
    if not SUBTITLE_SUPPORTED:
        logger.error("Cannot reassemble subtitle: Pysubs2 library is not available.")
        return None

    if len(original_timing_info) != len(translated_text_segments):
        logger.error(f"Mismatch in segment count for reassembly. Timings: {len(original_timing_info)}, Translated Texts: {len(translated_text_segments)}")
        return None

    reassembled_subs = pysubs2.SSAFile()
    # Optionally, define a default style if you want the output ASS/SSA to have one.
    # If not, pysubs2 might create a very basic "Default" style.
    # default_style = pysubs2.SSAStyle()
    # default_style.fontname = "Arial"
    # default_style.fontsize = 20.0
    # reassembled_subs.styles["Default"] = default_style

    for i, translated_text in enumerate(translated_text_segments):
        timing = original_timing_info[i]
        try:
            start_ms = int(timing['start'])
            end_ms = int(timing['end'])

            if start_ms >= end_ms:
                logger.warning(f"Skipping event {i+1} due to invalid timing: start ({start_ms}ms) >= end ({end_ms}ms). Text: '{translated_text[:50]}...'")
                continue

            # Create a new dialogue event. Style will be default.
            event = pysubs2.SSAEvent(start=start_ms, end=end_ms, text=translated_text.strip())
            reassembled_subs.append(event)
        except KeyError:
            logger.error(f"Missing 'start' or 'end' key in timing_info for segment {i+1}. Skipping.")
            continue
        except ValueError:
            logger.error(f"Invalid 'start' or 'end' value in timing_info for segment {i+1}. start='{timing.get('start')}', end='{timing.get('end')}'. Skipping.")
            continue
        except Exception as e:
            logger.error(f"Unexpected error creating SSAEvent for segment {i+1}: {e}. Text: '{translated_text[:50]}...'. Skipping.", exc_info=True)
            continue


    logger.info(f"Pysubs2 subtitle reassembly complete with {len(reassembled_subs)} events.")
    return reassembled_subs


# --- Function to reassemble translated text with original events ---
def reassemble_translated_subs(original_events: list, translated_text_segments: list) -> 'pysubs2.SSAFile':
    """
    Reassembles translated text segments into a new SSAFile object using the original events
    as a base, preserving non-dialogue events and inserting translated text into dialogue events.
    original_events: List of original pysubs2.SSAEvent objects.
    translated_text_segments: List of translated text strings (should match the count of
                              translatable events from extract_text_and_format_info).
    Returns the reassembled pysubs2.SSAFile object, or None on error.
    """
    if not SUBTITLE_SUPPORTED:
        logger.error("Cannot reassemble subtitle: Pysubs2 library is not available.")
        return None

    if not original_events:
        logger.error("Original events list is empty for reassembly.")
        return None

    reassembled_subs = pysubs2.SSAFile()
    # Copy styles and info from the first original event's SSAFile if available
    if original_events and hasattr(original_events[0], 'parent'):
        try:
            reassembled_subs.styles = original_events[0].styles
            reassembled_subs.info = original_events[0].info
        except Exception as e:
            logger.warning(f"Could not copy styles/info from original SSAFile: {e}")


    translated_index = 0
    for original_event in original_events:
        # Check if this original event was included in the list sent for translation
        # (Dialogue or Drawing events from extract_text_and_format_info)
        is_translatable_type = original_event.type == "Dialogue" or original_event.type == "Drawing"

        if is_translatable_type:
            if translated_index < len(translated_text_segments):
                translated_text = translated_text_segments[translated_index]

                # Create a new Dialogue event with translated text and timing
                new_event = pysubs2.SSAEvent(
                    start=original_event.start,
                    end=original_event.end,
                    text=translated_text, # Use the translated/placeholder text
                    type="Dialogue" # Ensure output is Dialogue type for these
                )

                # ONLY copy ASS/SSA specific attributes if the original event was a Dialogue event
                if original_event.type == "Dialogue":
                    # Safely copy attributes that might exist on Dialogue events
                    new_event.style = original_event.style if hasattr(original_event, 'style') else reassembled_subs.styles.get("Default", pysubs2.SSAStyle()).name # Fallback to default style name
                    new_event.actor = original_event.actor if hasattr(original_event, 'actor') else ""
                    new_event.marginl = original_event.marginl if hasattr(original_event, 'marginl') else 0
                    new_event.marginr = original_event.marginr if hasattr(original_event, 'marginr') else 0
                    new_event.marginv = original_event.marginv if hasattr(original_event, 'marginv') else 0
                    new_event.effect = original_event.effect if hasattr(original_event, 'effect') else ""
                    new_event.name = original_event.name if hasattr(original_event, 'name') else "Default" # Style name in ASS/SSA
                    new_event.layer = original_event.layer if hasattr(original_event, 'layer') else 0
                # Note: Drawing events do not have these ASS-specific attributes, so they are not copied.

                reassembled_subs.append(new_event)
                translated_index += 1
            else:
                # This should not happen if counts match, but as a fallback:
                logger.warning(f"Ran out of translated segments for original event at {original_event.start}-{original_event.end} ms. Appending original event as fallback.")
                # Keep the original event as fallback if translated segments run out unexpectedly
                reassembled_subs.append(original_event)

        elif original_event.type == "Comment":
            # Keep comment events as they are
            reassembled_subs.append(original_event)
            logger.debug(f"Keeping comment event at {original_event.start}-{original_event.end} ms.")
        else:
            # Keep other non-dialogue, non-drawing, non-comment events as they are
            reassembled_subs.append(original_event)
            logger.debug(f"Keeping event type '{original_event.type}' at {original_event.start}-{original_event.end} ms.")


    if translated_index != len(translated_text_segments):
         logger.warning(f"Mismatch after reassembly loop: Used {translated_index} translated segments, but had {len(translated_text_segments)} available.")


    logger.info(f"Pysubs2 subtitle reassembly complete with {len(reassembled_subs)} events.")
    return reassembled_subs


# --- Function to save subtitle file ---
def save_subtitle_file(subtitle_data: 'pysubs2.SSAFile', filepath: str):
    """
    Saves a pysubs2.SSAFile object to a file. pysubs2 determines format from extension.
    subtitle_data: The pysubs2.SSAFile object.
    filepath: The path to save the file.
    Returns True on success, False on failure.
    """
    if not SUBTITLE_SUPPORTED:
        logger.error("Cannot save subtitle: Pysubs2 library is not available.")
        return False

    if not isinstance(subtitle_data, pysubs2.SSAFile):
        logger.error(f"Unsupported data structure for saving: {type(subtitle_data)}. Expected pysubs2.SSAFile.")
        return False

    try:
        # Ensure the directory for the output file exists
        output_dir = os.path.dirname(filepath)
        if output_dir and not os.path.exists(output_dir): # Check if output_dir is not empty
            os.makedirs(output_dir, exist_ok=True)
            logger.info(f"Created directory for subtitle output: {output_dir}")

        # pysubs2.save handles format based on file extension (e.g. .srt, .ass, .vtt)
        # Always save as UTF-8 for broad compatibility
        subtitle_data.save(filepath, encoding="utf-8")
        logger.info(f"Successfully saved subtitle file with pysubs2: {os.path.basename(filepath)}")
        return True
    except Exception as e:
        logger.error(f"Error saving subtitle file {os.path.basename(filepath)} with pysubs2: {e}", exc_info=True)
        return False

