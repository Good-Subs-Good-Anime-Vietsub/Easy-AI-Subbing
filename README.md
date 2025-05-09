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

1.  **Activate your virtual environment** (if you created one):
    ```bash
    # On Windows
    .\venv\Scripts\activate

    # On macOS and Linux
    source venv/bin/activate
    ```

2.  **Run the main script:**
    ```bash
    python main.py
    ```

3.  When the application opens, paste your Gemini API key into the "Gemini API Key" field and click "Save Key". The key will be securely stored in `~/.gemini_srt_key` on your system.

## Building the Executable (Windows)

If you want a standalone application bundle (requiring users to only have FFmpeg), you can use PyInstaller.

1.  **Ensure you have PyInstaller installed** (it's included in `requirements.txt`):
    ```bash
    pip install pyinstaller
    ```

2.  **Run the PyInstaller command** (using `--onedir` for a smaller main executable):
    ```bash
    pyinstaller --name "Easy AI Subbing" --icon app_icon.ico --windowed --onedir --add-data "app_icon.ico;." main.py
    ```
    *   Make sure `app_icon.ico` is in the same directory as `main.py`.

3.  The executable bundle will be created in the `dist` folder, specifically `dist\Easy AI Subbing`.

4.  To distribute, zip the `dist\Easy AI Subbing` folder and share it. Users will need to extract it and run `Easy AI Subbing.exe` from within that folder. Remember, **users still need FFmpeg installed and in their PATH.**

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

## Troubleshooting

*   **FFmpeg Not Found:** Ensure FFmpeg is installed and its `bin` directory is added to your system's PATH. Restart your terminal/IDE after adding to PATH.
*   **API Errors (401, 429, Model Not Found):** Double-check your API key, ensure it's correct and hasn't expired, check your usage quota on Google AI Studio, and verify the model name is correct and available to you.
*   **"Failed to load Python DLL" error after building:** Ensure you have the correct Microsoft Visual C++ Redistributable installed (usually 2015-2022 version for recent Python). Try running `pyinstaller --clean main.py` and rebuilding. Temporarily disable antivirus if it might be interfering. Make sure you run the `.exe` from inside the `dist\Easy AI Subbing` folder.
*   **No output or strange output:** Check your prompts for syntax errors or missing placeholders. Ensure the selected file is valid for the chosen task.
*   **Icon not displaying:** Ensure `app_icon.ico` was included in the PyInstaller build using `--add-data` and that the path in `main.py` is correct relative to the bundle structure.

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

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! If you find a bug or have a feature request, please open an issue on GitHub.