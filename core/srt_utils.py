# EasyAISubbing/core/srt_utils.py
# (v4.4.1 - Fix Undefined Variables - Refactored for clarity - Verified - Added missing os import)
import srt # Make sure this library is installed: pip install srt
from datetime import timedelta
import logging
import re
import os # <--- THÊM DÒNG NÀY

logger = logging.getLogger(__name__)

GEMINI_LINE_REGEX_PATTERN = re.compile(
    r"^\s*\[\s*(\d+)(?::|,)(\d{1,2}),(\d)\s*-\s*(\d+)(?::|,)(\d{1,2}),(\d)\s*\]\s*(.*?)(?:\s*\{([^}]+)\})?\s*$"
)
TIMESTAMP_BLOCK_REGEX_PATTERN = re.compile(r"\[\s*\d+(?::|,)\d{1,2},\d\s*-\s*\d+(?::|,)\d{1,2},\d\s*\]")

MAX_SUBTITLE_DURATION_SECONDS = 10
MIN_SUBTITLE_DURATION_MS = 100
DEFAULT_MIN_GAP_MS = 100
DEFAULT_ADJUST_GAP_THRESHOLD_S = 0.5
DEFAULT_OVERLAP_RESOLUTION_GAP_MS = 50

def parse_timecode_to_timedelta(minutes_str, seconds_str, tenth_seconds_str):
    try:
        minutes = int(minutes_str)
        seconds = int(seconds_str)
        tenth_seconds = int(tenth_seconds_str)
        if not (0 <= seconds <= 59):
            raise ValueError(f"Seconds component ({seconds}) out of range 0-59.")
        if not (0 <= tenth_seconds <= 9):
            raise ValueError(f"Tenth of seconds component ({tenth_seconds}) out of range 0-9.")
        milliseconds = tenth_seconds * 100
        return timedelta(minutes=minutes, seconds=seconds, milliseconds=milliseconds)
    except ValueError as e:
        raise ValueError(f"Invalid timecode component value: {e}")

