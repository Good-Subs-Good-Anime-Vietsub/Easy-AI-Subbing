import tkinter as tk
from tkinter import messagebox
import logging
import os
import threading
import time
import subprocess
import re
from queue import Queue, Empty

from core import ffmpeg_utils
from .ui_utils import show_scrollable_messagebox

logger = logging.getLogger(__name__)

# Placeholder for task function that will be moved here
# def task_process_video(...):
#     pass

# Helper function to read from a pipe and put lines into a queue
def enqueue_output(out, queue):
    for line in iter(out.readline, ''):
        queue.put(line)
    out.close()

# Function to process the queues and update UI (runs in main thread)
def check_ffmpeg_output_queues(tab_instance):
    """Periodically checks the FFMPEG output queues and updates the UI."""
    try:
        # Process stdout queue
        while True:
            try:
                line = tab_instance._stdout_queue.get_nowait()
                line_strip = line.strip()
                tab_instance._update_log_text(line_strip)

                # Parse FFMPEG progress if 'time=' is present and video_duration is valid
                if "time=" in line_strip and hasattr(tab_instance, 'video_duration') and tab_instance.video_duration and tab_instance.video_duration > 0:
                    try:
                        time_str_match = re.search(r"time=(\d{2}:\d{2}:\d{2}\.\d{2,3})", line_strip) # Allow 2 or 3 decimal places for ms
                        if time_str_match:
                            time_str = time_str_match.group(1)
                            parts = time_str.split(':')
                            h = float(parts[0])
                            m = float(parts[1])
                            s_parts = parts[2].split('.')
                            s = float(s_parts[0])
                            if len(s_parts) > 1:
                                s += float(f"0.{s_parts[1]}")
                                
                        current_seconds = h * 3600 + m * 60 + s
                        # Adjust progress range
                        progress_percent = (current_seconds / tab_instance.video_duration) * 80 # Assuming 80% for this step
                        tab_instance._update_processing_progress(10 + progress_percent, f"Processing: {time_str} / {ffmpeg_utils.format_seconds_to_hhmmss(tab_instance.video_duration)}")

                    except Exception as e_parse:
                        tab_instance.logger.warning(f"Failed to parse FFMPEG progress line '{line_strip[:50]}...': {e_parse}")

                # Update status with first 100 chars of line if not a progress line
                elif line_strip:
                    tab_instance._update_processing_progress(tab_instance.processing_progress_var.get(), line_strip[:100])

            except Empty:
                break # No more lines in stdout queue

        # Process stderr queue
        while True:
            try:
                line = tab_instance._stderr_queue.get_nowait()
                line_strip = line.strip()
                tab_instance._update_log_text(line_strip)
                # Optionally parse stderr for specific errors here
            except Empty:
                break # No more lines in stderr queue

    except Exception as e:
        tab_instance.logger.error(f"Error in check_ffmpeg_output_queues: {e}", exc_info=True)
    finally:
        # Schedule the next check if the process is still running
        if tab_instance._ffmpeg_process and tab_instance._ffmpeg_process.poll() is None and tab_instance.winfo_exists():
            tab_instance.after(100, lambda: check_ffmpeg_output_queues(tab_instance)) # Check every 100ms

# Add helper function to process remaining queue output
def process_remaining_queue_output(tab_instance):
    """Processes any remaining items in the stdout/stderr queues after the process finishes."""
    tab_instance.logger.debug("Processing remaining queue output...")
    # Process stdout queue
    while True:
        try:
            line = tab_instance._stdout_queue.get_nowait()
            tab_instance._update_log_text(line.strip())
        except Empty:
            break
    # Process stderr queue
    while True:
        try:
            line = tab_instance._stderr_queue.get_nowait()
            tab_instance._update_log_text(f"ERROR: {line.strip()}")
        except Empty:
            break
    tab_instance.logger.debug("Finished processing remaining queue output.")

