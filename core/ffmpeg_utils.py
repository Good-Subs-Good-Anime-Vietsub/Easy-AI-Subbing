# EasyAISubbing/core/ffmpeg_utils.py
import subprocess
import os
import logging
import re # Import re for regex parsing
import json # Import json for ffprobe output parsing
import time # Import time for generating unique temp filenames

logger = logging.getLogger(__name__)

def _get_startup_info_for_windows():
    """Returns STARTUPINFO to hide console window on Windows, else None."""
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        return startupinfo
    return None

def check_ffmpeg_exists():
    """Checks if ffmpeg is accessible."""
    try:
        startupinfo = _get_startup_info_for_windows()
        subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True, text=True, startupinfo=startupinfo)
        logger.info("FFMPEG found.")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.error("FFMPEG command not found. Please ensure FFMPEG is installed and in your system's PATH.")
        return False

def check_yt_dlp_exists():
    """Checks if yt-dlp is accessible."""
    try:
        startupinfo = _get_startup_info_for_windows()
        # Use --version or -U (update) as a lightweight check
        subprocess.run(["yt-dlp", "--version"], check=True, capture_output=True, text=True, startupinfo=startupinfo)
        logger.info("yt-dlp found.")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.error("yt-dlp command not found. Please ensure yt-dlp is installed and in your system's PATH.")
        return False

def extract_audio(video_path, output_audio_path="temp_extracted_audio.wav"):
    """
    Extracts audio from a video file to WAV format.
    Returns the path to the audio file or None on failure.
    """
    if not check_ffmpeg_exists():
        return None

    if os.path.exists(output_audio_path):
        try:
            os.remove(output_audio_path)
            logger.info(f"Removed existing temp audio file: {output_audio_path}")
        except OSError as e:
            logger.warning(f"Could not remove existing temp audio file {output_audio_path}: {e}")

    command = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",                # No video
        "-acodec", "pcm_s16le", # WAV format (signed 16-bit little-endian PCM)
        "-ar", "16000",       # Sample rate (Gemini prefers 16kHz for ASR tasks)
        "-ac", "1",           # Mono channel
        output_audio_path
    ]
    logger.info(f"Executing FFMPEG to extract audio: {' '.join(command)}")
    try:
        startupinfo = _get_startup_info_for_windows()
        process = subprocess.run(command, check=True, capture_output=True, text=True, startupinfo=startupinfo)
        logger.debug(f"FFMPEG stdout (extract_audio): {process.stdout}")
        logger.debug(f"FFMPEG stderr (extract_audio): {process.stderr}")
        if os.path.exists(output_audio_path) and os.path.getsize(output_audio_path) > 0:
            logger.info(f"Audio successfully extracted to: {output_audio_path}")
            return output_audio_path
        else:
            logger.error(f"FFMPEG ran but output file {output_audio_path} is missing or empty. Stderr: {process.stderr}")
            return None
    except subprocess.CalledProcessError as e:
        logger.error(f"FFMPEG error during audio extraction: {e.stderr}")
        return None
    except FileNotFoundError:
        logger.error("FFMPEG command not found. Ensure it is installed and in PATH.")
        return None


def extract_audio_segment(full_audio_path, start_time_sec, end_time_sec, output_segment_path):
    """
    Extracts a segment from an audio file. (Currently unused in the latest workflow but kept)
    Returns path to segment or None on failure.
    """
    if not check_ffmpeg_exists():
        return None

    if os.path.exists(output_segment_path):
        try:
            os.remove(output_segment_path)
        except OSError as e:
            logger.warning(f"Could not remove existing segment file {output_segment_path}: {e}")

    duration_sec = end_time_sec - start_time_sec
    if duration_sec <= 0:
        logger.error(f"Invalid duration for audio segment: {duration_sec}s (start: {start_time_sec}, end: {end_time_sec})")
        return None

    command = [
        "ffmpeg", "-y",
        "-i", full_audio_path,
        "-ss", str(start_time_sec),
        "-t", str(duration_sec),
        "-acodec", "pcm_s16le", # Keep WAV format
        "-ar", "16000",        # Keep sample rate
        "-ac", "1",            # Keep mono
        output_segment_path
    ]
    logger.info(f"Executing FFMPEG for segment: {' '.join(command)}")
    try:
        startupinfo = _get_startup_info_for_windows()
        process = subprocess.run(command, check=True, capture_output=True, text=True, startupinfo=startupinfo)
        logger.debug(f"FFMPEG segment stdout: {process.stdout}")
        logger.debug(f"FFMPEG segment stderr: {process.stderr}")
        if os.path.exists(output_segment_path) and os.path.getsize(output_segment_path) > 0:
            logger.info(f"Audio segment successfully extracted to: {output_segment_path}")
            return output_segment_path
        else:
            logger.error(f"FFMPEG ran for segment but output {output_segment_path} is missing or empty. Stderr: {process.stderr}")
            return None
    except subprocess.CalledProcessError as e:
        logger.error(f"FFMPEG error extracting audio segment: {e.stderr}")
        return None
    except FileNotFoundError:
        logger.error("FFMPEG command not found during segment extraction.")
        return None

