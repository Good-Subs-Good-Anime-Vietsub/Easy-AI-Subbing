# EasyAISubbing/app_gui/guide_tab.py
import tkinter as tk
from tkinter import ttk, font as tkFont
import logging
import textwrap
# Optional: import webbrowser if we want clickable links (though the plan was text-only)
# import webbrowser # Keeping it text-only for now as per plan

logger = logging.getLogger(__name__)

# TextHandler class for local tab logging
class TextHandler(logging.Handler):
    def __init__(self, text_widget, tab_logger_name):
        super().__init__()
        self.text_widget = text_widget
        # Filter messages to only show logs from this specific tab's logger
        self.tab_logger_name = tab_logger_name
        self.formatter = logging.Formatter('%(asctime)s %(levelname)-7s: %(message)s', datefmt='%H:%M:%S')

    def format(self, record):
        return self.formatter.format(record)

    def emit(self, record):
        # Only emit messages from the logger specific to this tab or lower levels (e.g. handlers within this tab)
        if not record.name.startswith(self.tab_logger_name):
            return

        msg = self.format(record)
        try:
            # Use after() to ensure thread-safe update to the Tkinter widget
            if hasattr(self, 'text_widget') and self.text_widget.winfo_exists():
                self.text_widget.after(0, self._append_text_thread_safe, msg + '\n')
        except tk.TclError:
            # Widget might be destroyed during processing
            pass
        except Exception as e:
            # Fallback to print to console if GUI update fails completely
            print(f"Error emitting log to GUI (TextHandler for {self.tab_logger_name}): {e}")

    def _append_text_thread_safe(self, text_to_append):
        try:
            if not hasattr(self, 'text_widget') or not self.text_widget.winfo_exists(): return
            current_state = self.text_widget.cget("state")
            self.text_widget.config(state=tk.NORMAL) # Temporarily enable
            self.text_widget.insert(tk.END, text_to_append)
            self.text_widget.config(state=current_state) # Restore state
            self.text_widget.see(tk.END) # Scroll to the end
        except tk.TclError:
            pass
        except Exception as e:
            print(f"Error appending text to GUI log widget (TextHandler for {self.tab_logger_name}): {e}")


