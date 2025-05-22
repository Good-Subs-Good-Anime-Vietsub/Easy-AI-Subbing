# EasyAISubbing/app_gui/video_audio_tab.py
# This file was previously part of Gemini Subtitler Pro vNext
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font as tkFont
import logging
import os
import srt
import textwrap
import time # For _task_initial_gemini_processing

try:
    from tkinterdnd2 import DND_FILES # Only need DND_FILES for drop_target_register
    DND_TAB_SUPPORTED = True
except ImportError:
    DND_TAB_SUPPORTED = False

from core import config_manager, ffmpeg_utils, gemini_utils, srt_utils
from .ui_utils import ToolTip, show_scrollable_messagebox
from . import media_input_helpers # Cho D&D và URL trực tiếp
from . import yt_dlp_helper       # Cho yt-dlp
from . import video_audio_tasks # Import the tasks module

logger = logging.getLogger(__name__)

COMMON_LANGUAGES_GEMINI_TARGET = [
    "English", "Vietnamese", "Japanese", "Chinese (Simplified)", "Spanish",
    "French", "German", "Korean", "Russian", "Portuguese (Brazilian)",
    "Italian", "Hindi", "Arabic", "Turkish", "Polish", "Dutch"
]

INITIAL_GEMINI_PROMPT_TEMPLATE = textwrap.dedent("""\
    You are a professional translator and subtitler. I have provided a full audio file.
    Your primary task is to accurately translate and then create perfectly timed subtitles.
    Follow these instructions METICULOUSLY:
    1.  **Audio Analysis & Translation:**
        *   Listen to the ENTIRE audio carefully.
        *   Translate the spoken content into {target_lang} with utmost accuracy, ensuring natural phrasing. {style_instruction}
    2.  **Subtitle Segmentation & Timing (CRITICAL):**
        *   Divide the translation into VERY SHORT, coherent subtitle lines, respecting natural speech pauses.
        *   **Line Duration:** Aim for lines between 3 to 7 seconds. STRICTLY AVOID lines longer than 10 seconds unless it's a single, completely indivisible spoken phrase. If a thought is longer, break it into multiple shorter subtitle lines.
        *   **Timestamp Format:** For EACH subtitle line, provide timestamps in the EXACT format: '[m:s,x - m:s,x]'
            *   'm' = minutes (e.g., 0, 1, 58, 120).
            *   's' = seconds (0-59, e.g., 6 or 06).
            *   'x' = tenth of a second (0-9, ONE digit after comma).
            *   Example: [0:06,1 - 0:12,7] or [1:02,5 - 1:08,0]
        *   **No Duplicate/Overlapping Timestamps:** Each distinct dialogue line MUST have a unique start and end time. Ensure timestamps are sequential. Small non-overlapping gaps (<0.1s) are preferred over overlaps.
    3.  **Output Structure (CRITICAL):**
        *   The output MUST be a list of lines.
        *   Each line strictly following: '[m:s,x - m:s,x] Translated text.'
        *   If applicable, a brief terminological note can be added: '[m:s,x - m:s,x] Translated text. {{note}}'
    4.  **Contextual Information:**
        *   If provided, refer to this list of preferred {target_lang} terms/names: [{keywords_string_formatted}].
    5.  **General Guidelines:**
        *   Do NOT add any extra commentary, introductions, or summaries outside the required line format.
        *   If there are silent parts, do NOT generate lines for them.
    Example of **GOOD** output lines:
    [0:00,7 - 0:03,2] This is a short first sentence.
    [0:03,3 - 0:05,9] The next one, also concise. {{with a note}}
    Example of **BAD** output (wrong format, or duplicate timestamps):
    [00:10.0 - 00:25.0] Incorrect separator and potentially too long.
    [0:26,0 - 0:28,0] First part of bad duplicate.
    [0:26,0 - 0:28,0] Second part of bad duplicate.
    [0:30,55 - 0:32,1] '55' is not a tenth of a second, use ',5' for 5 tenths.
    Strict adherence to all formatting and timing rules is essential.
    """)

CUSTOM_FIX_PROMPT_HEADER_TEMPLATE = textwrap.dedent("""\
    Please correct your previous subtitle generation based on the following issues and rules.
    {analysis_feedback}
    REQUIRED CORRECTIONS & OUTPUT FORMAT:
    1. Fix any identified issues related to timestamps or formatting in the subtitle text I am asking you to correct.
    2. {style_reminder}
    3. The corrected output MUST be ONLY a list of subtitle lines.
    4. Each line MUST strictly follow the format: '[m:s,x - m:s,x] Translated text. {{Optional note}}'
       - 'm' = minutes (e.g., 0, 58, 120).
       - 's' = seconds (0-59, e.g., 6 or 06).
       - 'x' = tenth of a second (0-9, ONE digit after comma).
    5. Ensure all timestamps are logical: Start time < End time. Timestamps must be sequential. NO identical timestamps for different dialogue lines.
    IMPORTANT: The text you need to correct is your immediately preceding subtitle generation in our current conversation.
    For your reference, here is the current state of that text (after my potential edits), which you should correct:
    --- START OF CURRENT SUBTITLE TEXT TO CORRECT ---
    {current_subtitle_text}
    --- END OF CURRENT SUBTITLE TEXT ---
    Provide ONLY the fully corrected subtitle script. Do not add any other commentary or explanations.
    """)