def get_video_duration(video_path):
    """
    Gets the duration of a video file in seconds using ffprobe.
    Returns duration in seconds or None on failure.
    """
    if not check_ffmpeg_exists(): # ffprobe is usually bundled
        return None

    command = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    logger.info(f"Executing ffprobe to get duration: {' '.join(command)}")
    try:
        startupinfo = _get_startup_info_for_windows()
        process = subprocess.run(command, check=True, capture_output=True, text=True, startupinfo=startupinfo)
        duration_str = process.stdout.strip()
        if duration_str:
            try:
                duration_seconds = float(duration_str)
                logger.info(f"Video duration found: {duration_seconds:.2f} seconds")
                return duration_seconds
            except ValueError:
                logger.error(f"Could not parse ffprobe duration output: {duration_str}")
                return None
        else:
            logger.error(f"ffprobe returned empty duration for {video_path}. Stderr: {process.stderr}")
            return None
    except subprocess.CalledProcessError as e:
        logger.error(f"ffprobe error getting duration: {e.stderr}")
        return None
    except FileNotFoundError:
        logger.error("ffprobe command not found. Ensure FFMPEG (with ffprobe) is installed and in PATH.")
        return None

def format_seconds_to_hhmmss(seconds):
    """
    Formats seconds into HH:MM:SS.ss string.
    """
    if seconds is None:
        return "N/A"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    remaining_seconds = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{remaining_seconds:05.2f}"

def get_video_resolution(video_path):
    """
    Gets the resolution (widthxheight) of a video file using ffprobe.
    Returns resolution string (e.g., "1920x1080") or None on failure.
    """
    if not check_ffmpeg_exists(): # ffprobe is usually bundled
        return None

    command = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of",
        "csv=p=0:s=x", video_path
    ]
    logger.info(f"Executing ffprobe to get resolution: {' '.join(command)}")
    try:
        startupinfo = _get_startup_info_for_windows()
        process = subprocess.run(command, check=True, capture_output=True, text=True, startupinfo=startupinfo)
        resolution_str = process.stdout.strip()
        if resolution_str and 'x' in resolution_str:
            logger.info(f"Video resolution found: {resolution_str}")
            return resolution_str
        else:
            logger.error(f"ffprobe returned invalid resolution output for {video_path}: {resolution_str}. Stderr: {process.stderr}")
            return None
    except subprocess.CalledProcessError as e:
        logger.error(f"ffprobe error getting resolution: {e.stderr}")
        return None
    except FileNotFoundError:
        logger.error("ffprobe command not found during resolution check.")
        return None

def list_subtitle_tracks(video_path):
    """
    Lists available subtitle tracks in a video file using ffprobe.
    Returns a list of dictionaries, each describing a subtitle stream, or None on failure.
    Each dictionary includes 'index', 'codec_name', 'language', and 'title'.
    """
    if not check_ffmpeg_exists(): # ffprobe is usually bundled
        return None

    # Command to list subtitle streams in JSON format
    # select_streams s: subtitle streams
    # show_entries stream=index,codec_name,tags:language,tags:title : extract index, codec, language tag, title tag
    # of json: output format is JSON
    command = [
        "ffprobe", "-v", "error", "-select_streams", "s",
        "-show_entries", "stream=index,codec_name,codec_type,tags",
        "-of", "json",
        video_path
    ]
    logger.info(f"Executing ffprobe to list subtitle tracks: {' '.join(command)}")
    try:
        startupinfo = _get_startup_info_for_windows()
        process = subprocess.run(command, check=True, capture_output=True, text=True, startupinfo=startupinfo)
        output_json = process.stdout.strip()

        if not output_json:
            logger.info(f"No subtitle tracks found or ffprobe output empty for {video_path}. Stderr: {process.stderr.strip()}")
            return [] # Return empty list if no subtitle tracks found

        try:
            data = json.loads(output_json)
            streams = data.get('streams', [])
            subtitle_tracks = []
            for stream in streams:
                track_info = {
                    'index': stream.get('index'),
                    'codec_name': stream.get('codec_name'),
                    'language': stream.get('tags', {}).get('language', 'unknown'),
                    'title': stream.get('tags', {}).get('title', 'N/A')
                }
                # Only include actual subtitle streams, filtering out potential garbage
                if track_info['codec_name'] in ['srt', 'ass', 'ssa', 'webvtt', 'subrip', 'mov_text', 'text']: # Add common subtitle codecs
                    subtitle_tracks.append(track_info)
                else:
                    logger.debug(f"Skipping non-subtitle stream with codec: {track_info['codec_name']} (Index: {track_info['index']})")

            logger.info(f"Found {len(subtitle_tracks)} usable subtitle track(s).")
            logger.debug(f"Usable Subtitle tracks info: {subtitle_tracks}")
            return subtitle_tracks
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse ffprobe JSON output for {video_path}: {e}. Output: {output_json[:500]}...")
            return None

    except subprocess.CalledProcessError as e:
        logger.error(f"ffprobe error listing subtitle tracks for {video_path}: {e.stderr}")
        return None
    except FileNotFoundError:
        logger.error("ffprobe command not found during subtitle track listing.")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during subtitle track listing: {e}", exc_info=True)
        return None


