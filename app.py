import streamlit as st
import yt_dlp
import os
import google.generativeai as genai
import time
import re
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor

st.set_page_config(page_title="Auto Vietsub Tool", page_icon="🎬", layout="wide")
st.title("🎬 Tool Auto Vietsub & Lồng Tiếng Việt bằng Gemini")
st.write("Tự động trích xuất âm thanh -> Dịch thuật bằng Gemini -> Lồng tiếng song song & Xuất video hoàn chỉnh")

# 1. Cấu hình API Key
st.subheader("🔑 Cấu hình API Key")
col_api1, col_api2 = st.columns(2)

with col_api1:
    api_key = st.text_input("1. Gemini API Key (Bắt buộc cho dịch thuật):", type="password", help="Lấy API Key miễn phí tại Google AI Studio")

# 2. Tùy chọn dịch vụ Lồng tiếng
st.subheader("🎙️ Tùy chọn Lồng tiếng")
tts_service = st.radio(
    "Chọn dịch vụ AI lồng tiếng:",
    ("Miễn phí (Edge-TTS)", "Trả phí (OpenAI TTS API - Giọng đọc Siêu thực)"),
    horizontal=True
)

openai_api_key = ""
if tts_service == "Trả phí (OpenAI TTS API - Giọng đọc Siêu thực)":
    with col_api2:
        openai_api_key = st.text_input("2. OpenAI API Key (Bắt buộc nếu dùng TTS trả phí):", type="password")
    
    voice_option = st.selectbox(
        "Chọn giọng đọc OpenAI:",
        options=[
            "nova (Nữ - Truyền cảm, tự nhiên)",
            "shimmer (Nữ - Giọng trẻ trung, rõ ràng)",
            "onyx (Nam - Giọng trầm ấm, chuyên nghiệp)",
            "alloy (Trung tính - Rõ chữ)",
            "echo (Nam - Nhẹ nhàng)",
            "fable (Giọng kể chuyện)"
        ],
        index=0
    )
    selected_voice = voice_option.split(" ")[0]
else:
    voice_option = st.selectbox(
        "Chọn giọng đọc Edge-TTS miễn phí:",
        options=["vi-VN-HoaiMyNeural (Nữ)", "vi-VN-NamMinhNeural (Nam)"],
        index=0
    )
    selected_voice = voice_option.split(" ")[0]

col1, col2 = st.columns(2)
with col1:
    vol_option = st.selectbox(
        "Âm lượng video gốc (Nhạc nền):",
        options=["Tắt âm hoàn toàn (0%)", "Nhạc nền cực nhỏ (5%)", "Vừa phải (15%)"],
        index=1
    )
with col2:
    cover_original = st.checkbox("Tạo khung đen bao trùm che chữ Trung Quốc gốc", value=True)

# 3. Nguồn Video
option = st.radio("Chọn nguồn video:", ("Tải tệp video từ máy (MP4, MOV,...)", "Dán link Douyin / Xiaohongshu"))

uploaded_file = None
raw_video_input = ""

if option == "Tải tệp video từ máy (MP4, MOV,...)":
    uploaded_file = st.file_uploader("Chọn video từ máy tính/điện thoại:", type=["mp4", "mov", "mkv", "avi", "webm"])
else:
    raw_video_input = st.text_input("Nhập link video (hoặc văn bản chia sẻ từ Douyin):")

if "srt_content" not in st.session_state:
    st.session_state.srt_content = ""
if "temp_video_path" not in st.session_state:
    st.session_state.temp_video_path = ""

def cleanup_files(*filepaths):
    for path in filepaths:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

def extract_clean_url(text):
    url_match = re.search(r'https?://[^\s]+', text)
    if url_match:
        return url_match.group(0)
    return text.strip()

