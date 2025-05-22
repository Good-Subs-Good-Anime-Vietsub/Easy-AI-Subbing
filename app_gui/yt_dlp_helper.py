# EasyAISubbing/app_gui/yt_dlp_helper.py
import tkinter as tk # For type hinting only if needed
from tkinter import messagebox
import os
import subprocess
import shutil
import re
import logging
import threading # Import threading here

logger = logging.getLogger(__name__) # Will be app_gui.yt_dlp_helper

def check_yt_dlp_command_exists():
    if shutil.which("yt-dlp"):
        logger.info("yt-dlp command found in PATH.")
        return True
    logger.error("yt-dlp command not found. Please ensure yt-dlp is installed and in your system's PATH.")
    return False

def _get_subprocess_startup_info():
    """Hides the console window on Windows for subprocess."""
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        return startupinfo
    return None

def start_yt_dlp_download_task(url, app_controller, video_audio_tab_instance, download_audio_only=False):
    """
    Starts video/audio download task using yt-dlp in a separate thread.
    app_controller: MainWindow instance.
    video_audio_tab_instance: VideoAudioTab instance.
    """
    if not check_yt_dlp_command_exists():
        messagebox.showerror("yt-dlp Error", "yt-dlp command not found. Please install yt-dlp and ensure it's in your system's PATH.", parent=app_controller)
        return False # Cannot proceed

    # Cập nhật UI từ VideoAudioTab instance
    video_audio_tab_instance._set_ui_state(processing=True)
    video_audio_tab_instance._clear_all_process_states() # Clear previous process states
    video_audio_tab_instance.progress_var.set(0)
    video_audio_tab_instance.video_file_var.set(f"Preparing yt-dlp download...") # Temporary message
    logger.info(f"Starting yt-dlp download for URL: {url}")

    thread = threading.Thread(target=_task_download_with_yt_dlp_entry,
                               args=(url, app_controller, video_audio_tab_instance, download_audio_only),
                               daemon=True)
    thread.start()
    return True # Task has been started (in thread)