def format_timedelta_to_gemini_style(td):
    if not isinstance(td, timedelta):
        raise TypeError("Input must be a timedelta object.")
    if td.total_seconds() < 0:
        logger.warning(f"Encountered negative timedelta ({td}), formatting as 00:00,0.")
        return "00:00,0"
    if td.total_seconds() == 0:
        return "00:00,0"
    total_seconds_val = td.total_seconds()
    absolute_total_seconds = abs(total_seconds_val)
    total_minutes_abs = int(absolute_total_seconds // 60)
    remaining_seconds_float_abs = absolute_total_seconds % 60
    effective_milliseconds_abs = round(remaining_seconds_float_abs * 1000)
    seconds_part_abs = effective_milliseconds_abs // 1000
    tenth_seconds_part_abs = (effective_milliseconds_abs % 1000) // 100
    if tenth_seconds_part_abs >= 10:
        seconds_part_abs += tenth_seconds_part_abs // 10
        tenth_seconds_part_abs %= 10
    if seconds_part_abs >= 60:
        total_minutes_abs += seconds_part_abs // 60
        seconds_part_abs %= 60
    minute_format = f"{total_minutes_abs:02d}" if total_minutes_abs < 100 else str(total_minutes_abs)
    second_format = f"{seconds_part_abs:02d}"
    return f"{minute_format}:{second_format},{tenth_seconds_part_abs}"

def detailed_analyze_gemini_output(lines_list):
    analysis_messages = []
    previous_segment_end_time_td = timedelta(seconds=-1)
    seen_full_timestamps_for_duplicates = {}

    for i, line_text_original in enumerate(lines_list):
        line_num = i + 1
        current_line_text_stripped = line_text_original.strip()
        if not current_line_text_stripped:
            continue

        match = GEMINI_LINE_REGEX_PATTERN.match(current_line_text_stripped)
        original_ts_block_visual_for_error = "N/A" # Default value
        if match:
             original_ts_block_visual_for_error = current_line_text_stripped[current_line_text_stripped.find("["):current_line_text_stripped.find("]")+1]

        if not match:
            if TIMESTAMP_BLOCK_REGEX_PATTERN.search(current_line_text_stripped):
                analysis_messages.append(
                    f"L{line_num}: FORMAT ERROR - Timestamp block (m:s,x) malformed. Original: '{current_line_text_stripped[:80]}...'"
                )
            elif ":" in current_line_text_stripped and "," in current_line_text_stripped and "-" in current_line_text_stripped :
                 analysis_messages.append(
                    f"L{line_num}: FORMAT ERROR - Line has time-like elements but not '[m<sep>s,x - m<sep>s,x] text' pattern. Original: '{current_line_text_stripped[:80]}...'"
                )
            else:
                analysis_messages.append(
                    f"L{line_num}: FORMAT WARNING - Line does not appear to contain a timestamp block. Content: '{current_line_text_stripped[:80]}...'"
                )
            continue # Guard clause: exit if no match

        groups = match.groups()
        s_m_str, s_s_str, s_x_str = groups[0], groups[1], groups[2]
        e_m_str, e_s_str, e_x_str = groups[3], groups[4], groups[5]

        current_line_has_component_error = False
        time_components_data = [
            (s_m_str, "Start Minute"), (s_s_str, "Start Second"), (s_x_str, "Start TenthSec"),
            (e_m_str, "End Minute"), (e_s_str, "End Second"), (e_x_str, "End TenthSec")
        ]

        for val_str, comp_name in time_components_data:
            if not val_str.isdigit():
                analysis_messages.append(f"L{line_num}: FORMAT ERROR - {comp_name} ('{val_str}') non-digit.")
                current_line_has_component_error = True
                break
            if "Second" in comp_name and not (1 <= len(val_str) <= 2):
                analysis_messages.append(f"L{line_num}: FORMAT ERROR - {comp_name} ('{val_str}') must be 1-2 digits.")
                current_line_has_component_error = True
                break
            elif "Second" in comp_name and int(val_str) > 59 :
                 analysis_messages.append(f"L{line_num}: FORMAT ERROR - {comp_name} ('{val_str}') > 59.")
                 current_line_has_component_error = True
                 break
            if "TenthSec" in comp_name and (len(val_str) != 1 or int(val_str) > 9):
                analysis_messages.append(f"L{line_num}: FORMAT ERROR - {comp_name} ('{val_str}') must be 1 digit (0-9).")
                current_line_has_component_error = True
                break

        if current_line_has_component_error:
            continue

        try:
            start_time_td = parse_timecode_to_timedelta(s_m_str, s_s_str, s_x_str)
            end_time_td = parse_timecode_to_timedelta(e_m_str, e_s_str, e_x_str)

            normalized_s_str = format_timedelta_to_gemini_style(start_time_td)
            normalized_e_str = format_timedelta_to_gemini_style(end_time_td)
            normalized_ts_block_str = f"[{normalized_s_str} - {normalized_e_str}]"

            if normalized_ts_block_str != original_ts_block_visual_for_error.replace(" ", ""):
                 analysis_messages.append(
                    f"L{line_num}: FORMAT INFO - Python's standard m:s,x format for TS is '{normalized_ts_block_str}'. Original visual: '{original_ts_block_visual_for_error}'."
                )

            if start_time_td >= end_time_td:
                analysis_messages.append(
                    f"L{line_num}: LOGIC ERROR - Start time ({normalized_s_str}) not strictly before end time ({normalized_e_str})."
                )
            if previous_segment_end_time_td > timedelta(seconds=-0.5):
                if start_time_td < previous_segment_end_time_td:
                    overlap_duration = previous_segment_end_time_td - start_time_td
                    if overlap_duration.total_seconds() * 1000 > 50:
                        analysis_messages.append(
                            f"L{line_num}: LOGIC WARNING - Sequence overlap. Starts ({normalized_s_str}) {overlap_duration.total_seconds():.1f}s BEFORE previous line ended ({format_timedelta_to_gemini_style(previous_segment_end_time_td)})."
                        )

            current_normalized_ts_tuple = (normalized_s_str, normalized_e_str)
            if current_normalized_ts_tuple in seen_full_timestamps_for_duplicates:
                prev_line_num = seen_full_timestamps_for_duplicates[current_normalized_ts_tuple]
                analysis_messages.append(
                    f"L{line_num}: DUPLICATE TS ERROR - Timestamp block ({normalized_s_str} - {normalized_e_str}) is identical to L{prev_line_num}."
                )
            else:
                seen_full_timestamps_for_duplicates[current_normalized_ts_tuple] = line_num
            if start_time_td < end_time_td :
                previous_segment_end_time_td = end_time_td
        except ValueError as ve:
            analysis_messages.append(
                f"L{line_num}: PARSE ERROR - Could not parse time components: {ve}. Original: '{original_ts_block_visual_for_error}'"
            )
        except Exception as e_gen:
             analysis_messages.append(
                f"L{line_num}: UNEXPECTED ANALYSIS ERROR - {e_gen}. Original block: '{original_ts_block_visual_for_error}'"
            )
    return analysis_messages

def convert_gemini_format_to_srt_content(gemini_output_text, apply_python_normalization=True):
    subs = []
    conversion_error_messages = []
    lines_to_process = gemini_output_text.splitlines()

    if apply_python_normalization:
        normalized_lines, norm_log_messages = analyze_and_pre_correct_gemini_lines_for_srt(lines_to_process)
        lines_to_process = normalized_lines
        if norm_log_messages:
            logger.info("SRT Pre-conversion Normalization Log (m:s,x format):")
            for log_msg in norm_log_messages:
                logger.info(f"  SRT PRE-CONV: {log_msg}")
                if "ERROR" in log_msg.upper() or "SKIPPING" in log_msg.upper() or "MALFORMED" in log_msg.upper() :
                    conversion_error_messages.append(log_msg.replace("L", "SRT Norm. L"))

    subtitle_srt_index = 1
    last_valid_srt_end_time_td = timedelta(seconds=-1)

    for i, line_text_original in enumerate(lines_to_process):
        current_line_text_stripped = line_text_original.strip()
        if not current_line_text_stripped:
            continue

        match = GEMINI_LINE_REGEX_PATTERN.match(current_line_text_stripped)
        original_ts_block_for_error_conv = "N/A"
        if match:
            original_ts_block_for_error_conv = current_line_text_stripped[current_line_text_stripped.find("["):current_line_text_stripped.find("]")+1]

        if not match:
            if current_line_text_stripped and not current_line_text_stripped.startswith(("#", "//")):
                conversion_error_messages.append(f"SRT Conv. Line {i+1}: Does not match format [m<sep>s,x - m<sep>s,x]. Skipped. Content: '{current_line_text_stripped[:70]}...'")
            continue

        groups = match.groups()
        s_m_str, s_s_str, s_x_str = groups[0], groups[1], groups[2]
        e_m_str, e_s_str, e_x_str = groups[3], groups[4], groups[5]
        text_content = groups[6].strip() if groups[6] else ""
        note_content = groups[7].strip() if groups[7] else ""
        try:
            start_td = parse_timecode_to_timedelta(s_m_str, s_s_str, s_x_str)
            end_td = parse_timecode_to_timedelta(e_m_str, e_s_str, e_x_str)

            if start_td >= end_td:
                conversion_error_messages.append(f"SRT Conv. Line {i+1}: Start time ({format_timedelta_to_gemini_style(start_td)}) not before end ({format_timedelta_to_gemini_style(end_td)}). Skipped.")
                continue
            duration_ms = (end_td - start_td).total_seconds() * 1000
            if duration_ms < MIN_SUBTITLE_DURATION_MS:
                conversion_error_messages.append(f"SRT Conv. Line {i+1}: Duration too short ({duration_ms:.0f}ms). Skipped. ({format_timedelta_to_gemini_style(start_td)} - {format_timedelta_to_gemini_style(end_td)})")
                continue

            if last_valid_srt_end_time_td > timedelta(seconds=-0.5):
                 if start_td < last_valid_srt_end_time_td:
                    overlap_ms = (last_valid_srt_end_time_td - start_td).total_seconds() * 1000
                    if overlap_ms > 50:
                        original_start_str = format_timedelta_to_gemini_style(start_td)
                        potential_new_start = last_valid_srt_end_time_td + timedelta(milliseconds=DEFAULT_OVERLAP_RESOLUTION_GAP_MS // 2)
                        if potential_new_start < end_td and (end_td - potential_new_start).total_seconds() * 1000 >= MIN_SUBTITLE_DURATION_MS:
                            start_td = potential_new_start
                            conversion_error_messages.append(f"SRT Conv. Line {i+1}: Adjusted start from {original_start_str} to {format_timedelta_to_gemini_style(start_td)} to fix overlap.")
                        else:
                             conversion_error_messages.append(f"SRT Conv. Line {i+1}: Severe overlap with previous. Start {original_start_str} vs prev_end {format_timedelta_to_gemini_style(last_valid_srt_end_time_td)}. Could not adjust. Skipped.")
                             continue

            full_text_for_srt = text_content
            if note_content:
                full_text_for_srt += f" {{{note_content}}}"
            if not full_text_for_srt.strip():
                conversion_error_messages.append(f"SRT Conv. Line {i+1}: Empty text. Skipped. ({format_timedelta_to_gemini_style(start_td)} - {format_timedelta_to_gemini_style(end_td)})")
                continue

            subtitle = srt.Subtitle(
                index=subtitle_srt_index,
                start=start_td,
                end=end_td,
                content=full_text_for_srt
            )
            subs.append(subtitle)
            subtitle_srt_index += 1
            last_valid_srt_end_time_td = end_td
        except ValueError as e:
            conversion_error_messages.append(f"SRT Conv. Line {i+1}: Error parsing time from '{original_ts_block_for_error_conv}': {e}. Skipped.")
        except Exception as e_gen:
             conversion_error_messages.append(f"SRT Conv. Line {i+1}: Unexpected error processing '{original_ts_block_for_error_conv}': {e_gen}. Skipped.")
    if not subs:
        logger.warning("No valid subtitles generated after SRT conversion (m:s,x format).")
        if not conversion_error_messages:
            conversion_error_messages.append("No processable subtitle lines found in input.")
    return srt.compose(subs, reindex=True, strict=False), conversion_error_messages

def analyze_and_pre_correct_gemini_lines_for_srt(lines_list):
    corrected_lines_output = []
    analysis_log_output = []
    for i, line_text_original in enumerate(lines_list):
        line_num = i + 1
        current_line_text_stripped = line_text_original.strip()
        line_to_add_this_iteration = current_line_text_stripped

        if not current_line_text_stripped:
            corrected_lines_output.append("")
            continue

        match = GEMINI_LINE_REGEX_PATTERN.match(current_line_text_stripped)
        original_ts_block_visual_for_log = "N/A"
        if match:
            original_ts_block_visual_for_log = current_line_text_stripped[current_line_text_stripped.find("["):current_line_text_stripped.find("]")+1]

        if not match:
            if TIMESTAMP_BLOCK_REGEX_PATTERN.search(current_line_text_stripped):
                analysis_log_output.append(f"L{line_num} (SRT Norm): FORMAT ERROR - Malformed m:s,x TS (separator/digit issue?). Kept as is: '{current_line_text_stripped[:60]}...'")
        else:
            groups = match.groups()
            s_m_str, s_s_str, s_x_str = groups[0], groups[1], groups[2]
            e_m_str, e_s_str, e_x_str = groups[3], groups[4], groups[5]
            text_content = groups[6].strip() if groups[6] else ""
            note_content = groups[7].strip() if groups[7] else ""

            try:
                start_td = parse_timecode_to_timedelta(s_m_str, s_s_str, s_x_str)
                end_td = parse_timecode_to_timedelta(e_m_str, e_s_str, e_x_str)
                normalized_s_str = format_timedelta_to_gemini_style(start_td)
                normalized_e_str = format_timedelta_to_gemini_style(end_td)
                reconstructed_ts_block = f"[{normalized_s_str} - {normalized_e_str}]"
                line_to_add_this_iteration = f"{reconstructed_ts_block} {text_content}"
                if note_content:
                    line_to_add_this_iteration += f" {{{note_content}}}"
                if reconstructed_ts_block != original_ts_block_visual_for_log.replace(" ", ""):
                    analysis_log_output.append(f"L{line_num} (SRT Norm): Auto-normalized m:s,x TS. Original visual: '{original_ts_block_visual_for_log}' -> Corrected: '{reconstructed_ts_block}'")
                if start_td >= end_td:
                    analysis_log_output.append(f"L{line_num} (SRT Norm): LOGIC ERROR (Not Fixed by Norm) - Start >= End. Line: '{line_to_add_this_iteration[:80]}...'")
            except ValueError as ve:
                analysis_log_output.append(f"L{line_num} (SRT Norm): PARSE ERROR - Cannot normalize m:s,x TS: {ve}. Kept original: '{current_line_text_stripped[:80]}...'")
            except Exception as e_gen:
                 analysis_log_output.append(f"L{line_num} (SRT Norm): UNEXPECTED ERROR during m:s,x normalization: {e_gen}. Kept original: '{current_line_text_stripped[:80]}...'")
        corrected_lines_output.append(line_to_add_this_iteration)
    return corrected_lines_output, analysis_log_output

def refine_subtitle_timing(subtitles,
                           min_gap_milliseconds=DEFAULT_MIN_GAP_MS,
                           adjust_gap_threshold_seconds=DEFAULT_ADJUST_GAP_THRESHOLD_S,
                           overlap_resolution_gap_ms=DEFAULT_OVERLAP_RESOLUTION_GAP_MS
                           ):
    if not subtitles:
        return [], []
    try:
        temp_srt_content = srt.compose(subtitles, reindex=False, strict=False)
        processed_subs = list(srt.parse(temp_srt_content))
    except Exception as e:
        logger.error(f"Refine Timing: Error during pre-processing of subtitles list: {e}")
        return subtitles, [f"ERROR: Pre-processing subs failed: {e}"]

    if not processed_subs:
        logger.warning("Refine Timing: No subtitles to process after internal sanitization.")
        return [], []

    change_logs = []
    num_subs = len(processed_subs)

    for i in range(num_subs - 1):
        current_sub = processed_subs[i]
        next_sub = processed_subs[i+1]

        if not isinstance(current_sub.start, timedelta) or not isinstance(current_sub.end, timedelta) or \
           not isinstance(next_sub.start, timedelta):
            change_logs.append(f"L{current_sub.index if hasattr(current_sub, 'index') else i+1}: "
                               f"SKIPPING - Invalid time object found.")
            continue

        original_current_end_str = format_timedelta_to_gemini_style(current_sub.end)
        time_diff_td = next_sub.start - current_sub.end
        time_diff_seconds = time_diff_td.total_seconds()
        min_duration_for_current_sub_td = timedelta(milliseconds=MIN_SUBTITLE_DURATION_MS)

        if time_diff_seconds > 0:
            if time_diff_seconds < adjust_gap_threshold_seconds:
                new_end_time = next_sub.start - timedelta(milliseconds=min_gap_milliseconds)
                if new_end_time >= (current_sub.start + min_duration_for_current_sub_td):
                    current_sub.end = new_end_time
                    change_logs.append(
                        f"L{current_sub.index if hasattr(current_sub, 'index') else i+1}: "
                        f"Gap narrowed. End: {original_current_end_str} -> {format_timedelta_to_gemini_style(current_sub.end)} "
                        f"(gap with next was {time_diff_seconds:.3f}s)"
                    )
                else:
                    logger.debug(f"Skipping gap narrowing for L{current_sub.index if hasattr(current_sub, 'index') else i+1}: would make duration too short or invalid.")
        elif time_diff_seconds < 0:
            overlap_seconds = abs(time_diff_seconds)
            new_end_time = next_sub.start - timedelta(milliseconds=overlap_resolution_gap_ms)
            if new_end_time >= (current_sub.start + min_duration_for_current_sub_td):
                current_sub.end = new_end_time
                change_logs.append(
                    f"L{current_sub.index if hasattr(current_sub, 'index') else i+1}: "
                    f"Overlap resolved. End: {original_current_end_str} -> {format_timedelta_to_gemini_style(current_sub.end)} "
                    f"(was overlapping by {overlap_seconds:.3f}s)"
                )
            else:
                logger.warning(f"L{current_sub.index if hasattr(current_sub, 'index') else i+1}: Could not fully resolve overlap of {overlap_seconds:.3f}s by adjusting current sub's end time without making it too short. Trying partial adjustment.")
                potential_new_end = next_sub.start - timedelta(milliseconds=1)
                if potential_new_end >= (current_sub.start + min_duration_for_current_sub_td):
                    current_sub.end = potential_new_end
                    change_logs.append(
                        f"L{current_sub.index if hasattr(current_sub, 'index') else i+1}: "
                        f"Overlap partially resolved (almost touching). End: {original_current_end_str} -> {format_timedelta_to_gemini_style(current_sub.end)}"
                    )
                else:
                    change_logs.append(
                        f"L{current_sub.index if hasattr(current_sub, 'index') else i+1}: "
                        f"Overlap UNRESOLVED by shrinking current. Overlap: {overlap_seconds:.3f}s. Original end: {original_current_end_str}"
                    )

    final_srt_content = srt.compose(processed_subs, reindex=True, strict=False)
    final_subs_list = list(srt.parse(final_srt_content))
    return final_subs_list, change_logs

def save_srt_file(srt_content_string, output_filepath):
    try:
        # Ensure the directory for the output file exists
        output_dir = os.path.dirname(output_filepath)
        if output_dir and not os.path.exists(output_dir): # Check if output_dir is not empty (e.g. saving to current dir)
            os.makedirs(output_dir)
            logger.info(f"Created directory for SRT output: {output_dir}")

        with open(output_filepath, 'w', encoding='utf-8') as f:
            f.write(srt_content_string)
        logger.info(f"SRT file successfully saved to: {output_filepath}")
        return True
    except IOError as e:
        logger.error(f"Failed to save SRT file to {output_filepath}: {e}")
        return False
    except Exception as e_general: # Catch other potential errors like permission issues during makedirs
        logger.error(f"An unexpected error occurred while saving SRT to {output_filepath}: {e_general}")
        return False