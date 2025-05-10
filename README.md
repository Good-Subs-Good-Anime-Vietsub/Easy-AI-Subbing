# Easy AI Subbing

## Project Title
Easy AI Subbing

## Short Description
Easy AI Subbing is a simple graphical user interface (GUI) application built with Tkinter that leverages the Google Gemini API and FFmpeg to facilitate the process of generating and correcting subtitles (.srt) for video and audio files.

## Features
*   **Direct Translation:** Translate speech directly from audio/video files into a target language and generate an SRT file.
*   **SRT Validation & Correction:** Review and correct existing SRT files against the original audio/video, including adjusting timestamps and text based on AI analysis.
*   **Flexible Input:** Supports various video and audio formats (handled by FFmpeg) and existing SRT files for validation.
*   **API Key Management:** Securely save your Gemini API key locally in your home directory.
*   **Custom Prompts:** Customize the API prompts for translation and validation tasks.
*   **Glossary/Tone Control:** Include a custom glossary and define a desired translation tone/style.
*   **User-Friendly GUI:** Simple interface with status updates and easy file browsing/saving.

## Prerequisites

Before you can run this application, you need to have the following installed:

1.  **Python 3.6+:** You can download Python from [python.org](https://www.python.org/downloads/).
2.  **Git:** For cloning the repository. Download from [git-scm.com](https://git-scm.com/downloads).
3.  **FFmpeg:** This is **required** for processing audio and video files. Download FFmpeg from [ffmpeg.org](https://ffmpeg.org/download.html). **Ensure FFmpeg executables are added to your system's PATH environment variable.**
4.  **A Google Gemini API Key:** You need an API key to use the Google Gemini models. Get one for free from [Google AI Studio](https://aistudio.google.com/apikey).

## Running the Application

1.  **Activate your virtual environment** 
    ```bash
    # On Windows
    python -m venv venv
    .\venv\Scripts\activate

    # On macOS and Linux
    source venv/bin/activate
    ```

2.  **Run the main script:**

    ```bash
    pip install -r requirements.txt
    ```

    ```bash
    python main.py
    ```


3.  When the application opens, paste your Gemini API key into the "Gemini API Key" field and click "Save Key". The key will be securely stored in `~/.gemini_srt_key` on your system.

## Usage

1.  **Select Original File:** Click "Browse..." to select your video, audio, or existing SRT file.
2.  **Enter API Key:** Paste and Save your Gemini API key (once saved, it loads automatically).
3.  **Select Language/Tone:** Choose the target language and optional translation tone/style. Source language can be "Auto Detect".
4.  **Choose Model:** Select the API model name (default is usually fine, check [Gemini Models Info](https://ai.google.dev/gemini-api/docs/models) for options).
5.  **Optional: Edit Prompts/Glossary:** Adjust the prompt templates and add glossary terms if needed.
6.  **Run Task:**
    *   Click "1. Direct Translate to SRT" to translate the *selected media file* from scratch. The result appears in the "Direct Translate Output" box.
    *   Click "2. Validate & Correct SRT" to validate and correct the content currently in the "Direct Translate Output" box, using the *selected original file* for context (media or SRT). The result appears in the "Validated/Corrected SRT Output" box.
7.  **Save Output:** Use the "Save..." buttons to save the content of the respective output boxes as an SRT file.

## Configuration

*   **API Key:** Stored in `~/.gemini_srt_key`. You can also place a `.env` file in the project directory with `GEMINI_API_KEY=YOUR_KEY_HERE`, which will be loaded if the file in the home directory is not found.
*   **Default Model:** Can be changed in the GUI.
*   **Default Prompts:** Can be edited directly in the GUI text areas.

## Credits

*   Developed by: GioChieu@KiOZ
    *   Website: [https://gsga.moe/](https://gsga.moe/)
    *   Facebook: [https://www.facebook.com/tranthanhkioz](https://www.facebook.com/tranthanhkioz)
*   Powered by:
    *   Google Gemini API ([https://ai.google.dev/](https://ai.google.dev/))
    *   FFmpeg ([https://ffmpeg.org/](https://ffmpeg.org/))
    *   Python ([https://www.python.org/](https://www.python.org/)) & Tkinter
    *   PyDub ([https://github.com/jiaaro/pydub](https://github.com/jiaaro/pydub))
    *   python-dotenv ([https://github.com/theskumar/python-dotenv](https://github.com/theskumar/python-dotenv))
    *   PyInstaller ([https://pyinstaller.org/](https://pyinstaller.org/))

## Contributing

Contributions are welcome! If you find a bug or have a feature request, please open an issue on GitHub.