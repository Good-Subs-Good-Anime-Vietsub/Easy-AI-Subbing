# EasyAISubbing/app_gui/about_tab.py
import tkinter as tk
from tkinter import ttk, font as tkFont
import logging
import webbrowser # Import webbrowser to open links

logger = logging.getLogger(__name__)

# TextHandler class (copied for local tab logging, if needed)
# Using the same TextHandler as in guide_tab.py and video_audio_tab.py
class TextHandler(logging.Handler):
    def __init__(self, text_widget, tab_logger_name):
        super().__init__()
        self.text_widget = text_widget
        self.tab_logger_name = tab_logger_name
        self.formatter = logging.Formatter('%(asctime)s %(levelname)-7s: %(message)s', datefmt='%H:%M:%S')

    def format(self, record):
        return self.formatter.format(record)

    def emit(self, record):
        if not record.name.startswith(self.tab_logger_name):
            return

        msg = self.format(record)
        try:
            if hasattr(self, 'text_widget') and self.text_widget.winfo_exists():
                self.text_widget.after(0, self._append_text_thread_safe, msg + '\n')
        except tk.TclError:
            pass
        except Exception as e:
            print(f"Error emitting log to GUI (TextHandler for {self.tab_logger_name}): {e}")

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
            print(f"Error appending text to GUI log widget (TextHandler for {self.tab_logger_name}): {e}")