class GuideTab(ttk.Frame):
    def __init__(self, parent_notebook, app_controller):
        super().__init__(parent_notebook)
        self.app_controller = app_controller
        self.logger = logging.getLogger(f"{__name__}.GuideTab")

        # Access font from app_controller as defined in main_window.py
        # Ensure main_window.py initializes custom_font and custom_bold_font
        self.custom_font = getattr(self.app_controller, 'custom_font', tkFont.nametofont("TkDefaultFont"))
        self.custom_bold_font = getattr(self.app_controller, 'custom_bold_font', tkFont.nametofont("TkDefaultFont"))
        # Fallback if custom fonts are not set, use defaults
        if not hasattr(self.app_controller, 'default_font_family'):
            self.default_font_family = self.custom_font.actual()['family']
        else:
            self.default_font_family = self.app_controller.default_font_family

        if not hasattr(self.app_controller, 'default_font_size'):
             self.default_font_size = self.custom_font.actual()['size']
        else:
             self.default_font_size = self.app_controller.default_font_size


        # --- Local logging setup ---
        # Create a Text widget for local tab logs first, so the handler can use it
        self._create_local_log_area(self) # Create this log area within the tab

        # Add a handler to the tab's logger to direct messages to the text widget
        # Ensure the logger level is set appropriately, e.g., logging.INFO
        if hasattr(self, 'log_text_widget') and self.log_text_widget:
             gui_log_handler = TextHandler(self.log_text_widget, self.logger.name)
             gui_log_handler.setLevel(logging.INFO) # Set level for this handler
             # Prevent adding duplicate handlers if __init__ is called multiple times
             if not any(isinstance(h, TextHandler) for h in self.logger.handlers):
                  self.logger.addHandler(gui_log_handler)
             self.logger.setLevel(logging.INFO) # Set the minimum level for the logger itself
        else:
             self.logger.warning("Local log text widget not available for GuideTab. Logging only to console/file.")
        # --- End Local logging setup ---


        self._init_ui() # Initialize the rest of the UI
        self.logger.info("Guide Tab initialized.")


    def _create_local_log_area(self, parent_frame):
        """Creates a simple text area for local tab logging."""
        log_frame = ttk.LabelFrame(parent_frame, text="Tab Log", padding="5")
        # log_frame.pack(fill=tk.BOTH, expand=False, padx=10, pady=(0, 10)) # Will pack later
        self.log_text_widget = tk.Text(log_frame, wrap=tk.WORD, state="disabled",
                                      height=5, # Keep it relatively small
                                      font=(self.default_font_family, self.default_font_size -2),
                                      relief=tk.SUNKEN) # Indicate it's a log area
        scroll_y = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text_widget.yview)
        self.log_text_widget.config(yscrollcommand=scroll_y.set)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        return log_frame


    def _init_ui(self):
        # Main content frame for the guide text
        guide_content_frame = ttk.LabelFrame(self, text="EasyAISubbing Guide", padding="10")
        # pack the main content frame first
        guide_content_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5)) # Add some padding at the bottom

        # Use a Text widget for scrollable, read-only content
        # Use the custom_font accessed from app_controller
        self.guide_text_widget = tk.Text(guide_content_frame, wrap=tk.WORD, state="disabled",
                                         font=self.custom_font,
                                         relief=tk.FLAT) # Use FLAT relief for a cleaner look

        # Add scrollbars
        scroll_y = ttk.Scrollbar(guide_content_frame, orient=tk.VERTICAL, command=self.guide_text_widget.yview)
        scroll_x = ttk.Scrollbar(guide_content_frame, orient=tk.HORIZONTAL, command=self.guide_text_widget.xview)
        self.guide_text_widget.config(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.guide_text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Define tags AFTER creating the text widget
        # Access fonts from app_controller
        custom_font = getattr(self.app_controller, 'custom_font', tkFont.nametofont("TkDefaultFont"))
        custom_bold_font = getattr(self.app_controller, 'custom_bold_font', tkFont.nametofont("TkDefaultFont"))

        # Define custom fonts for tags (Tkinter fonts need to be named or kept referenced)
        # Use size relative to the default font size from app_controller
        base_size = getattr(self.app_controller, 'default_font_size', 10) # Default to 10 if not available
        self.h1_font = tkFont.Font(family=custom_bold_font.actual('family'), size=int(base_size * 1.5), weight="bold")
        self.h2_font = tkFont.Font(family=custom_bold_font.actual('family'), size=base_size + 1, weight="bold") # Slightly larger than default
        self.italic_font = tkFont.Font(family=custom_font.actual('family'), size=base_size, slant="italic")
        # self.link_font = tkFont.Font(family=custom_font.actual('family'), size=custom_font.actual('size'), underline=True) # Keep as text, maybe just blue color


        self.guide_text_widget.tag_configure("h1", font=self.h1_font, spacing3=base_size) # Add space after H1, use font size for relative spacing
        self.guide_text_widget.tag_configure("h2", font=self.h2_font, spacing3=base_size // 2) # Add space after H2
        self.guide_text_widget.tag_configure("bold", font=custom_bold_font)
        self.guide_text_widget.tag_configure("italic", font=self.italic_font)
        self.guide_text_widget.tag_configure("link", foreground="blue") # Just change color for links as text
        self.guide_text_widget.tag_configure("bullet", lmargin1=15, lmargin2=30, spacing3=3) # Indent and spacing for list items
        self.guide_text_widget.tag_configure("numbered", lmargin1=15, lmargin2=35, spacing3=3) # Indent and spacing for numbered list items
        # Configure default tag for general text appearance
        self.guide_text_widget.tag_configure("default", font=custom_font, spacing3=3) # Add some default spacing


        self._populate_guide_content()

        # Pack the local log area after the main guide content frame
        log_frame = getattr(self, 'log_text_widget', None) # Check if log widget was created
        if log_frame and log_frame.winfo_exists():
             # Find the parent frame of the log_text_widget (which is the log_frame itself)
             log_frame_container = self.log_text_widget.master # The LabelFrame returned by _create_local_log_area
             log_frame_container.pack(fill=tk.X, expand=False, padx=10, pady=(5, 10)) # Pack the log frame at the bottom


    def _populate_guide_content(self):
        self.guide_text_widget.config(state="normal") # Temporarily enable to insert
        self.guide_text_widget.delete("1.0", tk.END) # Clear existing content

        # Insert content with tags

        # Title
        self.guide_text_widget.insert(tk.END, "EasyAISubbing User Guide\n\n", "h1")

        # Welcome
        self.guide_text_widget.insert(tk.END, "Welcome to EasyAISubbing, a tool designed to simplify creating subtitles for your media using AI.\n\n", "default")

        # Prerequisites Section
        self.guide_text_widget.insert(tk.END, "Prerequisites: Installing FFmpeg and yt-dlp\n\n", "h2")
        self.guide_text_widget.insert(tk.END, "EasyAISubbing requires ", "default")
        self.guide_text_widget.insert(tk.END, "FFmpeg", "bold")
        self.guide_text_widget.insert(tk.END, " for audio/video processing and ", "default")
        self.guide_text_widget.insert(tk.END, "yt-dlp", "bold")
        self.guide_text_widget.insert(tk.END, " for downloading online media. These must be installed and accessible via your system's PATH.\n\n", "default")

        # Installing FFmpeg Subsection
        self.guide_text_widget.insert(tk.END, "Installing FFmpeg\n\n", "h2") # Using h2 for subsections too
        self.guide_text_widget.insert(tk.END, "FFmpeg is essential for tasks like extracting audio or muxing subtitles into videos.\n\n", "default")

        # Use a helper function to insert list items to handle indentation and spacing
        def insert_list_item(widget, text, tag=None):
            if tag:
                widget.insert(tk.END, text, tag)
            else:
                widget.insert(tk.END, text)

        insert_list_item(self.guide_text_widget, "Download: ", "bullet")
        self.guide_text_widget.insert(tk.END, "Get the latest version for your OS: ", "default")
        self.guide_text_widget.insert(tk.END, "https://ffmpeg.org/download.html\n", "link")

        insert_list_item(self.guide_text_widget, "Installation & Adding to PATH:\n", "bullet")
        self.guide_text_widget.insert(tk.END, "    - Windows: Download the zip, extract it (e.g., C:\\ffmpeg). Add the bin folder (e.g., C:\\ffmpeg\\bin) to your system's Environment Variables (specifically, the PATH variable). Search online for \"how to add to path windows\" if needed.\n", "default")

        insert_list_item(self.guide_text_widget, "    - macOS (using Homebrew): Open Terminal and run ", "bullet")
        self.guide_text_widget.insert(tk.END, "brew install ffmpeg", "italic")
        self.guide_text_widget.insert(tk.END, ".\n", "default")

        insert_list_item(self.guide_text_widget, "    - Linux (using package manager): Open Terminal. For Debian/Ubuntu: ", "bullet")
        self.guide_text_widget.insert(tk.END, "sudo apt update && sudo apt install ffmpeg", "italic")
        self.guide_text_widget.insert(tk.END, ". For Fedora: ", "default")
        self.guide_text_widget.insert(tk.END, "sudo dnf install ffmpeg", "italic")
        self.guide_text_widget.insert(tk.END, ".\n", "default")

        insert_list_item(self.guide_text_widget, "Verify: ", "bullet")
        self.guide_text_widget.insert(tk.END, "Open your terminal/command prompt and run ", "default")
        self.guide_text_widget.insert(tk.END, "ffmpeg -version", "italic")
        self.guide_text_widget.insert(tk.END, ".\n\n", "default")


        # Installing yt-dlp Subsection
        self.guide_text_widget.insert(tk.END, "Installing yt-dlp\n\n", "h2")
        self.guide_text_widget.insert(tk.END, "yt-dlp lets you download videos from YouTube and many other sites directly into the app.\n\n", "default")

        insert_list_item(self.guide_text_widget, "Download: ", "bullet")
        self.guide_text_widget.insert(tk.END, "Get the executable for your OS from the releases page: ", "default")
        self.guide_text_widget.insert(tk.END, "https://github.com/yt-dlp/yt-dlp\n", "link")

        insert_list_item(self.guide_text_widget, "Installation & Adding to PATH:\n", "bullet")
        insert_list_item(self.guide_text_widget, "    - Windows: Download ", "bullet")
        self.guide_text_widget.insert(tk.END, "yt-dlp.exe", "italic")
        self.guide_text_widget.insert(tk.END, ". Place it in a directory already in your PATH (e.g., C:\\Windows\\System32 - use caution, or create a dedicated tools folder and add that to PATH).\n", "default")

        insert_list_item(self.guide_text_widget, "    - macOS/Linux: Download the binary (", "bullet")
        self.guide_text_widget.insert(tk.END, "yt-dlp", "italic")
        self.guide_text_widget.insert(tk.END, "). Make it executable (", "default")
        self.guide_text_widget.insert(tk.END, "chmod +x yt-dlp", "italic")
        self.guide_text_widget.insert(tk.END, "). Place it in a directory in your PATH (e.g., /usr/local/bin). Alternatively: ", "default")
        self.guide_text_widget.insert(tk.END, "pip install yt-dlp", "italic")
        self.guide_text_widget.insert(tk.END, ".\n", "default")

        self.guide_text_widget.insert(tk.END, "Troubleshooting Tip: ", "bold")
        self.guide_text_widget.insert(tk.END, "If EasyAISubbing reports FFmpeg or yt-dlp missing, double-check your PATH settings and restart the application.\n\n", "default")


        # How to Use Section
        self.guide_text_widget.insert(tk.END, "How to Use EasyAISubbing Tabs\n\n", "h2")
        self.guide_text_widget.insert(tk.END, "The application is organized into several tabs for different parts of the subtitling workflow:\n\n", "default")


        # Translate Video/Audio Tab Subsection
        self.guide_text_widget.insert(tk.END, "Translate Video/Audio Tab\n\n", "h2")
        self.guide_text_widget.insert(tk.END, "Use this tab to get subtitles from media files using Gemini.\n\n", "default")

        def insert_numbered_list_item(widget, number, text):
            widget.insert(tk.END, f"{number}. ", "numbered")
            widget.insert(tk.END, text + "\n", "default")


        insert_numbered_list_item(self.guide_text_widget, 1, "Input: Load a local file (\"Browse...\"), a direct URL (\"Load URL\"), or an online video URL (\"Download (yt-dlp)\"). Drag and drop also works.")
        insert_numbered_list_item(self.guide_text_widget, 2, "Gemini Settings: Choose a Gemini model and set the Temperature (controls output randomness).")
        insert_numbered_list_item(self.guide_text_widget, 3, "Targeting: Select the output language (\"Target Lang\") and optionally set a \"Translation Style\" and \"Context Keywords\" (terms in the target language).")
        insert_numbered_list_item(self.guide_text_widget, 4, "Start: Click \"1. Start Gemini Process\". The app extracts audio, sends it to Gemini, and shows the result in the editor.")
        insert_numbered_list_item(self.guide_text_widget, 5, "Review & Edit: Manually correct subtitles in the editor if needed.")
        insert_numbered_list_item(self.guide_text_widget, 6, "Analyze Timestamps: Click \"2. Analyze Timestamps\" to check formatting and timing errors.")
        insert_numbered_list_item(self.guide_text_widget, 7, "Request Gemini Fix: Use \"3. Request Gemini Fix\" to send the current text back to Gemini with a custom prompt for corrections.")
        insert_numbered_list_item(self.guide_text_widget, 8, "Refine Timing: Click \"Refine Timing (Gaps/Overlaps)\" for automatic gap/overlap adjustments.")
        insert_numbered_list_item(self.guide_text_widget, 9, "Save SRT: Click \"Save Subtitles as SRT\". After saving, you'll be asked if you want to send the video and SRT to the \"Mux/Encode Video\" tab.")
        self.guide_text_widget.insert(tk.END, "\n", "default") # Add extra space after numbered list

        # Translate Subtitles Tab Subsection
        self.guide_text_widget.insert(tk.END, "Translate Subtitles Tab\n\n", "h2")
        self.guide_text_widget.insert(tk.END, "Use this tab to translate existing subtitle files (like SRT or ASS).\n\n", "default")

        insert_numbered_list_item(self.guide_text_widget, 1, "Load Subtitle File: Use the browse button or drag-and-drop to load an existing subtitle file.")
        insert_numbered_list_item(self.guide_text_widget, 2, "Gemini Settings: (Likely uses the same global API key and potentially models/temperature as the Video/Audio tab).")
        insert_numbered_list_item(self.guide_text_widget, 3, "Source/Target Language: Specify the original language of the subtitle file and the desired target language for translation.")
        insert_numbered_list_item(self.guide_text_widget, 4, "Translate: Click a button to initiate the translation process.")
        insert_numbered_list_item(self.guide_text_widget, 5, "Review & Edit: Review and make manual corrections to the translated subtitles.")
        insert_numbered_list_item(self.guide_text_widget, 6, "Save Subtitles: Save the translated subtitles, likely in SRT or the original format.")
        self.guide_text_widget.insert(tk.END, "\n", "default") # Add extra space after numbered list


        # Mux/Encode Video Tab Subsection
        self.guide_text_widget.insert(tk.END, "Mux/Encode Video Tab\n\n", "h2")
        self.guide_text_widget.insert(tk.END, "Use this tab to combine a video file with a subtitle file.\n\n", "default")

        insert_numbered_list_item(self.guide_text_widget, 1, "Input Video/Subtitle: Load the video and subtitle files. The app might pre-fill these if you sent them from the \"Translate Video/Audio\" tab.")
        insert_numbered_list_item(self.guide_text_widget, 2, "Mode: Choose \"Mux Subtitles\" (add as a selectable track) or \"Hardcode Subtitles\" (burn into video).")
        insert_numbered_list_item(self.guide_text_widget, 3, "Settings: Configure output format, quality, and subtitle appearance (font, size, color, etc. for hardcoding).")
        insert_numbered_list_item(self.guide_text_widget, 4, "Output File: Specify where to save the final video.")
        insert_numbered_list_item(self.guide_text_widget, 5, "Start: Click the button to begin processing with FFmpeg.")
        insert_numbered_list_item(self.guide_text_widget, 6, "Monitor: Check the log area for progress and status.")
        self.guide_text_widget.insert(tk.END, "\n", "default") # Add extra space after numbered list


        # Getting Help Section
        self.guide_text_widget.insert(tk.END, "Getting Help\n\n", "h2")

        insert_list_item(self.guide_text_widget, "Check the log area in each tab for process details and error messages.\n", "bullet")
        insert_list_item(self.guide_text_widget, "Refer to the main application log file (", "bullet")
        self.guide_text_widget.insert(tk.END, "app_logs/easyaisubbing.log", "italic")
        self.guide_text_widget.insert(tk.END, ") for a complete history.\n\n", "default")


        self.guide_text_widget.insert(tk.END, "Enjoy using EasyAISubbing!\n", "default")


        self.guide_text_widget.config(state="disabled") # Disable editing
        self.guide_text_widget.see("1.0") # Scroll to the top
# End of GuideTab class and TextHandler class
# Ensure no extra lines or spaces are here