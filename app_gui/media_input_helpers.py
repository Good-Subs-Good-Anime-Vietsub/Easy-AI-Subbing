# EasyAISubbing/app_gui/media_input_helpers.py
import tkinter as tk # Chỉ cho type hinting hoặc messagebox nếu cần
from tkinter import messagebox
import os
import time
import requests # Cho tải URL trực tiếp
from urllib.parse import urlparse # Cho tải URL trực tiếp
import logging
import re # Cho D&D parsing
import threading # Cho tải URL trực tiếp

logger = logging.getLogger(__name__)

def start_url_download_task(url, app_controller, video_audio_tab_instance):
    """
    Bắt đầu tác vụ tải file từ URL trực tiếp trong một thread riêng.
    """
    if not (url.startswith("http://") or url.startswith("https://")):
        messagebox.showerror("Invalid URL", "URL must start with http:// or https://", parent=app_controller)
        return False

    video_audio_tab_instance._set_ui_state(processing=True)
    video_audio_tab_instance._clear_all_process_states()
    video_audio_tab_instance.progress_var.set(0)
    video_audio_tab_instance.video_file_var.set(f"Downloading from URL...")
    logger.info(f"Starting direct download from URL: {url}")

    thread = threading.Thread(target=_task_load_from_url,
                               args=(url, app_controller, video_audio_tab_instance),
                               daemon=True)
    thread.start()
    return True

def _task_load_from_url(url, app_controller, video_audio_tab_instance):
    """
    Tác vụ chạy trong thread để tải file từ URL trực tiếp.
    """
    download_path = None
    try:
        video_audio_tab_instance._update_progress(5, "Initiating direct download...")
        parsed_url = urlparse(url)
        filename_from_url = os.path.basename(parsed_url.path)
        if not filename_from_url: # Nếu URL không có path rõ ràng
            filename_from_url = "downloaded_direct_file"

        # Tạo tên file an toàn và thêm đuôi .tmp nếu cần
        safe_filename_base = "".join(c if c.isalnum() or c in ['.', '_', '-'] else '_' for c in filename_from_url)
        _, current_ext = os.path.splitext(safe_filename_base)
        if not current_ext: # Nếu không có phần mở rộng từ URL path
            # Cố gắng lấy từ Content-Type header
            temp_ext_from_header = ".tmp"
            try:
                with requests.head(url, timeout=10, allow_redirects=True) as r_head: # HEAD request để lấy header
                    r_head.raise_for_status()
                    content_type = r_head.headers.get('content-type')
                    if content_type:
                        if 'video/mp4' in content_type: temp_ext_from_header = ".mp4"
                        elif 'video/webm' in content_type: temp_ext_from_header = ".webm"
                        elif 'video/x-matroska' in content_type: temp_ext_from_header = ".mkv"
                        elif 'audio/mpeg' in content_type: temp_ext_from_header = ".mp3"
                        elif 'audio/wav' in content_type: temp_ext_from_header = ".wav"
                        # Thêm các content type khác nếu cần
            except Exception as e_head:
                logger.warning(f"Could not get Content-Type header for extension: {e_head}")
            safe_filename_base += temp_ext_from_header
        
        temp_filename = f"direct_url_{int(time.time())}_{safe_filename_base[:50]}" # Giới hạn độ dài tên file
        download_path = os.path.join(app_controller.app_temp_dir, temp_filename)

        logger.info(f"Downloading directly to temporary file: {download_path}")

        with requests.get(url, stream=True, timeout=60, allow_redirects=True) as r: # timeout 60 giây, cho phép redirect
            r.raise_for_status() # Sẽ raise HTTPError nếu status code là lỗi (4xx or 5xx)
            total_size = int(r.headers.get('content-length', 0))
            bytes_downloaded = 0
            with open(download_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192): # 8KB chunk
                    if video_audio_tab_instance.cancel_requested:
                        logger.info("Direct URL download cancelled by user.")
                        if download_path and os.path.exists(download_path):
                            try: os.remove(download_path) # Xóa file đang tải dở
                            except OSError as e_rm: logger.warning(f"Could not remove cancelled download {download_path}: {e_rm}")
                        return # Thoát sớm
                    f.write(chunk)
                    bytes_downloaded += len(chunk)
                    if total_size > 0:
                        progress = (bytes_downloaded / total_size) * 90 # Giả sử download chiếm 90%
                        video_audio_tab_instance._update_progress(5 + progress, f"Downloading... {bytes_downloaded//1024}KB / {total_size//1024}KB")
                    else: # Nếu không biết total_size, chỉ hiển thị số KB đã tải
                        video_audio_tab_instance._update_progress(max(5, video_audio_tab_instance.progress_var.get() + 1) % 90, f"Downloading... {bytes_downloaded//1024}KB (size unknown)")

        if video_audio_tab_instance.cancel_requested: return # Kiểm tra lại sau khi vòng lặp kết thúc

        video_audio_tab_instance._update_progress(95, "Direct download complete.")
        logger.info(f"File downloaded directly successfully: {download_path}")
        # Sau khi tải xong, gọi hàm xử lý file của tab từ main thread
        video_audio_tab_instance.after(0, video_audio_tab_instance._process_selected_file, download_path, "url_direct")

    except requests.exceptions.RequestException as e:
        logger.error(f"Error downloading directly from URL {url}: {e}", exc_info=True)
        video_audio_tab_instance.after(0, lambda: messagebox.showerror("Direct Download Error", f"Failed to download from URL.\nError: {e}", parent=app_controller))
        video_audio_tab_instance.after(0, lambda: video_audio_tab_instance.video_file_var.set("Direct download failed"))
        if download_path and os.path.exists(download_path): # Xóa file tải lỗi
            try: os.remove(download_path)
            except OSError: logger.warning(f"Could not remove failed direct download: {download_path}")
    except Exception as e:
        logger.error(f"Unexpected error during direct URL download: {e}", exc_info=True)
        video_audio_tab_instance.after(0, lambda: messagebox.showerror("Direct Download Error", f"An unexpected error occurred: {e}", parent=app_controller))
        video_audio_tab_instance.after(0, lambda: video_audio_tab_instance.video_file_var.set("Direct download error"))
        if download_path and os.path.exists(download_path): # Xóa file tải lỗi
            try: os.remove(download_path)
            except OSError: logger.warning(f"Could not remove failed direct download: {download_path}")
    finally:
        is_cancelled = video_audio_tab_instance.cancel_requested
        def final_ui_update_direct():
            if is_cancelled:
                video_audio_tab_instance._clear_all_process_states()
                video_audio_tab_instance.video_file_var.set("Download cancelled")
            video_audio_tab_instance._set_ui_state(False)
            video_audio_tab_instance.progress_var.set(0)
        video_audio_tab_instance.after(0, final_ui_update_direct)


