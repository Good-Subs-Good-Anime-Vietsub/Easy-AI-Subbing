import tkinter as tk
from tkinter import messagebox
import logging
import os
import threading
import time
import textwrap
import srt

from core import config_manager, ffmpeg_utils, gemini_utils, srt_utils
from .ui_utils import ToolTip, show_scrollable_messagebox

logger = logging.getLogger(__name__)

# Placeholder for task functions that will be moved here
# def task_initial_gemini_processing(...):
#     pass

# def task_analyze_timestamps_python_only(...):
#     pass

# def task_refine_timing(...):
#     pass

# def task_request_gemini_fix(...):
#     pass

def task_analyze_timestamps_python_only(app_controller, tab_instance, subtitle_text_to_analyze):
    """
    Task to perform detailed subtitle timestamp analysis using Python (srt_utils).
    Runs in a separate thread.
    """
    try:
        tab_instance.logger.info(f"Analyzing subtitle content (first 200 chars):\n{subtitle_text_to_analyze[:200]}...\n")
        raw_lines = subtitle_text_to_analyze.splitlines()
        tab_instance.last_detailed_analysis_messages = srt_utils.detailed_analyze_gemini_output(raw_lines)
        corrected_lines_list_by_python, norm_log_messages = srt_utils.analyze_and_pre_correct_gemini_lines_for_srt(raw_lines)
        tab_instance.suggested_auto_format_text = "\n".join(corrected_lines_list_by_python)
        actionable_issues_for_user_messagebox = []
        if tab_instance.last_detailed_analysis_messages:
            tab_instance.logger.info("--- Detailed Subtitle Analysis (All Findings) ---")
            for msg in tab_instance.last_detailed_analysis_messages:
                tab_instance.logger.info(f"- {msg}")
                if "ERROR" in msg.upper() or "WARNING" in msg.upper():
                    actionable_issues_for_user_messagebox.append(msg)
        tab_instance.after(0, lambda: tab_instance.review_auto_format_button.config(state=tk.DISABLED))
        if norm_log_messages:
            tab_instance.logger.info("--- Auto-Formatting Attempt Log (Python Pre-correction) ---")
            for log_msg in norm_log_messages: tab_instance.logger.info(f"  {log_msg}")
            original_text_for_compare = "\n".join(raw_lines)
            if tab_instance.suggested_auto_format_text.strip() != original_text_for_compare.strip():
                tab_instance.logger.info("Auto-formatter has generated a version with attempted corrections.")
                tab_instance.after(0, lambda: tab_instance.review_auto_format_button.config(state=tk.NORMAL))
        if not actionable_issues_for_user_messagebox:
            tab_instance.logger.info("Timestamp Analysis: No critical timestamp/format issues (errors/warnings) found by Python analysis.")
            tab_instance.after(0, lambda: messagebox.showinfo("Timestamp Analysis", "No critical timestamp/format issues detected by Python analysis.", parent=app_controller))
            tab_instance.after(0, lambda: tab_instance.request_gemini_fix_button.config(state=tk.DISABLED))
        else:
            tab_instance.logger.warning("Timestamp Analysis Report: Potential critical issues found by Python analysis.")
            error_report_text_for_display = ""
            for i, msg in enumerate(actionable_issues_for_user_messagebox):
                if i < 15:
                    error_report_text_for_display += f"- {msg}\n"
            if len(actionable_issues_for_user_messagebox) > 15:
                error_report_text_for_display += f"\n... and {len(actionable_issues_for_user_messagebox) - 15} more items. Check tab log for full details."
            if len(actionable_issues_for_user_messagebox) > 7 :
                 tab_instance.after(0, lambda title="Timestamp Analysis Report", message=error_report_text_for_display: \
                            show_scrollable_messagebox(app_controller, title, message, tab_instance.default_font_family, tab_instance.default_font_size))
            else:
                 tab_instance.after(0, lambda: messagebox.showwarning("Timestamp Analysis Report", "Potential critical issues found:\n\n" + error_report_text_for_display, parent=app_controller))
            prompt_gemini_fix = messagebox.askyesno("Request Gemini Fix?", f"{len(actionable_issues_for_user_messagebox)} issue(s) found. Enable 'Request Gemini Fix' to send these issues to Gemini?", parent=app_controller)
            if prompt_gemini_fix:
                tab_instance.after(0, lambda: tab_instance.request_gemini_fix_button.config(state=tk.NORMAL))
            else:
                tab_instance.after(0, lambda: tab_instance.request_gemini_fix_button.config(state=tk.DISABLED))
    except Exception as e:
        tab_instance.logger.error(f"Error in detailed timestamp analysis task: {e}", exc_info=True)
        tab_instance.after(0, lambda err=e: messagebox.showerror("Analysis Error", f"Error during timestamp analysis: {err}", parent=app_controller))
    finally:
        tab_instance.after(0, tab_instance._set_ui_state, False)
        current_content_in_editor = ""
        if hasattr(tab_instance, 'subtitle_edit_text_widget') and tab_instance.subtitle_edit_text_widget.winfo_exists():
            current_content_in_editor = tab_instance.subtitle_edit_text_widget.get("1.0", tk.END).strip()
        if current_content_in_editor:
             tab_instance.after(0, lambda: tab_instance._populate_subtitle_edit_area(current_content_in_editor, make_editable=True))
        else:
             if hasattr(tab_instance, "edit_mode_label") and tab_instance.edit_mode_label_packed:
                try: tab_instance.edit_mode_label.pack_forget()
                except tk.TclError: pass
                tab_instance.edit_mode_label_packed = False

