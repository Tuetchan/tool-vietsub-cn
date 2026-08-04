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
st.title("🎬 Tool Auto Vietsub & Lồng Tiếng Việt bằng AI")
st.write("Tự động trích xuất âm thanh -> Dịch thuật bằng Gemini -> Lồng tiếng song song & Xuất video hoàn chỉnh")

# 1. Cấu hình AI Dịch thuật
st.subheader("🔑 1. Cấu hình AI Dịch thuật")
api_key = st.text_input("Nhập Gemini API Key (Bắt buộc):", type="password")

# 2. Tùy chọn dịch vụ Lồng tiếng
st.subheader("🎙️ 2. Tùy chọn Lồng tiếng")
tts_service = st.radio(
    "Chọn dịch vụ AI lồng tiếng:",
    ("Miễn phí (Edge-TTS)", "Trả phí (OpenAI - Giọng Siêu thực)", "Trả phí (ElevenLabs - Giọng Cảm xúc)"),
    horizontal=True
)

selected_voice = ""
active_api_key = ""

if tts_service == "Trả phí (OpenAI - Giọng Siêu thực)":
    active_api_key = st.text_input("Nhập OpenAI API Key:", type="password")
    voice_option = st.selectbox(
        "Chọn giọng mặc định của OpenAI:",
        options=[
            "nova (Nữ - Truyền cảm, tự nhiên)", "shimmer (Nữ - Giọng trẻ trung)",
            "onyx (Nam - Giọng trầm ấm)", "alloy (Trung tính)",
            "echo (Nam - Nhẹ nhàng)", "fable (Giọng kể chuyện)"
        ]
    )
    selected_voice = voice_option.split(" ")[0]

elif tts_service == "Trả phí (ElevenLabs - Giọng Cảm xúc)":
    active_api_key = st.text_input("Nhập ElevenLabs API Key:", type="password")
    eleven_voices = {
        "Rachel (Nữ - Tự nhiên)": "21m00Tcm4TlvDq8ikWAM",
        "Antoni (Nam - Trẻ trung)": "ErXwobaYiN019PkySvjV",
        "Bella (Nữ - Nhẹ nhàng)": "EXAVITQu4vr4xnSDxMaL",
        "Arnold (Nam - Trầm ấm)": "VR6AewLTigWG4xSOukaG",
        "Adam (Nam - Kể chuyện)": "pNInz6obpgDQGcFmaJcg",
        "Elli (Nữ - Trẻ trung)": "MF3mGyEYCl7XYWbV9V6O"
    }
    voice_option = st.selectbox("Chọn giọng mặc định của ElevenLabs:", options=list(eleven_voices.keys()))
    selected_voice = eleven_voices[voice_option]

