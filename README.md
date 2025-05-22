# EasyAISubbing User Guide

Welcome to EasyAISubbing, a tool designed to simplify creating subtitles for your media using AI.

Prerequisites: Installing FFmpeg and yt-dlp

EasyAISubbing requires FFmpeg for audio/video processing and yt-dlp for downloading online media. These must be installed and accessible via your system's PATH.

## Installing FFmpeg

FFmpeg is essential for tasks like extracting audio or muxing subtitles into videos.

- Download: Get the latest version for your OS: https://ffmpeg.org/download.html

- Installation & Adding to PATH:
    1. Windows: Download the zip, extract it (e.g., C:\ffmpeg). Add the bin folder (e.g., C:\ffmpeg\bin) to your system's Environment Variables (specifically, the PATH variable). Search online for "how to add to path windows" if needed.
    2. macOS (using Homebrew): Open Terminal and run brew install ffmpeg.
    3. Linux (using package manager): Open Terminal. For Debian/Ubuntu: sudo apt update && sudo apt install ffmpeg. For Fedora: sudo dnf install ffmpeg.

Verify: Open your terminal/command prompt and run ffmpeg -version.

## Installing yt-dlp

yt-dlp lets you download videos from YouTube and many other sites directly into the app.

- Download: Get the executable for your OS from the releases page: https://github.com/yt-dlp/yt-dlp

- Installation & Adding to PATH:
    1. Windows: Download yt-dlp.exe. Place it in a directory already in your PATH (e.g., C:\Windows\System32 - use caution, or create a dedicated tools folder and add that to PATH).
    2. macOS/Linux: Download the binary (yt-dlp). Make it executable (chmod +x yt-dlp). Place it in a directory in your PATH (e.g., /usr/local/bin). Alternatively: pip install yt-dlp.
Troubleshooting Tip: If EasyAISubbing reports FFmpeg or yt-dlp missing, double-check your PATH settings and restart the application.

## How to Use EasyAISubbing Tabs

The application is organized into several tabs for different parts of the subtitling workflow:

### Translate Video/Audio Tab

Use this tab to get subtitles from media files using Gemini.

1. Input: Load a local file ("Browse..."), a direct URL ("Load URL"), or an online video URL ("Download (yt-dlp)"). Drag and drop also works.
2. Gemini Settings: Choose a Gemini model and set the Temperature (controls output randomness).
3. Targeting: Select the output language ("Target Lang") and optionally set a "Translation Style" and "Context Keywords" (terms in the target language).
4. Start: Click "1. Start Gemini Process". The app extracts audio, sends it to Gemini, and shows the result in the editor.
5. Review & Edit: Manually correct subtitles in the editor if needed.
6. Analyze Timestamps: Click "2. Analyze Timestamps" to check formatting and timing errors.
7. Request Gemini Fix: Use "3. Request Gemini Fix" to send the current text back to Gemini with a custom prompt for corrections.
8. Refine Timing: Click "Refine Timing (Gaps/Overlaps)" for automatic gap/overlap adjustments.
9. Save SRT: Click "Save Subtitles as SRT". After saving, you'll be asked if you want to send the video and SRT to the "Mux/Encode Video" tab.

### Translate Subtitles Tab

Use this tab to translate existing subtitle files (like SRT or ASS).

1. Load Subtitle File: Use the browse button or drag-and-drop to load an existing subtitle file.
2. Gemini Settings: (Likely uses the same global API key and potentially models/temperature as the Video/Audio tab).
3. Source/Target Language: Specify the original language of the subtitle file and the desired target language for translation.
4. Translate: Click a button to initiate the translation process.
5. Review & Edit: Review and make manual corrections to the translated subtitles.
6. Save Subtitles: Save the translated subtitles, likely in SRT or the original format.

### Mux/Encode Video Tab

Use this tab to combine a video file with a subtitle file.

1. Input Video/Subtitle: Load the video and subtitle files. The app might pre-fill these if you sent them from the "Translate Video/Audio" tab.
2. Mode: Choose "Mux Subtitles" (add as a selectable track) or "Hardcode Subtitles" (burn into video).
3. Settings: Configure output format, quality, and subtitle appearance (font, size, color, etc. for hardcoding).
4. Output File: Specify where to save the final video.
5. Start: Click the button to begin processing with FFmpeg.
6. Monitor: Check the log area for progress and status.

### Getting Help

Check the log area in each tab for process details and error messages.
Refer to the main application log file (app_logs/easyaisubbing.log) for a complete history.

Enjoy using EasyAISubbing!
