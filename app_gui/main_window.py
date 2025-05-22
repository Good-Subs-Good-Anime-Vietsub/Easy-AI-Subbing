# EasyAISubbing/app_gui/main_window.py
import tkinter as tk
from tkinter import ttk, messagebox, font as tkFont
import os
import shutil
import tempfile
import logging

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_SUPPORTED = True
    TkinterDnDRoot = TkinterDnD.Tk
except ImportError:
    DND_SUPPORTED = False
    TkinterDnDRoot = tk.Tk
    logging.warning("tkinterdnd2 library not found. Drag and drop functionality will be disabled.")

logger = logging.getLogger(__name__) # Should be app_gui.main_window if run from main

class MainWindow(TkinterDnDRoot):
    def __init__(self):
        super().__init__()
        self.title("Easy Ai Subbing")

        self.style = ttk.Style(self)
        self._configure_styles()
        self._setup_geometry()
        self.app_temp_dir = None
        self.temp_files_to_cleanup = [] # List to store paths of temp files created by tabs
        self._setup_temp_directory()

        # Biến chia sẻ giữa các tab (ví dụ)
        self.last_processed_video_path_for_sharing = tk.StringVar()
        self.last_generated_srt_path_for_sharing = tk.StringVar()

        # --- Global API Key Configuration ---
        self.api_key_var = tk.StringVar()
        self._create_api_config_section()
        self._load_initial_api_key() # Load key on startup

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # --- IMPORT TABS ---
        from .video_audio_tab import VideoAudioTab
        from .subtitle_translate_tab import SubtitleTranslateTab # <--- IMPORT TAB MỚI
        from .video_processing_tab import VideoProcessingTab
        from .guide_tab import GuideTab # Import the new Guide Tab
        from .about_tab import AboutTab # Import the new About Tab

        # --- KHỞI TẠO TABS ---
        # VideoAudioTab phải được tạo trước vì SubtitleTranslateTab có thể phụ thuộc vào các biến của nó
        self.video_audio_tab = VideoAudioTab(self.notebook, self)
        self.subtitle_translate_tab = SubtitleTranslateTab(self.notebook, self) # <--- KHỞI TẠO TAB MỚI
        self.video_processing_tab = VideoProcessingTab(self.notebook, self)
        # --- KHỞI TẠO TABS MỚI ---
        self.guide_tab = GuideTab(self.notebook, self) # Initialize the Guide Tab
        self.about_tab = AboutTab(self.notebook, self) # Initialize the About Tab

        # --- THÊM TABS VÀO NOTEBOOK ---
        # Add tabs to the notebook with updated names
        self.notebook.add(self.video_audio_tab, text="Translate Video/Audio")
        self.notebook.add(self.subtitle_translate_tab, text="Translate Subtitles")
        self.notebook.add(self.video_processing_tab, text="Mux/Encode Video")
        # --- THÊM TABS MỚI VÀO NOTEBOOK (ở cuối) ---
        self.notebook.add(self.guide_tab, text="Guide")
        self.notebook.add(self.about_tab, text="About")

        if not DND_SUPPORTED:
            logger.warning("Drag and drop is NOT available (tkinterdnd2 missing).")
        else:
            logger.info("Drag and drop support enabled via tkinterdnd2.")

        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        logger.info("MainWindow initialized.")

    def _create_api_config_section(self):
        """Creates the global API key configuration section."""
        api_frame = ttk.Frame(self, padding="5")
        api_frame.pack(fill=tk.X, padx=5, pady=(5, 0))
        api_frame.columnconfigure(1, weight=1)

        api_key_label = ttk.Label(api_frame, text="Gemini API Key:")
        api_key_label.grid(row=0, column=0, sticky=tk.W, padx=5, pady=3)

        self.api_key_entry = ttk.Entry(api_frame, textvariable=self.api_key_var, width=60, show="*")
        self.api_key_entry.grid(row=0, column=1, sticky=tk.EW, padx=5, pady=3)

        # Instructions for using environment variable
        # Add a help button for environment variable instructions
        self.env_var_help_button = ttk.Button(api_frame, text="?", width=2, command=self._show_env_var_help)
        self.env_var_help_button.grid(row=1, column=0, padx=(5,0), pady=(0,3), sticky=tk.W)

        # Instructions for using environment variable
        env_var_instruction_label = ttk.Label(api_frame, text="For better security, you can use the GEMINI_API_KEY environment variable instead of saving the key here.\nIf the environment variable is set, the key in this field will be ignored and removed from the config file.", font=('Segoe UI', 8, 'italic'))
        env_var_instruction_label.grid(row=1, column=1, columnspan=2, sticky=tk.W, padx=(0,5), pady=(0,3)) # Adjusted column and columnspan

        self.save_api_key_button = ttk.Button(api_frame, text="Save & Test", command=self._save_and_test_api_key)
        self.save_api_key_button.grid(row=0, column=2, padx=5, pady=3, sticky=tk.E)
        # Assuming ToolTip is available from ui_utils or similar
        from .ui_utils import ToolTip # Ensure ToolTip is imported
        ToolTip(self.save_api_key_button, "Save the API Key and test its validity with Gemini.")
        ToolTip(self.env_var_help_button, "Show instructions on how to set the GEMINI_API_KEY environment variable.")

    def _show_env_var_help(self):
        """Displays a help window with instructions on setting the environment variable."""
        help_window = tk.Toplevel(self)
        help_window.title("Environment Variable Help")
        help_window.transient(self) # Make the help window appear on top of the main window
        help_window.grab_set() # Prevent interaction with the main window while help is open
        help_window.resizable(False, False)

        help_text = """
Using the GEMINI_API_KEY Environment Variable (Recommended for Security)

Instead of saving your API key directly in the application's configuration file,
you can set it as an environment variable on your operating system.
This is a more secure way to handle sensitive information.

Follow the instructions for your operating system:

Windows:
1. Search for "Environment Variables" in the Start menu and select "Edit the system environment variables".
2. In the System Properties window, click the "Environment Variables..." button.
3. Under "User variables for [Your Username]", click "New...".
4. Enter "GEMINI_API_KEY" as the Variable name.
5. Paste your Gemini API Key as the Variable value.
6. Click "OK" on all open windows to save.
7. You may need to restart your computer or log out and back in for changes to take effect.
   Alternatively, you can set it temporarily in your command prompt:
   set GEMINI_API_KEY=YOUR_API_KEY
   (This only lasts for the current terminal session)
   Or permanently from Command Prompt (Windows 7+):
   setx GEMINI_API_KEY "YOUR_API_KEY"
   (Requires closing and reopening the terminal)

macOS and Linux:
1. Open your terminal.
2. Edit your shell's profile file (e.g., ~/.bashrc, ~/.zshrc, ~/.profile).
   You can use a text editor like nano or vim:
   nano ~/.bashrc  (or your preferred shell file)
3. Add the following line to the end of the file:
   export GEMINI_API_KEY="YOUR_API_KEY"
   (Replace YOUR_API_KEY with your actual key)
4. Save the file and exit the editor.
5. Apply the changes by closing and reopening your terminal, or by running:
   source ~/.bashrc (or the file you edited)
   You can test if it's set by running: echo $GEMINI_API_KEY

After setting the environment variable, the application will automatically
detect and use it, and will remove any saved key from the config file.
"""

        text_widget = tk.Text(help_window, wrap=tk.WORD, width=80, height=25, font=('Segoe UI', 9))
        text_widget.insert(tk.END, help_text.strip())
        text_widget.config(state=tk.DISABLED) # Make text read-only
        text_widget.pack(padx=10, pady=10)

        close_button = ttk.Button(help_window, text="Close", command=help_window.destroy)
        close_button.pack(pady=(0, 10))

        # Center the help window
        help_window.update_idletasks()
        main_window_x = self.winfo_x()
        main_window_y = self.winfo_y()
        main_window_width = self.winfo_width()
        main_window_height = self.winfo_height()
        help_window_width = help_window.winfo_width()
        help_window_height = help_window.winfo_height()

        center_x = main_window_x + (main_window_width // 2) - (help_window_width // 2)
        center_y = main_window_y + (main_window_height // 2) - (help_window_height // 2)

        help_window.geometry(f'+{center_x}+{center_y}')


    def _load_initial_api_key(self):
        """Loads the API key from config on startup and configures gemini_utils."""
        from core import config_manager, gemini_utils # Import here to avoid circular dependency on init
        api_key = config_manager.load_api_key()
        
        key_source = "config file"
        if os.environ.get('GEMINI_API_KEY'):
            key_source = "environment variable GEMINI_API_KEY"

        if api_key:
            self.api_key_var.set(api_key)
            if gemini_utils.configure_api(api_key):
                logger.info(f"Gemini API configured successfully with key loaded from {key_source}.")
            else:
                logger.warning(f"Failed to configure Gemini API with key loaded from {key_source} on startup.")
        else:
            logger.info(f"No Gemini API key found in {key_source} on startup.")

    def _save_and_test_api_key(self):
        """Saves the API key and tests its validity."""
        from core import config_manager, gemini_utils # Import here
        api_key = self.api_key_var.get()
        if not api_key:
            messagebox.showerror("Error", "API Key cannot be empty.", parent=self)
            return

        logger.info("Testing Gemini API Key...")
        if gemini_utils.configure_api(api_key):
            models_info = gemini_utils.list_available_models() # Test by listing models
            is_fallback = any("fallback list" in m.get("display_name","").lower() for m in models_info if isinstance(m, dict))

            if models_info and not is_fallback:
                config_manager.save_api_key(api_key)
                logger.info("Gemini API Key saved & validated successfully.")
                messagebox.showinfo("API Key Test", "API Key is valid and has been saved.", parent=self)
                # Trigger model list refresh in tabs if they are already created
                if hasattr(self, 'video_audio_tab') and self.video_audio_tab:
                    self.video_audio_tab._load_gemini_models()
                if hasattr(self, 'subtitle_translate_tab') and self.subtitle_translate_tab:
                    self.subtitle_translate_tab._load_gemini_models_for_tab()
            else:
                logger.error("Failed to validate Gemini API key (could not fetch actual models or only fallback returned).")
                messagebox.showerror("API Key Test Failed", "The API Key might be for a different project, has insufficient permissions, or is incorrect. Models could not be listed.", parent=self)
        else:
            logger.error("Failed to configure Gemini API with the provided key.")
            messagebox.showerror("API Key Test Failed", "The provided API Key is invalid or there's a connection issue.", parent=self)


    def _on_closing(self):
        logger.info("Close button clicked.")

        # Save global settings
        from core import config_manager # Import here
        config_manager.save_api_key(self.api_key_var.get()) # Save API key

        # Save settings from all tabs before closing
        if hasattr(self, 'video_audio_tab') and self.video_audio_tab:
            self.video_audio_tab._save_current_ui_settings() # Đảm bảo hàm này có trong video_audio_tab
        if hasattr(self, 'subtitle_translate_tab') and self.subtitle_translate_tab:
            self.subtitle_translate_tab._save_settings() # Hàm này đã được thêm vào SubtitleTranslateTab
        if hasattr(self, 'video_processing_tab') and self.video_processing_tab:
            self.video_processing_tab._save_settings() # Đảm bảo hàm này có trong video_processing_tab
        # Save settings from new tabs before closing (if they have a _save_settings method)
        if hasattr(self, 'guide_tab') and self.guide_tab and hasattr(self.guide_tab, '_save_settings'):
             self.guide_tab._save_settings()
        if hasattr(self, 'about_tab') and self.about_tab and hasattr(self.about_tab, '_save_settings'):
             self.about_tab._save_settings()

        # --- Clean up temporary files tracked by tabs ---
        if self.temp_files_to_cleanup:
            logger.info(f"Cleaning up {len(self.temp_files_to_cleanup)} tracked temporary files...")
            for temp_file in self.temp_files_to_cleanup:
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                        logger.debug(f"Cleaned up tracked temp file: {temp_file}")
                    except OSError as e:
                        logger.warning(f"Could not remove tracked temp file {temp_file}: {e}")
            self.temp_files_to_cleanup.clear() # Clear the list after attempting cleanup
            logger.info("Finished cleaning up tracked temporary files.")

        # ... (phần còn lại của _on_closing giữ nguyên) ...

        if self.app_temp_dir and os.path.exists(self.app_temp_dir):
            try:
                if any(os.scandir(self.app_temp_dir)):
                    if messagebox.askyesno("Clean Up Temporary Files",
                                           f"Do you want to remove temporary files from '{os.path.basename(self.app_temp_dir)}' before exiting?",
                                           parent=self):
                        self._cleanup_temp_directory(clear_all=True)
                        try:
                            if not os.listdir(self.app_temp_dir):
                                shutil.rmtree(self.app_temp_dir, ignore_errors=True)
                                logger.info(f"Removed empty temp directory: {self.app_temp_dir}")
                        except Exception as e_rmdir:
                            logger.warning(f"Could not remove temp directory {self.app_temp_dir} after cleanup: {e_rmdir}")
                else:
                     try:
                         shutil.rmtree(self.app_temp_dir, ignore_errors=True)
                         logger.info(f"Removed empty temp directory: {self.app_temp_dir}")
                     except Exception as e:
                         logger.warning(f"Could not remove empty temp directory {self.app_temp_dir}: {e}")
            except Exception as e:
                 logger.warning(f"Error during temp dir cleanup check on closing: {e}")

        if messagebox.askokcancel("Quit Application", "Are you sure you want to quit?", parent=self):
            logger.info("User confirmed quit. Destroying main window.")
            self.destroy()
        else:
            logger.info("User cancelled quit.")


    def _configure_styles(self):
        # ... (giữ nguyên) ...
        available_themes = self.style.theme_names()
        desired_theme = 'vista'
        if desired_theme not in available_themes:
            if 'xpnative' in available_themes: desired_theme = 'xpnative'
            elif 'clam' in available_themes: desired_theme = 'clam'
            else: desired_theme = self.style.theme_use()

        try:
            self.style.theme_use(desired_theme)
            logger.info(f"Using ttk theme: {desired_theme}")
        except tk.TclError:
            current_theme = self.style.theme_use()
            logger.warning(f"Could not apply preferred theme '{desired_theme}'. Using '{current_theme}'.")

        self.default_font_size = 10 # Reverted font size to 10
        self.default_font_family = "Segoe UI"
        try:
            self.custom_font = tkFont.Font(family=self.default_font_family, size=self.default_font_size)
            self.custom_bold_font = tkFont.Font(family=self.default_font_family, size=self.default_font_size, weight="bold")
        except tk.TclError:
            logger.warning(f"Font '{self.default_font_family}' not found. Using system default.")
            self.custom_font = tkFont.nametofont("TkDefaultFont")
            bold_config = self.custom_font.actual()
            bold_config['weight'] = 'bold'
            self.custom_bold_font = tkFont.Font(**bold_config)

        self.style.configure('.', font=self.custom_font)
        self.style.configure('TButton', font=self.custom_font, padding=3) # Reverted button padding

        # Configure style for Notebook tabs to increase their size slightly via padding
        self.style.configure('TNotebook.Tab', font=self.custom_font, padding=[10, 8]) # Adjusted padding for tabs (increased vertical padding)

        self.style.configure('TLabel', font=self.custom_font)
        self.style.configure('TEntry', font=self.custom_font)

        self.style.configure('TCombobox', font=self.custom_font)
        self.style.map('TCombobox',
            fieldbackground=[
                ('readonly', '!focus', 'white'),
                ('readonly', 'focus', 'white'),
                ('!readonly', 'white')
            ],
            selectbackground=[('focus', 'SystemHighlight')],
            selectforeground=[('focus', 'SystemHighlightText')],
            foreground=[
                ('readonly', 'black'),
                ('!readonly', 'black')
            ]
        )

        self.style.configure('TCheckbutton', font=self.custom_font)
        self.style.configure('TSpinbox', font=self.custom_font)
        self.style.configure('TScale', font=self.custom_font)
        self.style.configure('TLabelFrame.Label', font=self.custom_bold_font)
        self.style.configure('Treeview.Heading', font=self.custom_bold_font)

    def _setup_geometry(self):
        # ... (giữ nguyên) ...
        window_width = 1000
        window_height = 1000 # Adjusted height for a more standard aspect ratio
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        center_x = int(screen_width/2 - window_width / 2)
        center_y = int(screen_height/2 - window_height / 2)
        if center_x < 0: center_x = 0
        if center_y < 0: center_y = 0
        # Giảm kích thước cửa sổ một chút nếu màn hình quá nhỏ
        if window_width > screen_width * 0.9: window_width = int(screen_width * 0.9)
        if window_height > screen_height * 0.9: window_height = int(screen_height * 0.9)

        self.geometry(f'{window_width}x{window_height}+{center_x}+{center_y}')
        self.minsize(max(800, window_width), max(600, window_height))


    def _setup_temp_directory(self):
        # ... (giữ nguyên) ...
        try:
            app_root_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.app_temp_dir = os.path.join(app_root_path, "temp_sub_files")
            os.makedirs(self.app_temp_dir, exist_ok=True)
            logger.info(f"Using app temporary directory: {self.app_temp_dir}")
        except Exception as e1:
            logger.warning(f"Could not create temp directory in app root ({e1}). Using system temp.")
            try:
                self.app_temp_dir = tempfile.mkdtemp(prefix="gemini_sub_")
                logger.info(f"Using system temporary directory: {self.app_temp_dir}")
            except Exception as e2:
                logger.error(f"Could not create any temporary directory: {e2}")
                messagebox.showerror("Fatal Error", "Could not create a temporary directory. Application cannot continue.")
                self.destroy()
                return
        self._cleanup_temp_directory(clear_all=True)

    def _cleanup_temp_directory(self, clear_all=False):
        # ... (giữ nguyên) ...
        if not self.app_temp_dir or not os.path.exists(self.app_temp_dir):
            logger.debug("Temp directory does not exist or not set, skipping cleanup.")
            return

        if clear_all:
            logger.info(f"Cleaning ALL contents of temp directory: {self.app_temp_dir}")
            for item in os.listdir(self.app_temp_dir):
                item_path = os.path.join(self.app_temp_dir, item)
                try:
                    if os.path.isfile(item_path) or os.path.islink(item_path):
                        os.unlink(item_path)
                    elif os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                except Exception as e:
                    logger.error(f'Failed to delete {item_path} during cleanup: {e}')
