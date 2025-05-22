# EasyAISubbing/app_gui/subtitle_translate_tab.py
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import logging
import threading
from app_gui.ui_utils import ToolTip
import os
import textwrap # For prompt templates
import tkinter.simpledialog # Import simpledialog for track selection

DND_TAB_SUPPORTED = False # Initialize DND support flag
# Try importing tkinterdnd2
try:
    from tkinterdnd2 import DND_FILES # Only need DND_FILES for drop_target_register
    DND_TAB_SUPPORTED = True
except ImportError:
    DND_TAB_SUPPORTED = False

# --- Imports for core modules ---
import re # Import the regex module
from core import config_manager
from core import gemini_utils
from core import subtitle_parser

logger = logging.getLogger(__name__) # Will be app_gui.subtitle_translate_tab

# Common language list, can be shared or defined separately
COMMON_LANGUAGES_FOR_TRANSLATION = [
    "English", "Vietnamese", "Japanese", "Chinese (Simplified)", "Spanish",
    "French", "German", "Korean", "Russian", "Portuguese (Brazilian)",
    "Italian", "Hindi", "Arabic", "Turkish", "Polish", "Dutch"
]

# Common translation style list
COMMON_TRANSLATION_STYLES = [
    "Default/Neutral", "Formal", "Informal/Colloquial", "Humorous",
    "Serious/Academic", "Poetic", "Anime/Manga",
    "Historical/Archaic", "Technical"
]


SUBTITLE_TRANSLATION_PROMPT_TEMPLATE = textwrap.dedent("""\
    You are a professional translator. Your task is to translate the following subtitle text segments from {source_lang_for_prompt} into {target_lang}.
    {style_instruction}
    Contextual Keywords (for terminology guidance in {target_lang}, if applicable): [{keywords_string_formatted}]

    Translate ALL of the following segments. Each original segment is prefixed with "[Segment X]:" where X is its original number.
    CRITICAL: Respond ONLY with the translated segments. Each translated segment MUST start with its corresponding "[Segment X]:" marker (where X is the original segment number) and each translated segment MUST be on a new line. You MUST return EXACTLY {expected_translated_segments_count} translated segments, each starting with its "[Segment X]:" marker.
    Do NOT add any numbering, additional prefixes, explanations, or any text other than the translated segments and their "[Segment X]:" markers.

    Segments to Translate:
    ---
    {all_segments_to_translate_text}
    ---

    Your Translated Segments (MUST be {expected_translated_segments_count} segments, each starting with its [Segment X]: marker, each on a new line):
    """)