def handle_dropped_file_for_tab(event_data, tab_instance, app_controller):
    """
    Xử lý dữ liệu từ sự kiện kéo thả, tìm file hợp lệ và gọi hàm xử lý của tab cụ thể.
    """
    logger.debug(f"Drag and drop event data received by D&D helper for tab {tab_instance.__class__.__name__}: '{event_data}'")
    filepaths_str = event_data

    # tkinterdnd2 có thể trả về chuỗi với các file được bao trong {} nếu tên có dấu cách
    # và cách nhau bởi dấu cách. Ví dụ: "{C:/path with space/file1.mp4} C:/another/file2.avi"
    # Hoặc chỉ một file: "C:/path with space/file1.mp4" (có thể có hoặc không có {})

    if not filepaths_str:
        logger.warning(f"Empty data received from drag and drop event for {tab_instance.__class__.__name__}.")
        return

    potential_paths_parsed = []
    # Regex để tìm các mục trong dấu ngoặc nhọn {} hoặc các mục không có dấu cách/ngoặc
    # (([^{}\s]+)|\{([^}]+)\}) : Group 1 là toàn bộ match, Group 2 là không ngoặc, Group 3 là trong ngoặc
    for match in re.finditer(r'(?:\{([^}]+)\}|([^{}\s]+))', filepaths_str):
        path_in_braces = match.group(1)
        path_not_in_braces = match.group(2)
        if path_in_braces:
            potential_paths_parsed.append(path_in_braces.strip())
        elif path_not_in_braces:
            potential_paths_parsed.append(path_not_in_braces.strip())

    if not potential_paths_parsed and filepaths_str.strip(): # Nếu regex không match (ví dụ: 1 file có space nhưng không có {})
        potential_paths_parsed.append(filepaths_str.strip().strip("\"'"))


    dropped_file_path = None
    if potential_paths_parsed:
        logger.debug(f"Potential D&D paths after parsing for {tab_instance.__class__.__name__}: {potential_paths_parsed}")
        # Chỉ xử lý file đầu tiên hợp lệ theo yêu cầu của người dùng
        for p_path in potential_paths_parsed:
            cleaned_path = p_path.strip("'\"") # Xóa dấu nháy đơn/kép bao quanh (nếu có)
            if os.path.isfile(cleaned_path): # Kiểm tra xem có phải là file không
                dropped_file_path = cleaned_path
                logger.info(f"Valid file dropped and identified for {tab_instance.__class__.__name__}: {dropped_file_path}")
                break # Lấy file đầu tiên hợp lệ
            else:
                logger.debug(f"Path from DND for {tab_instance.__class__.__name__} is not a file or does not exist: '{cleaned_path}' (original from DND event data part: '{p_path}')")

    if dropped_file_path:
        # Kiểm tra sơ bộ extension (tùy chọn). Tùy từng tab mà file hợp lệ là video hay phụ đề.
        # Sẽ để logic kiểm tra cụ thể hơn trong _process_dropped_file của từng tab.
        # Chỉ kiểm tra chung để log cảnh báo, không chặn xử lý ở đây.
        # allowed_extensions = (".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv",
        #                       ".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a",
        #                       ".srt", ".ass", ".ssa", ".vtt") # Broad list for warning
        # if not dropped_file_path.lower().endswith(allowed_extensions):
        #     logger.warning(f"Dropped file '{os.path.basename(dropped_file_path)}' has an unconfirmed extension. Attempting to process anyway.")
        #     # Không hiển thị messagebox ở đây để tránh làm phiền, logic xử lý file của tab sẽ báo lỗi nếu không xử lý được.

        # Call the tab instance's specific processing method
        if hasattr(tab_instance, '_process_dropped_file'):
            tab_instance._process_dropped_file(dropped_file_path, source="drag-drop")
        else:
            logger.error(f"Tab instance {tab_instance.__class__.__name__} is missing the required _process_dropped_file method.")
            messagebox.showerror("Internal Error", f"The tab {tab_instance.__class__.__name__} is not set up to handle dropped files.", parent=app_controller)

    else:
        logger.warning(f"Drag and drop event did not yield a valid file path after parsing all potential paths for {tab_instance.__class__.__name__}.")
        messagebox.showwarning("Drag & Drop Error", "Could not identify a valid file from the dropped item(s). Please ensure you are dropping a single video or audio/subtitle file.", parent=app_controller) # Updated message