def extract_audio_from_video(input_video_path, output_audio_path):
    cmd = [
        "ffmpeg", "-y",
        "-i", input_video_path,
        "-vn",
        "-acodec", "libmp3lame",
        "-q:a", "4",
        output_audio_path
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def filter_only_vietnamese_srt(srt_text):
    cleaned_blocks = []
    blocks = re.split(r'\n\s*\n', srt_text.strip())
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            header = lines[:2]
            content_lines = lines[2:]
            vi_lines = [l for l in content_lines if not re.search(r'[\u4e00-\u9fff]', l)]
            if vi_lines:
                cleaned_blocks.append("\n".join(header + vi_lines))
            else:
                cleaned_blocks.append("\n".join(lines))
        else:
            cleaned_blocks.append(block)
    return "\n\n".join(cleaned_blocks)

def time_to_seconds(time_str):
    time_str = time_str.replace(',', '.')
    parts = time_str.split(':')
    hours = float(parts[0])
    minutes = float(parts[1])
    seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds

def parse_srt(srt_text):
    blocks = re.split(r'\n\s*\n', srt_text.strip())
    subtitles = []
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            time_match = re.match(r'(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})', lines[1])
            if time_match:
                start_sec = time_to_seconds(time_match.group(1))
                end_sec = time_to_seconds(time_match.group(2))
                text_lines = [l for l in lines[2:] if not re.search(r'[\u4e00-\u9fff]', l)]
                text = " ".join(text_lines).strip()
                if text:
                    subtitles.append({"start": start_sec, "end": end_sec, "text": text})
    return subtitles

def convert_srt_time_to_ass(srt_time_str):
    srt_time_str = srt_time_str.replace(',', '.')
    parts = srt_time_str.split(':')
    h = int(parts[0])
    m = int(parts[1])
    s_parts = parts[2].split('.')
    s = int(s_parts[0])
    cs = int(s_parts[1][:2]) if len(s_parts) > 1 else 0
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def create_ass_file(srt_text, ass_filename, cover_original=True):
    vi_srt = filter_only_vietnamese_srt(srt_text)
    blocks = re.split(r'\n\s*\n', vi_srt.strip())
    
    border_style = "3" if cover_original else "1"
    back_color = "&H00000000" if cover_original else "&H00000000"
    outline = "12" if cover_original else "2"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,24,&H00FFFFFF,&H00000000,&H00000000,{back_color},0,0,0,0,100,100,0,0,{border_style},{outline},0,2,10,10,25,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dialogues = []
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            time_match = re.match(r'(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})', lines[1])
            if time_match:
                start_ass = convert_srt_time_to_ass(time_match.group(1))
                end_ass = convert_srt_time_to_ass(time_match.group(2))
                text_lines = [l for l in lines[2:] if not re.search(r'[\u4e00-\u9fff]', l)]
                text = r"\N".join(text_lines).strip()
                if text:
                    if cover_original:
                        text = r"\h\h\h\h" + text + r"\h\h\h\h"
                    dialogues.append(f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{text}")
    
    with open(ass_filename, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(dialogues))

# Tạo Audio với Edge-TTS (Free) hoặc OpenAI TTS (Paid)
def generate_single_tts(sub_item):
    idx, sub, voice, service_type, oai_key = sub_item
    text = sub['text']
    start_sec = sub['start']
    temp_speech_file = f"temp_speech_{idx}.mp3"
    
    for attempt in range(3):
        try:
            if service_type == "Paid_OpenAI":
                headers = {
                    "Authorization": f"Bearer {oai_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": "tts-1",
                    "input": text,
                    "voice": voice
                }
                response = requests.post("https://api.openai.com/v1/audio/speech", json=payload, headers=headers, timeout=15)
                if response.status_code == 200:
                    with open(temp_speech_file, "wb") as f:
                        f.write(response.content)
            else: # Free Edge-TTS
                cmd = ["edge-tts", "--voice", voice, "--text", text, "--write-media", temp_speech_file]
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            if os.path.exists(temp_speech_file) and os.path.getsize(temp_speech_file) > 0:
                return idx, start_sec, temp_speech_file
        except Exception:
            time.sleep(1)
            
    return idx, start_sec, None

def build_audio_ffmpeg_parallel(subtitles, voice, output_audio_path, service_type, oai_key):
    tasks = [(idx, sub, voice, service_type, oai_key) for idx, sub in enumerate(subtitles)]
    
    max_workers = 5 if service_type == "Paid_OpenAI" else 3
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(generate_single_tts, tasks))
    
    results.sort(key=lambda x: x[0])

    inputs = []
    filter_complex_parts = []
    temp_files = []
    
    for idx, start_sec, temp_speech_file in results:
        if temp_speech_file:
            temp_files.append(temp_speech_file)
            delay_ms = max(1, int(start_sec * 1000))
            file_input_idx = len(temp_files) - 1
            inputs.extend(["-i", temp_speech_file])
            filter_complex_parts.append(f"[{file_input_idx}:a]adelay={delay_ms}|{delay_ms}[a{file_input_idx}]")

    if not filter_complex_parts:
        return False

    mix_inputs = "".join([f"[a{i}]" for i in range(len(filter_complex_parts))])
    filter_complex_str = ";".join(filter_complex_parts) + f";{mix_inputs}amix=inputs={len(filter_complex_parts)}:normalize=0:dropout_transition=0[outa]"

    filter_script_file = "audio_filter.txt"
    with open(filter_script_file, "w", encoding="utf-8") as f:
        f.write(filter_complex_str)

    cmd = ["ffmpeg", "-y"] + inputs + ["-filter_complex_script", filter_script_file, "-map", "[outa]", output_audio_path]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    cleanup_files(*temp_files)
    cleanup_files(filter_script_file)
    return True

# ==========================================
# BƯỚC 1: TRÍCH XUẤT PHỤ ĐỀ
# ==========================================
st.subheader("Bước 1: Phân tích Video & Dịch toàn bộ")

if st.button("🚀 Bắt đầu phân tích Video & Dịch"):
    if not api_key:
        st.error("Vui lòng nhập Gemini API Key!")
    elif option == "Tải tệp video từ máy (MP4, MOV,...)" and not uploaded_file:
        st.warning("Vui lòng tải tệp video lên!")
    elif option == "Dán link Douyin / Xiaohongshu" and not raw_video_input:
        st.warning("Vui lòng nhập đường link video!")
    else:
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-1.5-flash')

            temp_video_path = "temp_video.mp4"
            temp_audio_path = "temp_audio_for_ai.mp3"
            
            cleanup_files(temp_video_path, temp_audio_path, "phu_de_vietsub.srt", "phu_de_vietsub.ass", "video_hoanchinh.mp4", "vietnamese_voice.mp3")

            if option == "Tải tệp video từ máy (MP4, MOV,...)":
                file_ext = uploaded_file.name.split('.')[-1]
                temp_video_path = f"temp_input_video.{file_ext}"
                with open(temp_video_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
            else:
                clean_url = extract_clean_url(raw_video_input)
                ydl_opts = {
                    'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best',
                    'outtmpl': temp_video_path,
                    'quiet': True,
                    'no_warnings': True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([clean_url])

            st.session_state.temp_video_path = temp_video_path

            st.info("🎵 Đang trích xuất âm thanh gửi cho AI...")
            extract_audio_from_video(temp_video_path, temp_audio_path)

            st.info("⚡ Đang phân tích & dịch thuật TOÀN BỘ video bằng Gemini...")
            uploaded_audio = genai.upload_file(path=temp_audio_path)
            
            while uploaded_audio.state.name == "PROCESSING":
                time.sleep(2)
                uploaded_audio = genai.get_file(uploaded_audio.name)

            prompt = """
            Bạn là chuyên gia làm phụ đề phim chuyên nghiệp.
            Hãy nghe âm thanh tiếng Trung trong file từ GIÂY ĐẦU TIÊN đến GIÂY CUỐI CÙNG để tạo phụ đề dịch Tiếng Việt.
            
            YÊU CẦU BẮT BUỘC:
            1. PHẢI TẠO PHỤ ĐỀ CHO TOÀN BỘ VIDEO, TUYỆT ĐỐI KHÔNG ĐƯỢC DỪNG GIỮA CHỪNG HOẶC BỎ DỞ BẤT KỲ ĐOẠN NÀO.
            2. Căn thời gian (timestamp) chính xác từng câu thoại.
            3. Mỗi ô phụ đề gồm 2 dòng:
               Dòng 1: Tiếng Trung gốc
               Dòng 2: Bản dịch Tiếng Việt (ngắn gọn, tự nhiên, dưới 8 từ)
            4. Trình bày CHÍNH XÁC theo chuẩn định dạng file .srt.
            """

            # Cấu hình max_output_tokens=8192 chống tràn và cắt ngang phụ đề ở nửa sau video
            generation_config = genai.types.GenerationConfig(
                max_output_tokens=8192,
                temperature=0.2
            )

            response = model.generate_content([prompt, uploaded_audio], generation_config=generation_config)
            srt_text = response.text.strip().replace('```srt', '').replace('```', '').strip()

            st.session_state.srt_content = srt_text
            genai.delete_file(uploaded_audio.name)
            cleanup_files(temp_audio_path)
            
            st.success("🎉 Trích xuất phụ đề toàn bộ video thành công! Kiểm tra và sửa đổi ở Bước 2.")

        except Exception as e:
            st.error(f"Đã xảy ra lỗi: {e}")

# ==========================================
# BƯỚC 2: TẠO 1 VIDEO HOÀN CHỈNH
# ==========================================
if st.session_state.srt_content:
    st.divider()
    st.subheader("Bước 2: Đối chiếu Tiếng Trung gốc & Xuất Video")
    st.info("💡 Ô bên dưới hiển thị chữ Trung gốc để đối chiếu. Bạn có thể kiểm tra danh sách phụ đề đã kéo dài tới cuối video hay chưa.")
    
    edited_srt = st.text_area(
        label="Nội dung phụ đề (Xem chữ Trung gốc và sửa câu Tiếng Việt tại đây):",
        value=st.session_state.srt_content,
        height=380
    )

    if st.button("🎬 Xác nhận & Xuất Video Hoàn Chỉnh"):
        if tts_service == "Trả phí (OpenAI TTS API - Giọng đọc Siêu thực)" and not openai_api_key:
            st.error("Vui lòng nhập OpenAI API Key để sử dụng dịch vụ TTS trả phí!")
        else:
            try:
                srt_filename = "phu_de_vietsub.srt"
                ass_filename = "phu_de_vietsub.ass"
                output_video_file = "video_hoanchinh.mp4"
                audio_tts_file = "vietnamese_voice.mp3"

                vi_only_srt = filter_only_vietnamese_srt(edited_srt)
                with open(srt_filename, "w", encoding="utf-8") as f:
                    f.write(vi_only_srt)

                create_ass_file(edited_srt, ass_filename, cover_original=cover_original)
                input_video_path = st.session_state.temp_video_path

                st.info("🎙️ Đang tạo giọng đọc AI lồng tiếng toàn bộ video...")
                subtitles = parse_srt(edited_srt)
                
                service_type = "Paid_OpenAI" if "OpenAI" in tts_service else "Free_EdgeTTS"
                has_audio = build_audio_ffmpeg_parallel(subtitles, selected_voice, audio_tts_file, service_type, openai_api_key)

                st.info("🎬 Đang ghép Phụ đề & Âm thanh vào Video...")
                
                vol_mapping = {
                    "Tắt âm hoàn toàn (0%)": "0.0",
                    "Nhạc nền cực nhỏ (5%)": "0.05",
                    "Vừa phải (15%)": "0.15"
                }
                bg_vol = vol_mapping[vol_option]
                
                if has_audio and os.path.exists(audio_tts_file):
                    if bg_vol == "0.0":
                        cmd_mix = [
                            "ffmpeg", "-y",
                            "-i", input_video_path,
                            "-i", audio_tts_file,
                            "-filter_complex", f"[0:v]subtitles={ass_filename}[outv]",
                            "-map", "[outv]",
                            "-map", "1:a",
                            "-c:v", "libx264",
                            "-c:a", "aac",
                            output_video_file
                        ]
                    else:
                        cmd_mix = [
                            "ffmpeg", "-y",
                            "-i", input_video_path,
                            "-i", audio_tts_file,
                            "-filter_complex",
                            f"[0:a]volume={bg_vol}[bg];[bg][1:a]amix=inputs=2:duration=first:normalize=0[outa];[0:v]subtitles={ass_filename}[outv]",
                            "-map", "[outv]",
                            "-map", "[outa]",
                            "-c:v", "libx264",
                            "-c:a", "aac",
                            output_video_file
                        ]
                    
                    try:
                        subprocess.run(cmd_mix, check=True, capture_output=True, text=True)
                    except subprocess.CalledProcessError:
                        cmd_replace_audio = [
                            "ffmpeg", "-y",
                            "-i", input_video_path,
                            "-i", audio_tts_file,
                            "-filter_complex", f"[0:v]subtitles={ass_filename}[outv]",
                            "-map", "[outv]",
                            "-map", "1:a",
                            "-c:v", "libx264",
                            "-c:a", "aac",
                            output_video_file
                        ]
                        subprocess.run(cmd_replace_audio, check=True, capture_output=True, text=True)
                else:
                    cmd_no_audio = [
                        "ffmpeg", "-y",
                        "-i", input_video_path,
                        "-vf", f"subtitles={ass_filename}",
                        "-c:a", "copy",
                        output_video_file
                    ]
                    subprocess.run(cmd_no_audio, check=True, capture_output=True, text=True)

                st.success("🎉 Hoàn tất! Video đã được Vietsub & Lồng tiếng full từ đầu đến cuối.")

                col_a, col_b = st.columns(2)
                with col_a:
                    with open(srt_filename, "rb") as file_srt:
                        st.download_button(
                            label="📝 Tải File Phụ Đề (.srt)",
                            data=file_srt,
                            file_name="vietsub.srt",
                            mime="text/plain"
                        )
                with col_b:
                    if os.path.exists(output_video_file):
                        with open(output_video_file, "rb") as file_vid:
                            st.download_button(
                                label="🎬 Tải Video Hoàn Chỉnh (Vietsub + Lồng Tiếng)",
                                data=file_vid,
                                file_name="video_vietsub_longtieng.mp4",
                                mime="video/mp4"
                            )

            except subprocess.CalledProcessError as e:
                err_text = e.stderr if isinstance(e.stderr, str) else e.stderr.decode('utf-8', errors='ignore')
                last_lines = "\n".join(err_text.strip().splitlines()[-10:])
                st.error(f"Lỗi FFmpeg: {last_lines}")
            except Exception as e:
                st.error(f"Lỗi khi xử lý video: {e}")