class SubtitleTranslateTab(ttk.Frame):
    def __init__(self, parent_notebook, app_controller):
        super().__init__(parent_notebook)
        self.app_controller = app_controller
        self.logger = logging.getLogger(f"app_gui.{__name__}")

        # --- Style and Font (inherited from app_controller) ---
        self.default_font_family = self.app_controller.default_font_family
        self.default_font_size = self.app_controller.default_font_size
        self.custom_font = self.app_controller.custom_font

        # --- Tab-specific State Variables ---
        self.current_subtitle_file_path = None
        self.loaded_subs_object = None
        self.original_timing_info = []
        self.translated_subs_object = None
        self.cancel_translation_requested = False

        # --- Tkinter Variables for THIS TAB's UI Settings ---
        self.subtitle_file_var = tk.StringVar()
        self.source_language_var = tk.StringVar()
        self.target_language_var = tk.StringVar()

        # Gemini settings specific to this tab (API Key is managed globally in MainWindow)
        self.gemini_model_var = tk.StringVar()
        self.gemini_temperature_var = tk.DoubleVar()
        self.gemini_temperature_display_var = tk.StringVar() # For displaying rounded temp
        self.translation_style_var = tk.StringVar()
        # self.context_keywords_content = tk.StringVar() # Not needed, tk.Text has its own storage

        self.processing_status_var = tk.StringVar(value="Idle.")
        self.processing_progress_var = tk.DoubleVar(value=0)

        # --- Load Settings for this tab ---
        self._load_settings()

        # --- Build Tab UI ---
        self._init_tab_ui()

        if DND_TAB_SUPPORTED:
            # Register the main frame as a drop target for files
            main_frame = self.children.get('!frame') # Assuming the main frame is named '!frame'
            if main_frame:
                 main_frame.drop_target_register(DND_FILES) # Option 2: Main frame as drop zone
                 main_frame.dnd_bind('<<Drop>>', self._handle_drop_event)
                 self.logger.info("Drag and drop target registered for SubtitleTranslateTab.")
            else:
                 self.logger.warning("Could not find main_frame for D&D registration in SubtitleTranslateTab.")
        else:
            self.logger.warning("Drag and drop for SubtitleTranslateTab disabled (tkinterdnd2 missing).")


        self.logger.info("SubtitleTranslateTab UI initialized.")
    def _round_to_nearest_005(self, value):
        return round(value / 0.05) * 0.05

    def _update_gemini_temp_display_and_round(self, scale_value_str):
        try:
            current_scale_val = float(scale_value_str)
            rounded_val = self._round_to_nearest_005(current_scale_val)
            if abs(self.gemini_temperature_var.get() - rounded_val) > 0.0001:
                 self.gemini_temperature_var.set(rounded_val)
            self.gemini_temperature_display_var.set(f"{rounded_val:.2f}")
        except (tk.TclError, ValueError) as e:
            self.logger.debug(f"Error updating temp display for subtitle tab: {e}")


    def _load_settings(self):
        """Loads settings specifically for the Subtitle Translation tab."""
        # API Key is managed globally in MainWindow, no need to load here.
        # For model, temp, style: load settings specific to this tab's purpose or shared defaults
        self.gemini_model_var.set(config_manager.load_setting("subtitle_gemini_model", "gemini-1.5-pro-latest"))

        loaded_temp = config_manager.load_setting("subtitle_gemini_temperature", 0.3) # Default for translation
        try:
            rounded_initial_temp = self._round_to_nearest_005(float(loaded_temp))
        except ValueError:
            rounded_initial_temp = self._round_to_nearest_005(0.3) # Fallback
        self.gemini_temperature_var.set(rounded_initial_temp)
        self.gemini_temperature_display_var.set(f"{rounded_initial_temp:.2f}")


        self.translation_style_var.set(config_manager.load_setting("subtitle_translation_style", "Default/Neutral"))

        self.source_language_var.set(config_manager.load_setting("subtitle_source_language", "auto"))
        self.target_language_var.set(config_manager.load_setting("subtitle_target_language", "English"))

        self.logger.info("Subtitle Translation tab specific settings loaded.")

    def _save_settings(self):
        """Saves current settings of the Subtitle Translation tab to config."""
        # API key is saved globally by VideoAudioTab, no need to save here again if using shared key
        config_manager.save_setting("subtitle_gemini_model", self.gemini_model_var.get())
        config_manager.save_setting("subtitle_gemini_temperature", str(self.gemini_temperature_var.get()))
        config_manager.save_setting("subtitle_translation_style", self.translation_style_var.get())
        config_manager.save_setting("subtitle_source_language", self.source_language_var.get())
        config_manager.save_setting("subtitle_target_language", self.target_language_var.get())
        if hasattr(self, 'context_keywords_text'):
            config_manager.save_setting("subtitle_context_keywords", self.context_keywords_text.get("1.0", tk.END).strip())
        self.logger.info("Subtitle Translation tab specific settings saved.")


    def _init_tab_ui(self):
        # Use a main frame directly within the tab
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.columnconfigure(1, weight=1)

        current_row = 0

        # --- Input Subtitle File ---
        input_file_frame = ttk.LabelFrame(main_frame, text="Input Subtitle", padding="5")
        input_file_frame.grid(row=current_row, column=0, columnspan=3, sticky=tk.EW, padx=5, pady=5)
        input_file_frame.columnconfigure(1, weight=1)
        ttk.Label(input_file_frame, text="Subtitle File (SRT/VTT/ASS/SSA):").grid(row=0, column=0, sticky=tk.W, padx=5, pady=3)
        self.subtitle_file_entry = ttk.Entry(input_file_frame, textvariable=self.subtitle_file_var, width=70, state="readonly")
        self.subtitle_file_entry.grid(row=0, column=1, sticky=tk.EW, padx=5, pady=3)
        # Add tooltip for subtitle_file_entry
        ToolTip(self.subtitle_file_entry, "Displays the path to the selected subtitle file.")

        self.browse_subtitle_button = ttk.Button(input_file_frame, text="Browse...", command=self._browse_subtitle_file)
        self.browse_subtitle_button.grid(row=0, column=2, sticky=tk.E, padx=5, pady=3)
        ToolTip(self.browse_subtitle_button, "Browse for a subtitle file (SRT, VTT, ASS, SSA).")

        note_label = ttk.Label(input_file_frame, text="Note: ASS/SSA formatting tags will be removed before translation. Styling info is preserved.",
                           font=(self.default_font_family, self.default_font_size -1), foreground="grey"
                          )
        note_label.grid(row=1, column=0, columnspan=3, sticky=tk.W, padx=7, pady=(0,3))
        ToolTip(note_label, "Note regarding ASS/SSA file processing: Formatting tags like {\\b1} are removed before sending text to Gemini. Original styling information is preserved for reassembly.")

        current_row += 1
        # --- Language Settings ---
        lang_frame = ttk.LabelFrame(main_frame, text="Language Settings", padding="10")
        lang_frame.grid(row=current_row, column=0, columnspan=3, sticky=tk.EW, padx=5, pady=10)
        lang_frame.columnconfigure(1, weight=1); lang_frame.columnconfigure(3, weight=1)
        ttk.Label(lang_frame, text="Source Language:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        self.source_language_combobox = ttk.Combobox(lang_frame, textvariable=self.source_language_var, values=["auto"] + COMMON_LANGUAGES_FOR_TRANSLATION, width=20, state="normal")
        self.source_language_combobox.grid(row=0, column=1, sticky=tk.EW, padx=5, pady=5)
        ToolTip(ttk.Label(lang_frame, text="Source Language:"), "Select the source language of the subtitle. Use 'auto' for automatic detection.")
        ToolTip(self.source_language_combobox, "Select the source language of the subtitle. Use 'auto' for automatic detection.")
        self.source_language_combobox.bind("<<ComboboxSelected>>", self._handle_combobox_selection_visual_reset)

        ttk.Label(lang_frame, text="Target Language:").grid(row=0, column=2, sticky=tk.W, padx=5, pady=5)
        self.target_language_combobox = ttk.Combobox(lang_frame, textvariable=self.target_language_var, values=COMMON_LANGUAGES_FOR_TRANSLATION, width=20, state="normal")
        self.target_language_combobox.grid(row=0, column=3, sticky=tk.EW, padx=5, pady=5)
        self.target_language_combobox.bind("<<ComboboxSelected>>", self._handle_combobox_selection_visual_reset)
        ToolTip(ttk.Label(lang_frame, text="Target Language:"), "Select the desired output language for translation.")
        ToolTip(self.target_language_combobox, "Select the desired output language for translation.")

        current_row += 1
        # --- Gemini Settings (Specific to this tab) ---
        gemini_settings_frame = ttk.LabelFrame(main_frame, text="Gemini Settings for Translation", padding="10")
        gemini_settings_frame.grid(row=current_row, column=0, columnspan=3, sticky=tk.EW, padx=5, pady=10)
        gemini_settings_frame.columnconfigure(1, weight=1)
        # Model
        ttk.Label(gemini_settings_frame, text="Gemini Model:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=3)
        self.gemini_model_combo = ttk.Combobox(gemini_settings_frame, textvariable=self.gemini_model_var, width=30, state="readonly")
        self.gemini_model_combo.grid(row=0, column=1, sticky=tk.EW, padx=5, pady=3)
        self.gemini_model_combo.bind("<<ComboboxSelected>>", self._handle_combobox_selection_visual_reset)
        ToolTip(ttk.Label(gemini_settings_frame, text="Gemini Model:"), "Select the Gemini model to use for translation.")
        ToolTip(self.gemini_model_combo, "Select the Gemini model to use for translation.")
        self.refresh_models_button = ttk.Button(gemini_settings_frame, text="Refresh Models", command=self._load_gemini_models_for_tab)
        self.refresh_models_button.grid(row=0, column=2, padx=5, pady=3, sticky=tk.W)
        self._load_gemini_models_for_tab() # Load models on init
        ToolTip(self.refresh_models_button, "Refresh the list of available Gemini models.")

        # Temperature
        ttk.Label(gemini_settings_frame, text="Temperature:").grid(row=0, column=3, sticky=tk.W, padx=(15,2), pady=3)
        self.gemini_temp_scale = ttk.Scale(gemini_settings_frame, from_=0.0, to=2.0, orient=tk.HORIZONTAL,
                                         variable=self.gemini_temperature_var, length=120,
                                         command=self._update_gemini_temp_display_and_round)
        ToolTip(ttk.Label(gemini_settings_frame, text="Temperature:"), "Controls the randomness of the Gemini model's output. Lower values are less random, higher values are more creative. Rounded to 0.05.")
        ToolTip(self.gemini_temp_scale, "Controls the randomness of the Gemini model's output. Lower values are less random, higher values are more creative. Rounded to 0.05.")
        self.gemini_temp_scale.grid(row=0, column=4, sticky=tk.EW, padx=0, pady=3)
        self.gemini_temp_label_val = ttk.Label(gemini_settings_frame, textvariable=self.gemini_temperature_display_var, width=4)
        self.gemini_temp_label_val.grid(row=0, column=5, sticky=tk.W, padx=(2,5), pady=3)
        # Add tooltip for gemini_temp_label_val
        ToolTip(self.gemini_temp_label_val, "The current value of the Gemini model's Temperature parameter.")


        # Translation Style
        ttk.Label(gemini_settings_frame, text="Translation Style:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=3)
        self.translation_style_combo = ttk.Combobox(gemini_settings_frame, textvariable=self.translation_style_var, values=COMMON_TRANSLATION_STYLES, width=30)
        self.translation_style_combo.grid(row=1, column=1, sticky=tk.EW, padx=5, pady=3)
        ToolTip(ttk.Label(gemini_settings_frame, text="Translation Style:"), "Optional: Specify a desired translation style or tone.")
        ToolTip(self.translation_style_combo, "Optional: Specify a desired translation style or tone.")
        self.translation_style_combo.bind("<<ComboboxSelected>>", self._handle_combobox_selection_visual_reset)


        # Context Keywords
        ttk.Label(gemini_settings_frame, text="Context Keywords\n(for translation):").grid(row=2, column=0, sticky=tk.NW, padx=5, pady=5)
        self.context_keywords_text = tk.Text(gemini_settings_frame, height=2, width=50, relief=tk.SOLID, borderwidth=1, font=self.custom_font)
        self.context_keywords_text.grid(row=2, column=1, columnspan=3, sticky=tk.EW, padx=5, pady=5)
        ToolTip(ttk.Label(gemini_settings_frame, text="Context Keywords\n(for translation):"), "Enter keywords (names, terms, etc.) that Gemini should use for translation. One keyword or phrase per line.")
        ToolTip(self.context_keywords_text, "Enter keywords (names, terms, etc.) that Gemini should use for translation. One keyword or phrase per line.")
        self.context_keywords_text.insert("1.0", config_manager.load_setting("subtitle_context_keywords", ""))


        current_row += 1
        # --- Action Buttons ---
        action_button_frame = ttk.Frame(main_frame)
        action_button_frame.grid(row=current_row, column=0, columnspan=3, pady=(10,0), sticky=tk.EW) # Adjusted pady
        action_button_frame.columnconfigure(0, weight=1); action_button_frame.columnconfigure(1, weight=1)
        self.translate_button = ttk.Button(action_button_frame, text="Start Translation", command=self._start_translation_process, state="disabled")
        self.translate_button.grid(row=0, column=0, padx=(0,5), sticky=tk.EW)
        ToolTip(self.translate_button, "Start the subtitle translation process using the selected Gemini model and settings.")

        self.cancel_button = ttk.Button(action_button_frame, text="Cancel", command=self._request_cancellation, state="disabled")
        self.cancel_button.grid(row=0, column=1, padx=(5,0), sticky=tk.EW)
        # Add tooltip for cancel_button
        ToolTip(self.cancel_button, "Cancel the running subtitle translation process.")


        current_row += 1
        # --- Progress Bar and Status ---
        self.progress_bar = ttk.Progressbar(main_frame, variable=self.processing_progress_var, maximum=100)
        self.progress_bar.grid(row=current_row, column=0, columnspan=3, sticky=tk.EW, padx=5, pady=5)
        # Add tooltip for progress_bar
        ToolTip(self.progress_bar, "Displays the overall progress of the translation process.")

        current_row += 1
        self.status_label = ttk.Label(main_frame, textvariable=self.processing_status_var)
        self.status_label.grid(row=current_row, column=0, columnspan=3, sticky=tk.W, padx=5, pady=5)
        # Add tooltip for status_label
        ToolTip(self.status_label, "Displays the current status of the translation process (e.g., Translating batch X, Preparing...).")

        current_row += 1
        # --- Save Button (Moved Down) ---
        self.save_translated_button = ttk.Button(main_frame, text="Save Translated Subtitle", command=self._save_translated_subtitle, state="disabled")
        self.save_translated_button.grid(row=current_row, column=0, columnspan=3, pady=(10,0), padx=5, sticky=tk.EW) # Moved down
        # Add tooltip for save_translated_button
        ToolTip(self.save_translated_button, "Save the translated subtitle content to a new file.")

        current_row += 1 # Increment row after placing save button

        # --- Subtitle Display Areas ---
        subtitle_panes = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        subtitle_panes.grid(row=current_row, column=0, columnspan=3, sticky=tk.NSEW, padx=5, pady=10)
        main_frame.rowconfigure(current_row, weight=1) # Give weight to the row containing subtitle panes
        original_frame = ttk.LabelFrame(subtitle_panes, text="Original Subtitles (Plain Text)", padding="5")
        self.original_subtitle_text = tk.Text(original_frame, wrap=tk.WORD, state="disabled", font=self.custom_font, relief=tk.SOLID, borderwidth=1, padx=2, pady=2)
        original_scrollbar_y = ttk.Scrollbar(original_frame, orient=tk.VERTICAL, command=self.original_subtitle_text.yview)
        self.original_subtitle_text.config(yscrollcommand=original_scrollbar_y.set)
        original_scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y); self.original_subtitle_text.pack(fill=tk.BOTH, expand=True)
        # Add tooltip for original_subtitle_text
        ToolTip(self.original_subtitle_text, "Displays the content of the loaded original subtitles with line numbers. This content cannot be edited directly.")


        subtitle_panes.add(original_frame, weight=1)
        translated_frame = ttk.LabelFrame(subtitle_panes, text="Translated Subtitles (Plain Text)", padding="5")
        self.translated_subtitle_text = tk.Text(translated_frame, wrap=tk.WORD, state="disabled", font=self.custom_font, relief=tk.SOLID, borderwidth=1, padx=2, pady=2)
        translated_scrollbar_y = ttk.Scrollbar(translated_frame, orient=tk.VERTICAL, command=self.translated_subtitle_text.yview)
        self.translated_subtitle_text.config(yscrollcommand=translated_scrollbar_y.set)
        translated_scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y); self.translated_subtitle_text.pack(fill=tk.BOTH, expand=True)
        # Add tooltip for translated_subtitle_text
        ToolTip(self.translated_subtitle_text, "Displays the content of the translated subtitles with line numbers. This content will be updated after the translation process is complete.")

        subtitle_panes.add(translated_frame, weight=1)
        def _sync_scroll_original(*args):
            if self.translated_subtitle_text.winfo_exists(): self.translated_subtitle_text.yview_moveto(args[0])
            original_scrollbar_y.set(*args)
        def _sync_scroll_translated(*args):
            if self.original_subtitle_text.winfo_exists(): self.original_subtitle_text.yview_moveto(args[0])
            translated_scrollbar_y.set(*args)
        self.original_subtitle_text.config(yscrollcommand=_sync_scroll_original)
        self.translated_subtitle_text.config(yscrollcommand=_sync_scroll_translated)

        self._set_ui_state(False)


    def _load_gemini_models_for_tab(self):
        """Loads Gemini models specifically for this tab's combobox."""
        # Get the global API key from the main window controller
        current_api_key = self.app_controller.api_key_var.get()
        if not current_api_key:
            self.logger.warning("Gemini API Key not set in main application settings. Cannot load models from API.")
            # Use fallback directly from gemini_utils if key is missing
            models_info = gemini_utils.list_available_models() # This will use its internal fallback
        elif not gemini_utils.configure_api(current_api_key):
            self.logger.error("Failed to configure Gemini API with the key for Subtitle Tab. Using fallback models.")
            models_info = gemini_utils.list_available_models() # This will use its internal fallback
        else:
            self.logger.info("Fetching available Gemini models for Subtitle Translation Tab...")
            models_info = gemini_utils.list_available_models()

        if models_info:
            model_names = [m['name'] for m in models_info] # Get 'models/model-name'
            self.gemini_model_combo['values'] = model_names
            # Set selection based on saved or default
            saved_model = config_manager.load_setting("subtitle_gemini_model")
            if saved_model and saved_model in model_names:
                self.gemini_model_var.set(saved_model)
            elif self.gemini_model_var.get() and self.gemini_model_var.get() in model_names:
                pass # Already set and valid
            elif "gemini-1.5-pro-latest" in model_names: # Preferred default
                self.gemini_model_var.set("gemini-1.5-pro-latest")
            elif "gemini-1.5-flash-latest" in model_names: # Secondary default
                self.gemini_model_var.set("gemini-1.5-flash-latest")
            elif model_names: # Fallback to first available
                self.gemini_model_var.set(model_names[0])
            else:
                self.gemini_model_var.set("") # No models available
            self.logger.info(f"Subtitle Tab Gemini models updated. Selected: {self.gemini_model_var.get() or 'None'}")
        else:
            self.logger.error("Could not fetch or find any Gemini models for Subtitle Tab (even fallback failed).")
            self.gemini_model_combo['values'] = []
            self.gemini_model_var.set("")

    def _handle_combobox_selection_visual_reset(self, event):
        widget = event.widget
        def clear_highlight():
            if widget.winfo_exists():
                widget.selection_clear()
                parent_frame_name = widget.winfo_parent()
                if parent_frame_name:
                    try: widget.nametowidget(parent_frame_name).focus_set()
                    except Exception: self.focus_set()
                else: self.focus_set()
        widget.after(10, clear_highlight)

    def _handle_drop_event(self, event):
        """Handles files dropped onto the tab."""
        if not DND_TAB_SUPPORTED: return # Should not happen if tkinterdnd2 is missing

        # Call the shared helper function
        from . import media_input_helpers # Import locally to avoid circular dependency
        media_input_helpers.handle_dropped_file_for_tab(event.data, self, self.app_controller)

    def _process_dropped_file(self, filepath, source="drag-drop"):
        """Processes the file path received from a drag and drop event."""
        if not filepath or not os.path.exists(filepath) or not os.path.isfile(filepath):
            self.logger.error(f"Invalid or non-existent file path provided for processing: {filepath} (source: {source})")
            display_filename = os.path.basename(filepath or "unknown file")
            messagebox.showerror("File Error", f"Selected file '{display_filename}' is invalid or does not exist.", parent=self.app_controller)
            return

        filename, file_extension = os.path.splitext(filepath)
        file_extension = file_extension.lower()

        subtitle_extensions = (".srt", ".ass", ".ssa", ".vtt")
        video_extensions = (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm") # Add common video extensions

        if file_extension in subtitle_extensions:
            self.logger.info(f"Subtitle file dropped and processing: {filepath}")
            self.subtitle_file_var.set(filepath)
            self._load_and_display_subtitle(filepath)
            self._set_ui_state(False)
            # Clear translated area and state when a new original subtitle is loaded
            self.translated_subtitle_text.config(state="normal"); self.translated_subtitle_text.delete("1.0", tk.END); self.translated_subtitle_text.config(state="disabled")
            self.translated_subs_object = None
            self.save_translated_button.config(state="disabled")

        elif file_extension in video_extensions:
            self.logger.info(f"Video file dropped, attempting to find/extract subtitles: {filepath}")
            self.processing_status_var.set("Checking video for subtitle tracks...")
            self._set_ui_state(True) # Disable UI while checking tracks
            self.subtitle_file_var.set(f"Processing video: {os.path.basename(filepath)}") # Update input field display

            # Check FFMPEG exists before attempting to list tracks
            from core import ffmpeg_utils # Import locally
            if not ffmpeg_utils.check_ffmpeg_exists():
                 messagebox.showerror("FFMPEG Error", "FFMPEG command not found. Cannot extract subtitles from video. Please ensure FFMPEG is installed and in your system's PATH.", parent=self.app_controller)
                 self.processing_status_var.set("FFMPEG not found.")
                 self._set_ui_state(False)
                 self.subtitle_file_var.set("") # Clear input display on error
                 return

            # List tracks in a thread to keep UI responsive
            import threading
            threading.Thread(target=self._task_list_and_extract_subtitle_from_video,
                             args=(filepath,),
                             daemon=True).start()

        else:
            messagebox.showwarning("Unsupported File Type",
                                   f"Dropped file type '{file_extension}' is not supported by the Subtitle Translate tab. "
                                   "Please drop a subtitle (.srt, .ass, etc.) or video (.mp4, .mkv, etc.) file.",
                                   parent=self.app_controller)
            self.logger.warning(f"Unsupported file type dropped on Subtitle Translate tab: {filepath}")
            self.subtitle_file_var.set("") # Clear input display


    def _task_list_and_extract_subtitle_from_video(self, video_filepath):
        """Task to list tracks and prompt user for selection/extraction."""
        try:
            from core import ffmpeg_utils # Import locally

            self._update_progress(10, "Listing subtitle tracks...")
            subtitle_tracks = ffmpeg_utils.list_subtitle_tracks(video_filepath)

            if self.cancel_translation_requested: return # Check cancel flag

            if not subtitle_tracks:
                self.logger.info(f"No usable subtitle tracks found in {video_filepath}.")
                self.after(0, lambda: messagebox.showinfo("No Subtitles", "No embedded subtitle tracks were found in this video.", parent=self.app_controller))
                self._update_progress(100, "No subtitles found.")
                self.after(0, self.subtitle_file_var.set, "") # Clear input display
            else:
                self.logger.info(f"Found {len(subtitle_tracks)} subtitle track(s).")
                # Schedule the dialog to run in the main thread
                self.after(0, self._show_subtitle_track_selection_dialog, video_filepath, subtitle_tracks)

        except Exception as e:
            self.logger.error(f"Error listing subtitle tracks from {video_filepath}: {e}", exc_info=True)
            self.after(0, lambda: messagebox.showerror("Extraction Error", f"An error occurred while checking video for subtitles: {e}", parent=self.app_controller))
            self._update_progress(100, "Error checking video.")
            self.after(0, self.subtitle_file_var.set, "") # Clear input display
        finally:
             self.after(0, self._set_ui_state, False) # Re-enable UI



    def _show_subtitle_track_selection_dialog(self, video_filepath, tracks):
        """Displays a dialog for the user to select a subtitle track."""
        dialog = tk.Toplevel(self.app_controller)
        dialog.title("Select Subtitle Track"); dialog.transient(self.app_controller); dialog.grab_set()
        dialog.resizable(False, False)

        main_frame = ttk.Frame(dialog, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Multiple subtitle tracks found. Please select one:").pack(pady=(0,10), anchor="w")

        # Use a Listbox or similar to display tracks
        track_listbox_frame = ttk.Frame(main_frame)
        track_listbox_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        track_listbox = tk.Listbox(track_listbox_frame, height=min(10, len(tracks) + 1), width=60) # Limit height
        track_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(track_listbox_frame, command=track_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        track_listbox.config(yscrollcommand=scrollbar.set)

        for i, track in enumerate(tracks):
            display_text = f"Track {track['index']}: {track.get('language', 'Unknown Language')} ({track.get('codec_name', 'Unknown Codec')})"
            if track.get('title') and track.get('title') != 'N/A':
                 display_text += f" - \"{track['title']}\""
            track_listbox.insert(tk.END, display_text)
            # Store the entire track info dict with the listbox instance when selected
            track_listbox.bind("<<ListboxSelect>>", lambda e, lb=track_listbox, t=tracks: setattr(lb, '_selected_track_info', t[lb.curselection()[0]]) if lb.curselection() else None)

        # Select the first item by default if available
        if tracks: track_listbox.select_set(0)


        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=(10,0))

        def on_select():
            selected_indices = track_listbox.curselection()
            if not selected_indices:
                messagebox.showwarning("Selection Error", "Please select a subtitle track.", parent=dialog)
                return

            # Get the actual track info from the stored attribute
            selected_track_info = getattr(track_listbox, '_selected_track_info', None)
            if not selected_track_info: # Fallback if bind didn't work (shouldn't happen with select_set(0))
                 selected_track_info = tracks[selected_indices[0]]

            selected_ffmpeg_track_index = selected_track_info['index'] # Use the FFmpeg stream index
            selected_codec_name = selected_track_info.get('codec_name', 'srt') # Get the codec name, default to srt


            dialog.destroy() # Close the dialog
            # Start the extraction task in a new thread, passing the codec name
            self._update_progress(20, f"Extracting track {selected_ffmpeg_track_index} (codec: {selected_codec_name})...")
            self.processing_status_var.set(f"Extracting subtitle track {selected_ffmpeg_track_index}...")
            self._set_ui_state(True) # Disable UI during extraction

            # Pass app_controller to the task if needed for temp dir or UI updates
            threading.Thread(target=self._task_extract_subtitle_to_temp,
                             args=(video_filepath, selected_ffmpeg_track_index, selected_codec_name, self.app_controller), # Pass codec name
                             daemon=True).start()


        def on_cancel():
            dialog.destroy()
            self.logger.info("Subtitle track selection cancelled by user.")
            self._update_progress(100, "Track selection cancelled.")
            self.subtitle_file_var.set("") # Clear input display

        select_button = ttk.Button(button_frame, text="Select Track", command=on_select)
        select_button.pack(side=tk.LEFT, padx=5)

        cancel_button = ttk.Button(button_frame, text="Cancel", command=on_cancel)
        cancel_button.pack(side=tk.LEFT, padx=5)

        # --- Canh giữa cửa sổ dialog ---
        # Đảm bảo các widget trong dialog đã được tính toán kích thước
        dialog.update_idletasks()

        # Lấy kích thước và vị trí của cửa sổ chính
        root_width = self.app_controller.winfo_width()
        root_height = self.app_controller.winfo_height()
        root_x = self.app_controller.winfo_x()
        root_y = self.app_controller.winfo_y()

        # Lấy kích thước yêu cầu của dialog
        dialog_width = dialog.winfo_reqwidth()
        dialog_height = dialog.winfo_reqheight()

        # Tính toán vị trí mới cho dialog để canh giữa cửa sổ chính
        position_x = root_x + (root_width // 2) - (dialog_width // 2)
        position_y = root_y + (root_height // 2) - (dialog_height // 2)

        # Đặt vị trí cho dialog
        dialog.geometry(f"+{position_x}+{position_y}")
        # --- Kết thúc Canh giữa cửa sổ dialog ---
        dialog.protocol("WM_DELETE_WINDOW", on_cancel) # Handle closing dialog via window manager
        dialog.focus_set()
        self.app_controller.wait_window(dialog) # Wait for the dialog to close

    def _task_extract_subtitle_to_temp(self, video_filepath, track_index, codec_name, app_controller): # Receive codec_name
        """Task to extract the selected subtitle track to a temporary file."""
        try:
            from core import ffmpeg_utils # Import locally
            # Ensure temp directory exists (already handled in main_window init, but check again)
            temp_dir = app_controller.app_temp_dir
            if not os.path.exists(temp_dir):
                 os.makedirs(temp_dir, exist_ok=True)

            self._update_progress(30, f"Extracting track {track_index} (codec: {codec_name}) to temp file...")

            # Determine output format based on codec name
            output_extension = 'srt' # Default to srt
            if codec_name in ['ass', 'ssa', 'webvtt']: # Use original format if ASS, SSA, or VTT
                output_extension = codec_name
            # Note: For 'mov_text', stick to 'srt' extraction as it's a text format and srt is generally compatible.
            # Other complex formats might need more specific handling or a different approach than -c:s copy.

            temp_subtitle_path = ffmpeg_utils.extract_subtitle_to_temp_file(
                 video_filepath,
                 track_index,
                 output_extension=output_extension, # Use determined extension
                 temp_dir=temp_dir
            )

            if self.cancel_translation_requested: return # Check cancel flag

            if temp_subtitle_path and os.path.exists(temp_subtitle_path):
                self.logger.info(f"Successfully extracted track {track_index} to temp file: {temp_subtitle_path}")
                # Add temp file to cleanup list
                if hasattr(app_controller, 'temp_files_to_cleanup'):
                     app_controller.temp_files_to_cleanup.append(temp_subtitle_path)
                     self.logger.debug(f"Added {temp_subtitle_path} to cleanup list.")
                else:
                     self.logger.warning("app_controller does not have temp_files_to_cleanup list.")

                # Load and display the temporary subtitle file in the main thread
                self.after(0, self._update_progress, 50, f"Loading extracted subtitle from track {track_index}...")
                self.after(0, self.subtitle_file_var.set, temp_subtitle_path) # Set input field to temp file path
                self.after(0, self._load_and_display_subtitle, temp_subtitle_path) # Load and display

            else:
                self.logger.error(f"Failed to extract track {track_index} from {video_filepath}.")
                self.after(0, lambda: messagebox.showerror("Extraction Error", f"Failed to extract subtitle track {track_index} from video.", parent=self.app_controller))
                self.after(0, self.subtitle_file_var.set, "") # Clear input display

        except Exception as e:
            self.logger.error(f"Error extracting subtitle track {track_index} from {video_filepath}: {e}", exc_info=True)
            self.after(0, lambda: messagebox.showerror("Extraction Error", f"An error occurred during subtitle extraction: {e}", parent=self.app_controller))
            self.after(0, self.subtitle_file_var.set, "") # Clear input display
        finally:
             self._update_progress(100, "Extraction task finished.")
             self.after(0, self._set_ui_state, False) # Re-enable UI


    def _request_cancellation(self):
        if not self.cancel_translation_requested:
            if messagebox.askyesno("Cancel Translation", "Are you sure?", parent=self.app_controller):
                self.logger.info("Translation cancellation requested.")
                self.cancel_translation_requested = True
                self.cancel_button.config(text="Cancelling...", state="disabled")
                self.processing_status_var.set("Cancellation requested...")

    def _browse_subtitle_file(self):
        filepath = filedialog.askopenfilename(
            title="Select Subtitle File",
            filetypes=(("Subtitle Files", "*.srt *.ass *.ssa *.vtt"), ("All Files", "*.*")),
            parent=self.app_controller
        )
        if filepath:
            self.subtitle_file_var.set(filepath)
            self.logger.info(f"Input subtitle selected: {filepath}")
            self._load_and_display_subtitle(filepath)
            self._set_ui_state(False)
            self.translated_subtitle_text.config(state="normal"); self.translated_subtitle_text.delete("1.0", tk.END); self.translated_subtitle_text.config(state="disabled")
            self.translated_subs_object = None
            self.save_translated_button.config(state="disabled")

    def _load_and_display_subtitle(self, filepath):
        if not os.path.exists(filepath):
            self.logger.error(f"File not found: {filepath}")
            self.original_subtitle_text.config(state="normal"); self.original_subtitle_text.delete("1.0", tk.END)
            self.original_subtitle_text.insert("1.0", f"Error: File not found."); self.original_subtitle_text.config(state="disabled")
            self.loaded_subs_object = None; self.original_timing_info = []
            self.translate_button.config(state="disabled")
            return
        try:
            subs_object = subtitle_parser.load_subtitle_file(filepath)
            if subs_object is None:
                 self.logger.error(f"Failed to parse: {filepath}")
                 self.original_subtitle_text.config(state="normal"); self.original_subtitle_text.delete("1.0", tk.END)
                 self.original_subtitle_text.insert("1.0", f"Error: Could not parse file."); self.original_subtitle_text.config(state="disabled")
                 self.loaded_subs_object = None; self.original_timing_info = []
                 self.translate_button.config(state="disabled")
                 return
            self.loaded_subs_object = subs_object
            text_segments, original_events = subtitle_parser.extract_text_and_format_info(self.loaded_subs_object)
            self.original_timing_info = [ {'start': ev.start, 'end': ev.end} for ev in original_events ] # Store timing info

            # Prepare text with line numbers for display
            display_text_lines = [f"{i+1}: {segment}" for i, segment in enumerate(text_segments)]
            display_text = "\n".join(display_text_lines)

            self.original_subtitle_text.config(state="normal"); self.original_subtitle_text.delete("1.0", tk.END)
            self.original_subtitle_text.insert("1.0", display_text); self.original_subtitle_text.config(state="disabled")
            self.logger.info(f"Subtitle loaded, plain text with line numbers displayed: {filepath}")
            if text_segments: self.translate_button.config(state="normal")
            else:
                self.translate_button.config(state="disabled")
                messagebox.showinfo("Empty Subtitle", "No translatable dialogue found.", parent=self.app_controller)
        except Exception as e:
            self.logger.error(f"Error loading/displaying {filepath}: {e}", exc_info=True)
            self.original_subtitle_text.config(state="normal"); self.original_subtitle_text.delete("1.0", tk.END)
            self.original_subtitle_text.insert("1.0", f"Error: {e}"); self.original_subtitle_text.config(state="disabled")
            self.loaded_subs_object = None; self.original_timing_info = []
            self.translate_button.config(state="disabled")

    def _set_ui_state(self, processing: bool):
        state_normal = tk.NORMAL
        state_disabled = tk.DISABLED
        # combo_state_normal = "readonly" # Not needed anymore as languages/style can be edited

        self.browse_subtitle_button.config(state=state_disabled if processing else state_normal)
        # Language and style comboboxes should be editable when not processing
        self.source_language_combobox.config(state=state_disabled if processing else "normal")
        self.target_language_combobox.config(state=state_disabled if processing else "normal")
        self.gemini_model_combo.config(state=state_disabled if processing else "readonly") # Model should remain readonly
        self.refresh_models_button.config(state=state_disabled if processing else state_normal)
        self.gemini_temp_scale.config(state=state_disabled if processing else state_normal)
        self.translation_style_combo.config(state=state_disabled if processing else "normal")
        self.context_keywords_text.config(state=state_disabled if processing else state_normal)

        can_translate = bool(self.loaded_subs_object and self.original_timing_info)
        self.translate_button.config(state=state_disabled if processing or not can_translate else state_normal)
        can_save = bool(self.translated_subs_object)
        self.save_translated_button.config(state=state_disabled if processing or not can_save else state_normal)
        self.cancel_button.config(state=state_normal if processing else state_disabled)
        if not processing: self.cancel_button.config(text="Cancel")

        self.processing_status_var.set("Translating..." if processing else "Idle.")
        if processing: self.processing_progress_var.set(0)

    def _start_translation_process(self):
        if not self.loaded_subs_object or not self.original_timing_info:
            messagebox.showerror("Error", "No subtitle loaded or no content.", parent=self.app_controller)
            return
        # Get the global API key from the main window controller
        api_key = self.app_controller.api_key_var.get()
        # Although configure_api is called in MainWindow, re-calling it here ensures the latest key is used before a critical API call
        if not api_key or not gemini_utils.configure_api(api_key):
            messagebox.showerror("API Error", "Gemini API Key is not set or invalid in main application settings. Please check and update the API key.", parent=self.app_controller)
            return
        if not self.gemini_model_var.get():
            messagebox.showerror("Setup Error", "Please select a Gemini Model.", parent=self.app_controller)
            return
        if not self.target_language_var.get():
             messagebox.showerror("Setup Error", "Please select a target language.", parent=self.app_controller)
             return

        self._set_ui_state(True)
        self.processing_status_var.set("Starting translation...")
        self.logger.info("Starting subtitle translation process (single request mode).")
        self.cancel_translation_requested = False
        threading.Thread(target=self._task_translate_subtitle_full_request, daemon=True).start()

    def _task_translate_subtitle_full_request(self):
        chat = None # Initialize chat object
        try:
            self.logger.info("TASK: Starting full subtitle translation request.")
            self._update_progress(5, "Preparing data...")

            # extract_text_and_format_info returns (list of plaintext segments for translation, list of original SSAEvent objects including non-dialogue)
            text_segments_for_translation, original_events_full = subtitle_parser.extract_text_and_format_info(self.loaded_subs_object)

            if not text_segments_for_translation:
                self.logger.warning("No text to translate.")
                self.after(0, lambda: messagebox.showwarning("Warning", "No translatable content found.", parent=self.app_controller))
                self._update_progress(100, "No text.")
                return

            total_segments_to_translate = len(text_segments_for_translation)
            self.logger.info(f"Total {total_segments_to_translate} segments to translate.")
            self._update_progress(10, f"Extracted {total_segments_to_translate} segments.")

            # --- Prepare data for the single prompt ---
            # Format all segments with markers [Segment X]:
            all_segments_to_translate_text_for_prompt = "\n".join(
                [f"[Segment {idx + 1}]: {segment}"
                 for idx, segment in enumerate(text_segments_for_translation)]
            )

            source_lang = self.source_language_var.get()
            target_lang = self.target_language_var.get()
            style = self.translation_style_var.get().strip()
            style_instr = f"Adopt a '{style}' style." if style and style.lower() not in ["default/neutral", "default", "neutral", ""] else "Adopt a neutral style."
            keywords = self.context_keywords_text.get("1.0", tk.END).strip()
            keywords_fmt = ", ".join([f'"{k.strip()}"' for k in keywords.splitlines() if k.strip()]) if keywords else "None provided"

            # --- Build the single prompt ---
            prompt = SUBTITLE_TRANSLATION_PROMPT_TEMPLATE.format(
                source_lang_for_prompt=source_lang if source_lang.lower() != "auto" else "the source language (auto-detected)",
                target_lang=target_lang,
                style_instruction=style_instr,
                keywords_string_formatted=keywords_fmt,
                all_segments_to_translate_text=all_segments_to_translate_text_for_prompt,
                expected_translated_segments_count=total_segments_to_translate
            )

            self.logger.debug(f"Prepared full prompt (first 500 chars):\n{prompt[:500]}...")
            self._update_progress(20, "Prepared prompt.")

            # --- Cancellation Check 1 (Before starting chat and sending API request) ---
            if self.cancel_translation_requested:
                self.logger.info("Subtitle translation cancellation requested before API call.")
                self._update_progress(self.processing_progress_var.get(), "Cancelled.")
                return

            # --- Initialize Chat Session ---
            model = self.gemini_model_var.get()
            temp = self.gemini_temperature_var.get()
            # Corrected parameter name from model_name to model_name_from_user
            chat = gemini_utils.start_gemini_chat(model_name_from_user=model)

            if not chat:
                self.logger.error("Failed to initialize chat for translation.");
                self.after(0, lambda: messagebox.showerror("API Error", "Could not initialize chat for translation. Check API key and model selection.", parent=self.app_controller))
                self._update_progress(0, "Chat initialization failed.")
                return # Stop processing if chat fails to initialize

            self._update_progress(25, "Sending request to API...")

            # --- Send request to Gemini using the chat session ---
            # Pass temperature via generation_config in send_message
            response = gemini_utils.send_message_to_chat(chat, [gemini_utils.to_part(prompt)], temperature=temp)

            # --- Cancellation Check 2 (After API response, before processing) ---
            if self.cancel_translation_requested:
                self.logger.info("Subtitle translation cancellation requested after API call.")
                self._update_progress(self.processing_progress_var.get(), "Cancelled.")
                return

            # --- Handle API Response ---
            if response is None or response.startswith(("[Error]", "[Blocked]")):
                self.logger.error(f"API call failed/blocked: {response}")
                error_msg = f"API Error during translation.\nResponse: {response}"
                self.after(0, lambda msg=error_msg: messagebox.showerror("API Error", msg, parent=self.app_controller))
                self._update_progress(self.processing_progress_var.get(), "API Error.")
                return # Stop processing on API error

            translated_response_text = response.strip()
            self.logger.debug(f"Received response from Gemini (first 500 chars):\n{translated_response_text[:500]}...")
            self._update_progress(70, "Processing API response...")

            # --- Cancellation Check 3 (After processing API response, before post-processing) ---
            if self.cancel_translation_requested:
                self.logger.info("Subtitle translation cancellation requested before post-processing.")
                self._update_progress(self.processing_progress_var.get(), "Cancelled.")
                return

            # --- Post-process the translated text ---
            # Use the single version of _post_process_translated_text (starts line 762)
            processed_translated_segments, actual_count = self._post_process_translated_text(translated_response_text, total_segments_to_translate)

            # --- Cancellation Check 4 (After post-processing, before reassembly) ---
            if self.cancel_translation_requested:
                self.logger.info("Subtitle translation cancellation requested after post-processing.")
                self._update_progress(self.processing_progress_var.get(), "Cancelled.")
                return

            # --- Check Segment Count ---
            if actual_count != total_segments_to_translate:
                 self.logger.error(f"Post-processing failed: Translated segment count mismatch. Expected {total_segments_to_translate}, Got {actual_count}.")
                 error_msg = f"Post-processing error: Translated segment count mismatch.\n" \
                             f"Expected: {total_segments_to_translate}\n" \
                             f"Actually received: {actual_count}\n\n" \
                             f"The raw response text from Gemini has been displayed in the right pane for your review."
                 self.after(0, lambda msg=error_msg: messagebox.showerror("Post-processing Error", msg, parent=self.app_controller))
                 self._update_progress(self.processing_progress_var.get(), "Post-processing error.")
                 # Display what was received - need to make sure _display_translated_text can handle partial/raw text
                 self.after(0, self._display_translated_text, translated_response_text)
                 self.translated_subs_object = None # Ensure translated object is not set on error
                 return # Stop processing on post-processing error

            self._update_progress(85, "Reassembling translated subtitles...")

            # --- Reassembly ---
            # original_events_full contains all original events, including non-dialogue
            # processed_translated_segments contains only the translated dialogue/drawing segments
            self.logger.info(f"Reassembling {len(processed_translated_segments)} translated segments with {len(original_events_full)} total original events.")

            self.translated_subs_object = subtitle_parser.reassemble_translated_subs(original_events_full, processed_translated_segments)

            # --- Cancellation Check 5 (After reassembly, before final display) ---
            if self.cancel_translation_requested:
                self.logger.info("Subtitle translation cancellation requested after reassembly.")
                self._update_progress(self.processing_progress_var.get(), "Cancelled.")
                return


            # --- Finalize ---
            if self.translated_subs_object:
                # Filter out Comment events before creating display_text for the UI
                texts_for_display = []
                for ev in self.translated_subs_object:
                    # Only include text from non-Comment events for UI display
                    if hasattr(ev, 'type') and ev.type != "Comment":
                         if hasattr(ev, 'plaintext'):
                              texts_for_display.append(ev.plaintext)
                         elif hasattr(ev, 'text'): # Fallback just in case plaintext is missing
                             texts_for_display.append(ev.text)
                         # else: skip events without text content

                display_text_for_ui = "\n".join(texts_for_display)
                self.after(0, self._display_translated_text, display_text_for_ui)
                self.logger.info("Reassembly complete.")
                self._update_progress(100, "Translation complete.")
                self.after(0, lambda: messagebox.showinfo("Complete", "Subtitle translation complete!", parent=self.app_controller))
                self.after(0, self.save_translated_button.config, {'state': tk.NORMAL}) # Enable save button
            else:
                self.logger.error("Reassembly failed (parser returned None).")
                self.after(0, lambda: messagebox.showerror("Error", "Subtitle reassembly failed.", parent=self.app_controller))
                self._update_progress(self.processing_progress_var.get(), "Reassembly error.")

        except Exception as e:
            if not self.cancel_translation_requested:
                self.logger.error(f"Error in translation task: {e}", exc_info=True)
                self.after(0, lambda err=e: messagebox.showerror("Task Error", f"An error occurred during translation: {err}", parent=self.app_controller))
                if hasattr(self, 'processing_status_var'): self.processing_status_var.set("Subtitle translation failed.")
        finally:
            self.after(0, self._set_ui_state, False)
            # Ensure chat object is closed/released if it exists
            if chat:
                 try: chat.close()
                 except AttributeError: pass # Some objects might not have a close method
                 chat = None




    def _post_process_translated_text(self, translated_response_text: str, expected_count: int) -> tuple[list, int]:
        """
        Attempts to parse translated text from Gemini response, expecting segments
        prefixed with "[Segment X]:" and separated by newlines.
        Returns a tuple: (list of processed translated segments, actual count of segments found).
        The calling function is responsible for checking if the actual count matches expected.
        This version parses based on [Segment X]: markers and assumes each translated segment
        is followed by a newline. It does NOT rely on a separate separator like _||_.
        """
        self.logger.info(f"Starting post-processing. Expected {expected_count} segments.") # Use expected_count directly
        self.logger.debug(f"Raw translated response text (first 500 chars):\n{translated_response_text.strip()[:500]}...") # Log raw input

        processed_segments = []
        # Split the response text by lines
        lines = translated_response_text.strip().splitlines()

        current_segment_text_lines = []
        # Use a regex to find the segment marker and capture the index
        segment_marker_regex = re.compile(r"\[Segment \d+]:")

        for line in lines:
            line = line.strip()
            if not line:
                continue # Skip empty lines

            # Check if the line starts with a segment marker
            if segment_marker_regex.match(line):
                # Found a new segment marker
                if current_segment_text_lines:
                    # If we were building a segment, finish it and add to the list
                    processed_segments.append("\n".join(current_segment_text_lines).strip())
                    current_segment_text_lines = [] # Reset for the new segment

                # Start building the new segment. Add the line with the marker.
                current_segment_text_lines.append(line)
            elif current_segment_text_lines:
                # This line is part of the current segment
                current_segment_text_lines.append(line)
            # If no marker and current_segment_text_lines is empty, this line is unexpected noise before the first segment

        # Add the last segment if there was one being built
        if current_segment_text_lines:
             processed_segments.append("\n".join(current_segment_text_lines).strip())

        # Now processed_segments contains the translated segments including their [Segment X]: markers

        # We need to extract just the text after the markers and ensure we have the correct count.
        final_translated_segments = []
        actual_count = 0

        for segment_with_marker in processed_segments:
            marker_match = re.match(r"\[Segment (\d+)]:", segment_with_marker)
            if marker_match:
                actual_count += 1
                # Extract the text after the marker
                translated_text = segment_with_marker[marker_match.end():].strip()
                final_translated_segments.append(translated_text)
            else:
                 self.logger.warning(f"Post-processing: Found segment without expected marker: '{segment_with_marker[:100]}...'")


        self.logger.debug(f"Post-processing extracted {actual_count} segments (text only):\n{final_translated_segments}")


        if actual_count == expected_count:
            self.logger.info("Post-processing successful: Segment counts match.")
            return final_translated_segments, actual_count
        else:
            self.logger.warning(f"Post-processing failed: Segment count mismatch. Expected {expected_count}, Got {actual_count}.")
            return final_translated_segments, actual_count # Return the list of text only

    def _display_translated_text(self, translated_plain_text):
        if hasattr(self, 'translated_subtitle_text') and self.translated_subtitle_text.winfo_exists():
            self.translated_subtitle_text.config(state="normal")
            self.translated_subtitle_text.delete("1.0", tk.END)

            # Add line numbers to translated text for display
            # Assuming translated_plain_text is a single string with segments separated by newlines
            translated_segments = translated_plain_text.splitlines()
            display_text_lines = [f"{i+1}: {segment}" for i, segment in enumerate(translated_segments)]
            display_text_with_numbers = "\n".join(display_text_lines)

            self.translated_subtitle_text.insert("1.0", display_text_with_numbers)
            self.translated_subtitle_text.config(state="disabled")

    def _save_translated_subtitle(self):
        if not self.translated_subs_object:
            messagebox.showwarning("Save Error", "No translated content to save.", parent=self.app_controller)
            return
        original_fp = self.subtitle_file_var.get()
        base_name = os.path.splitext(os.path.basename(original_fp))[0] if original_fp else "translated_sub"
        orig_ext = os.path.splitext(original_fp)[1].lower() if original_fp and os.path.splitext(original_fp)[1].lower() in [".srt", ".ass", ".ssa", ".vtt"] else ".srt"
        target_lang_short = self.target_language_var.get()[:3].lower() or "trans"
        default_name = f"{base_name}_{target_lang_short}{orig_ext}"
        save_path = filedialog.asksaveasfilename(
            title="Save Translated Subtitle", initialfile=default_name, defaultextension=orig_ext,
            filetypes=(("SubRip", "*.srt"), ("ASS", "*.ass"), ("SSA", "*.ssa"), ("WebVTT", "*.vtt"), ("All", "*.*")),
            parent=self.app_controller
        )
        if not save_path: self.logger.info("Save cancelled."); return
        try:
            if subtitle_parser.save_subtitle_file(self.translated_subs_object, save_path):
                 self.logger.info(f"Saved to: {save_path}")
                 messagebox.showinfo("Saved", f"Saved to:\n{save_path}", parent=self.app_controller)
            else:
                 self.logger.error(f"Failed to save (parser returned False): {save_path}")
                 messagebox.showerror("Save Error", "Failed to save file.", parent=self.app_controller)
        except Exception as e:
            self.logger.error(f"Error saving {save_path}: {e}", exc_info=True)
            messagebox.showerror("Save Error", f"Error: {e}", parent=self.app_controller)

    def _update_progress(self, value, message=None):
        if self.winfo_exists():
            if hasattr(self, 'processing_progress_var'): self.processing_progress_var.set(value)
        if message:
            self.logger.info(f"SUB_TRANS_PROG: {message} ({value:.0f}%)")
            if self.winfo_exists() and hasattr(self, 'processing_status_var'):
                self.processing_status_var.set(message)