def _task_download_with_yt_dlp_entry(url, app_controller, video_audio_tab_instance, download_audio_only=True):
    """
    Task running in a thread to download with yt-dlp.
    """
    output_file_path_final = None # Final file path after download completes
    try:
        video_audio_tab_instance._update_progress(5, "Initializing yt-dlp...")

        output_dir = app_controller.app_temp_dir # Application's temporary directory

        # Build command for yt-dlp
        command = ["yt-dlp", "--no-check-certificates", "--no-mtime", "--ignore-config", "-P", output_dir]
        # Use output template for a more predictable filename and length limit
        # %(title).200B: Takes the first 200 bytes of the title.
        # %(ext)s: File extension.
        output_template = "%(title).200B.%(ext)s"
        command.extend(["-o", output_template])


        if download_audio_only:
            command.extend([
                "-x",  # Extract audio
                "--audio-format", "wav",
                "--audio-quality", "0", # yt-dlp will select the best and convert if needed
                 # Add --ppa (postprocessor arguments) to pass args to the ffmpeg postprocessor
                "--ppa", "ffmpeg:-ar 16000 -ac 1" # Force 16kHz mono after download
            ])
            target_ext_expected = ".wav"
        else: # Download video (and accompanying audio)
            command.extend([
                # Priority sorting: highest resolution, then mp4 video, m4a audio
                # then generic mp4 video, finally any best format
                "-S", "res,ext:mp4:m4a", # Sort priority by resolution, then mp4 video, m4a audio
                # Try to recode to mp4 if the original video format is not mp4
                # This ensures the output is mp4 if possible, useful for later muxing.
                "--recode-video", "mp4",
            ])
            target_ext_expected = ".mp4"
        command.append(url) # Final URL

        logger.info(f"Executing yt-dlp command: {' '.join(command)}")
        video_audio_tab_instance.video_file_var.set(f"yt-dlp downloading...") # Update UI

        startupinfo = _get_subprocess_startup_info()
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding='utf-8', errors='replace',
                                   startupinfo=startupinfo, bufsize=1) # bufsize=1 for line buffering

        final_filename_from_yt_dlp = None # Final filename reported by yt-dlp

        while True:
            if video_audio_tab_instance.cancel_requested:
                logger.info("yt-dlp download cancelled by user during process.")
                if process.poll() is None: # If process is still running
                    process.terminate()
                    try: process.wait(timeout=3) # Wait for 3 seconds
                    except subprocess.TimeoutExpired: process.kill() # If it doesn't stop, kill it
                return # Exit task

            line = process.stdout.readline()
            if not line and process.poll() is not None: # No more output and process has stopped
                break # Exit loop

            if line:
                line_strip = line.strip()
                logger.debug(f"yt-dlp stdout: {line_strip}")

                # Improved filename extraction logic
                match_info_output = re.search(r"^\[info\] Output: (.*)", line_strip)
                if match_info_output:
                    final_filename_from_yt_dlp = os.path.basename(match_info_output.group(1).strip("\"'"))
                    logger.info(f"yt-dlp final output file detected (from [info] Output): {final_filename_from_yt_dlp}")

                # If no [info] Output, try Destination lines (usually for intermediate steps or simple downloads)
                if not final_filename_from_yt_dlp:
                    match_dest = re.search(r"\[(?:ExtractAudio|download|Fixup\w*)\] Destination: (.*)", line_strip)
                    if match_dest:
                        potential_fn = os.path.basename(match_dest.group(1).strip("\"'"))
                        # Only take if it matches the expected extension (sign of the final file)
                        if potential_fn.lower().endswith(target_ext_expected):
                            final_filename_from_yt_dlp = potential_fn
                            logger.info(f"yt-dlp (post-process/direct) destination updated: {final_filename_from_yt_dlp}")

                if not final_filename_from_yt_dlp: # Still no match, try Merger line
                    match_merger = re.search(r"Merging formats into \"([^\"]+)\"", line_strip)
                    if match_merger:
                        final_filename_from_yt_dlp = os.path.basename(match_merger.group(1).strip("\"'"))
                        logger.info(f"yt-dlp merged file detected: {final_filename_from_yt_dlp}")


                # Parse progress percentage
                progress_match = re.search(r"\[download\]\s+([0-9\.]+)\%", line_strip)
                if progress_match:
                    try:
                        percent = float(progress_match.group(1))
                        # Assume download takes 90% of total progress, first 5% is init, final 5% is post-processing
                        video_audio_tab_instance._update_progress(5 + (percent * 0.9), f"yt-dlp: {percent:.1f}%")
                    except ValueError:
                         video_audio_tab_instance._update_progress(video_audio_tab_instance.progress_var.get(), f"yt-dlp: Processing...")


        # Wait for the process to finish completely and get the exit code
        stdout_rem, stderr_rem = process.communicate() # Get remaining output (if any)
        logger.debug(f"yt-dlp final stdout after communicate: {stdout_rem.strip()}")
        return_code = process.returncode

        if video_audio_tab_instance.cancel_requested: # Check again after communicate
            logger.info("yt-dlp download cancelled by user after process completion signal.")
            return

        if return_code != 0:
            logger.error(f"yt-dlp failed with return code {return_code}.")
            full_stderr = stderr_rem.strip()
            logger.error(f"yt-dlp stderr: {full_stderr}")
            video_audio_tab_instance.after(0, lambda: messagebox.showerror("yt-dlp Error", f"yt-dlp failed (code {return_code}).\nDetails: {full_stderr[:500]}...\nCheck logs for more.", parent=app_controller))
            video_audio_tab_instance.after(0, lambda: video_audio_tab_instance.video_file_var.set("yt-dlp failed"))
            return

        video_audio_tab_instance._update_progress(95, "yt-dlp download/processing finished.")

        # Determine the final file path
        if final_filename_from_yt_dlp:
            # Filename from yt-dlp might contain unsafe characters or be too long if the template is not well-limited.
            # Output template already has ".200B" so it's not too concerning.
            output_file_path_final = os.path.join(output_dir, final_filename_from_yt_dlp)
            if not os.path.exists(output_file_path_final):
                logger.error(f"yt-dlp reported filename '{final_filename_from_yt_dlp}' but not found at '{output_file_path_final}'. This indicates an issue.")
                output_file_path_final = None # Reset to search again
        
        if not output_file_path_final: # If no filename from stdout or that file doesn't exist
            logger.warning("Could not reliably determine final filename from yt-dlp stdout. Attempting to find latest matching file in temp directory.")
            found_files = []
            for f_name in os.listdir(output_dir):
                # Check expected extension (target_ext_expected)
                if f_name.lower().endswith(target_ext_expected):
                    full_f_path = os.path.join(output_dir, f_name)
                    if os.path.isfile(full_f_path):
                        found_files.append(full_f_path)
            
            if found_files:
                found_files.sort(key=os.path.getmtime, reverse=True) # Get the latest file by modification time
                output_file_path_final = found_files[0]
                logger.info(f"Fallback file search: Found potential output file: {output_file_path_final}")
            else:
                logger.error(f"yt-dlp finished, but no output file with extension '{target_ext_expected}' found in '{output_dir}'.")
                video_audio_tab_instance.after(0, lambda: messagebox.showerror("yt-dlp Error", f"yt-dlp completed, but no output file with extension '{target_ext_expected}' could be found. Check logs and temporary folder: '{output_dir}'.", parent=app_controller))
                return

        if os.path.exists(output_file_path_final):
            logger.info(f"File downloaded/processed by yt-dlp: {output_file_path_final}")
            video_audio_tab_instance.after(0, video_audio_tab_instance._process_selected_file, output_file_path_final, "yt-dlp")
        else: # This case is very rare if the logic above ran correctly
            logger.error(f"yt-dlp process finished but determined output file not found: {output_file_path_final}")
            video_audio_tab_instance.after(0, lambda: messagebox.showerror("yt-dlp Error", f"yt-dlp seemed to finish, but the output file '{os.path.basename(output_file_path_final or 'unknown')}' was not found. Check logs.", parent=app_controller))

    except Exception as e:
        logger.error(f"Unexpected error during yt-dlp task: {e}", exc_info=True)
        video_audio_tab_instance.after(0, lambda: messagebox.showerror("yt-dlp Processing Error", f"An unexpected error occurred during yt-dlp processing: {e}", parent=app_controller))
        video_audio_tab_instance.after(0, lambda: video_audio_tab_instance.video_file_var.set("yt-dlp processing error"))
    finally:
        is_cancelled = video_audio_tab_instance.cancel_requested # Save cancel state before calling after
        
        def final_ui_update_yt_dlp(): # Function to run in the main thread
            if is_cancelled:
                video_audio_tab_instance._clear_all_process_states() # Clean up if user cancelled
                video_audio_tab_instance.video_file_var.set("Download cancelled")
            video_audio_tab_instance._set_ui_state(False) # Always re-enable UI
            video_audio_tab_instance.progress_var.set(0) # Always reset progress to 0
            
        video_audio_tab_instance.after(0, final_ui_update_yt_dlp)