class VideoAudioTab(ttk.Frame):
    def __init__(self, parent_notebook, app_controller):
        super().__init__(parent_notebook)
        self.app_controller = app_controller
        self.logger = logging.getLogger(f"{__name__}.VideoAudioTab")

        self.default_font_family = self.app_controller.default_font_family
        self.default_font_size = self.app_controller.default_font_size
        self.custom_font = self.app_controller.custom_font

        self.current_video_path = None
        self.full_audio_path_for_gemini = None
        self.current_chat_session = None
        self.current_subtitle_data = ""
        self.last_detailed_analysis_messages = []
        self.suggested_auto_format_text = ""
        self.user_has_edited_subtitle_area = False
        self.edit_mode_label_packed = False # Initialize to prevent AttributeError

        self.progress_var = tk.DoubleVar()
        self.cancel_requested = False

        # API Key is now managed globally in MainWindow
        # self.api_key_var = tk.StringVar() # Removed

        self.video_file_var = tk.StringVar()
        self.video_url_var = tk.StringVar()
        self.yt_dlp_url_var = tk.StringVar()
        self.yt_dlp_audio_only_var = tk.BooleanVar(value=False)
        self.gemini_model_var = tk.StringVar()
        self.target_translation_lang_var = tk.StringVar()
        self.translation_style_var = tk.StringVar()
        self.gemini_temperature_var = tk.DoubleVar()
        self.gemini_temperature_display_var = tk.StringVar()

        self._init_ui_layout()
        self._load_initial_settings_for_tab()
        # Moved _load_gemini_models definition here
    def _load_gemini_models(self):
        """Fetches and populates the Gemini model combobox."""
        self.logger.info("Fetching available Gemini models for Video/Audio Tab...")
        api_key_present_and_configured = False
        if hasattr(self.app_controller, 'api_key_var') and self.app_controller.api_key_var.get():
             if gemini_utils.configure_api(self.app_controller.api_key_var.get()):
                 self.logger.info("Gemini API configured successfully for model loading.")
                 api_key_present_and_configured = True
             else:
                 self.logger.warning("Failed to configure Gemini API with key from app_controller for model loading.")

        models_info = gemini_utils.list_available_models()

        if models_info:
            model_names = [m['name'] for m in models_info]
            self.gemini_model_combo['values'] = model_names

            current_selected_model = self.gemini_model_var.get() # Value loaded from config

            # Check if the model loaded from config is in the available models list
            if current_selected_model and current_selected_model in model_names:
                # Keep the model loaded from config if it's valid
                self.logger.info(f"Keeping model loaded from config: {current_selected_model}")
                # self.gemini_model_var.set(current_selected_model) # Already set by _load_initial_settings_for_tab
            else:
                # If model from config is not valid or not set, apply the selection logic
                self.logger.info("Model from config not valid or not set. Applying default/preferred selection logic.")
                is_fallback_list = any("fallback list" in m.get("display_name","").lower() for m in models_info if isinstance(m, dict))
                preferred_model_order = ["gemini-1.5-pro-latest", "gemini-1.5-flash-latest"]

                selected_model_to_set = ""
                if api_key_present_and_configured and not is_fallback_list:
                     for pref_model in preferred_model_order:
                         if pref_model in model_names:
                             selected_model_to_set = pref_model
                             break

                if selected_model_to_set:
                     self.gemini_model_var.set(selected_model_to_set)
                elif model_names:
                     # Default to the first model if no preferred is available
                     self.gemini_model_var.set(model_names[0])
                else:
                     self.gemini_model_var.set("") # No models available

                self.logger.info(f"Gemini models list updated for tab. Selected (via default/preferred logic): {self.gemini_model_var.get() or 'None'}")
        else:
            self.logger.error("Could not fetch or find any Gemini models for tab (even fallback failed).")
            self.gemini_model_combo['values'] = []
            self.gemini_model_var.set("")

        # Try to load models after loading settings (and potentially after API key is set in MainWindow)
        # The call to _load_gemini_models is handled within _load_initial_settings_for_tab

        if DND_TAB_SUPPORTED:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self._handle_drop_event)
            self.logger.info("Drag and drop target registered for VideoAudioTab.")
        else:
            self.logger.warning("Drag and drop for VideoAudioTab disabled (tkinterdnd2 missing).")

        self.logger.info("Video/Audio Tab initialized.")

    def _handle_combobox_selection_visual_reset(self, event): # (Keep as is)
        widget = event.widget
        def clear_highlight_and_refocus_away():
            if widget.winfo_exists():
                widget.selection_clear()
                self.app_controller.focus_set()
        widget.after(10, clear_highlight_and_refocus_away)

    def _on_gemini_model_selected(self, event=None):
        """Handles Gemini model selection change, saves setting and resets visual."""
        self._save_current_ui_settings() # Save settings immediately
        self._handle_combobox_selection_visual_reset(event) # Keep the visual reset

    def _on_subtitle_area_modified(self, event=None): # (Keep as is)
        if hasattr(self, 'subtitle_edit_text_widget') and self.subtitle_edit_text_widget.cget("state") == "normal":
            self.user_has_edited_subtitle_area = True
        if hasattr(self, 'subtitle_edit_text_widget'):
            self.subtitle_edit_text_widget.edit_modified(False)

    def _create_text_display_area(self, parent_frame, title, height=15, is_subtitle_editor=False): # (Keep as is)
        lframe = ttk.LabelFrame(parent_frame, text=title, padding="5")
        text_widget = tk.Text(lframe, height=height, wrap=tk.WORD,
                              relief=tk.SOLID, borderwidth=1, state="disabled",
                              font=(self.default_font_family, self.default_font_size -1), undo=True)
        if is_subtitle_editor:
            text_widget.bind("<<Modified>>", self._on_subtitle_area_modified)
        scroll_y = ttk.Scrollbar(lframe, orient=tk.VERTICAL, command=text_widget.yview)
        scroll_x = ttk.Scrollbar(lframe, orient=tk.HORIZONTAL, command=text_widget.xview)
        text_widget.config(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        return lframe, text_widget

    def _init_ui_layout(self): # (Needs row_idx adjustment for large sections)
        controls_outer_frame = ttk.Frame(self)
        controls_outer_frame.pack(fill=tk.X, pady=(0,10), padx=5)
        controls_frame = ttk.Frame(controls_outer_frame, padding="5")
        controls_frame.pack(fill=tk.X)
        controls_frame.columnconfigure(1, weight=1)

        # Quản lý row cho các section lớn trong controls_frame
        current_main_row = 0
        # API Key section is now in MainWindow, removed from here
        # current_main_row = self._create_api_config_section(controls_frame, start_row=current_main_row) # Removed
        current_main_row = self._create_file_input_section(controls_frame, start_row=current_main_row)
        current_main_row = self._create_gemini_settings_section(controls_frame, start_row=current_main_row)
        current_main_row = self._create_targeting_section(controls_frame, start_row=current_main_row)
        current_main_row = self._create_action_buttons_section(controls_frame, start_row=current_main_row)
        current_main_row = self._create_progress_bar_section(controls_frame, start_row=current_main_row)

        self._create_display_panes_section(self) # This section uses pack

        if hasattr(self, 'log_text_widget') and self.log_text_widget:
            gui_log_handler = TextHandler(self.log_text_widget, self.logger)
            self.logger.addHandler(gui_log_handler)
            self.logger.setLevel(logging.INFO)
        else:
            self.logger.warning("Log text widget not available for VideoAudioTab.")
        self._populate_subtitle_edit_area("Subtitle output from Gemini will appear here and will be editable.")

    # Removed _create_api_config_section method

    def _create_file_input_section(self, parent, start_row):
        current_row = start_row
        # --- Local File Input ---
        video_file_label = ttk.Label(parent, text="Video/Audio File:")
        video_file_label.grid(row=current_row, column=0, sticky=tk.W, padx=5, pady=3)
        self.video_file_entry = ttk.Entry(parent, textvariable=self.video_file_var, width=60, state="readonly")
        self.video_file_entry.grid(row=current_row, column=1, columnspan=2, sticky=tk.EW, padx=5, pady=3)
        self.browse_video_button = ttk.Button(parent, text="Browse...", command=self._browse_local_file)
        self.browse_video_button.grid(row=current_row, column=3, padx=5, pady=3, sticky=tk.E)
        ToolTip(self.browse_video_button, "Browse for a local video or audio file.")

        current_row += 1
        # --- URL Input (Direct File) ---
        url_file_label = ttk.Label(parent, text="Or Direct File URL:")
        url_file_label.grid(row=current_row, column=0, sticky=tk.W, padx=5, pady=3)
        self.url_file_entry = ttk.Entry(parent, textvariable=self.video_url_var, width=60)
        self.url_file_entry.grid(row=current_row, column=1, columnspan=2, sticky=tk.EW, padx=5, pady=3)
        self.load_url_button = ttk.Button(parent, text="Load URL", command=self._start_direct_url_download)
        self.load_url_button.grid(row=current_row, column=3, padx=5, pady=3, sticky=tk.E)
        ToolTip(self.load_url_button, "Load a video/audio file directly from a URL.")

        current_row += 1
        # --- yt-dlp URL Input ---
        yt_dlp_label = ttk.Label(parent, text="Or URL (YouTube, etc.):")
        yt_dlp_label.grid(row=current_row, column=0, sticky=tk.W, padx=5, pady=3)
        self.yt_dlp_url_entry = ttk.Entry(parent, textvariable=self.yt_dlp_url_var, width=60)
        self.yt_dlp_url_entry.grid(row=current_row, column=1, columnspan=1, sticky=tk.EW, padx=5, pady=3) # columnspan=1
        self.yt_dlp_audio_only_check = ttk.Checkbutton(parent, text="Audio Only", variable=self.yt_dlp_audio_only_var)
        self.yt_dlp_audio_only_check.grid(row=current_row, column=2, sticky=tk.W, padx=5, pady=3)
        ToolTip(self.yt_dlp_audio_only_check, "If checked, only audio (WAV) will be downloaded. Else, video (MP4).")
        self.yt_dlp_button = ttk.Button(parent, text="Download (yt-dlp)", command=self._start_yt_dlp_download)
        self.yt_dlp_button.grid(row=current_row, column=3, padx=5, pady=3, sticky=tk.E)
        ToolTip(self.yt_dlp_button, "Download video/audio using yt-dlp.")

        if DND_TAB_SUPPORTED:
            current_row += 1
            dnd_info_label = ttk.Label(parent, text="Tip: You can also drag & drop files onto this tab.",
                                       font=(self.default_font_family, self.default_font_size - 1),
                                       foreground="grey")
            dnd_info_label.grid(row=current_row, column=0, columnspan=4, sticky=tk.W, padx=7, pady=(0,3))
        return current_row + 1

    def _create_gemini_settings_section(self, parent, start_row):
        gemini_settings_frame = ttk.LabelFrame(parent, text="Gemini Settings", padding="5")
        gemini_settings_frame.grid(row=start_row, column=0, columnspan=4, sticky=tk.EW, padx=5, pady=(5,3))
        # ... (UI Code inside LabelFrame as before, using grid row 0, 1... of gemini_settings_frame)
        gemini_settings_frame.columnconfigure(1, weight=1)
        gemini_model_label = ttk.Label(gemini_settings_frame, text="Gemini Model:")
        gemini_model_label.grid(row=0, column=0, sticky=tk.W, padx=5, pady=3)
        self.gemini_model_combo = ttk.Combobox(gemini_settings_frame, textvariable=self.gemini_model_var, width=30, state="readonly")
        self.gemini_model_combo.grid(row=0, column=1, sticky=tk.EW, padx=5, pady=3)
        self.gemini_model_combo.bind("<<ComboboxSelected>>", self._on_gemini_model_selected) # MODIFIED: Bind to new handler
        self.refresh_models_button = ttk.Button(gemini_settings_frame, text="Refresh Models", command=self._load_gemini_models)
        self.refresh_models_button.grid(row=0, column=2, padx=5, pady=3)
        ToolTip(self.refresh_models_button, "Refresh the list of available Gemini models.")
        gemini_temp_label = ttk.Label(gemini_settings_frame, text="Temperature:")
        gemini_temp_label.grid(row=0, column=3, sticky=tk.W, padx=(15,2), pady=3)
        self.gemini_temp_scale = ttk.Scale(gemini_settings_frame, from_=0.0, to=2.0, orient=tk.HORIZONTAL, variable=self.gemini_temperature_var, length=120, command=self._update_gemini_temp_display_and_round)
        self.gemini_temp_scale.grid(row=0, column=4, sticky=tk.EW, padx=0, pady=3)
        self.gemini_temp_label_val = ttk.Label(gemini_settings_frame, textvariable=self.gemini_temperature_display_var, width=4)
        self.gemini_temp_label_val.grid(row=0, column=5, sticky=tk.W, padx=(2,5), pady=3)
        ToolTip(self.gemini_temp_scale, "Controls randomness. Rounded to 0.05.")
        return start_row + 1

    def _create_targeting_section(self, parent, start_row):
        lang_keywords_frame = ttk.LabelFrame(parent, text="Targeting, Style & Context", padding="5")
        lang_keywords_frame.grid(row=start_row, column=0, columnspan=4, sticky=tk.EW, padx=5, pady=3)
        # ... (UI Code inside LabelFrame as before)
        lang_keywords_frame.columnconfigure(1, weight=1)
        lang_keywords_frame.columnconfigure(3, weight=1)
        target_lang_label = ttk.Label(lang_keywords_frame, text="Target Lang:")
        target_lang_label.grid(row=0, column=0, sticky=tk.W, padx=5, pady=3)
        self.target_translation_lang_combo = ttk.Combobox(lang_keywords_frame, textvariable=self.target_translation_lang_var, values=COMMON_LANGUAGES_GEMINI_TARGET, width=23, state="normal")
        self.target_translation_lang_combo.grid(row=0, column=1, sticky=tk.EW, padx=5, pady=3)
        self.target_translation_lang_combo.bind("<<ComboboxSelected>>", self._handle_combobox_selection_visual_reset)
        ToolTip(self.target_translation_lang_combo, "Select the desired output language for Gemini.")
        translation_style_label = ttk.Label(lang_keywords_frame, text="Translation Style:")
        translation_style_label.grid(row=0, column=2, sticky=tk.W, padx=(10,2), pady=3)
        common_styles = ["Default/Neutral", "Formal", "Informal/Colloquial", "Humorous", "Serious/Academic", "Poetic", "Anime/Manga", "Historical/Archaic", "Technical"]
        self.translation_style_combo = ttk.Combobox(lang_keywords_frame, textvariable=self.translation_style_var, values=common_styles, width=23)
        self.translation_style_combo.bind("<<ComboboxSelected>>", self._handle_combobox_selection_visual_reset)
        self.translation_style_combo.grid(row=0, column=3, sticky=tk.EW, padx=5, pady=3)
        ToolTip(self.translation_style_combo, "Optional: Specify a desired translation style/tone.")
        context_keywords_label = ttk.Label(lang_keywords_frame, text="Context Keywords:")
        context_keywords_label.grid(row=1, column=0, sticky=tk.NW, padx=5, pady=3)
        self.context_keywords_text = tk.Text(lang_keywords_frame, height=2, width=50, relief=tk.SOLID, borderwidth=1, font=self.custom_font)
        self.context_keywords_text.grid(row=1, column=1, columnspan=3, sticky=tk.EW, padx=5, pady=3)
        ToolTip(self.context_keywords_text, "Keywords in TARGET language (names, terms) for Gemini. One per line.")
        return start_row + 1

    def _create_action_buttons_section(self, parent, start_row):
        current_internal_row = start_row
        button_action_frame = ttk.Frame(parent)
        button_action_frame.grid(row=current_internal_row, column=0, columnspan=4, pady=(10,0), sticky=tk.EW)
        # ... (UI Code for the first row of buttons)
        button_action_frame.columnconfigure(0, weight=2); button_action_frame.columnconfigure(1, weight=1); button_action_frame.columnconfigure(2, weight=1); button_action_frame.columnconfigure(3, weight=1)
        self.start_gemini_button = ttk.Button(button_action_frame, text="1. Start Gemini Process", command=self._start_gemini_processing_thread)
        self.start_gemini_button.grid(row=0, column=0, padx=3, pady=3, sticky=tk.EW)
        ToolTip(self.start_gemini_button, "Extract audio and send to Gemini.")
        self.analyze_timestamps_button = ttk.Button(button_action_frame, text="2. Analyze Timestamps", command=self._start_python_timestamp_analysis_thread, state="disabled")
        self.analyze_timestamps_button.grid(row=0, column=1, padx=3, pady=3, sticky=tk.EW)
        ToolTip(self.analyze_timestamps_button, "Run analysis on current subtitles for errors.")
        self.request_gemini_fix_button = ttk.Button(button_action_frame, text="3. Request Gemini Fix", command=self._open_custom_prompt_dialog, state="disabled")
        self.request_gemini_fix_button.grid(row=0, column=2, padx=3, pady=3, sticky=tk.EW)
        ToolTip(self.request_gemini_fix_button, "Open a dialog to write a custom prompt for Gemini to fix.")
        self.cancel_button = ttk.Button(button_action_frame, text="Cancel Process", command=self._request_cancellation, state="disabled")
        self.cancel_button.grid(row=0, column=3, padx=5, pady=3, sticky=tk.E)
        ToolTip(self.cancel_button, "Request to cancel the current running operation.")

        current_internal_row +=1
        button_action_frame_row2 = ttk.Frame(parent)
        button_action_frame_row2.grid(row=current_internal_row, column=0, columnspan=4, pady=(0,5), sticky=tk.EW)
        self.review_auto_format_button = ttk.Button(button_action_frame_row2, text="Review & Apply Auto-Format", command=self._show_apply_auto_format_dialog, state="disabled")
        self.review_auto_format_button.pack(fill=tk.X, padx=3, pady=3)
        ToolTip(self.review_auto_format_button, "Review and optionally apply automatic formatting corrections.")
        return current_internal_row + 1

    def _create_progress_bar_section(self, parent, start_row):
        self.progressbar = ttk.Progressbar(parent, variable=self.progress_var, maximum=100)
        self.progressbar.grid(row=start_row, column=0, columnspan=4, pady=(5,10), sticky=tk.EW)
        return start_row + 1

    def _create_display_panes_section(self, parent_for_panes): # (Keep as is)
        # The display panes (subtitle editor and log) should be below the scrollable controls area
        display_panes = ttk.PanedWindow(self, orient=tk.VERTICAL)
        display_panes.pack(fill=tk.BOTH, expand=True, pady=5, padx=5) # Pack below the canvas/scrollbar
        self.subtitle_edit_frame, self.subtitle_edit_text_widget = self._create_text_display_area(display_panes, "Subtitle Output / Editor", height=20, is_subtitle_editor=True)
        display_panes.add(self.subtitle_edit_frame, weight=3)
        self.edit_mode_label = ttk.Label(self.subtitle_edit_frame, text="Output is editable. Run 'Analyze' or 'Save' after manual changes.", foreground="blue", font=(self.default_font_family, self.default_font_size -1))
        self.refine_timing_button = ttk.Button(self.subtitle_edit_frame, text="Refine Timing (Gaps/Overlaps)", command=self._start_refine_timing_thread, state="disabled")
        self.refine_timing_button.pack(side=tk.BOTTOM, pady=(5,2), fill=tk.X, padx=5)
        ToolTip(self.refine_timing_button, "Attempt to automatically adjust short gaps and resolve overlaps between subtitles.")
        self.save_srt_button = ttk.Button(self.subtitle_edit_frame, text="Save Subtitles as SRT", command=self._save_current_subtitles_as_srt, state="disabled")
        self.save_srt_button.pack(side=tk.BOTTOM, pady=(2,5), fill=tk.X, padx=5)
        ToolTip(self.save_srt_button, "Convert current subtitles in editor to SRT and save.")
        self.log_display_frame, self.log_text_widget = self._create_text_display_area(display_panes, "Video/Audio Tab Log & Status", height=8)
        display_panes.add(self.log_display_frame, weight=1)

    # --- Helper Functions ---
    def _browse_local_file(self): # (Keep as is)
        filepath = filedialog.askopenfilename(
            title="Select Video/Audio File",
            filetypes=(("Video Files", "*.mp4 *.mkv *.avi *.mov *.webm *.flv *.wmv"), ("Audio Files", "*.mp3 *.wav *.ogg *.flac *.aac *.m4a"), ("All Files", "*.*")),
            parent=self.app_controller
        )
        if filepath:
            self.yt_dlp_url_var.set("") # Clear yt-dlp URL if local file is selected
            self.video_url_var.set("")  # Clear direct URL if local file is selected
            self._process_selected_file(filepath, source="browse")

    def _start_direct_url_download(self):
        url = self.video_url_var.get().strip()
        if not url:
            messagebox.showwarning("Input Error", "Please enter a direct file URL.", parent=self.app_controller)
            return
        self.yt_dlp_url_var.set("") # Clear yt-dlp URL
        media_input_helpers.start_url_download_task(url, self.app_controller, self)

    def _start_yt_dlp_download(self):
        url = self.yt_dlp_url_var.get().strip()
        if not url:
            messagebox.showwarning("Input Error", "Please enter a URL for yt-dlp (e.g., YouTube).", parent=self.app_controller)
            return
        self.video_url_var.set("") # Clear direct download URL
        audio_only = self.yt_dlp_audio_only_var.get()
        yt_dlp_helper.start_yt_dlp_download_task(url, self.app_controller, self, download_audio_only=audio_only)

    def _handle_drop_event(self, event): # (Keep as is)
        if not DND_TAB_SUPPORTED: return
        self.yt_dlp_url_var.set("") # Clear URLs when dropping file
        self.video_url_var.set("")
        # Call the helper function to handle the dropped file data
        media_input_helpers.handle_dropped_file_for_tab(event.data, self, self.app_controller)

    def _process_dropped_file(self, filepath, source="drag-drop"):
        """Handles a file that was dropped onto the tab."""
        self.logger.info(f"Processing dropped file in VideoAudioTab: {filepath} (source: {source})")
        # Clear other URL inputs if a file is dropped
        self.yt_dlp_url_var.set("")
        self.video_url_var.set("")
        # Call the existing method for processing selected files
        self._process_selected_file(filepath, source=source)

    def _process_selected_file(self, filepath, source="browse"): # (Update to call Processing tab)
        if not filepath or not os.path.exists(filepath) or not os.path.isfile(filepath):
            self.logger.error(f"Invalid or non-existent file path provided for processing: {filepath} (source: {source})")
            display_filename = os.path.basename(filepath or "unknown file")
            messagebox.showerror("File Error", f"Selected file '{display_filename}' is invalid or does not exist.", parent=self.app_controller)
            self.video_file_var.set("")
            return

        self.current_video_path = filepath
        self.video_file_var.set(os.path.basename(filepath))
        # Clear other URL inputs if a file is selected
        if source != "url_direct": self.video_url_var.set("")
        if source != "yt-dlp": self.yt_dlp_url_var.set("")

        self.logger.info(f"File ready for Gemini processing (source: {source}): {filepath}")
        self._clear_all_process_states()

        # Cập nhật biến chia sẻ trong app_controller
        if self.current_video_path:
            self.app_controller.last_processed_video_path_for_sharing.set(self.current_video_path)
            self.logger.info(f"Shared video path for other tabs updated: {self.current_video_path}")

            # Ask user if they want to send to Mux/Encode Video tab
            # Automatically send to Mux/Encode Video tab after processing file
            if hasattr(self.app_controller, 'video_processing_tab') and \
               self.app_controller.video_processing_tab.winfo_exists():
                self.app_controller.video_processing_tab.input_video_path_var.set(self.current_video_path)
                # Comment out or remove the automatic tab switch
                # self.app_controller.notebook.select(self.app_controller.video_processing_tab)
                # self.logger.info("Automatically sent video path and switched to Mux/Encode Video tab.")

    # --- Remaining Logic Functions, UI State, Settings, Tasks (Keep as in the previous complete file) ---
    # (Bao gồm _set_ui_state, _round_to_nearest_005, _update_gemini_temp_display_and_round,
    # _request_cancellation, _populate_subtitle_edit_area, _clear_all_process_states,
    # _load_initial_settings_for_tab, _save_and_test_api_key, _load_gemini_models, _update_progress,
    # _set_ui_state_for_python_analysis, _save_current_ui_settings, _get_edited_subtitle_text,
    # _start_gemini_processing_thread, _task_initial_gemini_processing,
    # _start_python_timestamp_analysis_thread, _task_analyze_timestamps_python_only,
    # _show_apply_auto_format_dialog, _start_refine_timing_thread, _task_refine_timing,
    # _show_review_dialog_generic, _open_custom_prompt_dialog,
    # _start_request_gemini_fix_thread_with_custom_prompt, _task_request_gemini_fix,
    # _save_current_subtitles_as_srt, và class TextHandler)
    # Ensure you copy all these parts from the previous complete version of video_audio_tab.py
    # (After I provided the "give me the complete files, one by one if too long" and you confirmed "added"
    # and then fixed the "time" not defined error)

    # Paste those functions back here (already provided in previous responses)
    # Starting from _set_ui_state:
    def _set_ui_state(self, processing=False):
        gui_state = tk.DISABLED if processing else tk.NORMAL
        readonly_state = "readonly"

        if hasattr(self, 'browse_video_button'): self.browse_video_button.config(state=gui_state)
        if hasattr(self, 'url_file_entry'): self.url_file_entry.config(state="normal" if not processing else tk.DISABLED)
        if hasattr(self, 'load_url_button'): self.load_url_button.config(state=gui_state)
        if hasattr(self, 'yt_dlp_url_entry'): self.yt_dlp_url_entry.config(state="normal" if not processing else tk.DISABLED)
        if hasattr(self, 'yt_dlp_audio_only_check'): self.yt_dlp_audio_only_check.config(state=gui_state)
        if hasattr(self, 'yt_dlp_button'): self.yt_dlp_button.config(state=gui_state)

        if hasattr(self, 'gemini_model_combo'): self.gemini_model_combo.config(state=readonly_state if not processing else tk.DISABLED)
        if hasattr(self, 'refresh_models_button'): self.refresh_models_button.config(state=gui_state)
        if hasattr(self, 'gemini_temp_scale'): self.gemini_temp_scale.config(state=gui_state)

        # Target language combobox should be editable when not processing
        if hasattr(self, 'target_translation_lang_combo'): self.target_translation_lang_combo.config(state="normal" if not processing else tk.DISABLED)
        if hasattr(self, 'translation_style_combo'): self.translation_style_combo.config(state="normal" if not processing else tk.DISABLED)
        if hasattr(self, 'context_keywords_text'): self.context_keywords_text.config(state="normal" if not processing else tk.DISABLED)

        if hasattr(self, 'start_gemini_button'): self.start_gemini_button.config(state=gui_state)

        has_subtitle_content = False
        if hasattr(self, 'subtitle_edit_text_widget') and self.subtitle_edit_text_widget.winfo_exists():
             has_subtitle_content = bool(self.current_subtitle_data or self.subtitle_edit_text_widget.get("1.0", tk.END).strip())

        if processing:
            if hasattr(self, 'analyze_timestamps_button'): self.analyze_timestamps_button.config(state=tk.DISABLED)
            if hasattr(self, 'request_gemini_fix_button'): self.request_gemini_fix_button.config(state=tk.DISABLED)
            if hasattr(self, 'review_auto_format_button'): self.review_auto_format_button.config(state=tk.DISABLED)
            if hasattr(self, 'refine_timing_button'): self.refine_timing_button.config(state=tk.DISABLED)
            if hasattr(self, 'save_srt_button'): self.save_srt_button.config(state=tk.DISABLED)
            if hasattr(self, "edit_mode_label") and self.edit_mode_label_packed:
                try: self.edit_mode_label.pack_forget()
                except tk.TclError: pass
                self.edit_mode_label_packed = False
        else:
            if hasattr(self, 'analyze_timestamps_button'): self.analyze_timestamps_button.config(state=tk.NORMAL if has_subtitle_content else tk.DISABLED)
            if hasattr(self, 'refine_timing_button'): self.refine_timing_button.config(state=tk.NORMAL if has_subtitle_content else tk.DISABLED)
            if hasattr(self, 'save_srt_button'): self.save_srt_button.config(state=tk.NORMAL if has_subtitle_content else tk.DISABLED)

        if hasattr(self, 'cancel_button'):
            self.cancel_button.config(state=tk.NORMAL if processing else tk.DISABLED)
            if not processing:
                self.cancel_button.config(text="Cancel Process")

    # (All other functions from _round_to_nearest_005 to the end of TextHandler class, copy from the previous complete version of video_audio_tab.py)
    # ... (đảm bảo bạn đã có phần này từ các phản hồi trước)
    # ...
    # Ví dụ, copy từ đoạn này trở đi of video_audio_tab.py (sau _set_ui_state)
    def _round_to_nearest_005(self, value): # (Keep as is)
        return round(value / 0.05) * 0.05

    def _update_gemini_temp_display_and_round(self, scale_value_str): # (Keep as is)
        try:
            current_scale_val = float(scale_value_str)
            rounded_val = self._round_to_nearest_005(current_scale_val)
            if abs(self.gemini_temperature_var.get() - rounded_val) > 0.0001:
                 self.gemini_temperature_var.set(rounded_val)
            self.gemini_temperature_display_var.set(f"{rounded_val:.2f}")
        except (tk.TclError, ValueError) as e:
            self.logger.debug(f"Error updating temp display: {e}")

    def _request_cancellation(self): # (Keep as is)
        if not self.cancel_requested:
            if messagebox.askyesno("Cancel Process", "Are you sure you want to cancel the current operation?", parent=self.app_controller):
                self.logger.info("Cancellation requested by user.")
                self.cancel_requested = True
                if hasattr(self, 'cancel_button'):
                    self.cancel_button.config(text="Cancelling...", state="disabled")

    def _populate_subtitle_edit_area(self, text_content, make_editable=False): # (Keep as is)
        if not hasattr(self, 'subtitle_edit_text_widget') and not self.subtitle_edit_text_widget.winfo_exists():
            self.logger.warning("Subtitle edit text widget not available to populate.")
            return
        if not hasattr(self, 'subtitle_edit_text_widget') and not self.subtitle_edit_text_widget.winfo_exists():
            self.logger.warning("Subtitle edit text widget not available to populate.")
            return

        self.subtitle_edit_text_widget.config(state="normal")
        self.subtitle_edit_text_widget.delete("1.0", tk.END)

        # Add line numbers for display
        self.subtitle_edit_text_widget.insert("1.0", text_content.strip()) # Insert the raw, stripped content

        if make_editable:
            # Store the raw text (without line numbers) for internal use
            self.current_subtitle_data = text_content.strip()
            self.user_has_edited_subtitle_area = False
            self.subtitle_edit_text_widget.config(state="normal")
            if not self.edit_mode_label_packed:
                try:
                    if hasattr(self, 'edit_mode_label') and self.edit_mode_label.winfo_exists() and \
                       hasattr(self, 'refine_timing_button') and self.refine_timing_button.winfo_exists():
                        self.edit_mode_label.pack(side=tk.BOTTOM, before=self.refine_timing_button, pady=(0,2), padx=5, fill=tk.X)
                        self.edit_mode_label_packed = True
                except tk.TclError as e:
                    self.logger.debug(f"TclError packing edit_mode_label: {e}")
                    self.edit_mode_label_packed = False
        else:
             # Store the raw text (without line numbers) for internal use
            self.current_subtitle_data = text_content.strip()
            self.subtitle_edit_text_widget.config(state="disabled")
            if self.edit_mode_label_packed:
                try:
                    if hasattr(self, 'edit_mode_label') and self.edit_mode_label.winfo_exists():
                        self.edit_mode_label.pack_forget()
                except tk.TclError as e:
                     self.logger.debug(f"TclError forgetting edit_mode_label: {e}")
                self.edit_mode_label_packed = False

        self.subtitle_edit_text_widget.see("1.0")
        self.subtitle_edit_text_widget.edit_modified(False)
        if self.winfo_exists():
            self.update_idletasks()

    def _clear_all_process_states(self): # (Keep as is)
        self.current_subtitle_data = ""
        self.current_chat_session = None
        self.last_detailed_analysis_messages = []
        self.suggested_auto_format_text = ""
        self.user_has_edited_subtitle_area = False
        if self.full_audio_path_for_gemini and os.path.exists(self.full_audio_path_for_gemini):
            try:
                os.remove(self.full_audio_path_for_gemini)
                self.logger.info(f"Cleaned up previous temp audio: {self.full_audio_path_for_gemini}")
            except OSError as e:
                self.logger.warning(f"Could not remove previous temp audio {self.full_audio_path_for_gemini}: {e}")
        self.full_audio_path_for_gemini = None
        if hasattr(self, 'subtitle_edit_text_widget'):
            self._populate_subtitle_edit_area("Subtitle output from Gemini will appear here and will be editable.", make_editable=False)
            if hasattr(self, 'save_srt_button'): self.save_srt_button.config(state="disabled")
            if hasattr(self, 'analyze_timestamps_button'): self.analyze_timestamps_button.config(state="disabled")
            if hasattr(self, 'request_gemini_fix_button'): self.request_gemini_fix_button.config(state="disabled")
            if hasattr(self, 'review_auto_format_button'): self.review_auto_format_button.config(state="disabled")
            if hasattr(self, 'refine_timing_button'): self.refine_timing_button.config(state="disabled")
        if hasattr(self, 'progress_var'): self.progress_var.set(0)

    def _load_initial_settings_for_tab(self): # (Update to clear yt_dlp_url_var)
        if hasattr(self, 'progress_var'): self.progress_var.set(0)
        # API Key is now managed globally in MainWindow
        # self._save_and_test_api_key() # Removed - API key test/save is now done in MainWindow

        # Load other settings
        last_gemini_model = config_manager.load_last_gemini_model()
        if last_gemini_model:
            self.gemini_model_var.set(last_gemini_model)

        gemini_temp = config_manager.load_gemini_temperature()
        self.gemini_temperature_var.set(gemini_temp)
        self._update_gemini_temp_display_and_round(str(gemini_temp)) # Update display label

        target_lang = config_manager.load_target_translation_language()
        if target_lang:
            self.target_translation_lang_var.set(target_lang)
        else:
            self.target_translation_lang_var.set("Vietnamese") # Default

        translation_style = config_manager.load_setting("translation_style", default="Default/Neutral")
        self.translation_style_var.set(translation_style)

        yt_dlp_audio_only = config_manager.load_setting("yt_dlp_audio_only", default=False)
        self.yt_dlp_audio_only_var.set(yt_dlp_audio_only)

        context_keywords = config_manager.load_setting("context_keywords", default="")
        if hasattr(self, 'context_keywords_text'):
            self.context_keywords_text.delete("1.0", tk.END)
            self.context_keywords_text.insert("1.0", context_keywords)

        self.logger.info("Initial UI settings for Video/Audio tab loaded.")

        # Try to load models after loading settings (and potentially after API key is set in MainWindow)
        self._load_gemini_models()


    def _update_progress(self, value, message=None): # (Keep as is)
        if hasattr(self, 'progress_var') and self.winfo_exists():
            self.after(0, self.progress_var.set, value)
        if message:
            self.logger.info(f"PROGRESS (V/A Tab): {message} ({value:.0f}%)")

    def _set_ui_state_for_python_analysis(self, analyzing_py): # (Keep as is)
        if hasattr(self, 'start_gemini_button'): self.start_gemini_button.config(state=tk.DISABLED if analyzing_py else tk.NORMAL)
        if hasattr(self, 'analyze_timestamps_button'): self.analyze_timestamps_button.config(state=tk.DISABLED)
        if hasattr(self, 'request_gemini_fix_button'): self.request_gemini_fix_button.config(state=tk.DISABLED)
        if hasattr(self, 'review_auto_format_button'): self.review_auto_format_button.config(state=tk.DISABLED)
        has_output = False
        if hasattr(self, 'subtitle_edit_text_widget') and self.subtitle_edit_text_widget.winfo_exists():
            has_output = bool(self.current_subtitle_data or self.subtitle_edit_text_widget.get("1.0", tk.END).strip())
        if hasattr(self, 'refine_timing_button'): self.refine_timing_button.config(state=tk.DISABLED if analyzing_py else (tk.NORMAL if has_output else tk.DISABLED))
        if hasattr(self, 'save_srt_button'): self.save_srt_button.config(state=tk.DISABLED if analyzing_py else (tk.NORMAL if has_output else tk.DISABLED))
        if hasattr(self, 'cancel_button'): self.cancel_button.config(state=tk.DISABLED)
        if analyzing_py and hasattr(self, "edit_mode_label") and self.edit_mode_label_packed:
            try: self.edit_mode_label.pack_forget()
            except tk.TclError: pass
            self.edit_mode_label_packed = False

    def _save_current_ui_settings(self): # (Keep as is)
        if hasattr(self, 'gemini_model_var') and self.gemini_model_var.get():
            config_manager.save_last_gemini_model(self.gemini_model_var.get())
        if hasattr(self, 'gemini_temperature_var'):
            config_manager.save_gemini_temperature(self.gemini_temperature_var.get())
        if hasattr(self, 'target_translation_lang_var') and self.target_translation_lang_var.get():
            config_manager.save_target_translation_language(self.target_translation_lang_var.get())
        if hasattr(self, 'translation_style_var') and self.translation_style_var.get():
            config_manager.save_setting("translation_style", self.translation_style_var.get())

        # Save yt-dlp audio only setting
        if hasattr(self, 'yt_dlp_audio_only_var'):
            config_manager.save_setting("yt_dlp_audio_only", self.yt_dlp_audio_only_var.get())

        # Save context keywords
        if hasattr(self, 'context_keywords_text'):
            config_manager.save_setting("context_keywords", self.context_keywords_text.get("1.0", tk.END).strip())

        self.logger.info("Current UI settings for Video/Audio tab saved.")


    def _get_edited_subtitle_text(self): # (Keep as is)
        if hasattr(self, 'subtitle_edit_text_widget') and \
           self.subtitle_edit_text_widget.cget("state") == "normal" and \
           self.user_has_edited_subtitle_area:
            widget_content = self.subtitle_edit_text_widget.get("1.0", tk.END).strip()
            if widget_content != self.current_subtitle_data:
                self.logger.info("User edits from subtitle editor applied to internal data.")
                self.current_subtitle_data = widget_content
            self.user_has_edited_subtitle_area = False
        return self.current_subtitle_data

    # --- CORE LOGIC THREADS AND TASKS ---
    def _task_initial_gemini_processing(self):
        """
        Task to extract audio, send to Gemini, and process the initial response.
        Runs in a separate thread.
        """
        try:
            self._update_progress(5, "Extracting audio...")
            temp_audio_path = ffmpeg_utils.extract_audio(self.current_video_path) # Use self.app_controller and self._update_progress if extract_audio function supports it
            if self.cancel_requested:
                self.logger.info("Cancellation requested during audio extraction.")
                return

            if not temp_audio_path or not os.path.exists(temp_audio_path):
                self.after(0, lambda: messagebox.showerror("Processing Error", "Failed to extract audio.", parent=self.app_controller))
                self.logger.error("Audio extraction failed.")
                return

            self.full_audio_path_for_gemini = temp_audio_path
            self.logger.info(f"Audio extracted to: {temp_audio_path}")

            self._update_progress(20, "Sending audio to Gemini...")

            # Prepare prompt and audio part
            target_lang = self.target_translation_lang_var.get()
            translation_style = self.translation_style_var.get().strip()
            style_instruction = f"Ensure the translation adopts a '{translation_style}' style." if translation_style and translation_style.lower() not in ["default/neutral", "default", "neutral", ""] else "Use a neutral and natural style."

            context_keywords = self.context_keywords_text.get("1.0", tk.END).strip()
            keywords_string_formatted = ", ".join([kw.strip() for kw in context_keywords.splitlines() if kw.strip()])

            initial_prompt = INITIAL_GEMINI_PROMPT_TEMPLATE.format(
                target_lang=target_lang,
                style_instruction=style_instruction,
                keywords_string_formatted=keywords_string_formatted
            )

            prompt_part = gemini_utils.to_part(initial_prompt)
            with open(temp_audio_path, 'rb') as f_audio:
                audio_bytes = f_audio.read()
            audio_part = gemini_utils.to_part({"mime_type": "audio/wav", "data": audio_bytes})

            if self.cancel_requested:
                self.logger.info("Cancellation requested before sending to Gemini.")
                return

            self._update_progress(40, "Waiting for Gemini response...")
            selected_model = self.gemini_model_var.get()
            temperature = self.gemini_temperature_var.get()

            chat = gemini_utils.start_gemini_chat(model_name_from_user=selected_model, initial_history=None) # Removed temperature as start_gemini_chat doesn't use it, temperature is used in send_message
            self.current_chat_session = chat # Store chat session for follow-ups

            response_text = gemini_utils.send_message_to_chat(chat, [prompt_part, audio_part], temperature)

            if self.cancel_requested:
                self.logger.info("Cancellation requested after Gemini response.")
                return

            if response_text is None or response_text.startswith(("[Error]", "[Blocked]")):
                self.logger.error(f"Gemini API call failed/blocked. Response: {response_text}")
                self.after(0, lambda resp=response_text: messagebox.showerror("Gemini API Error", f"Gemini processing failed or was blocked.\nDetails: {resp}", parent=self.app_controller))
                self.current_chat_session = None # Clear session on failure
            else:
                self.logger.info("Received initial response from Gemini.")
                self.current_subtitle_data = response_text.strip()
                self.after(0, lambda text=response_text.strip(): self._populate_subtitle_edit_area(text, make_editable=True))
                self.after(0, lambda: messagebox.showinfo("Gemini Process Complete", "Initial Gemini processing complete. Please review the output.", parent=self.app_controller))

            self._update_progress(100, "Gemini processing complete.")

        except Exception as e:
            if not self.cancel_requested:
                self.logger.error(f"Critical error during initial Gemini processing: {e}", exc_info=True)
                self.after(0, lambda err=e: messagebox.showerror("Critical Error", f"An unexpected error occurred during Gemini processing: {err}. Check logs.", parent=self.app_controller))
            self._update_progress(100, "Gemini processing failed or cancelled.")
        finally:
            # Clean up temp audio file regardless of success/failure, unless cancelled midway
            if self.full_audio_path_for_gemini and os.path.exists(self.full_audio_path_for_gemini):
                 try:
                     os.remove(self.full_audio_path_for_gemini)
                     self.logger.info(f"Cleaned up temp audio: {self.full_audio_path_for_gemini}")
                 except OSError as e:
                     self.logger.warning(f"Could not remove temp audio {self.full_audio_path_for_gemini}: {e}")
            self.full_audio_path_for_gemini = None # Reset the path
            self.after(0, self._set_ui_state, False)
            if self.cancel_requested:
                 self.logger.info("Initial Gemini process was cancelled by user.")
    def _start_gemini_processing_thread(self):
        """
        Starts a thread for the initial Gemini processing task.
        """
        if not self.current_video_path:
            messagebox.showerror("Input Error", "Please select a video or audio file first (local, URL, or drag & drop).", parent=self.app_controller)
            return
        # API Key check is now handled by MainWindow, but a quick check here is good practice before starting a task
        if not hasattr(self.app_controller, 'api_key_var') or not self.app_controller.api_key_var.get():
             messagebox.showerror("Setup Error", "Gemini API Key is not set. Please enter and save it in the main window.", parent=self.app_controller)
             return
        if not hasattr(self, 'gemini_model_var') or not self.gemini_model_var.get():
            messagebox.showerror("Setup Error", "Please select a Gemini Model.", parent=self.app_controller)
            return

        self._save_current_ui_settings()
        self.cancel_requested = False
        self._set_ui_state(processing=True)
        self.logger.info(f"Starting Gemini Processing for: {os.path.basename(self.current_video_path)}")
        self.progress_var.set(0)

        import threading
        # The target method is now a correct instance method, no need to pass 'self' explicitly in args
        thread = threading.Thread(target=self._task_initial_gemini_processing, daemon=True)
        thread.start()

    def _start_python_timestamp_analysis_thread(self): # (Keep as is)
        text_to_analyze = self._get_edited_subtitle_text()
        if not text_to_analyze:
            messagebox.showerror("Error", "No subtitle content available to analyze.", parent=self.app_controller)
            return
        self._set_ui_state_for_python_analysis(True)
        self.logger.info("Starting detailed subtitle timestamp analysis...")
        from . import video_audio_tasks # Import the tasks module
        import threading
        thread = threading.Thread(target=video_audio_tasks.task_analyze_timestamps_python_only, args=(self.app_controller, self, text_to_analyze,), daemon=True)
        thread.start()

    def _show_apply_auto_format_dialog(self): # (Keep as is)
        current_text_from_editor = self._get_edited_subtitle_text()
        if not hasattr(self, 'suggested_auto_format_text') or not self.suggested_auto_format_text:
            messagebox.showinfo("No Auto-Format Suggestions", "No auto-format suggestions available (run analysis first).", parent=self.app_controller)
            if hasattr(self, 'review_auto_format_button'): self.review_auto_format_button.config(state=tk.DISABLED)
            return
        if self.suggested_auto_format_text.strip() == current_text_from_editor.strip():
            messagebox.showinfo("No Changes by Auto-Format", "Auto-formatting did not introduce any changes to the current text.", parent=self.app_controller)
            if hasattr(self, 'review_auto_format_button'): self.review_auto_format_button.config(state=tk.DISABLED)
            return
        self._show_review_dialog_generic(
            original_text=current_text_from_editor,
            processed_text=self.suggested_auto_format_text,
            dialog_title="Review Auto-Formatting Suggestions",
            processed_label="Auto-Formatted Version (Python Pre-correction)",
            action_type="auto_format"
        )

    def _start_refine_timing_thread(self): # (Keep as is)
        current_subtitle_text_to_opt = self._get_edited_subtitle_text()
        if not current_subtitle_text_to_opt:
            messagebox.showerror("Error", "No subtitle content available to refine.", parent=self.app_controller)
            return
        if messagebox.askyesno("Confirm Timing Refinement",
                               "This will attempt to automatically adjust short gaps and resolve overlaps in the current subtitles. "
                               "It's recommended to run 'Analyze Timestamps' first.\n\nProceed with timing refinement?",
                               parent=self.app_controller):
            self.logger.info("Starting subtitle timing refinement...")
            self._set_ui_state(processing=True)
            self.cancel_requested = False
            import threading
            thread = threading.Thread(target=video_audio_tasks.task_refine_timing, args=(self.app_controller, self, current_subtitle_text_to_opt,), daemon=True)
            thread.start()

    def _show_review_dialog_generic(self, original_text, processed_text, dialog_title, processed_label, action_type=None): # (Keep as is)
        dialog = tk.Toplevel(self.app_controller)
        dialog.title(dialog_title); dialog.transient(self.app_controller); dialog.grab_set(); dialog.resizable(True, True)
        dialog_width = 850; dialog_height = 600
        parent_x = self.app_controller.winfo_x(); parent_y = self.app_controller.winfo_y()
        parent_width = self.app_controller.winfo_width(); parent_height = self.app_controller.winfo_height()
        x_pos = parent_x + (parent_width // 2) - (dialog_width // 2); y_pos = parent_y + (parent_height // 2) - (dialog_height // 2)
        dialog.geometry(f"{dialog_width}x{dialog_height}+{max(0,x_pos)}+{max(0,y_pos)}")
        dialog.minsize(600, 400)
        main_dialog_frame = ttk.Frame(dialog, padding=10); main_dialog_frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(main_dialog_frame, text="Compare current subtitle text with the processed version:").pack(anchor="w", pady=(0,5))
        pane = ttk.PanedWindow(main_dialog_frame, orient=tk.HORIZONTAL); pane.pack(fill=tk.BOTH, expand=True, pady=5)
        original_frame = ttk.LabelFrame(pane, text="Current Text in Editor", padding=5)
        original_text_widget = tk.Text(original_frame, wrap=tk.WORD, height=20, font=self.custom_font, relief=tk.SOLID, borderwidth=1, undo=False)
        original_scrollbar_y = ttk.Scrollbar(original_frame, orient=tk.VERTICAL, command=original_text_widget.yview)
        original_scrollbar_x = ttk.Scrollbar(original_frame, orient=tk.HORIZONTAL, command=original_text_widget.xview)
        original_text_widget.config(yscrollcommand=original_scrollbar_y.set, xscrollcommand=original_scrollbar_x.set, wrap="none")
        original_scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y); original_scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)
        original_text_widget.pack(fill=tk.BOTH, expand=True); original_text_widget.insert("1.0", original_text); original_text_widget.config(state="disabled")
        pane.add(original_frame, weight=1)
        corrected_frame = ttk.LabelFrame(pane, text=processed_label, padding=5)
        corrected_text_widget = tk.Text(corrected_frame, wrap=tk.WORD, height=20, font=self.custom_font, relief=tk.SOLID, borderwidth=1, undo=False)
        corrected_scrollbar_y = ttk.Scrollbar(corrected_frame, orient=tk.VERTICAL, command=corrected_text_widget.yview)
        corrected_scrollbar_x = ttk.Scrollbar(corrected_frame, orient=tk.HORIZONTAL, command=corrected_text_widget.xview)
        corrected_text_widget.config(yscrollcommand=corrected_scrollbar_y.set, xscrollcommand=corrected_scrollbar_x.set, wrap="none")
        corrected_scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y); corrected_scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)
        corrected_text_widget.pack(fill=tk.BOTH, expand=True); corrected_text_widget.insert("1.0", processed_text); corrected_text_widget.config(state="disabled")
        pane.add(corrected_frame, weight=1)
        button_frame = ttk.Frame(main_dialog_frame); button_frame.pack(fill=tk.X, pady=(10,0))
        def apply_changes():
            self._populate_subtitle_edit_area(processed_text, make_editable=True)
            self.logger.info(f"Applied '{processed_label}' to editor. Recommended: Run 'Analyze Timestamps' again if content structure changed.")
            if action_type == "auto_format" and hasattr(self, 'review_auto_format_button'):
                 self.review_auto_format_button.config(state=tk.DISABLED)
            dialog.destroy()
            messagebox.showinfo("Changes Applied", f"'{processed_label}' has been applied to the editor. \nPlease review and consider running 'Analyze Timestamps' again.", parent=self.app_controller)
        apply_button_text = f"Apply These '{processed_label}'"
        apply_style = "TButton"
        try:
            if "Accent.TButton" in self.app_controller.style.theme_names() and \
               self.app_controller.style.layout("Accent.TButton"):
                apply_style = "Accent.TButton"
        except tk.TclError: pass
        apply_button = ttk.Button(button_frame, text=apply_button_text, command=apply_changes, style=apply_style)
        apply_button.pack(side=tk.LEFT, padx=5)
        cancel_button = ttk.Button(button_frame, text="Close (Do Not Apply)", command=dialog.destroy)
        cancel_button.pack(side=tk.LEFT, padx=5)
        self.app_controller.wait_window(dialog)

    def _open_custom_prompt_dialog(self): # (Keep as is)
        if not hasattr(self, 'current_chat_session') or not self.current_chat_session:
            messagebox.showerror("Error", "No active Gemini chat session. Please run the initial Gemini process first.", parent=self.app_controller)
            return
        if not hasattr(self, 'current_subtitle_data') or not self.current_subtitle_data:
            messagebox.showerror("Error", "No subtitle content to send for fixing. Please generate or load subtitles first.", parent=self.app_controller)
            return
        dialog = tk.Toplevel(self.app_controller)
        dialog.title("Custom Prompt for Gemini Fix"); dialog.transient(self.app_controller); dialog.grab_set(); dialog.resizable(True, True)
        dialog_width = 700; dialog_height = 550
        parent_x = self.app_controller.winfo_x(); parent_y = self.app_controller.winfo_y()
        parent_width = self.app_controller.winfo_width(); parent_height = self.app_controller.winfo_height()
        x_pos = parent_x + (parent_width // 2) - (dialog_width // 2); y_pos = parent_y + (parent_height // 2) - (dialog_height // 2)
        dialog.geometry(f"{dialog_width}x{dialog_height}+{max(0,x_pos)}+{max(0,y_pos)}")
        dialog.minsize(500, 400)
        main_frame = ttk.Frame(dialog, padding=10); main_frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(main_frame, text="Edit the prompt below to guide Gemini on how to fix the current subtitles:", wraplength=dialog_width-30).pack(pady=(0,10), anchor="w")
        text_frame = ttk.Frame(main_frame); text_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        prompt_text_widget = tk.Text(text_frame, wrap=tk.WORD, height=20, undo=True, font=self.custom_font, relief=tk.SOLID, borderwidth=1)
        prompt_text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=prompt_text_widget.yview); scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        prompt_text_widget.config(yscrollcommand=scrollbar.set)
        analysis_feedback_lines = []
        actionable_issues_for_gemini = []
        if hasattr(self, 'last_detailed_analysis_messages') and self.last_detailed_analysis_messages:
            for msg in self.last_detailed_analysis_messages:
                if ("ERROR" in msg.upper() or "WARNING" in msg.upper()) and "main app log" not in msg.lower():
                    actionable_issues_for_gemini.append(msg.split(":", 1)[1].strip() if ":" in msg else msg)
        if actionable_issues_for_gemini:
            analysis_feedback_lines.append("\nPotential issues identified by local analysis (please verify and guide correction):")
            for i, msg in enumerate(actionable_issues_for_gemini):
                if i < 7:
                    analysis_feedback_lines.append(f"- {msg}")
            if len(actionable_issues_for_gemini) > 7:
                analysis_feedback_lines.append("- ... (and other issues. Focus on these primary ones or refer to the full subtitle text).")
        else:
            analysis_feedback_lines.append("\n(No specific critical issues auto-detected by local analysis, or analysis not run recently. Describe the desired fixes.)")
        analysis_feedback_str = "\n".join(analysis_feedback_lines)
        translation_style_for_fix = self.translation_style_var.get().strip()
        style_reminder = f"Maintain '{translation_style_for_fix}' style." if translation_style_for_fix and translation_style_for_fix.lower() not in ["default/neutral", "default", "neutral", ""] else "Maintain neutral and natural style."
        final_custom_prompt = CUSTOM_FIX_PROMPT_HEADER_TEMPLATE.format(
            analysis_feedback=analysis_feedback_str,
            style_reminder=style_reminder,
            current_subtitle_text=self.current_subtitle_data
        )
        prompt_text_widget.insert("1.0", final_custom_prompt)
        ttk.Label(main_frame, text="Note: The prompt above includes the current text from the editor for Gemini's reference.",
                  wraplength=dialog_width-30, font=(self.default_font_family, self.default_font_size -1), foreground="blue").pack(pady=(5,0), anchor="w")
        button_frame = ttk.Frame(main_frame); button_frame.pack(fill=tk.X, pady=(10,0))
        def on_submit():
            prompt_content = prompt_text_widget.get("1.0", tk.END).strip()
            if not prompt_content:
                messagebox.showwarning("Empty Prompt", "Custom prompt cannot be empty.", parent=dialog)
                return
            dialog.destroy()
            self._start_request_gemini_fix_thread_with_custom_prompt(prompt_content)
        submit_style = "TButton"
        try:
            if "Accent.TButton" in self.app_controller.style.theme_names() and \
               self.app_controller.style.layout("Accent.TButton"):
                submit_style = "Accent.TButton"
        except tk.TclError: pass
        submit_button = ttk.Button(button_frame, text="Send to Gemini", command=on_submit, style=submit_style)
        submit_button.pack(side=tk.RIGHT, padx=5)
        cancel_button = ttk.Button(button_frame, text="Cancel", command=dialog.destroy)
        cancel_button.pack(side=tk.RIGHT)
        prompt_text_widget.focus_set()
        self.app_controller.wait_window(dialog)

    def _start_request_gemini_fix_thread_with_custom_prompt(self, custom_prompt): # (Keep as is)
        if not hasattr(self, 'current_chat_session') or not self.current_chat_session:
            messagebox.showerror("Error", "No active Gemini chat session. Please run initial Gemini process first.", parent=self.app_controller)
            return
        if not custom_prompt:
            messagebox.showerror("Error", "Custom prompt is empty. Cannot send to Gemini.", parent=self.app_controller)
            return
        self.cancel_requested = False
        self._set_ui_state(processing=True)
        self.progress_var.set(0)
        self.logger.info("Requesting Gemini Fix with Custom Prompt...")
        import threading
        thread = threading.Thread(target=video_audio_tasks.task_request_gemini_fix, args=(self.app_controller, self, custom_prompt,), daemon=True)
        thread.start()

    def _save_current_subtitles_as_srt(self): # (Update to use shared variable for Processing tab)
        text_to_convert = self._get_edited_subtitle_text()
        if not text_to_convert:
            messagebox.showwarning("Save Error", "No subtitle content to save.", parent=self.app_controller)
            return

        self.logger.info("Preparing to Save SRT (Final Analysis & Conversion)...")
        final_analysis_messages = srt_utils.detailed_analyze_gemini_output(text_to_convert.splitlines())
        actionable_issues_for_save_warning = []
        if final_analysis_messages:
            for msg in final_analysis_messages:
                if "ERROR" in msg.upper() or "WARNING" in msg.upper():
                    actionable_issues_for_save_warning.append(msg)
        if actionable_issues_for_save_warning:
            self.logger.warning("Final Analysis before SRT save: Potential critical issues found.")
            log_preview_for_messagebox = [f"- {msg}" for i, msg in enumerate(actionable_issues_for_save_warning) if i < 7]
            if len(actionable_issues_for_save_warning) > 7:
                log_preview_for_messagebox.append(f"\n... and {len(actionable_issues_for_save_warning)-7} more items. Check tab log.")
            preview_text = "\n".join(log_preview_for_messagebox)
            if not messagebox.askyesno("Potential Issues Before Saving SRT",
                                       f"Final analysis found potential issues in the current subtitles:\n{preview_text}\n\n"
                                       "SRT conversion will attempt to skip lines with critical errors. "
                                       "Do you want to proceed with saving?",
                                       parent=self.app_controller):
                self.logger.info("SRT save cancelled by user due to final analysis warnings."); return
        else:
            self.logger.info("Final Analysis: No critical issues detected by Python. Proceeding with SRT conversion.")
        srt_content, conversion_errors = srt_utils.convert_gemini_format_to_srt_content(text_to_convert, apply_python_normalization=True)
        if conversion_errors:
            self.logger.warning("SRT Conversion Warnings/Errors (these occurred AFTER Python pre-normalization):")
            error_summary_for_user = []
            for i, err_msg in enumerate(conversion_errors):
                self.logger.warning(f"  SRT_SAVE_CONV_ERR: {err_msg}")
                if i < 10: error_summary_for_user.append(err_msg)
            if len(conversion_errors) > 10:
                error_summary_for_user.append(f"...and {len(conversion_errors)-10} more issues. Check tab log for full details.")
            if not actionable_issues_for_save_warning or len(actionable_issues_for_save_warning) < 3:
                messagebox.showwarning("SRT Conversion Issues",
                                       "Some lines had issues during the final SRT conversion step:\n" +
                                       "\n".join(error_summary_for_user) +
                                       "\n\nThe SRT file will be generated with valid lines only. Please check the tab log.",
                                       parent=self.app_controller)
        if not srt_content.strip():
            messagebox.showerror("Save SRT Error", "No valid subtitle data could be converted to SRT format. Cannot save SRT file.", parent=self.app_controller)
            self.logger.error("No valid SRT content generated. File not saved."); return
        default_filename_base = "subtitles"
        if hasattr(self, 'current_video_path') and self.current_video_path:
            default_filename_base = os.path.splitext(os.path.basename(self.current_video_path))[0]
        target_lang_short = self.target_translation_lang_var.get()[:3].lower() if hasattr(self, 'target_translation_lang_var') and self.target_translation_lang_var.get() else "trans"
        default_filename = f"{default_filename_base}_{target_lang_short}.srt"
        save_path = filedialog.asksaveasfilename(
            title="Save Subtitles as SRT", initialfile=default_filename, defaultextension=".srt",
            filetypes=(("SubRip Subtitle", "*.srt"), ("All files", "*.*")), parent=self.app_controller
        )
        if not save_path:
            self.logger.info("SRT save cancelled by user (file dialog)."); return
        if srt_utils.save_srt_file(srt_content, save_path):
            self.logger.info(f"Successfully saved SRT to: {save_path}")
            messagebox.showinfo("SRT Saved", f"SRT file saved successfully to:\n{save_path}", parent=self.app_controller)

            # Update shared variable for processing tab
            if hasattr(self.app_controller, 'last_generated_srt_path_for_sharing'):
                 self.app_controller.last_generated_srt_path_for_sharing.set(save_path)
                 self.logger.info(f"Shared SRT path for other tabs updated: {save_path}")

            # Ask user if they want to send to Mux/Encode Video tab and switch tab if they agree
            if hasattr(self.app_controller, 'last_processed_video_path_for_sharing') and self.app_controller.last_processed_video_path_for_sharing.get(): # Chỉ hỏi nếu có video đã được xử lý
                # Dynamically get the actual tab name for consistency
                processing_tab_actual_name = "Mux/Encode Video" # Default value in case dynamic retrieval fails
                if hasattr(self.app_controller, 'notebook') and \
                   hasattr(self.app_controller, 'video_processing_tab') and \
                   self.app_controller.video_processing_tab.winfo_exists():
                    try:
                        # Get the actual text displayed on the tab
                        retrieved_name = self.app_controller.notebook.tab(self.app_controller.video_processing_tab, "text")
                        if retrieved_name: # Ensure a name was actually retrieved
                            processing_tab_actual_name = retrieved_name
                    except tk.TclError:
                        self.logger.warning(f"Could not dynamically get the {processing_tab_actual_name} tab name. Using default: '%s'", processing_tab_actual_name)

                if messagebox.askyesno(f"Switch to {processing_tab_actual_name}?",
                                       f"Do you agree to import the working video file and exported subtitles to the {processing_tab_actual_name} for Encode or Mux?", # TODO: Consider a more descriptive message
                                       parent=self.app_controller):
                    if hasattr(self.app_controller, 'video_processing_tab') and \
                       self.app_controller.video_processing_tab.winfo_exists():
                        if hasattr(self.app_controller.video_processing_tab, 'input_video_path_var'):
                            self.app_controller.video_processing_tab.input_video_path_var.set(self.app_controller.last_processed_video_path_for_sharing.get()) # Pass video path
                        if hasattr(self.app_controller.video_processing_tab, 'input_subtitle_path_var'):
                            self.app_controller.video_processing_tab.input_subtitle_path_var.set(save_path) # Set SRT path directly

                        input_video_path = self.app_controller.last_processed_video_path_for_sharing.get()
                        if input_video_path and os.path.exists(input_video_path):
                            video_name_no_ext, video_ext = os.path.splitext(os.path.basename(input_video_path))
                            output_dir = os.path.dirname(input_video_path)
                            default_name = f"{video_name_no_ext}_processed_final.mkv" # Default MKV for suggestion
                            # The VideoProcessingTab will handle its own output path suggestion when inputs are set.

                        if hasattr(self.app_controller, 'notebook'):
                            self.app_controller.notebook.select(self.app_controller.video_processing_tab) # Switch tab
                            self.logger.info(f"User confirmed and automatically sent saved SRT and recent video path, and switched to {processing_tab_actual_name} tab.")
                        else:
                           self.logger.warning(f"Could not switch to {processing_tab_actual_name} tab.")
                    else: # Corresponds to: if hasattr(self.app_controller, 'video_processing_tab') and self.app_controller.video_processing_tab.winfo_exists():
                        self.logger.warning(f"{processing_tab_actual_name} tab not available or does not exist.")
                else: # Corresponds to: if messagebox.askyesno(...)
                    self.logger.info(f"User chose NOT to switch to {processing_tab_actual_name} tab.")
            else: # Corresponds to: if hasattr(self.app_controller, 'last_processed_video_path_for_sharing') ...
                self.logger.info(f"No recent video path available to send to {processing_tab_actual_name} tab.")
        else: # srt_utils.save_srt_file failed
            messagebox.showerror("Save SRT Error", f"Failed to write SRT file to '{save_path}'. Check permissions and logs.", parent=self.app_controller)

