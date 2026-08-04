import streamlit as st
import yt_dlp
import os
import google.generativeai as genai
import time
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

st.set_page_config(page_title="Auto Vietsub Tool", page_icon="🎬", layout="wide")
st.title("🎬 Tool Auto Vietsub & Lồng Tiếng Việt bằng Gemini (Siêu Nhanh & Tiết Kiệm)")
st.write("Tự động trích xuất âm thanh -> Dịch thuật bằng Gemini -> Lồng tiếng song song & Xuất video hoàn chỉnh")

# Nhập API Key
api_key = st.text_input("Nhập Gemini API Key của bạn:", type="password", help="Lấy API Key miễn phí tại Google AI Studio")

if "srt_content" not in st.session_state:
    st.session_state.srt_content = ""
if "temp_video_path" not in st.session_state:
    st.session_state.temp_video_path = ""

cover_original = st.checkbox("Tự động tạo khung nền đen che lên chữ Trung Quốc gốc ở dưới video", value=True)

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

# Tách riêng file âm thanh MP3 từ Video để gửi cho AI (Giúp tiết kiệm Token & chạy siêu nhanh)
def extract_audio_from_video(input_video_path, output_audio_path):
    cmd = [
        "ffmpeg", "-y",
        "-i", input_video_path,
        "-vn",
        "-acodec", "libmp3lame",
        "-q:a", "4",
        output_audio_path
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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

def generate_single_tts(sub_item):
    idx, sub, voice = sub_item
    text = sub['text']
    start_sec = sub['start']
    temp_speech_file = f"temp_speech_{idx}.mp3"
    try:
        cmd = ["edge-tts", "--voice", voice, "--text", text, "--write-media", temp_speech_file]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(temp_speech_file):
            return idx, start_sec, temp_speech_file
    except Exception:
        pass
    return idx, start_sec, None

# Xử lý tạo giọng lồng tiếng SONG SONG (Đa luồng) giúp tăng tốc gấp 5 lần
def build_audio_ffmpeg_parallel(subtitles, voice, output_audio_path):
    tasks = [(idx, sub, voice) for idx, sub in enumerate(subtitles)]
    
    # Chạy 5 luồng cùng lúc để tải audio nhanh hơn
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(generate_single_tts, tasks))
    
    # Sắp xếp lại thứ tự đúng theo mốc thời gian
    results.sort(key=lambda x: x[0])

    inputs = []
    filter_complex_parts = []
    temp_files = []
    
    for idx, start_sec, temp_speech_file in results:
        if temp_speech_file:
            temp_files.append(temp_speech_file)
            delay_ms = int(start_sec * 1000)
            file_input_idx = len(temp_files) - 1
            inputs.extend(["-i", temp_speech_file])
            filter_complex_parts.append(f"[{file_input_idx}:a]adelay={delay_ms}|{delay_ms}[a{file_input_idx}]")

    if not filter_complex_parts:
        return False

    mix_inputs = "".join([f"[a{i}]" for i in range(len(filter_complex_parts))])
    filter_complex_str = ";".join(filter_complex_parts) + f";{mix_inputs}amix=inputs={len(filter_complex_parts)}:dropout_transition=0[outa]"

    cmd = ["ffmpeg", "-y"] + inputs + ["-filter_complex", filter_complex_str, "-map", "[outa]", output_audio_path]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cleanup_files(*temp_files)
    return True