else:
    voice_option = st.selectbox(
        "Chọn giọng đọc Edge-TTS miễn phí:",
        options=["vi-VN-HoaiMyNeural (Nữ)", "vi-VN-NamMinhNeural (Nam)"]
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
st.divider()
option = st.radio("Chọn nguồn video:", ("Tải tệp video từ máy (MP4, MOV,...)", "Dán link Douyin / Xiaohongshu"))
uploaded_file = None
raw_video_input = ""

if option == "Tải tệp video từ máy (MP4, MOV,...)":
    uploaded_file = st.file_uploader("Chọn video từ máy tính:", type=["mp4", "mov", "mkv", "avi", "webm"])
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
    cmd = ["ffmpeg", "-y", "-i", input_video_path, "-vn", "-acodec", "libmp3lame", "-q:a", "4", output_audio_path]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def filter_only_vietnamese_srt(srt_text):
    cleaned_blocks = []
    blocks = re.split(r'\n\s*\n', srt_text.strip())
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            header = lines[:2]
            vi_lines = [l for l in lines[2:] if not re.search(r'[\u4e00-\u9fff]', l)]
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
    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])

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
    h, m = int(parts[0]), int(parts[1])
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
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"""
    
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

# --- HÀM TÍNH THỜI LƯỢNG ÂM THANH ---
def get_audio_duration(file_path):
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprintwrappers=1:nokey=1", file_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(result.stdout.strip())
    except Exception:
        return 0.0

# --- HÀM TỰ ĐỘNG TĂNG TỐC ĐỘ ÂM THANH NẾU BỊ DÀI HƠN KHUNG THỜI GIAN GỐC ---
def adjust_audio_speed(input_file, speed_factor):
    if speed_factor <= 1.03:  # Bỏ qua nếu chênh lệch không đáng kể (dưới 3%)
        return
    
    temp_out = input_file + "_speed.mp3"
    try:
        # Tách chuỗi filter atempo nếu hệ số > 2.0 (FFmpeg atempo hỗ trợ từ 0.5 đến 2.0)
        factors = []
        f = speed_factor
        while f > 2.0:
            factors.append(2.0)
            f /= 2.0
        factors.append(f)
        filter_str = ",".join([f"atempo={x:.3f}" for x in factors])
        
        cmd = ["ffmpeg", "-y", "-i", input_file, "-filter:a", filter_str, temp_out]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        if os.path.exists(temp_out) and os.path.getsize(temp_out) > 0:
            os.replace(temp_out, input_file)
    except Exception:
        if os.path.exists(temp_out):
            os.remove(temp_out)

def generate_single_tts(sub_item):
    idx, sub, voice, service_type, key = sub_item
    text = sub['text']
    start_sec = sub['start']
    end_sec = sub['end']
    max_duration = max(0.5, end_sec - start_sec)
    temp_speech_file = f"temp_speech_{idx}.mp3"
    
    for attempt in range(3):
        try:
            if service_type == "Paid_OpenAI":
                headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                payload = {"model": "tts-1", "input": text, "voice": voice}
                response = requests.post("https://api.openai.com/v1/audio/speech", json=payload, headers=headers, timeout=15)
                if response.status_code == 200:
                    with open(temp_speech_file, "wb") as f:
                        f.write(response.content)

            elif service_type == "Paid_ElevenLabs":
                headers = {"Accept": "audio/mpeg", "Content-Type": "application/json", "xi-api-key": key}
                payload = {"text": text, "model_id": "eleven_multilingual_v2", "voice_settings": {"stability": 0.5, "similarity_boost": 0.5}}
                url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
                response = requests.post(url, json=payload, headers=headers, timeout=15)
                if response.status_code == 200:
                    with open(temp_speech_file, "wb") as f:
                        f.write(response.content)

            else: # Edge-TTS
                cmd = ["edge-tts", "--voice", voice, "--text", text, "--write-media", temp_speech_file]
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            if os.path.exists(temp_speech_file) and os.path.getsize(temp_speech_file) > 0:
                # TỰ ĐỘNG KIỂM TRA VÀ TĂNG TỐC ĐỘ NÓI KHỐP VỚI KHUNG THỜI GIAN VIDEO GỐC
                actual_duration = get_audio_duration(temp_speech_file)
                if actual_duration > max_duration:
                    speed_factor = min(actual_duration / max_duration, 2.5) # Giới hạn tăng tốc tối đa 2.5 lần để tránh vỡ giọng
                    adjust_audio_speed(temp_speech_file, speed_factor)
                
                return idx, start_sec, temp_speech_file
        except Exception:
            time.sleep(1)
            
    return idx, start_sec, None

def build_audio_ffmpeg_parallel(subtitles, voice, output_audio_path, service_type, key):
    tasks = [(idx, sub, voice, service_type, key) for idx, sub in enumerate(subtitles)]
    max_workers = 3 if service_type == "Free_EdgeTTS" else 5
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(generate_single_tts, tasks))
    
    results.sort(key=lambda x: x[0])
    inputs, filter_complex_parts, temp_files = [], [], []
    
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

    with open("audio_filter.txt", "w", encoding="utf-8") as f:
        f.write(filter_complex_str)

    cmd = ["ffmpeg", "-y"] + inputs + ["-filter_complex_script", "audio_filter.txt", "-map", "[outa]", output_audio_path]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    cleanup_files(*temp_files, "audio_filter.txt")
    return True

# ==========================================
# BƯỚC 1: TRÍCH XUẤT PHỤ ĐỀ
# ==========================================
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
            model = genai.GenerativeModel('gemini-3.5-flash')
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
                ydl_opts = {'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best', 'outtmpl': temp_video_path, 'quiet': True}
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

            prompt = """Bạn là chuyên gia làm phụ đề phim. 
            Nhiệm vụ: Dịch TOÀN BỘ file âm thanh sang tiếng Việt và tạo file SRT.
            
            LƯU Ý CỰC KỲ QUAN TRỌNG:
            - BẠN TUYỆT ĐỐI KHÔNG ĐƯỢC DỪNG GIỮA CHỪNG.
            - PHẢI dịch liên tục từ giây 00:00 cho đến giây CÚI CÙNG của âm thanh.
            - KHÔNG ĐƯỢC tóm tắt, KHÔNG ĐƯỢC bỏ sót bất kỳ câu thoại nào, cho dù video có dài đến đâu.
            - Nếu bạn không dịch hết đến cuối, hệ thống phần mềm của chúng tôi sẽ bị sập.
            - Định dạng: chuẩn file .srt. Dòng 1: Tiếng Trung, Dòng 2: Bản dịch Tiếng Việt."""

            generation_config = genai.types.GenerationConfig(max_output_tokens=8192, temperature=0.2)
            response = model.generate_content([prompt, uploaded_audio], generation_config=generation_config)
            
            st.session_state.srt_content = response.text.strip().replace('```srt', '').replace('```', '').strip()
            genai.delete_file(uploaded_audio.name)
            cleanup_files(temp_audio_path)
            
            st.success("🎉 Trích xuất xong! Vui lòng cuộn xuống kiểm tra xem AI đã dịch đến câu cuối cùng của video chưa ở Bước 2.")
        except Exception as e:
            st.error(f"Đã xảy ra lỗi: {e}")

# ==========================================
# BƯỚC 2: TẠO 1 VIDEO HOÀN CHỈNH
# ==========================================
if st.session_state.srt_content:
    st.divider()
    edited_srt = st.text_area("Nội dung phụ đề (Kiểm tra xem AI đã dịch đủ đến cuối video chưa, bạn có thể sửa trực tiếp):", value=st.session_state.srt_content, height=380)

    if st.button("🎬 Xác nhận & Xuất Video Hoàn Chỉnh"):
        if "Trả phí" in tts_service and not active_api_key:
            st.error("❌ Vui lòng nhập API Key cho dịch vụ Lồng tiếng bạn đã chọn!")
        elif not selected_voice:
            st.error("❌ Không có giọng đọc nào được chọn!")
        else:
            try:
                srt_filename, ass_filename, output_video_file, audio_tts_file = "phu_de_vietsub.srt", "phu_de_vietsub.ass", "video_hoanchinh.mp4", "vietnamese_voice.mp3"
                with open(srt_filename, "w", encoding="utf-8") as f:
                    f.write(filter_only_vietnamese_srt(edited_srt))
                create_ass_file(edited_srt, ass_filename, cover_original=cover_original)

                st.info("🎙️ Đang tạo giọng đọc AI...")
                if "ElevenLabs" in tts_service:
                    s_type = "Paid_ElevenLabs"
                elif "OpenAI" in tts_service:
                    s_type = "Paid_OpenAI"
                else:
                    s_type = "Free_EdgeTTS"

                has_audio = build_audio_ffmpeg_parallel(parse_srt(edited_srt), selected_voice, audio_tts_file, s_type, active_api_key)
                st.info("🎬 Đang ghép Phụ đề & Âm thanh vào Video...")
                
                bg_vol = {"Tắt âm hoàn toàn (0%)": "0.0", "Nhạc nền cực nhỏ (5%)": "0.05", "Vừa phải (15%)": "0.15"}[vol_option]
                
                if has_audio and os.path.exists(audio_tts_file):
                    cmd = ["ffmpeg", "-y", "-i", st.session_state.temp_video_path, "-i", audio_tts_file, "-filter_complex", 
                           f"[0:a]volume={bg_vol}[bg];[bg][1:a]amix=inputs=2:duration=first:normalize=0[outa];[0:v]subtitles={ass_filename}[outv]" if bg_vol != "0.0" 
                           else f"[0:v]subtitles={ass_filename}[outv]", 
                           "-map", "[outv]", "-map", "[outa]" if bg_vol != "0.0" else "1:a", "-c:v", "libx264", "-c:a", "aac", output_video_file]
                    try:
                        subprocess.run(cmd, check=True, capture_output=True, text=True)
                    except subprocess.CalledProcessError:
                        subprocess.run(["ffmpeg", "-y", "-i", st.session_state.temp_video_path, "-i", audio_tts_file, "-filter_complex", f"[0:v]subtitles={ass_filename}[outv]", "-map", "[outv]", "-map", "1:a", "-c:v", "libx264", "-c:a", "aac", output_video_file], check=True)
                else:
                    subprocess.run(["ffmpeg", "-y", "-i", st.session_state.temp_video_path, "-vf", f"subtitles={ass_filename}", "-c:a", "copy", output_video_file], check=True)

                st.success("🎉 Hoàn tất! Video đã được Vietsub & Lồng tiếng full.")
                col_a, col_b = st.columns(2)
                with col_a:
                    st.download_button("📝 Tải File Phụ Đề (.srt)", data=open(srt_filename, "rb"), file_name="vietsub.srt", mime="text/plain")
                with col_b:
                    st.download_button("🎬 Tải Video Hoàn Chỉnh", data=open(output_video_file, "rb"), file_name="video_vietsub_longtieng.mp4", mime="video/mp4")

            except Exception as e:
                st.error(f"Lỗi: {e}")
