import streamlit as st
import yt_dlp
import os
import google.generativeai as genai
import time
import re
import subprocess
import asyncio
import edge_tts
import nest_asyncio

# Áp dụng nest_asyncio để không đụng độ Event Loop trên Streamlit Cloud
nest_asyncio.apply()

st.set_page_config(page_title="Auto Vietsub Tool", page_icon="🎬", layout="wide")
st.title("🎬 Tool Auto Vietsub & Lồng Tiếng Việt bằng Gemini")
st.write("Soi câu dịch với chữ Trung gốc -> Tự động tạo giọng đọc Lồng Tiếng Việt & Ghép đè vào Video")

# Nhập API Key
api_key = st.text_input("Nhập Gemini API Key của bạn:", type="password", help="Lấy API Key miễn phí tại Google AI Studio")

if "srt_content" not in st.session_state:
    st.session_state.srt_content = ""
if "temp_video_path" not in st.session_state:
    st.session_state.temp_video_path = ""

# Tùy chọn che chữ Trung gốc & Lồng tiếng
col1, col2 = st.columns(2)
with col1:
    cover_original = st.checkbox("Tự động tạo khung nền đen che lên chữ Trung Quốc gốc ở dưới video", value=True)
with col2:
    enable_tts = st.checkbox("Bật Lồng tiếng Tiếng Việt (TTS)", value=True)

voice_option = st.selectbox(
    "Chọn giọng đọc Lồng tiếng AI:",
    options=["vi-VN-HoaiMyNeural (Nữ)", "vi-VN-NamMinhNeural (Nam)"],
    index=0
)
selected_voice = voice_option.split(" ")[0]

option = st.radio("Chọn nguồn video:", ("Tải tệp video từ máy (MP4, MOV,...)", "Dán link Douyin / Xiaohongshu"))

uploaded_file = None
raw_video_input = ""

if option == "Tải tệp video từ máy (MP4, MOV,...)":
    uploaded_file = st.file_uploader("Chọn video từ máy tính/điện thoại:", type=["mp4", "mov", "mkv", "avi", "webm"])
else:
    raw_video_input = st.text_input("Nhập link video (hoặc văn bản chia sẻ từ Douyin):")

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

async def generate_voice_file(text, voice, output_path):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)

def build_audio_ffmpeg(subtitles, voice, output_audio_path):
    """Trộn audio lồng tiếng dựa hoàn toàn vào FFmpeg, không cần pydub."""
    temp_files = []
    inputs = []
    filter_complex_parts = []
    
    for idx, sub in enumerate(subtitles):
        text = sub['text']
        start_sec = sub['start']
        temp_speech_file = f"temp_speech_{idx}.mp3"
        temp_files.append(temp_speech_file)

        asyncio.run(generate_voice_file(text, voice, temp_speech_file))

        if os.path.exists(temp_speech_file):
            delay_ms = int(start_sec * 1000)
            inputs.extend(["-i", temp_speech_file])
            filter_complex_parts.append(f"[{idx}:a]adelay={delay_ms}|{delay_ms}[a{idx}]")

    if not filter_complex_parts:
        return False

    mix_inputs = "".join([f"[a{i}]" for i in range(len(filter_complex_parts))])
    filter_complex_str = ";".join(filter_complex_parts) + f";{mix_inputs}amix=inputs={len(filter_complex_parts)}:dropout_transition=0[outa]"

    cmd = ["ffmpeg", "-y"] + inputs + ["-filter_complex", filter_complex_str, "-map", "[outa]", output_audio_path]
    subprocess.run(cmd, check=True)
    cleanup_files(*temp_files)
    return True