def task_process_video(app_controller, tab_instance, video_path, sub_path, out_path, mode, encoder, font_encoding, audio_handling, output_format):
    """
    Task to mux or hardsub using FFMPEG.
    Runs in a separate thread.
    """
    try:
        tab_instance.logger.info(f"FFMPEG task started for {os.path.basename(out_path)}")

        # TODO: Implement FFMPEG call logic here
        # You will need to build the command based on the `mode` ("mux" or "hardsub")
        # and use subprocess.Popen to run ffmpeg, parsing its output to update progress.
        # This is a very basic example, needs more development:

        # Delete output file if it already exists and user agrees (or automatically)
        if os.path.exists(out_path):
            # Must call messagebox from the main thread if possible, but here it's a background thread.
            # A safer way is to use tab_instance.after to call, but for simplicity, we accept a small risk
            # Or, if app_controller has a thread-safe method to display messagebox, that's better.
            # In this case, master=app_controller can help the dialog appear on top.
            # However, calling directly from a background thread is not ideal.
            # A better solution is to queue a task to the main thread to ask the user.
            # For now, for simplicity, we will still call directly.
            if messagebox.askyesno("Overwrite Output?",
                                   f"Output file '{os.path.basename(out_path)}' already exists. Overwrite?",
                                   parent=app_controller, # Giúp dialog có parent
                                   master=app_controller): # master để cố gắng đưa dialog lên trên
                try:
                    os.remove(out_path)
                    tab_instance.logger.info(f"Removed existing output file: {out_path}")
                except OSError as e_rm_out:
                    tab_instance.logger.error(f"Could not remove existing output file {out_path}: {e_rm_out}")
                    tab_instance._update_processing_progress(0, f"Error: Could not remove existing output: {os.path.basename(out_path)}")
                    # messagebox.showerror từ thread nền cũng không lý tưởng.
                    tab_instance.after(0, lambda: messagebox.showerror("File Error", f"Could not remove existing output file: {e_rm_out}", parent=app_controller))
                    return # Stop if deletion fails
            else:
                tab_instance._update_processing_progress(0, "Output cancelled by user (file exists).")
                tab_instance.logger.info("Video processing cancelled by user because output file exists.")
                return


        if mode == "hardsub":
            tab_instance._update_processing_progress(10, f"Encoding (hardsub)...")
            tab_instance.logger.info(f"Hardsub mode selected.")

            sub_ext = os.path.splitext(sub_path)[1].lower()
            filter_sub_path = sub_path.replace('\\', '/')
            filter_sub_path = filter_sub_path.replace(':', '\\:')

            vf_filters = f"subtitles='{filter_sub_path}'" # Base filter

            if sub_ext in ['.ass', '.ssa']:
                tab_instance.logger.info(f"Input subtitle is {sub_ext}. Using embedded style, ignoring UI settings.")
                # No force_style needed for ASS/SSA, FFMPEG uses embedded style by default
            else:
                tab_instance.logger.info(f"Input subtitle is {sub_ext}. Using UI style settings.")
                 # Map position string to alignment code
                position_map = {
                    "Bottom Center": 2, "Bottom Left": 1, "Bottom Right": 3,
                    "Top Center": 8, "Top Left": 7, "Top Right": 9
                }
                # Get alignment code from the dropdown value, default to 2 if not found
                alignment_code = position_map.get(tab_instance.hardsub_position_var.get(), 2)
                tab_instance.logger.info(f"Using hardsub alignment code from dropdown: {alignment_code}")

                # Construct the force_style string for non-ASS/SSA formats
                force_style_str = (
                    f"Fontname={tab_instance.hardsub_font_var.get()},"
                    f"FontSize={tab_instance.hardsub_size_var.get()},"
                    f"PrimaryColour={tab_instance.hardsub_color_var.get()},"
                    f"OutlineColour={tab_instance.hardsub_outline_color_var.get()},"
                    f"BorderStyle=1," # 1 for Outline+Shadow
                    f"Outline={tab_instance.hardsub_outline_var.get()},"
                    f"Shadow={tab_instance.hardsub_shadow_var.get()},"
                    f"Alignment={alignment_code}"
                )
                vf_filters += f":force_style='{force_style_str}'"


            # Add scaling filter if selected
            selected_resolution = tab_instance.hardsub_resolution_var.get()
            if selected_resolution and selected_resolution != "Original":
                if re.match(r"^\d+x\d+$", selected_resolution):
                    vf_filters += f",scale={selected_resolution}"
                else:
                    tab_instance.logger.warning(f"Invalid resolution format for scaling: {selected_resolution}. Ignoring scale filter.")

            command = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-vf", vf_filters,
                "-c:v", encoder, "-preset", "medium", "-crf", tab_instance.hardsub_crf_var.get(),
                "-c:a", audio_handling, # Use audio_handling here
                "-f", output_format, # Use output_format here
                out_path
            ]
            # Adjust audio encoding based on audio_handling option
            if audio_handling == "encode":
                 command.extend(["-c:a", "aac", "-b:a", "192k"]) # Example audio encoding
            elif audio_handling == "copy":
                 command.extend(["-c:a", "copy"]) # Copy audio

            # Remove placeholder if audio_handling is used
            if "-c:a" in command[:-1]: # Ensure it's not the last element (out_path)
                 try:
                      # Find index of "-c:a" and remove it and the next element ("aac" or "copy")
                      idx = command[:-1].index("-c:a")
                      del command[idx:idx+2] # Remove -c:a and its argument (e.g., aac or copy)
                 except ValueError:
                      pass # Already removed or not present


        elif mode == "mux":
             tab_instance._update_processing_progress(10, f"Muxing (softsub)...")
             # output_ext = os.path.splitext(out_path)[1].lower() # No longer needed, use output_format
             subtitle_codec = "srt"
             if output_format == "mp4":
                 subtitle_codec = "mov_text"

             command = [
                 "ffmpeg", "-y",
                 "-i", video_path, # Use original unquoted path
                 "-i", sub_path,   # Use original unquoted path
                 "-map", "0",      # Map all streams from first input
                 "-map", "1",      # Map all streams from second input
                 "-c", "copy",     # Copy all streams without re-encoding
                 "-c:s", subtitle_codec, # Specify subtitle codec
                 "-metadata:s:s:0", f"language={app_controller.video_audio_tab.target_translation_lang_var.get()[:3].lower() or 'und'}", # Set language for the first subtitle track
                 "-metadata:s:s:0", "title=Translated Subtitles", # Set title for the first subtitle track
                 "-f", output_format, # Specify output format explicitly
                 out_path # Use original unquoted path
             ]
        else:
            tab_instance.logger.error(f"Unknown processing mode: {mode}")
            tab_instance._update_processing_progress(0, f"Error: Unknown mode {mode}")
            return

        # Log the exact command being executed
        # Using shlex.quote for individual arguments can be more robust if paths have spaces
        # However, Popen with a list of args usually handles this well on Windows if not using shell=True
        tab_instance.logger.info(f"Preparing FFMPEG command: {command}")
        # For logging, show a more readable version:
        tab_instance.logger.info(f"Executing FFMPEG command (joined for readability): {' '.join(command)}")


        # Get video duration for progress calculation
        duration_seconds = ffmpeg_utils.get_video_duration(video_path)
        tab_instance.video_duration = duration_seconds # Store duration as instance variable
        tab_instance.logger.info(f"Input video duration: {tab_instance.video_duration if tab_instance.video_duration is not None else 'N/A'} seconds")

        startupinfo = ffmpeg_utils._get_startup_info_for_windows()
        # Capture stderr separately
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding='utf-8', errors='replace', startupinfo=startupinfo, bufsize=1)
        tab_instance._ffmpeg_process = process # Store process object

        # Start threads to read stdout and stderr
        tab_instance._stdout_thread = threading.Thread(target=enqueue_output, args=(process.stdout, tab_instance._stdout_queue), daemon=True)
        tab_instance._stderr_thread = threading.Thread(target=enqueue_output, args=(process.stderr, tab_instance._stderr_queue), daemon=True)
        tab_instance._stdout_thread.start()
        tab_instance._stderr_thread.start()
        tab_instance.logger.info("Started stdout/stderr reading threads.")

        # Start periodic check of queues in the main thread
        tab_instance.after(100, lambda: check_ffmpeg_output_queues(tab_instance)) # Start the periodic check

        # Wait for the process to finish (this will block the thread until process exits)
        final_returncode = process.wait()
        tab_instance.logger.info(f"FFMPEG process finished with return code: {final_returncode}")

        # Ensure all remaining output is processed from queues before final UI update
        tab_instance.after(0, lambda: process_remaining_queue_output(tab_instance)) # Process any lines left in queues

        is_cancelled = tab_instance.cancel_video_processing_requested

        # Ensure UI is updated correctly in the main thread based on final state
        def final_proc_ui_update_after_task():
            tab_instance._set_processing_ui_state(False) # Always re-enable buttons
            # Reset Cancel button text
            tab_instance.cancel_proc_button.config(text="Cancel Processing")

            if is_cancelled:
                tab_instance.logger.info("FFMPEG processing was explicitly cancelled.")
                tab_instance.processing_status_var.set("Processing cancelled by user.")
            elif final_returncode == 0:
                tab_instance.logger.info(f"FFMPEG processing completed successfully for: {out_path}")
                tab_instance._update_processing_progress(100, f"Success! Output: {os.path.basename(out_path)}")
                tab_instance.after(0, lambda: messagebox.showinfo("Processing Complete", f"Video processing finished successfully!\nOutput saved to: {out_path}", parent=app_controller))
            else:
                tab_instance.logger.error(f"FFMPEG processing failed for {out_path} with code {final_returncode}.")
                error_message_title = "Processing Error"
                error_message_content = f"FFMPEG processing failed with exit code {final_returncode}.\n\n"
                # Check if command exists before attempting to join it
                if 'command' in locals() and command:
                    error_message_content += f"Command executed:\n{' '.join(command)}\n\n"
                error_message_content += "Please check the 'FFmpeg Output' log area above for details on the error.\n"
                error_message_content += "Common issues: invalid input/output paths, incorrect hardsub options, corrupted input files."

                tab_instance._update_processing_progress(tab_instance.processing_progress_var.get(), f"Processing failed (code {final_returncode}).")
                tab_instance.after(0, lambda title=error_message_title, msg=error_message_content:
                           show_scrollable_messagebox(app_controller, title, msg, tab_instance.default_font_family, tab_instance.default_font_size))

            # tab_instance._update_speed_label("N/A") # Remove speed update if it exists

        # Schedule the final UI update on the main thread
        tab_instance.after(0, final_proc_ui_update_after_task)


    except FileNotFoundError as e_fnf:
        tab_instance.logger.error(f"FFMPEG command not found: {e_fnf}. Ensure FFMPEG is installed and in PATH.", exc_info=True)
        tab_instance._update_processing_progress(0, f"Error: FFMPEG not found. {e_fnf}")
        # tab_instance._update_speed_label("N/A") # Remove speed update
        tab_instance.after(0, lambda: messagebox.showerror("FFMPEG Error", "FFMPEG command not found. Please ensure FFMPEG is installed and in your system's PATH.", parent=app_controller))
    except Exception as e:
        # Only log/report unexpected errors if cancellation was NOT requested
        if not tab_instance.cancel_video_processing_requested:
            tab_instance.logger.error(f"Unexpected error during video processing task: {e}", exc_info=True)
            tab_instance._update_processing_progress(0, f"Unexpected Error: {str(e)[:100]}")
            # tab_instance._update_speed_label("N/A") # Remove speed update
            tab_instance.after(0, lambda err=e: messagebox.showerror("Processing Error", f"An unexpected error occurred: {err}", parent=app_controller))
        else:
             # If cancelled, log the exception as info/debug, not an error, to avoid confusion
             tab_instance.logger.info(f"Exception during cancelled processing task: {e}", exc_info=True)
    finally:
        # Ensure threads are joined or handled if still running (daemon=True helps with this on app exit)
        # Clean up process reference
        tab_instance._ffmpeg_process = None
        # Queues are handled by daemon threads, they should clean up on program exit.
        # No need to explicitly clear them here.

        # The final UI update is now scheduled *after* process.wait() in the main try block,
        # ensuring it happens only once and after the process truly finishes or is cancelled.
        pass # No need for another final UI update here