# --- TextHandler for GUI Logging (Local to this tab) ---
class TextHandler(logging.Handler):
    def __init__(self, text_widget, tab_logger):
        super().__init__()
        self.text_widget = text_widget
        self.tab_logger = tab_logger
        self.formatter = logging.Formatter('%(asctime)s %(levelname)-7s: (%(name)s) %(message)s', datefmt='%H:%M:%S')

    def format(self, record):
        return self.formatter.format(record)

    def emit(self, record):
        if not record.name.startswith(self.tab_logger.name):
            return
        msg = self.format(record)
        try:
            if hasattr(self, 'text_widget') and self.text_widget.winfo_exists():
                self.text_widget.after(0, self._append_text_thread_safe, msg + '\n')
        except tk.TclError:
            pass
        except Exception as e:
            print(f"Error emitting log to GUI (TextHandler): {e}")

    def _append_text_thread_safe(self, text_to_append):
        try:
            if not hasattr(self, 'text_widget') or not self.text_widget.winfo_exists(): return
            current_state = self.text_widget.cget("state")
            self.text_widget.config(state=tk.NORMAL)
            self.text_widget.insert(tk.END, text_to_append)
            self.text_widget.config(state=current_state)
            self.text_widget.see(tk.END)
        except tk.TclError:
            pass
        except Exception as e:
            print(f"Error appending text to GUI log widget (TextHandler): {e}")