# ==========================================
# BƯỚC 1: TRÍCH XUẤT PHỤ ĐỀ (MODEL GEMINI-3.5-FLASH)
# ==========================================
st.subheader("Bước 1: Trích xuất & Dịch phụ đề")

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
            
            # Giữ nguyên model gemini-3.5-flash theo yêu cầu
            model = genai.GenerativeModel('gemini-3.5-flash')

            temp_video_path = "temp_video.mp4"
            cleanup_files(temp_video_path, "phu_de_vietsub.srt", "video_vietsub_output.mp4", "vietnamese_voice.mp3")

            if option == "Tải tệp video từ máy (MP4, MOV,...)":
                file_ext = uploaded_file.name.split('.')[-1]
                temp_video_path = f"temp_input_video.{file_ext}"
                with open(temp_video_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
            else:
                clean_url = extract_clean_url(raw_video_input)
                ydl_opts = {
                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                    'outtmpl': temp_video_path,
                    'quiet': True,
                    'no_warnings': True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([clean_url])

            st.session_state.temp_video_path = temp_video_path

            st.info("Đang tải Video lên AI...")
            uploaded_video = genai.upload_file(path=temp_video_path)
            
            while uploaded_video.state.name == "PROCESSING":
                time.sleep(3)
                uploaded_video = genai.get_file(uploaded_video.name)

            prompt = """
            Bạn là chuyên gia làm phụ đề phim.
            Hãy nghe giọng nói và nhìn chữ trên màn hình video để tạo phụ đề.
            YÊU CẦU BẮT BỘC:
            1. Căn thời gian chính xác theo nhịp thoại của nhân vật.
            2. Mỗi ô phụ đề gồm 2 dòng:
               Dòng 1: Tiếng Trung gốc (để kiểm tra)
               Dòng 2: Bản dịch Tiếng Việt (câu ngắn, dưới 8 từ)
            3. Trình bày CHÍNH XÁC theo định dạng .srt.
            """

            response = model.generate_content([prompt, uploaded_video])
            srt_text = response.text.strip().replace('```srt', '').replace('```', '').strip()

            st.session_state.srt_content = srt_text
            genai.delete_file(uploaded_video.name)
            st.success("Trích xuất phụ đề thành công! Hãy kiểm tra nội dung bên dưới.")

        except Exception as e:
            st.error(f"Đã xảy ra lỗi: {e}")

# ==========================================
# BƯỚC 2: KIỂM TRA -> TẠO LỒNG TIẾNG & GHÉP VIDEO
# ==========================================
if st.session_state.srt_content:
    st.divider()
    st.subheader("Bước 2: Đối chiếu Tiếng Trung gốc & Sửa bản dịch Tiếng Việt")
    st.info("💡 Ô bên dưới hiển thị cả chữ Trung gốc để bạn đối chiếu. Khi bấm nút ghép video, ứng dụng sẽ TỰ ĐỘNG XÓA tiếng Trung, tạo giọng đọc lồng tiếng Việt và ghép đè vào video!")
    
    edited_srt = st.text_area(
        label="Nội dung phụ đề (Bạn có thể xem chữ Trung gốc và chỉnh sửa câu tiếng Việt):",
        value=st.session_state.srt_content,
        height=380
    )

    if st.button("🎬 Xác nhận & Ghép Lồng Tiếng vào Video"):
        try:
            srt_filename = "phu_de_vietsub.srt"
            output_video_file = "video_vietsub_output.mp4"
            audio_tts_file = "vietnamese_voice.mp3"

            # 1. Tự động lọc chỉ giữ lại tiếng Việt
            vi_only_srt = filter_only_vietnamese_srt(edited_srt)

            with open(srt_filename, "w", encoding="utf-8") as f:
                f.write(vi_only_srt)

            input_video_path = os.path.abspath(st.session_state.temp_video_path).replace("\\", "/")
            srt_path_clean = os.path.abspath(srt_filename).replace("\\", "/").replace(":", "\\:")
            output_video_path = os.path.abspath(output_video_file).replace("\\", "/")

            if cover_original:
                style_str = "FontName=Arial,FontSize=16,PrimaryColour=&H00FFFFFF,BorderStyle=3,BackColour=&H90000000,MarginV=20"
            else:
                style_str = "FontName=Arial,FontSize=16,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,MarginV=20"

            if enable_tts:
                st.info("🎙️ Đang tạo giọng đọc AI Lồng Tiếng Việt bằng FFmpeg...")
                subtitles = parse_srt(edited_srt)
                has_audio = build_audio_ffmpeg(subtitles, selected_voice, audio_tts_file)

                if has_audio and os.path.exists(audio_tts_file):
                    audio_tts_path = os.path.abspath(audio_tts_file).replace("\\", "/")
                    st.info("🎬 Đang trộn âm thanh và xuất video...")
                    cmd = [
                        "ffmpeg", "-y",
                        "-i", input_video_path,
                        "-i", audio_tts_path,
                        "-filter_complex",
                        f"[0:a]volume=0.15[bg];[bg][1:a]amix=inputs=2:duration=first[outa];[0:v]subtitles='{srt_path_clean}':force_style='{style_str}'[outv]",
                        "-map", "[outv]",
                        "-map", "[outa]",
                        "-c:v", "libx264",
                        "-c:a", "aac",
                        output_video_path
                    ]
                else:
                    cmd = [
                        "ffmpeg", "-y",
                        "-i", input_video_path,
                        "-vf", f"subtitles='{srt_path_clean}':force_style='{style_str}'",
                        "-c:a", "copy",
                        output_video_path
                    ]
            else:
                st.info("Đang tiến hành ghép Vietsub tiếng Việt vào video...")
                cmd = [
                    "ffmpeg", "-y",
                    "-i", input_video_path,
                    "-vf", f"subtitles='{srt_path_clean}':force_style='{style_str}'",
                    "-c:a", "copy",
                    output_video_path
                ]

            subprocess.run(cmd, check=True)
            st.success("🎉 Hoàn tất ghép Vietsub & Lồng Tiếng Việt vào video!")

            col_a, col_b = st.columns(2)
            with col_a:
                with open(srt_filename, "rb") as file_srt:
                    st.download_button(
                        label="📝 Tải file phụ đề Vietsub (.srt)",
                        data=file_srt,
                        file_name="vietsub.srt",
                        mime="text/plain"
                    )
            with col_b:
                with open(output_video_file, "rb") as file_vid:
                    st.download_button(
                        label="🎬 Tải Video Lồng Tiếng hoàn chỉnh (.mp4)",
                        data=file_vid,
                        file_name="video_longtieng_hoanchinh.mp4",
                        mime="video/mp4"
                    )

        except Exception as e:
            st.error(f"Lỗi khi xử lý video: {e}")
