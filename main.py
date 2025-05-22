# EasyAISubbing/main.py
import tkinter as tk
from tkinter import messagebox
import logging
import os
import sys # Add sys for encoding handling and app path
from core import ffmpeg_utils # Import ffmpeg_utils for dependency checks

# --- Basic stdout/stderr encoding setup for Windows if needed ---
# This helps if your console has issues with UTF-8 output from Python
if os.name == 'nt': # Only for Windows
    try:
        # Attempt to set console encoding to UTF-8
        # This might not always work depending on terminal/environment
        sys.stdout.reconfigure(encoding='utf-8') # type: ignore
        sys.stderr.reconfigure(encoding='utf-8') # type: ignore
    except Exception as e_enc:
        # Log this warning but don't crash the app
        # Initialize a basic logger for this specific warning if main logger isn't up yet
        logging.basicConfig(level=logging.WARNING)
        logging.warning(f"Could not reconfigure stdout/stderr encoding on Windows: {e_enc}")


# --- Setup Basic Logging ---
log_dir_name = "app_logs"

def get_app_executable_directory():
    """Determines the application's executable directory."""
    if getattr(sys, 'frozen', False): # If the application is run as a PyInstaller bundle
        return os.path.dirname(sys.executable)
    else: # If run as a normal Python script (main.py is in the project root)
        # Assuming main.py is in the root of the 'EasyAISubbing' project directory
        return os.path.dirname(os.path.abspath(__file__))

try:
    app_root_dir = get_app_executable_directory()
    log_dir_path = os.path.join(app_root_dir, log_dir_name)
    os.makedirs(log_dir_path, exist_ok=True)
    log_file_path = os.path.join(log_dir_path, "easyaisubbing_app.log") # Consistent log file name
except Exception as e_log_dir:
    # Fallback if log directory cannot be created in the desired location
    log_file_path = "easyaisubbing_app.log"
    logging.basicConfig(level=logging.WARNING) # Basic config for this warning
    logging.warning(f"Could not create log directory at {log_dir_path if 'log_dir_path' in locals() else 'unknown path'}: {e_log_dir}. Logging to current directory: {log_file_path}")


logging.basicConfig(
    level=logging.INFO, # Start with INFO, can change to DEBUG when needed
    format='%(asctime)s - %(name)-28s - %(levelname)-8s - %(message)s', # Adjusted name field width
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout), # Log to console (stdout)
        logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
    ]
)
# Main logger for the application, using the project's root name for clarity
logger = logging.getLogger("EasyAISubbing.MainApp")

# --- Log unhandled exceptions globally ---
def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.critical("Unhandled exception:", exc_info=(exc_type, exc_value, exc_traceback))
    # Optional: show a simple Tkinter messagebox for unhandled exceptions
    try:
        temp_root = tk.Tk()
        temp_root.withdraw()
        messagebox.showerror(
            "Unhandled Application Error", # UI String: English
            "An unexpected error occurred. Please check the logs for details.\n\n" # UI String: English
            f"Error: {exc_value}"
        )
        temp_root.destroy()
    except Exception:
        pass # Ignore if can't show messagebox

sys.excepthook = handle_exception


# --- Application Entry Point ---
if __name__ == "__main__":
    logger.info("============================================================")
    logger.info("    Starting Easy AI Subbing Application")
    logger.info("============================================================")
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Application executable directory: {get_app_executable_directory()}")
    logger.info(f"Log file: {os.path.abspath(log_file_path)}")

    # --- Check for external dependencies early ---
    missing_dependencies = []
    if not ffmpeg_utils.check_ffmpeg_exists():
        missing_dependencies.append("FFmpeg (for video/audio processing)")
    if not ffmpeg_utils.check_yt_dlp_exists():
        missing_dependencies.append("yt-dlp (for downloading from URLs)")

    if missing_dependencies:
        dependency_message = "The following external dependencies are missing or not in your system's PATH:\n\n" # UI String: English
        for dep in missing_dependencies:
            dependency_message += f"- {dep}\n"
        dependency_message += "\nPlease install them and ensure they are accessible from your command line.\n\n" # UI String: English
        dependency_message += "FFmpeg: https://ffmpeg.org/download.html\n"
        dependency_message += "yt-dlp: https://github.com/yt-dlp/yt-dlp#installation"

        root_dep_err = tk.Tk()
        root_dep_err.withdraw()
        messagebox.showerror("External Dependency Error", dependency_message) # UI String: English
        root_dep_err.destroy()

        if "FFmpeg (for video/audio processing)" in missing_dependencies:
             logger.critical("FFmpeg is missing. Application cannot continue.")
             sys.exit(1)
        if "yt-dlp (for downloading from URLs)" in missing_dependencies:
             logger.critical("yt-dlp is missing. URL download functionality will be affected. Application might still run.")
             # sys.exit(1) # Decided not to exit for yt-dlp for now


    # --- Check for pysubs2 early ---
    try:
        import pysubs2
        logger.info(f"Pysubs2 library found, version: {pysubs2.__version__}")
    except ImportError:
        logger.critical("CRITICAL: pysubs2 library is NOT installed. Subtitle parsing will fail.")
        logger.critical("Please install it by running: pip install pysubs2")
        root_err = tk.Tk()
        root_err.withdraw()
        messagebox.showerror(
            "Dependency Error", # UI String: English
            "The 'pysubs2' library is missing, which is essential for subtitle processing.\n\n" # UI String: English
            "Please install it by running:\n"
            "pip install pysubs2\n\n"
            "The application will now close." # UI String: English
        )
        root_err.destroy()
        sys.exit(1)

    # --- Import MainWindow after pysubs2 check ---
    try:
        from app_gui.main_window import MainWindow # Ensure this path is correct relative to main.py
    except ImportError as e:
        logger.critical(f"Failed to import MainWindow: {e}. Ensure all GUI modules are present and sys.path is correct.", exc_info=True)
        root_err_mw = tk.Tk()
        root_err_mw.withdraw()
        messagebox.showerror(
            "Application Import Error", # UI String: English
            f"Could not start the application.\nError: {e}\n\nPlease check application files and dependencies." # UI String: English
        )
        root_err_mw.destroy()
        sys.exit(1)
    except Exception as e_generic_import: # Catch other potential import errors
        logger.critical(f"A generic error occurred during MainWindow import: {e_generic_import}", exc_info=True)
        root_err_mw_gen = tk.Tk()
        root_err_mw_gen.withdraw()
        messagebox.showerror("Application Error", f"A critical error occurred while loading application components: {e_generic_import}") # UI String: English
        root_err_mw_gen.destroy()
        sys.exit(1)


    app_instance = None
    try:
        app_instance = MainWindow()
        app_instance.mainloop()
    except tk.TclError as e:
        logger.critical(f"Tkinter TclError at top level: {e}", exc_info=True)
        # If handle_exception is working, it might already show a messagebox.
        # Avoid double messageboxes.
    except Exception as e:
        logger.critical(f"Unhandled exception at application top level: {e}", exc_info=True)
    finally:
        logger.info("============================================================")
        logger.info("    Easy AI Subbing Application Closed")
        logger.info("============================================================")
        logging.shutdown() # Ensure all handlers are flushed