# ==========================================
# BƯỚC 1: TRÍCH XUẤT PHỤ ĐỀ (TỐI ƯU AUDIO)
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
            model = genai.GenerativeModel('gemini-3.5-flash')

            temp_video_path = "temp_video.mp4"
            temp_audio_path = "temp_audio_for_ai.mp3"
            
            cleanup_files(temp_video_path, temp_audio_path, "phu_de_vietsub.srt", "video_hoanchinh.mp4", "vietnamese_voice.mp3")

            if option == "Tải tệp video từ máy (MP4, MOV,...)":
                file_ext = uploaded_file.name.split('.')[-1]
                temp_video_path = f"temp_input_video.{file_ext}"
                with open(temp_video_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
            else:
                clean_url = extract_clean_url(raw_video_input)
                # Giới hạn độ phân giải max 720p để tải & render nhẹ, nhanh hơn
                ydl_opts = {
                    'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best',
                    'outtmpl': temp_video_path,
                    'quiet': True,
                    'no_warnings': True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([clean_url])

            st.session_state.temp_video_path = temp_video_path

            # Tách File âm thanh ra để gửi AI (Tiết kiệm >80% Token)
            st.info("🎵 Đang trích xuất file âm thanh nhẹ để gửi AI phân tích...")
            extract_audio_from_video(temp_video_path, temp_audio_path)

            st.info("⚡ Đang gửi âm thanh lên AI (Tối ưu tốc độ & tiết kiệm Token)...")
            uploaded_audio = genai.upload_file(path=temp_audio_path)
            
            while uploaded_audio.state.name == "PROCESSING":
                time.sleep(2)
                uploaded_audio = genai.get_file(uploaded_audio.name)

            prompt = """
            Bạn là chuyên gia làm phụ đề phim.
            Hãy nghe âm thanh tiếng Trung trong file để tạo phụ đề dịch Tiếng Việt.
            YÊU CẦU BẮT BUỘC:
            1. Căn thời gian (timestamp) chính xác theo nhịp thoại.
            2. Mỗi ô phụ đề gồm 2 dòng:
               Dòng 1: Tiếng Trung gốc (nghe từ lời thoại)
               Dòng 2: Bản dịch Tiếng Việt (câu ngắn gọn, tự nhiên, dưới 8 từ)
            3. Trình bày CHÍNH XÁC theo chuẩn định dạng .srt.
            """

            response = model.generate_content([prompt, uploaded_audio])
            srt_text = response.text.strip().replace('```srt', '').replace('```', '').strip()

            st.session_state.srt_content = srt_text
            genai.delete_file(uploaded_audio.name)
            cleanup_files(temp_audio_path)
            
            st.success("🎉 Trích xuất phụ đề thành công! Kiểm tra và sửa đổi ở Bước 2.")

        except Exception as e:
            st.error(f"Đã xảy ra lỗi: {e}")

# ==========================================
# BƯỚC 2: TẠO 1 VIDEO HOÀN CHỈNH (TỐI ƯU TTS)
# ==========================================
if st.session_state.srt_content:
    st.divider()
    st.subheader("Bước 2: Đối chiếu Tiếng Trung gốc & Xuất Video")
    st.info("💡 Ô bên dưới hiển thị chữ Trung gốc để bạn đối chiếu. Ứng dụng sẽ xóa chữ Trung, lồng tiếng Việt đa luồng cực nhanh và xuất ra 1 video duy nhất!")
    
    edited_srt = st.text_area(
        label="Nội dung phụ đề (Xem chữ Trung gốc và sửa câu Tiếng Việt tại đây):",
        value=st.session_state.srt_content,
        height=380
    )

    if st.button("🎬 Xác nhận & Xuất Video Hoàn Chỉnh"):
        try:
            srt_filename = "phu_de_vietsub.srt"
            output_video_file = "video_hoanchinh.mp4"
            audio_tts_file = "vietnamese_voice.mp3"

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

            st.info("🎙️ Đang tạo giọng đọc AI lồng tiếng đa luồng (Song song)...")
            subtitles = parse_srt(edited_srt)
            has_audio = build_audio_ffmpeg_parallel(subtitles, selected_voice, audio_tts_file)

            st.info("🎬 Đang ghép Phụ đề & Âm thanh vào Video...")
            if has_audio and os.path.exists(audio_tts_file):
                audio_tts_path = os.path.abspath(audio_tts_file).replace("\\", "/")
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

            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            st.success("🎉 Hoàn tất! Video đã ghép đầy đủ Vietsub và Lồng tiếng Việt thành công.")

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

        except Exception as e:
            st.error(f"Lỗi khi xử lý video: {e}")