def task_refine_timing(app_controller, tab_instance, subtitle_text_to_refine):
    """
    Task to refine subtitle timing (gaps/overlaps) using Python (srt_utils).
    Runs in a separate thread.
    """
    try:
        tab_instance.logger.info("Starting timing refinement process...")
        tab_instance._update_progress(10, "Converting to SRT for refinement...")
        standard_srt_content_str, conversion_errors = srt_utils.convert_gemini_format_to_srt_content(
            subtitle_text_to_refine, apply_python_normalization=True
        )
        if tab_instance.cancel_requested: tab_instance.logger.info("Timing refinement cancelled during SRT conversion."); return
        if conversion_errors:
            tab_instance.logger.warning("--- Issues during conversion to standard SRT for timing refinement ---")
            for err_msg in conversion_errors: tab_instance.logger.warning(f"  {err_msg}")
            if any("ERROR" in msg.upper() for msg in conversion_errors) or not standard_srt_content_str.strip():
                tab_instance.after(0, lambda: messagebox.showerror("Refinement Error", "Could not convert text to a valid SRT format for refinement. Check tab log for details.", parent=app_controller))
                return
        if not standard_srt_content_str.strip():
            tab_instance.logger.warning("No valid SRT content to refine timings after conversion.")
            tab_instance.after(0, lambda: messagebox.showinfo("Timing Refinement", "No valid subtitle data could be parsed to refine timings.", parent=app_controller))
            return
        tab_instance._update_progress(30, "Parsing standardized SRT...")
        try:
            original_subs_list = list(srt.parse(standard_srt_content_str))
        except srt.SRTParseError as e_srt_parse:
            tab_instance.logger.error(f"SRT Parse Error during timing refinement: {e_srt_parse}")
            tab_instance.after(0, lambda err=e_srt_parse: messagebox.showerror("Timing Refinement Error", f"Could not parse subtitles for refinement.\nDetails: {err}", parent=app_controller))
            return
        if tab_instance.cancel_requested: tab_instance.logger.info("Timing refinement cancelled after SRT parsing."); return
        if not original_subs_list:
            tab_instance.logger.warning("No subtitles parsed for timing refinement.")
            tab_instance.after(0, lambda: messagebox.showinfo("Timing Refinement", "No subtitles parsed to refine.", parent=app_controller))
            return
        tab_instance._update_progress(50, "Applying timing refinement rules...")
        refined_subs_list, change_logs = srt_utils.refine_subtitle_timing(original_subs_list)
        if tab_instance.cancel_requested: tab_instance.logger.info("Timing refinement cancelled after applying rules."); return
        tab_instance._update_progress(80, "Reformatting refined subs back to Gemini format...")
        refined_gemini_format_lines = []
        for sub_obj in refined_subs_list:
            start_str = srt_utils.format_timedelta_to_gemini_style(sub_obj.start)
            end_str = srt_utils.format_timedelta_to_gemini_style(sub_obj.end)
            content_for_gemini_line = sub_obj.content.replace('\n', ' ')
            refined_gemini_format_lines.append(f"[{start_str} - {end_str}] {content_for_gemini_line}")
        refined_output_for_editor = "\n".join(refined_gemini_format_lines)
        if change_logs:
            tab_instance.logger.info("--- Timing Refinement Log ---")
            for log_entry in change_logs: tab_instance.logger.info(f"  {log_entry}")
            if subtitle_text_to_refine.strip() == refined_output_for_editor.strip() :
                 tab_instance.logger.info("Timing refinement: no actual content changes after re-formatting to Gemini style.")
                 tab_instance.after(0, lambda: messagebox.showinfo("Timing Refinement", "No significant timing changes were applied or needed.", parent=app_controller))
            else:
                tab_instance.logger.info("Subtitle timings refined. Asking user to review/apply the changes.")
                tab_instance.after(0, tab_instance._show_review_dialog_generic,
                           subtitle_text_to_refine,
                           refined_output_for_editor,
                           "Review Refined Timings",
                           "Refined Timing Version (Gemini Format)",
                           "timing_refinement")
        else:
            tab_instance.logger.info("No timing adjustments made by refinement rules.")
            tab_instance.after(0, lambda: messagebox.showinfo("Timing Refinement", "No timing adjustments were necessary.", parent=app_controller))
        tab_instance._update_progress(100, "Timing refinement complete.")
    except Exception as e:
        if not tab_instance.cancel_requested:
            tab_instance.logger.error(f"Error during timing refinement: {e}", exc_info=True)
            tab_instance.after(0, lambda err=e: messagebox.showerror("Timing Refinement Error", f"An error occurred: {err}", parent=app_controller))
        tab_instance._update_progress(100, "Timing refinement failed or cancelled.")
    finally:
        if not tab_instance.cancel_requested:
            tab_instance.after(0, tab_instance._set_ui_state, False)

