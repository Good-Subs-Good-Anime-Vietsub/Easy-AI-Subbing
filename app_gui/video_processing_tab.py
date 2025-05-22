# EasyAISubbing/app_gui/video_processing_tab.py
# This file was previously part of Gemini Subtitler Pro vNext
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import logging
import os
import threading # Will be needed when adding encode/mux tasks
import time # For generating unique filenames or time-related tasks
import subprocess # To run FFMPEG
import re # Import re for regex parsing
import tkinter.colorchooser # Import colorchooser
from queue import Queue, Empty # Import Queue and Empty for thread-safe communication

# Try importing tkinterdnd2 for drag and drop support
DND_TAB_SUPPORTED = False # Initialize DND support flag
try:
    from tkinterdnd2 import DND_FILES # Only need DND_FILES for drop_target_register
    DND_TAB_SUPPORTED = True
except ImportError:
    DND_TAB_SUPPORTED = False

from core import ffmpeg_utils # Will be needed for calling ffmpeg
from .ui_utils import ToolTip # Will be needed when adding detailed tooltips
from . import video_processing_tasks # Import the tasks module
from core import config_manager # Import config_manager here to avoid circular dependency


logger = logging.getLogger(__name__) # Will be app_gui.video_processing_tab


class VideoProcessingTab(ttk.Frame):
    def __init__(self, parent_notebook, app_controller):
        super().__init__(parent_notebook)
        self.app_controller = app_controller
        self.logger = logging.getLogger(f"app_gui.{__name__}") # Separate logger for this tab

        # --- Style and Font (inherited from app_controller) ---
        self.default_font_family = self.app_controller.default_font_family
        self.default_font_size = self.app_controller.default_font_size
        self.custom_font = self.app_controller.custom_font
        # self.custom_bold_font = self.app_controller.custom_bold_font

        # --- Tab-specific State Variables ---
        self.input_video_path_var = tk.StringVar()
        self.input_subtitle_path_var = tk.StringVar()
        self.output_file_path_var = tk.StringVar() # This will now store directory path
        self.process_mode_var = tk.StringVar(value="mux") # "mux" (softsub) or "hardsub"
        self.processing_status_var = tk.StringVar(value="Idle.")
        self.processing_progress_var = tk.DoubleVar(value=0)
        self.cancel_video_processing_requested = False
        self._ffmpeg_process = None # To hold the subprocess object
        self._stdout_queue = Queue() # Queue for thread-safe stdout reading
        self._stderr_queue = Queue() # Queue for thread-safe stderr reading
        self._stdout_thread = None # To hold the stdout reading thread
        self._stderr_thread = None # To hold the stderr reading thread
        self.video_duration = 0 # Add video_duration attribute

        # Hardsub Options Variables
        self.hardsub_font_var = tk.StringVar(value="Arial")
        self.hardsub_size_var = tk.StringVar(value="24")
        self.hardsub_color_var = tk.StringVar(value="&H00FFFFFF") # Default white in ASS format
        self.hardsub_outline_color_var = tk.StringVar(value="&H00000000") # Default black outline
        self.hardsub_outline_var = tk.StringVar(value="1") # Default outline thickness
        self.hardsub_shadow_var = tk.StringVar(value="0.5") # Default shadow thickness
        self.hardsub_position_var = tk.StringVar(value="Bottom Center") # Simple position for UI
        self.hardsub_resolution_var = tk.StringVar(value="") # e.g., 1920x1080
        self.hardsub_crf_var = tk.StringVar(value="23") # Default CRF for libx264
        self.video_encoder_var = tk.StringVar(value="libx264") # Default video encoder
        self.hardsub_font_encoding_var = tk.StringVar(value="UTF-8") # Default font encoding
        self.audio_handling_var = tk.StringVar(value="copy") # Default audio handling
        self.output_format_var = tk.StringVar(value="mp4") # Default output format

        # --- Load Settings ---
        self._load_settings()

        # --- Build Tab UI ---
        self._init_tab_ui()
        self.logger.info("VideoProcessingTab UI initialized.")

        if DND_TAB_SUPPORTED:
            # Register the tab frame itself as a drop target for files
            try:
                 self.drop_target_register(DND_FILES) # Register 'self' (the tab frame)
                 self.dnd_bind('<<Drop>>', self._handle_drop_event)
                 self.logger.info("Drag and drop target registered for VideoProcessingTab (on tab frame).")
            except Exception as e:
                 self.logger.error(f"Failed to register D&D target on VideoProcessingTab frame: {e}")
                 # Even if registration fails, set DND_TAB_SUPPORTED to False for this instance
                 self.logger.error(f"Failed to register D&D target on VideoProcessingTab frame: {e}")
                 # Set DND_TAB_SUPPORTED to False for this instance only if the import failed (handled at module level)
                 # If import succeeded but registration failed, DND_TAB_SUPPORTED remains True
                 pass # Removed redundant DND_TAB_SUPPORTED = False assignment here
        else:
            self.logger.warning("Drag and drop for VideoProcessingTab disabled (tkinterdnd2 missing).")

    def _handle_drop_event(self, event):
        """Handles files dropped onto the tab."""
        if not DND_TAB_SUPPORTED: return # Should not happen if button is disabled, but good practice
        from . import media_input_helpers # Import locally to avoid circular dependency

        # Call the shared helper function
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

        video_extensions = (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm")
        subtitle_extensions = (".srt", ".ass", ".ssa", ".vtt")

        if file_extension in video_extensions:
            self.input_video_path_var.set(filepath)
            self.logger.info(f"Video file processed from drop: {filepath}")
            # Suggest output directory
            input_dir = os.path.dirname(filepath)
            self.output_file_path_var.set(input_dir)
            self.logger.info(f"Suggested output directory: {input_dir}")
            # Clear subtitle input if a new video is dropped
            self.input_subtitle_path_var.set("")
            self._update_hardsub_ui_state() # Update UI state if needed

        elif file_extension in subtitle_extensions:
            self.input_subtitle_path_var.set(filepath)
            self.logger.info(f"Subtitle file processed from drop: {filepath}")
            self._update_hardsub_ui_state() # Update UI state based on new subtitle type

        else:
            messagebox.showwarning("Unsupported File Type",
                                   f"Dropped file type '{file_extension}' is not supported by the Video Processing tab. "
                                   "Please drop a video (.mp4, .mkv, etc.) or subtitle (.srt, .ass, etc.) file.",
                                   parent=self.app_controller)
            self.logger.warning(f"Unsupported file type dropped on Video Processing tab: {filepath}")

    def _load_settings(self):
        """Loads settings for the Video Processing tab from config."""
        # from core import config_manager # Import locally to avoid circular dependency if core imports app_gui

        self.process_mode_var.set(config_manager.load_setting("video_processing_mode", "mux"))
        self.hardsub_font_var.set(config_manager.load_setting("hardsub_font", "Arial"))
        self.hardsub_size_var.set(config_manager.load_setting("hardsub_size", "24"))
        self.hardsub_color_var.set(config_manager.load_setting("hardsub_color", "&H00FFFFFF"))
        self.hardsub_outline_color_var.set(config_manager.load_setting("hardsub_outline_color", "&H00000000"))
        self.hardsub_outline_var.set(config_manager.load_setting("hardsub_outline", "1"))
        self.hardsub_shadow_var.set(config_manager.load_setting("hardsub_shadow", "0.5"))
        self.hardsub_position_var.set(config_manager.load_setting("hardsub_position", "Bottom Center"))
        self.hardsub_resolution_var.set(config_manager.load_setting("hardsub_resolution", "Original"))
        self.hardsub_crf_var.set(config_manager.load_setting("hardsub_crf", "23"))
        self.video_encoder_var.set(config_manager.load_setting("video_encoder", "libx264")) # Load encoder setting
        self.hardsub_font_encoding_var.set(config_manager.load_setting("hardsub_font_encoding", "UTF-8")) # Load font encoding
        self.audio_handling_var.set(config_manager.load_setting("audio_handling", "copy")) # Load audio handling
        self.output_format_var.set(config_manager.load_setting("output_format", "mp4")) # Load output format
        self.output_file_path_var.set(config_manager.load_setting("output_directory", "")) # Load output directory

        self.logger.info("Video Processing tab settings loaded.")

    def _save_settings(self):
        """Saves current settings of the Video Processing tab to config."""
        # from core import config_manager # Import locally

        config_manager.save_setting("video_processing_mode", self.process_mode_var.get())
        config_manager.save_setting("hardsub_font", self.hardsub_font_var.get())
        config_manager.save_setting("hardsub_size", self.hardsub_size_var.get())
        config_manager.save_setting("hardsub_color", self.hardsub_color_var.get())
        config_manager.save_setting("hardsub_outline_color", self.hardsub_outline_color_var.get())
        config_manager.save_setting("hardsub_outline", self.hardsub_outline_var.get())
        config_manager.save_setting("hardsub_shadow", self.hardsub_shadow_var.get())
        config_manager.save_setting("hardsub_position", self.hardsub_position_var.get())
        config_manager.save_setting("hardsub_resolution", self.hardsub_resolution_var.get())
        config_manager.save_setting("hardsub_crf", self.hardsub_crf_var.get())
        config_manager.save_setting("video_encoder", self.video_encoder_var.get()) # Save encoder setting
        config_manager.save_setting("hardsub_font_encoding", self.hardsub_font_encoding_var.get()) # Save font encoding
        config_manager.save_setting("audio_handling", self.audio_handling_var.get()) # Save audio handling
        config_manager.save_setting("output_format", self.output_format_var.get()) # Save output format
        config_manager.save_setting("output_directory", self.output_file_path_var.get()) # Save output directory


        self.logger.info("Video Processing tab settings saved.")


    def _init_tab_ui(self):
        """Initializes the UI elements for this tab."""
        # Create a Canvas and Scrollbar for the tab content
        canvas = tk.Canvas(self)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # Create a frame inside the canvas to hold the actual UI elements
        main_frame = ttk.Frame(canvas, padding="10")
        # Use create_window to put the frame inside the canvas
        # The window=main_frame argument tells the canvas what to scroll
        canvas_window = canvas.create_window((0, 0), window=main_frame, anchor="nw")

        # Configure canvas to resize the frame with the window
        def on_frame_configure(event):
            # Update the scrollregion when the size of the frame changes
            canvas.configure(scrollregion=canvas.bbox("all"))
        main_frame.bind("<Configure>", on_frame_configure)

        def on_canvas_configure(event):
            # Update the frame's width when the canvas width changes
            canvas_width = event.width
            canvas.itemconfig(canvas_window, width=canvas_width)
        canvas.bind("<Configure>", on_canvas_configure)

        main_frame.columnconfigure(1, weight=1) # Allow Entry widgets to expand

        current_row = 0
        # --- Input Video File ---
        ttk.Label(main_frame, text="Input Video File:").grid(row=current_row, column=0, sticky=tk.W, padx=5, pady=5)
        self.video_entry = ttk.Entry(main_frame, textvariable=self.input_video_path_var, width=70, state="readonly")
        self.video_entry.grid(row=current_row, column=1, sticky=tk.EW, padx=5, pady=5)
        self.browse_video_button = ttk.Button(main_frame, text="Browse Video...", command=self._browse_input_video)
        self.browse_video_button.grid(row=current_row, column=2, sticky=tk.E, padx=5, pady=5)
        ToolTip(self.browse_video_button, "Select the source video file for processing.")

        current_row += 1
        # --- Input Subtitle File ---
        ttk.Label(main_frame, text="Input Subtitle File (SRT/ASS/SSA/VTT):").grid(row=current_row, column=0, sticky=tk.W, padx=5, pady=5)
        self.subtitle_entry = ttk.Entry(main_frame, textvariable=self.input_subtitle_path_var, width=70, state="readonly")
        self.subtitle_entry.grid(row=current_row, column=1, sticky=tk.EW, padx=5, pady=5)
        self.browse_subtitle_button = ttk.Button(main_frame, text="Browse Subtitle...", command=self._browse_input_subtitle)
        self.browse_subtitle_button.grid(row=current_row, column=2, sticky=tk.E, padx=5, pady=5)
        ToolTip(self.browse_subtitle_button, "Select the SRT subtitle file to use.")

        current_row += 1
        # --- Output Directory ---
        ttk.Label(main_frame, text="Output Directory:").grid(row=current_row, column=0, sticky=tk.W, padx=5, pady=5) # Changed label text
        self.output_entry = ttk.Entry(main_frame, textvariable=self.output_file_path_var, width=70) # Use same variable, now stores directory
        self.output_entry.grid(row=current_row, column=1, sticky=tk.EW, padx=5, pady=5)
        self.browse_output_button = ttk.Button(main_frame, text="Set Output Dir...", command=self._set_output_file) # Changed button text and command
        self.browse_output_button.grid(row=current_row, column=2, sticky=tk.E, padx=5, pady=5)
        ToolTip(self.browse_output_button, "Set the directory where the processed video will be saved.") # Updated tooltip

        current_row += 1
        # --- Processing Options ---
        options_frame = ttk.LabelFrame(main_frame, text="Processing Options", padding="10")
        options_frame.grid(row=current_row, column=0, columnspan=3, sticky=tk.EW, padx=5, pady=10)

        self.mux_radio = ttk.Radiobutton(options_frame, text="Mux Subtitles (Softsub - Recommended for quality & flexibility)", variable=self.process_mode_var, value="mux", command=self._on_processing_mode_change)
        self.mux_radio.pack(anchor=tk.W, pady=2)
        ToolTip(self.mux_radio, "Embeds subtitles as a selectable track. Output format typically MKV or MP4 (with mov_text).")
        
        self.hardsub_radio = ttk.Radiobutton(options_frame, text="Encode Subtitles (Hardsub - Burn into video)", variable=self.process_mode_var, value="hardsub", command=self._on_processing_mode_change)
        self.hardsub_radio.pack(anchor=tk.W, pady=2)
        ToolTip(self.hardsub_radio, "Permanently burns subtitles into the video frames. Re-encodes video, may take longer and affect quality.")

        # Hardsub Options Frame (initially hidden)
        self.hardsub_options_frame = ttk.LabelFrame(options_frame, text="Hardsub Options", padding="10")
        # This frame will be packed/unpacked by _on_processing_mode_change

        # Hardsub Options Widgets (inside hardsub_options_frame)
        hardsub_options_frame_row = 0

        # Create frames for columns
        self.subtitle_settings_frame = ttk.LabelFrame(self.hardsub_options_frame, text="Subtitle Settings", padding="10")
        self.video_settings_frame = ttk.LabelFrame(self.hardsub_options_frame, text="Video Settings", padding="10")

        # Grid the frames within the hardsub_options_frame
        self.subtitle_settings_frame.grid(row=0, column=0, sticky=tk.NSEW, padx=5, pady=5)
        self.video_settings_frame.grid(row=0, column=1, sticky=tk.NSEW, padx=5, pady=5)

        # Configure the hardsub_options_frame columns to expand
        self.hardsub_options_frame.columnconfigure(0, weight=1) # Subtitle Settings Column
        self.hardsub_options_frame.columnconfigure(1, weight=1) # Video Settings Column

        subtitle_row = 0
        # Subtitle Settings Widgets (inside subtitle_settings_frame)

        # Row 0: Font, Size
        ttk.Label(self.subtitle_settings_frame, text="Font:").grid(row=subtitle_row, column=0, sticky=tk.W, padx=5, pady=2)
        self.hardsub_font_combobox = ttk.Combobox(self.subtitle_settings_frame, textvariable=self.hardsub_font_var, width=15)
        self.hardsub_font_combobox['values'] = ("Arial", "Times New Roman", "Courier New", "Verdana", "Tahoma", "Georgia")
        self.hardsub_font_combobox.grid(row=subtitle_row, column=1, sticky=tk.EW, padx=5, pady=2)
        self.hardsub_font_combobox.bind("<<ComboboxSelected>>", self._handle_combobox_selection_visual_reset)
        ToolTip(ttk.Label(self.subtitle_settings_frame, text="Font:"), "Select or type the font name for hardsubtitles.") # Tooltip for Label
        ToolTip(self.hardsub_font_combobox, "Select or type the font name for hardsubtitles.") # Tooltip for Combobox


        ttk.Label(self.subtitle_settings_frame, text="Size:").grid(row=subtitle_row, column=2, sticky=tk.W, padx=5, pady=2)
        self.hardsub_size_combobox = ttk.Combobox(self.subtitle_settings_frame, textvariable=self.hardsub_size_var, width=5)
        self.hardsub_size_combobox['values'] = ("18", "20", "22", "24", "26", "28", "30")
        self.hardsub_size_combobox.grid(row=subtitle_row, column=3, sticky=tk.EW, padx=5, pady=2)
        self.hardsub_size_combobox.bind("<<ComboboxSelected>>", self._handle_combobox_selection_visual_reset)
        ToolTip(ttk.Label(self.subtitle_settings_frame, text="Size:"), "Select or type the font size.") # Tooltip for Label
        ToolTip(self.hardsub_size_combobox, "Select or type the font size.") # Tooltip for Combobox

        subtitle_row += 1

        # Row 1: Color
        ttk.Label(self.subtitle_settings_frame, text="Color (ASS &HBBGGRR):").grid(row=subtitle_row, column=0, sticky=tk.W, padx=5, pady=2)
        self.hardsub_color_entry = ttk.Entry(self.subtitle_settings_frame, textvariable=self.hardsub_color_var, width=10)
        self.hardsub_color_entry.grid(row=subtitle_row, column=1, sticky=tk.EW, padx=5, pady=2)
        self.hardsub_color_button = ttk.Button(self.subtitle_settings_frame, text="Choose...", command=self._choose_hardsub_color)
        self.hardsub_color_button.grid(row=subtitle_row, column=2, sticky=tk.E, padx=5, pady=2)
        ToolTip(ttk.Label(self.subtitle_settings_frame, text="Color (ASS &HBBGGRR):"), "Specify the primary color in ASS format (&HBBGGRR). Default is white (&H00FFFFFF).") # Tooltip for Label
        ToolTip(self.hardsub_color_entry, "Specify the primary color in ASS format (&HBBGGRR). Default is white (&H00FFFFFF).") # Tooltip for Entry
        ToolTip(self.hardsub_color_button, "Open a color picker to select the primary color.") # Tooltip for Button

        subtitle_row += 1

        # Row 2: Outline Color
        ttk.Label(self.subtitle_settings_frame, text="Outline Color:").grid(row=subtitle_row, column=0, sticky=tk.W, padx=5, pady=2)
        self.hardsub_outline_color_entry = ttk.Entry(self.subtitle_settings_frame, textvariable=self.hardsub_outline_color_var, width=10)
        self.hardsub_outline_color_entry.grid(row=subtitle_row, column=1, sticky=tk.EW, padx=5, pady=2)
        self.hardsub_outline_color_button = ttk.Button(self.subtitle_settings_frame, text="Choose...", command=self._choose_hardsub_outline_color)
        self.hardsub_outline_color_button.grid(row=subtitle_row, column=2, sticky=tk.E, padx=5, pady=2)
        ToolTip(ttk.Label(self.subtitle_settings_frame, text="Outline Color:"), "Specify the outline color in ASS format (&HBBGGRR). Default is black (&H00000000).") # Tooltip for Label
        ToolTip(self.hardsub_outline_color_entry, "Specify the outline color in ASS format (&HBBGGRR). Default is black (&H00000000).") # Tooltip for Entry
        ToolTip(self.hardsub_outline_color_button, "Open a color picker to select the outline color.") # Tooltip for Button

        subtitle_row += 1

        # Row 3: Outline, Shadow
        ttk.Label(self.subtitle_settings_frame, text="Outline:").grid(row=subtitle_row, column=0, sticky=tk.W, padx=5, pady=2)
        self.hardsub_outline_entry = ttk.Entry(self.subtitle_settings_frame, textvariable=self.hardsub_outline_var, width=5)
        self.hardsub_outline_entry.grid(row=subtitle_row, column=1, sticky=tk.W, padx=5, pady=2)
        ToolTip(ttk.Label(self.subtitle_settings_frame, text="Outline:"), "Specify the outline thickness (pixels).") # Tooltip for Label
        ToolTip(self.hardsub_outline_entry, "Specify the outline thickness (pixels).") # Tooltip for Entry

        ttk.Label(self.subtitle_settings_frame, text="Shadow:").grid(row=subtitle_row, column=2, sticky=tk.W, padx=5, pady=2)
        self.hardsub_shadow_entry = ttk.Entry(self.subtitle_settings_frame, textvariable=self.hardsub_shadow_var, width=5)
        self.hardsub_shadow_entry.grid(row=subtitle_row, column=3, sticky=tk.W, padx=5, pady=2)
        ToolTip(ttk.Label(self.subtitle_settings_frame, text="Shadow:"), "Specify the shadow thickness (pixels).") # Tooltip for Label
        ToolTip(self.hardsub_shadow_entry, "Specify the shadow thickness (pixels).") # Tooltip for Entry

        subtitle_row += 1

        # Row 4: Position
        ttk.Label(self.subtitle_settings_frame, text="Position:").grid(row=subtitle_row, column=0, sticky=tk.W, padx=5, pady=2)
        self.hardsub_position_combobox = ttk.Combobox(self.subtitle_settings_frame, textvariable=self.hardsub_position_var, width=15, state="readonly")
        self.hardsub_position_combobox['values'] = ("Bottom Center", "Bottom Left", "Bottom Right", "Top Center", "Top Left", "Top Right")
        self.hardsub_position_combobox.grid(row=subtitle_row, column=1, sticky=tk.EW, padx=5, pady=2)
        self.hardsub_position_combobox.bind("<<ComboboxSelected>>", self._handle_combobox_selection_visual_reset)
        self.hardsub_position_combobox.set("Bottom Center")
        ToolTip(ttk.Label(self.subtitle_settings_frame, text="Position:"), "Select the subtitle position.") # Tooltip for Label
        ToolTip(self.hardsub_position_combobox, "Select the subtitle position.") # Tooltip for Combobox

        subtitle_row += 1 # Current row for next setting

        # Row 5: Font Encoding/Charset
        ttk.Label(self.subtitle_settings_frame, text="Font Encoding:").grid(row=subtitle_row, column=0, sticky=tk.W, padx=5, pady=2)
        self.hardsub_font_encoding_combobox = ttk.Combobox(self.subtitle_settings_frame, textvariable=self.hardsub_font_encoding_var, width=15)
        # Add common encodings. User might need to type others.
        self.hardsub_font_encoding_combobox['values'] = ("UTF-8", "SHIFT_JIS", "CP1252", "GBK", "Big5")
        self.hardsub_font_encoding_combobox.grid(row=subtitle_row, column=1, sticky=tk.EW, padx=5, pady=2)
        self.hardsub_font_encoding_combobox.bind("<<ComboboxSelected>>", self._handle_combobox_selection_visual_reset)
        ToolTip(ttk.Label(self.subtitle_settings_frame, text="Font Encoding:"), "Specify the font encoding (charset) for hardsubtitles.") # Tooltip for Label
        ToolTip(self.hardsub_font_encoding_combobox, "Specify the font encoding (charset) for hardsubtitles (e.g., UTF-8, SHIFT_JIS).") # Tooltip for Combobox


        video_row = 0
        # Video Settings Widgets (inside video_settings_frame)

        # Row 0: Resolution, CRF
        ttk.Label(self.video_settings_frame, text="Resolution (WxH):").grid(row=video_row, column=0, sticky=tk.W, padx=5, pady=2)
        self.hardsub_resolution_combobox = ttk.Combobox(self.video_settings_frame, textvariable=self.hardsub_resolution_var, width=15, state="readonly")
        self.hardsub_resolution_combobox['values'] = ["Original", "1920x1080", "1280x720", "854x480", "640x360"]
        self.hardsub_resolution_combobox.grid(row=video_row, column=1, sticky=tk.EW, padx=5, pady=2)
        self.hardsub_resolution_combobox.bind("<<ComboboxSelected>>", self._handle_combobox_selection_visual_reset)
        self.hardsub_resolution_var.set("Original")
        ToolTip(ttk.Label(self.video_settings_frame, text="Resolution (WxH):"), "Select output resolution. 'Original' keeps the source resolution.") # Tooltip for Label
        ToolTip(self.hardsub_resolution_combobox, "Select output resolution. 'Original' keeps the source resolution.") # Tooltip for Combobox

        ttk.Label(self.video_settings_frame, text="CRF (0-51):").grid(row=video_row, column=2, sticky=tk.W, padx=5, pady=2)
        self.hardsub_crf_entry = ttk.Entry(self.video_settings_frame, textvariable=self.hardsub_crf_var, width=5)
        self.hardsub_crf_entry.grid(row=video_row, column=3, sticky=tk.W, padx=5, pady=2)
        ToolTip(ttk.Label(self.video_settings_frame, text="CRF (0-51):"), "Constant Rate Factor for H.264 encoding (0 is lossless, 51 is worst quality). 23 is a good default.") # Tooltip for Label
        ToolTip(self.hardsub_crf_entry, "Constant Rate Factor for H.264 encoding (0 is lossless, 51 is worst quality). 23 is a good default.") # Tooltip for Entry

        video_row += 1 # Increment video row

        # Row 1: Encoder
        ttk.Label(self.video_settings_frame, text="Encoder:").grid(row=video_row, column=0, sticky=tk.W, padx=5, pady=2)
        self.video_encoder_combobox = ttk.Combobox(self.video_settings_frame, textvariable=self.video_encoder_var, width=15)
        # Note: Available encoders depend on FFmpeg build. Providing common ones.
        self.video_encoder_combobox['values'] = ("libx264", "libx265", "h264_nvenc", "hevc_nvenc", "h264_amf", "hevc_amf", "h264_qsv", "hevc_qsv", "libvpx", "libvpx-vp9", "libaom-av1")
        self.video_encoder_combobox.grid(row=video_row, column=1, sticky=tk.EW, padx=5, pady=2)
        self.video_encoder_combobox.bind("<<ComboboxSelected>>", self._handle_combobox_selection_visual_reset)
        ToolTip(ttk.Label(self.video_settings_frame, text="Encoder:"), "Select the video encoder to use.") # Tooltip for Label
        ToolTip(self.video_encoder_combobox, "Select the video encoder to use. Availability depends on your FFmpeg build.") # Tooltip for Combobox

        video_row += 1 # Increment video row

        # Row 2: Audio Handling
        ttk.Label(self.video_settings_frame, text="Audio Handling:").grid(row=video_row, column=0, sticky=tk.W, padx=5, pady=2)
        self.audio_handling_combobox = ttk.Combobox(self.video_settings_frame, textvariable=self.audio_handling_var, width=15, state="readonly")
        self.audio_handling_combobox['values'] = ("copy", "encode")
        self.audio_handling_combobox.grid(row=video_row, column=1, sticky=tk.EW, padx=5, pady=2)
        self.audio_handling_combobox.bind("<<ComboboxSelected>>", self._handle_combobox_selection_visual_reset)
        ToolTip(ttk.Label(self.video_settings_frame, text="Audio Handling:"), "Select how to handle the audio stream.") # Tooltip for Label
        ToolTip(self.audio_handling_combobox, "Select how to handle the audio stream ('copy' to keep original, 'encode' to re-encode).") # Tooltip for Combobox

        video_row += 1 # Increment video row

        # Row 3: Format
        ttk.Label(self.video_settings_frame, text="Format:").grid(row=video_row, column=0, sticky=tk.W, padx=5, pady=2)
        self.output_format_combobox = ttk.Combobox(self.video_settings_frame, textvariable=self.output_format_var, width=15, state="readonly")
        self.output_format_combobox['values'] = ("mp4", "mkv")
        self.output_format_combobox.grid(row=video_row, column=1, sticky=tk.EW, padx=5, pady=2)
        self.output_format_combobox.bind("<<ComboboxSelected>>", self._on_output_format_change) # Bind to a new handler
        ToolTip(ttk.Label(self.video_settings_frame, text="Format:"), "Select the output container format.") # Tooltip for Label
        ToolTip(self.output_format_combobox, "Select the output container format (e.g., mp4, mkv).") # Tooltip for Combobox

        video_row += 1 # Increment video row for future settings


        # Update column configurations for sub-frames
        # Subtitle Settings Frame Columns
        # Adjusted based on the grid layout within the subtitle frame
        self.subtitle_settings_frame.columnconfigure(0, weight=0) # Label (Font, Color, Outline, Position, Font Encoding)
        self.subtitle_settings_frame.columnconfigure(1, weight=1) # Widget (Font Combobox, Color Entry, Outline Entry, Position Combobox, Font Encoding Combobox)
        self.subtitle_settings_frame.columnconfigure(2, weight=0) # Label (Size, Color Button, Shadow)
        self.subtitle_settings_frame.columnconfigure(3, weight=1) # Widget (Size Combobox, Shadow Entry)
        self.subtitle_settings_frame.columnconfigure(4, weight=0) # Label (Outline Color)
        self.subtitle_settings_frame.columnconfigure(5, weight=1) # Widget (Outline Color Button)


        # Video Settings Frame Columns
        # Adjusted based on the grid layout within the video frame
        self.video_settings_frame.columnconfigure(0, weight=0) # Label (Resolution, CRF, Encoder, Audio Handling, Format)
        self.video_settings_frame.columnconfigure(1, weight=1) # Widget (Resolution Combobox, CRF Entry, Encoder Combobox, Audio Handling Combobox, Format Combobox)
        self.video_settings_frame.columnconfigure(2, weight=0) # Label (CRF)
        self.video_settings_frame.columnconfigure(3, weight=1) # Widget (CRF Entry)


        current_row += 1
        # --- Action Buttons ---
        action_button_frame = ttk.Frame(main_frame)
        action_button_frame.grid(row=current_row, column=0, columnspan=3, pady=10, sticky=tk.EW)
        action_button_frame.columnconfigure(0, weight=1) # Allow Start button to expand
        action_button_frame.columnconfigure(1, weight=0) # Cancel button does not need to expand

        self.process_button = ttk.Button(action_button_frame, text="Start Video Processing", command=self._start_video_processing_thread)
        self.process_button.grid(row=0, column=0, padx=(0,5), pady=5, sticky=tk.EW)
        ToolTip(self.process_button, "Start muxing or encoding the video with the selected subtitles.")

        self.cancel_proc_button = ttk.Button(action_button_frame, text="Cancel Processing", command=self._request_cancel_video_processing, state="disabled")
        self.cancel_proc_button.grid(row=0, column=1, padx=(5,0), pady=5, sticky=tk.E)
        ToolTip(self.cancel_proc_button, "Request to cancel the current video processing operation.")


        current_row += 1
        # --- Status Label & Progress Bar ---
        status_frame = ttk.Frame(main_frame)
        status_frame.grid(row=current_row, column=0, columnspan=3, pady=(5,0), sticky=tk.EW)
        status_frame.columnconfigure(0, weight=1)

        self.status_label = ttk.Label(status_frame, textvariable=self.processing_status_var)
        self.status_label.grid(row=0, column=0, sticky=tk.W, padx=2)

        self.progressbar_proc = ttk.Progressbar(status_frame, variable=self.processing_progress_var, maximum=100)
        self.progressbar_proc.grid(row=1, column=0, columnspan=2, pady=(2,10), sticky=tk.EW)

        current_row += 1
        # --- Log Output and Speed ---
        log_frame = ttk.LabelFrame(main_frame, text="FFmpeg Output", padding="10")
        log_frame.grid(row=current_row, column=0, columnspan=3, sticky=tk.EW, padx=5, pady=10)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, wrap=tk.WORD, height=10, state="disabled", font=(self.default_font_family, self.default_font_size))
        self.log_text.grid(row=0, column=0, sticky=tk.NSEW, padx=5, pady=5)

        log_scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        log_scrollbar.grid(row=0, column=1, sticky=tk.NS)
        self.log_text['yscrollcommand'] = log_scrollbar.set

        current_row += 1


        # Ensure initial state of hardsub options frame is correct
        # Defer the call to ensure the frame is fully initialized
        self.after(0, self._on_processing_mode_change)

    def _handle_combobox_selection_visual_reset(self, event):
        """Clears the selection highlight in a combobox after an item is selected."""
        widget = event.widget
        def clear_highlight_and_refocus_away():
            if widget.winfo_exists():
                widget.selection_clear()
                # Attempt to set focus to a different widget to ensure highlight is gone
                # Find the parent frame and try to focus on it or another widget
                parent_frame = widget.winfo_parent()
                if parent_frame:
                    try:
                        parent_widget = widget.nametowidget(parent_frame)
                        parent_widget.focus_set()
                    except Exception:
                        # Fallback if parent focusing fails
                        self.focus_set()
                else:
                    self.focus_set()

        widget.after(10, clear_highlight_and_refocus_away)

    def _on_output_format_change(self, event):
        """Does nothing in this revised UI where output is directory only."""
        pass # The output path is now just a directory, format change doesn't affect the entry text directly


    def _on_processing_mode_change(self):
        mode = self.process_mode_var.get()
        self.logger.info(f"Processing mode changed to: {mode}")

        # Ensure hardsub options frame is always packed (visible)
        if not self.hardsub_options_frame.winfo_ismapped():
             self.hardsub_options_frame.pack(fill=tk.X, pady=5)

        # Update the state of hardsub options based on the new mode
        self._update_hardsub_ui_state()


    def _update_hardsub_ui_state(self):
        """Enables/disables hardsub UI options based on subtitle type and processing mode."""
        subtitle_path = self.input_subtitle_path_var.get()
        sub_ext = os.path.splitext(subtitle_path)[1].lower() if subtitle_path else ""
        current_mode = self.process_mode_var.get()

        # Determine if hardsub options frame should be visible
        hardsub_options_visible = (current_mode == "hardsub")
        if hardsub_options_visible:
            if not self.hardsub_options_frame.winfo_ismapped():
                 self.hardsub_options_frame.pack(fill=tk.X, pady=5)
        else:
            if self.hardsub_options_frame.winfo_ismapped():
                 self.hardsub_options_frame.pack_forget()


        # Determine if subtitle settings should be disabled (within hardsub mode)
        # Disabled if mode is hardsub AND subtitle is ASS/SSA
        disable_subtitle_settings = (current_mode == "hardsub" and sub_ext in ['.ass', '.ssa'])

        # Determine if Video settings options should be disabled (within hardsub mode)
        # Video settings are only relevant in hardsub mode, so they are linked to hardsub_options_visible
        # disable_video_options = not hardsub_options_visible # This is implicitly handled by the frame visibility

        # Set the state for Subtitle Settings widgets
        subtitle_widgets_state = tk.DISABLED if disable_subtitle_settings else tk.NORMAL
        if hasattr(self, 'subtitle_settings_frame') and self.subtitle_settings_frame.winfo_exists():
            for child in self.subtitle_settings_frame.winfo_children():
                # Labels should always remain enabled
                if isinstance(child, ttk.Label):
                    continue

                # Apply the determined state to all other interactive widgets
                if 'state' in child.configure():
                     child.config(state=subtitle_widgets_state)


        # Video settings widgets state is controlled by the visibility of the parent video_settings_frame,
        # which is inside the hardsub_options_frame. No need to explicitly disable children here
        # when the entire frame is packed_forget.
        # If hardsub_options_frame is visible (hardsub mode), Video Settings should be enabled.
        video_widgets_state = tk.NORMAL # Always normal if hardsub_options_frame is packed


        self.logger.debug(f"Hardsub UI state updated. Subtitle type: {sub_ext}, Mode: {current_mode}, Hardsub Options Visible: {hardsub_options_visible}, Subtitle Settings Disabled: {disable_subtitle_settings}. Video Settings Enabled: {video_widgets_state == tk.NORMAL}")
        # Add more detailed logging for individual widget states
        if hasattr(self, 'subtitle_settings_frame') and self.subtitle_settings_frame.winfo_exists() and hardsub_options_visible:
            self.logger.debug("Subtitle Settings Widgets State:")
            for child in self.subtitle_settings_frame.winfo_children():
                if hasattr(child, 'cget'):
                    try:
                        state = child.cget('state') if 'state' in child.configure() else 'N/A (no state)'
                        self.logger.debug(f"  - {child.winfo_class()} '{child.winfo_name()}': {state}")
                    except Exception as e:
                         self.logger.debug(f"  - {child.winfo_class()} error getting state: {e}")

        if hasattr(self, 'video_settings_frame') and self.video_settings_frame.winfo_exists() and hardsub_options_visible:
            self.logger.debug("Video Settings Widgets State:")
            for child in self.video_settings_frame.winfo_children():
                if hasattr(child, 'cget'):
                    try:
                        state = child.cget('state') if 'state' in child.configure() else 'N/A (no state)'
                        self.logger.debug(f"  - {child.winfo_class()} '{child.winfo_name()}': {state}")
                    except Exception as e:
                         self.logger.debug(f"  - {child.winfo_class()} error getting state: {e}")


    def _browse_input_subtitle(self):
        filepath = filedialog.askopenfilename(
            title="Select Input Subtitle File",
            filetypes=(("Supported Subtitles", "*.srt *.ass *.ssa *.vtt"), ("SRT Subtitles", "*.srt"), ("ASS Subtitles", "*.ass"), ("SSA Subtitles", "*.ssa"), ("VTT Subtitles", "*.vtt"), ("All Files", "*.*")),
            parent=self.app_controller
        )
        if filepath:
            self.input_subtitle_path_var.set(filepath)
            self.logger.info(f"Input subtitle selected for processing: {filepath}")
            # Update the state of hardsub options based on the newly selected subtitle
            self._update_hardsub_ui_state()

    def _browse_input_video(self):
        """Opens a file dialog to select the input video file."""
        filepath = filedialog.askopenfilename(
            title="Select Input Video File",
            filetypes=(("Video Files", "*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm"), ("All Files", "*.*")),
            parent=self.app_controller
        )
        if filepath:
            self.input_video_path_var.set(filepath)
            self.logger.info(f"Input video selected for processing: {filepath}")
            # Suggest output directory based on the selected video's directory
            input_dir = os.path.dirname(filepath)
            self.output_file_path_var.set(input_dir) # Set output_file_path_var to directory
            self.logger.info(f"Suggested output directory: {input_dir}")


    def _set_output_file(self):
        """Opens a directory dialog to select the output directory."""
        # Use askdirectory instead of asksaveasfilename
        directory_path = filedialog.askdirectory(
            title="Select Output Directory",
            initialdir=self.output_file_path_var.get() or os.getcwd(), # Use current path or default
            parent=self.app_controller
        )
        if directory_path:
            self.output_file_path_var.set(directory_path) # Store only the directory path
            self.logger.info(f"Output directory set to: {directory_path}")

    def _ass_color_to_rgb(self, ass_color_str):
        """Converts an ASS color string (&HBBGGRR) to an RGB tuple (R, G, B)."""
        # Remove '&H' and ensure it's 6 hex characters
        ass_color_str = ass_color_str.replace('&H', '').strip()
        if len(ass_color_str) != 6:
            self.logger.warning(f"Invalid ASS color format: {ass_color_str}. Expected &HBBGGRR.")
            return (255, 255, 255) # Default to white on error

        try:
            # ASS is BBGGRR, so we need to extract in reverse order
            b = int(ass_color_str[0:2], 16)
            g = int(ass_color_str[2:4], 16)
            r = int(ass_color_str[4:6], 16)
            return (r, g, b)
        except ValueError:
            self.logger.warning(f"Could not parse ASS color hex: {ass_color_str}. Expected hex characters.")
            return (255, 255, 255) # Default to white on error

    def _choose_hardsub_color(self):
        """Opens a color chooser dialog and updates the hardsub color variable."""
        color_code, rgb_color = tkinter.colorchooser.askcolor(parent=self.app_controller,
                                                               title="Choose Hardsub Color",
                                                               initialcolor=self._ass_color_to_rgb(self.hardsub_color_var.get()))
        if color_code: # color_code is an RGB tuple (R, G, B)
            # Convert RGB tuple to ASS format &HBBGGRR
            # Tkinter returns (R, G, B) where R, G, B are 0-255
            # ASS format is &HBBGGRR (hexadecimal, Blue Green Red)
            ass_color = f"&H{color_code[2]:02X}{color_code[1]:02X}{color_code[0]:02X}"
            self.hardsub_color_var.set(ass_color)
            self.logger.info(f"Hardsub color selected: {ass_color}")

    def _choose_hardsub_outline_color(self):
        """Opens a color chooser dialog and updates the hardsub outline color variable."""
        color_code, rgb_color = tkinter.colorchooser.askcolor(parent=self.app_controller,
                                                               title="Choose Hardsub Outline Color",
                                                               initialcolor=self._ass_color_to_rgb(self.hardsub_outline_color_var.get()))
        if color_code: # color_code is an RGB tuple (R, G, B)
            # Convert RGB tuple to ASS format &HBBGGRR
            # Tkinter returns (R, G, B) where R, G, B are 0-255
            # ASS format is &HBBGGRR (hexadecimal, Blue Green Red)
            ass_color = f"&H{color_code[2]:02X}{color_code[1]:02X}{color_code[0]:02X}"
            self.hardsub_outline_color_var.set(ass_color)
            self.logger.info(f"Hardsub outline color selected: {ass_color}")

    def _set_processing_ui_state(self, processing: bool):
        state = tk.DISABLED if processing else tk.NORMAL
        # For output entry - may still allow copying text even when processing
        # readonly_state = "readonly" if processing else "normal"

        self.browse_video_button.config(state=state)
        self.browse_subtitle_button.config(state=state)
        self.process_button.config(state=state) # Disable Start button when processing
        # Enable cancel button when processing starts, disable when it finishes
        self.cancel_proc_button.config(state=tk.NORMAL if processing else tk.DISABLED)
    def _update_log_text(self, text):
        """Updates the log text area in a thread-safe manner."""
        if self.winfo_exists():
            def append_text():
                self.log_text.config(state="normal")
                self.log_text.insert(tk.END, text + "\n")
                self.log_text.see(tk.END)
                self.log_text.config(state="disabled")
            self.after(0, append_text)

    def _request_cancel_video_processing(self):
        if not self.cancel_video_processing_requested:
            if messagebox.askyesno("Cancel Processing", "Are you sure you want to cancel the current video processing operation?", parent=self.app_controller):
                self.logger.info("Video processing cancellation requested by user.")
                self.cancel_video_processing_requested = True
                # Update UI state to disable buttons, including Start, while waiting for cancellation
                self._set_processing_ui_state(processing=True)
                self.cancel_proc_button.config(text="Cancelling...", state="disabled")
                self.processing_status_var.set("Cancellation requested...")
                # Terminate the FFMPEG process if it's running
                if self._ffmpeg_process and self._ffmpeg_process.poll() is None:
                    self.logger.info("Attempting to terminate FFMPEG process.")
                    try:
                        self._ffmpeg_process.terminate()
                        # Start a thread to wait and potentially kill if terminate fails
                        threading.Thread(target=self._wait_and_kill_ffmpeg, daemon=True).start()
                    except Exception as e:
                        self.logger.error(f"Error initiating termination of FFMPEG process: {e}")
                        self._set_processing_ui_state(False) # Re-enable buttons if terminate fails immediately
                        self.processing_status_var.set("Error cancelling process.")

    def _wait_and_kill_ffmpeg(self):
        """Waits for FFMPEG to terminate, and kills it if it doesn't in time."""
        try:
            # Wait up to 5 seconds for the process to exit after terminate()
            self._ffmpeg_process.wait(timeout=5)
            self.logger.info("FFMPEG process terminated successfully after request.")
        except subprocess.TimeoutExpired:
            self.logger.warning("FFMPEG process did not terminate in time. Attempting to kill.")
            try:
                self._ffmpeg_process.kill()
                self.logger.info("FFMPEG process killed.")
            except Exception as e:
                self.logger.error(f"Error killing FFMPEG process: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error in _wait_and_kill_ffmpeg: {e}")
        finally:
            # The task_process_video thread's process.wait() will eventually finish
            # and trigger the final UI update in its finally block.
            pass # No need for UI update here


    def _update_processing_progress(self, value, message=None):
        """Updates the progress bar and status label in a thread-safe manner."""
        if self.winfo_exists(): # Ensure tab still exists
            self.after(0, self.processing_progress_var.set, value)
        if message:
            self.logger.info(f"VIDEO_PROC_PROGRESS: {message} ({value:.0f}%)")
            if self.winfo_exists():
                self.after(0, self.processing_status_var.set, message)


    def _start_video_processing_thread(self):
        video_path = self.input_video_path_var.get()
        sub_path = self.input_subtitle_path_var.get()
        output_dir = self.output_file_path_var.get() # Get output directory
        mode = self.process_mode_var.get()
        encoder = self.video_encoder_var.get() # Get selected encoder
        font_encoding = self.hardsub_font_encoding_var.get() # Get selected font encoding
        audio_handling = self.audio_handling_var.get() # Get selected audio handling
        output_format = self.output_format_var.get() # Get selected output format

        if not video_path or not os.path.exists(video_path):
            messagebox.showerror("Input Error", "Please specify a valid input video file.", parent=self.app_controller)
            return
        if not sub_path or not os.path.exists(sub_path):
            messagebox.showerror("Input Error", "Please specify a valid input subtitle (SRT) file.", parent=self.app_controller)
            return
        if not output_dir or not os.path.isdir(output_dir): # Check if output_dir is valid directory
            messagebox.showerror("Output Error", "Please specify a valid output directory.", parent=self.app_controller)
            return

        # Construct the full output file path dynamically
        video_name_no_ext = os.path.splitext(os.path.basename(video_path))[0]
        out_filename = f"{video_name_no_ext}_processed_final.{output_format}"
        out_path_full = os.path.join(output_dir, out_filename)

        # Kiểm tra nếu output trùng input
        if os.path.abspath(video_path) == os.path.abspath(out_path_full):
            messagebox.showerror("Output Error", "Output file cannot be the same as the input video file.", parent=self.app_controller)
            return

        # Kiểm tra FFMPEG
        if not ffmpeg_utils.check_ffmpeg_exists(): # Giả sử hàm này không hiển thị messagebox, chỉ trả về bool
            messagebox.showerror("FFMPEG Error", "FFMPEG command not found. Please ensure FFMPEG is installed and in your system's PATH.", parent=self.app_controller)
            return

        self.cancel_video_processing_requested = False # Reset cờ cancel
        self._set_processing_ui_state(processing=True)
        self.processing_status_var.set(f"Starting {mode} process...")
        self.processing_progress_var.set(0)

        self.logger.info(f"Starting video processing thread: Mode='{mode}', Video='{video_path}', Sub='{sub_path}', Out='{out_path_full}', Encoder='{encoder}', Font Encoding='{font_encoding}', Audio Handling='{audio_handling}', Output Format='{output_format}'")

        thread = threading.Thread(target=video_processing_tasks.task_process_video,
                                   args=(self.app_controller, self, video_path, sub_path, out_path_full, mode, encoder, font_encoding, audio_handling, output_format), # Pass full output path
                                   daemon=True)
        # Save settings when starting processing (captures current UI state)
        self._save_settings()
        thread.start()

    # Helper function to read from a pipe and put lines into a queue
    def _enqueue_output(self, out, queue):
        for line in iter(out.readline, ''):
            queue.put(line)
        out.close()

    # Function to process the queues and update UI (runs in main thread)
    def _check_ffmpeg_output_queues(self):
        """Periodically checks the FFMPEG output queues and updates the UI."""
        try:
            # Process stdout queue
            while True:
                try:
                    line = self._stdout_queue.get_nowait()
                    line_strip = line.strip()
                    self._update_log_text(line_strip)
                    # Parse FFMPEG progress and speed from stdout
                    if "time=" in line_strip and hasattr(self, 'video_duration') and self.video_duration and self.video_duration > 0: # Check if video_duration exists and is valid
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
                            # Adjust progress range if needed, e.g., 10% for setup, 80% for processing, 10% for finalization
                            progress_percent = (current_seconds / self.video_duration) * 80 # Assuming 80% for this step
                            self._update_processing_progress(10 + progress_percent, f"Processing: {time_str} / {ffmpeg_utils.format_seconds_to_hhmmss(self.video_duration)}")
                        except Exception as e_parse:
                            self.logger.warning(f"Failed to parse FFMPEG progress line '{line_strip[:50]}...': {e_parse}")
                            self._update_processing_progress(self.processing_progress_var.get(), line_strip[:100])

                        speed_match = re.search(r"speed=(\d+\.\d+x)", line_strip)
                        if speed_match:
                            self._update_speed_label(speed_match.group(1))

                    elif line_strip:
                        self._update_processing_progress(self.processing_progress_var.get(), line_strip[:100])
                except Empty:
                    break # No more lines in stdout queue

            # Process stderr queue
            while True:
                try:
                    line = self._stderr_queue.get_nowait()
                    line_strip = line.strip()
                    self._update_log_text(f"ERROR: {line_strip}")
                    # Optionally parse stderr for specific errors here
                except Empty:
                    break # No more lines in stderr queue

        except Exception as e:
            self.logger.error(f"Error in _check_ffmpeg_output_queues: {e}", exc_info=True)
        finally:
            # Schedule the next check if the process is still running
            if self._ffmpeg_process and self._ffmpeg_process.poll() is None and self.winfo_exists():
                self.after(100, self._check_ffmpeg_output_queues) # Check every 100ms

    # Add helper function to process remaining queue output
    def _process_remaining_queue_output(self):
        """Processes any remaining items in the stdout/stderr queues after the process finishes."""
        self.logger.debug("Processing remaining queue output...")
        # Process stdout queue
        while True:
            try:
                line = self._stdout_queue.get_nowait()
                self._update_log_text(line.strip())
            except Empty:
                break
        # Process stderr queue
        while True:
            try:
                line = self._stderr_queue.get_nowait()
                self._update_log_text(f"ERROR: {line.strip()}")
            except Empty:
                break
        self.logger.debug("Finished processing remaining queue output.")