def extract_subtitle_to_temp_file(video_path, track_index, output_extension='srt', temp_dir=None):
    """
    Extracts a specific subtitle track from a video file to a temporary file.
    Can specify output format using output_extension (e.g., 'srt', 'ass').
    Returns the path to the temporary subtitle file or None on failure.
    """
    if not check_ffmpeg_exists():
        return None

    # Map common subtitle formats to file extensions if needed, although ffmpeg often uses codec name
    # For extraction, often the codec name directly corresponds to a usable format/extension.
    # We'll trust the provided output_extension parameter from the caller.

    if temp_dir and not os.path.exists(temp_dir):
        try:
            os.makedirs(temp_dir, exist_ok=True)
            logger.info(f"Created temporary directory: {temp_dir}")
        except OSError as e:
            logger.error(f"Failed to create temporary directory {temp_dir}: {e}")
            return None

    # Generate a unique temporary filename using the specified output extension
    input_filename_base = os.path.splitext(os.path.basename(video_path))[0]
    temp_filename = f"{input_filename_base}_track{track_index}_{int(time.time())}.{output_extension.lstrip('.')}" # Ensure extension has no leading dot here
    if temp_dir:
        temp_filepath = os.path.join(temp_dir, temp_filename)
    else:
        # Fallback to current directory if temp_dir is not provided or failed
        temp_filepath = temp_filename
        logger.warning("Temporary directory not specified, using current directory for temp subtitle extraction.")

    # Ensure output path is absolute for clarity in logs/commands
    temp_filepath_abs = os.path.abspath(temp_filepath)

    # Determine output format for ffmpeg based on the extension
    ffmpeg_output_format = output_extension.lstrip('.') # FFmpeg -f requires format name, usually the extension is sufficient


    command = [
        "ffmpeg", "-y", # Overwrite output file without asking
        "-i", video_path,
        "-map", f"0:{track_index}", # Select input stream by global index (file 0, stream index)
        "-c:s", "copy", # Copy the subtitle stream without re-encoding (fastest)
        "-f", ffmpeg_output_format, # Specify output format based on extension
        temp_filepath_abs
    ]
    logger.info(f"Executing FFMPEG to extract subtitle track {track_index} to .{output_extension}: {' '.join(command)}")
    try:
        startupinfo = _get_startup_info_for_windows()
        process = subprocess.run(command, check=True, capture_output=True, text=True, startupinfo=startupinfo)
        logger.debug(f"FFMPEG stdout (extract_subtitle): {process.stdout}")
        logger.debug(f"FFMPEG stderr (extract_subtitle): {process.stderr}")

        if os.path.exists(temp_filepath_abs) and os.path.getsize(temp_filepath_abs) > 0:
            logger.info(f"Subtitle track {track_index} successfully extracted to: {temp_filepath_abs}")
            return temp_filepath_abs
        else:
             # Log stderr if the file is missing or empty
             logger.error(f"FFMPEG ran but output file {temp_filepath_abs} is missing or empty. Stderr: {process.stderr.strip()}")
             return None

    except subprocess.CalledProcessError as e:
        logger.error(f"FFMPEG error during subtitle extraction (track {track_index}) to .{output_extension}: {e.stderr}")
        # Clean up potentially partially created file
        if os.path.exists(temp_filepath_abs):
             try: os.remove(temp_filepath_abs)
             except OSError as e_rm: logger.warning(f"Could not remove partial subtitle file {temp_filepath_abs}: {e_rm}")
        return None
    except FileNotFoundError:
        logger.error("FFMPEG command not found during subtitle extraction.")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during subtitle extraction: {e}", exc_info=True)
        # Clean up potentially partially created file
        if os.path.exists(temp_filepath_abs):
             try: os.remove(temp_filepath_abs)
             except OSError as e_rm: logger.warning(f"Could not remove partial subtitle file {temp_filepath_abs}: {e_rm}")
        return None