def task_request_gemini_fix(app_controller, tab_instance, custom_correction_prompt):
    """
    Task to send a custom prompt to Gemini for subtitle correction.
    Runs in a separate thread.
    """
    try:
        tab_instance.logger.info("TASK: Sending custom correction prompt to Gemini...")
        tab_instance._update_progress(10, "Preparing custom prompt for Gemini fix...")
        if tab_instance.cancel_requested: tab_instance.logger.info("Cancelled before sending fix request to Gemini."); return
        tab_instance._update_progress(30, "Sending fix request to Gemini...")
        temperature_for_fix = tab_instance.gemini_temperature_var.get()
        correction_text_part = gemini_utils.to_part(custom_correction_prompt)
        response_text_fixed = gemini_utils.send_message_to_chat(tab_instance.current_chat_session, [correction_text_part], temperature_for_fix)
        if tab_instance.cancel_requested: tab_instance.logger.info("Cancelled after Gemini fix response."); return
        if response_text_fixed is None or response_text_fixed.startswith(("[Error]", "[Blocked]")):
            tab_instance.logger.error(f"Gemini fix request API call failed/blocked. Response: {response_text_fixed}")
            tab_instance.after(0, lambda resp=response_text_fixed: messagebox.showerror("Gemini API Error", f"Gemini processing failed or was blocked.\nDetails: {resp}", parent=app_controller))
        else:
            tab_instance.logger.info("Received fixed response from Gemini (custom prompt).")
            tab_instance.after(0, lambda text=response_text_fixed.strip(): tab_instance._populate_subtitle_edit_area(text, make_editable=True))
            tab_instance.after(0, lambda: messagebox.showinfo("Gemini Custom Fix Complete", "Gemini attempted to apply corrections based on your prompt. Please review the output and run 'Analyze Timestamps' again.", parent=app_controller))
        tab_instance._update_progress(100, "Gemini custom fix attempt complete.")
    except Exception as e:
        if not tab_instance.cancel_requested:
            tab_instance.logger.error(f"Critical error in task_request_gemini_fix: {e}", exc_info=True)
            tab_instance.after(0, lambda err=e: messagebox.showerror("Critical Error", f"An unexpected error occurred during Gemini fix request: {err}. Check logs.", parent=app_controller))
    finally:
        tab_instance.after(0, tab_instance._set_ui_state, False)
        if hasattr(tab_instance, 'request_gemini_fix_button'):
            tab_instance.after(0, lambda: tab_instance.request_gemini_fix_button.config(state=tk.DISABLED))
        if tab_instance.cancel_requested:
            tab_instance.logger.info("Gemini custom fix process was cancelled by user.")