class AboutTab(ttk.Frame):
    def __init__(self, parent_notebook, app_controller):
        super().__init__(parent_notebook)
        self.app_controller = app_controller
        self.logger = logging.getLogger(f"{__name__}.AboutTab")

        # Access font from app_controller
        self.custom_font = getattr(self.app_controller, 'custom_font', tkFont.nametofont("TkDefaultFont"))
        self.custom_bold_font = getattr(self.app_controller, 'custom_bold_font', tkFont.nametofont("TkDefaultFont"))
        if not hasattr(self.app_controller, 'default_font_family'):
            self.default_font_family = self.custom_font.actual()['family']
        else:
            self.default_font_family = self.app_controller.default_font_family

        if not hasattr(self.app_controller, 'default_font_size'):
             self.default_font_size = self.custom_font.actual()['size']
        else:
             self.default_font_size = self.app_controller.default_font_size

        # --- Local logging setup ---
        self._create_local_log_area(self)
        if hasattr(self, 'log_text_widget') and self.log_text_widget:
             gui_log_handler = TextHandler(self.log_text_widget, self.logger.name)
             gui_log_handler.setLevel(logging.INFO)
             if not any(isinstance(h, TextHandler) for h in self.logger.handlers):
                  self.logger.addHandler(gui_log_handler)
             self.logger.setLevel(logging.INFO)
        else:
             self.logger.warning("Local log text widget not available for AboutTab. Logging only to console/file.")
        # --- End Local logging setup ---


        self._init_ui()
        self.logger.info("About Tab initialized.")

    def _create_local_log_area(self, parent_frame):
        """Creates a simple text area for local tab logging."""
        log_frame = ttk.LabelFrame(parent_frame, text="Tab Log", padding="5")
        self.log_text_widget = tk.Text(log_frame, wrap=tk.WORD, state="disabled",
                                      height=5,
                                      font=(self.default_font_family, self.default_font_size -2),
                                      relief=tk.SUNKEN)
        scroll_y = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text_widget.yview)
        self.log_text_widget.config(yscrollcommand=scroll_y.set)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        return log_frame


    def _open_link(self, url):
        """Opens the given URL in a new web browser tab."""
        try:
            webbrowser.open_new_tab(url)
            self.logger.info(f"Opened link: {url}")
        except Exception as e:
            self.logger.error(f"Failed to open link {url}: {e}")

    def _init_ui(self):
        about_frame = ttk.LabelFrame(self, text="About EasyAISubbing", padding="10")
        about_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5)) # Add padding at the bottom

        # Use labels for static text information
        version_label = ttk.Label(about_frame, text="Version 0.2", font=self.custom_bold_font)
        version_label.pack(pady=(0, 10), anchor="center") # Center version label

        developed_by_label = ttk.Label(about_frame, text="Developed by:", font=self.custom_bold_font)
        developed_by_label.pack(pady=(5, 2), anchor="w")

        kioz_label = ttk.Label(about_frame, text="KiOZ (Gió Chiều):")
        kioz_label.pack(pady=(0, 2), anchor="w", padx=20)

        # Clickable links
        kioz_fb_url = "https://www.facebook.com/"
        kioz_fb_label = tk.Label(about_frame, text="Facebook", fg="blue", cursor="hand2", font=self.custom_font)
        kioz_fb_label.pack(pady=(0, 2), anchor="w", padx=40)
        kioz_fb_label.bind("<Button-1>", lambda e, url=kioz_fb_url: self._open_link(url))

        kioz_github_url = "https://github.com/realKiOZ"
        kioz_github_label = tk.Label(about_frame, text="GitHub", fg="blue", cursor="hand2", font=self.custom_font)
        kioz_github_label.pack(pady=(0, 5), anchor="w", padx=40)
        kioz_github_label.bind("<Button-1>", lambda e, url=kioz_github_url: self._open_link(url))


        in_collaboration_label = ttk.Label(about_frame, text="In collaboration with:", font=self.custom_bold_font)
        in_collaboration_label.pack(pady=(5, 2), anchor="w")

        gsga_label = ttk.Label(about_frame, text="GSGA Fansub:")
        gsga_label.pack(pady=(0, 2), anchor="w", padx=20)

        gsga_website_url = "https://gsga.moe/"
        gsga_website_label = tk.Label(about_frame, text="GSGA Website", fg="blue", cursor="hand2", font=self.custom_font)
        gsga_website_label.pack(pady=(0, 5), anchor="w", padx=40)
        gsga_website_label.bind("<Button-1>", lambda e, url=gsga_website_url: self._open_link(url))


        youtube_channels_label = ttk.Label(about_frame, text="Our YouTube Channels:", font=self.custom_bold_font)
        youtube_channels_label.pack(pady=(5, 2), anchor="w")

        furincine_url = "https://www.youtube.com/@FurinCine"
        furincine_label = tk.Label(about_frame, text="Furin Cine", fg="blue", cursor="hand2", font=self.custom_font)
        furincine_label.pack(pady=(0, 2), anchor="w", padx=40)
        furincine_label.bind("<Button-1>", lambda e, url=furincine_url: self._open_link(url))

        furinanimelody_url = "https://www.youtube.com/@FurinAnimelody"
        furinanimelody_label = tk.Label(about_frame, text="Furin Animelody", fg="blue", cursor="hand2", font=self.custom_font)
        furinanimelody_label.pack(pady=(0, 5), anchor="w", padx=40)
        furinanimelody_label.bind("<Button-1>", lambda e, url=furinanimelody_url: self._open_link(url))

        # --- Credits Section ---
        credits_frame = ttk.LabelFrame(about_frame, text="Libraries & Technologies Used", padding="10")
        credits_frame.pack(fill=tk.X, expand=False, padx=0, pady=(15, 5))

        libraries = [
            "Python",
            "Tkinter (for GUI)",
            "tkinterdnd2 (for Drag & Drop)",
            "yt-dlp (for online media download)",
            "FFmpeg (for audio/video processing)",
            "Google Gemini API (for AI translation & timing)"
        ]

        for lib_name in libraries:
            lib_label = ttk.Label(credits_frame, text=f"- {lib_name}", font=self.custom_font)
            lib_label.pack(anchor="w", padx=5)


        # Pack the local log area after the main about content frame
        log_frame = getattr(self, 'log_text_widget', None)
        if log_frame and log_frame.winfo_exists():
             log_frame_container = self.log_text_widget.master
             log_frame_container.pack(fill=tk.X, expand=False, padx=10, pady=(5, 10))


# End of AboutTab class and TextHandler class