import streamlit as st
import yt_dlp
import os
import google.generativeai as genai
import time
import re
import subprocess

st.set_page_config(page_title="Auto Vietsub Tool", page_icon="🎬", layout="wide")
st.title("🎬 Tool Auto Vietsub Video (Đọc Chữ & Nghe Giọng Nói)")
st.write("Tự động nhận diện phụ đề hoặc nghe giọng nói -> Dịch thuật bằng Gemini AI -> Xuất video Vietsub hoàn chỉnh")

# 1. Cấu hình AI Dịch thuật
st.subheader("🔑 1. Cấu hình AI Dịch thuật")
api_key = st.text_input("Nhập Gemini API Key (Bắt buộc):", type="password")

# 2. Tùy chọn Phụ đề
st.subheader("⚙️ 2. Tùy chọn Phụ đề")
cover_original = st.checkbox("Tạo khung nền đen mờ bao trùm để che chữ gốc (Khuyên dùng nếu video có sẵn chữ tiếng Trung)", value=True)

# 3. Nguồn Video
st.divider()
st.subheader("📹 3. Chọn nguồn video")
option = st.radio("Chọn cách tải video lên:", ("Tải tệp video từ máy (MP4, MOV,...)", "Dán link Douyin / Xiaohongshu"))
uploaded_file = None
raw_video_input = ""

if option == "Tải tệp video từ máy (MP4, MOV,...)":
    uploaded_file = st.file_uploader("Chọn video từ máy tính:", type=["mp4", "mov", "mkv", "avi", "webm"])
else:
    raw_video_input = st.text_input("Nhập link video (hoặc văn bản chia sẻ từ Douyin):")

# Khởi tạo session state
if "srt_content" not in st.session_state:
    st.session_state.srt_content = ""
if "temp_video_path" not in st.session_state:
    st.session_state.temp_video_path = ""

# --- CÁC HÀM XỬ LÝ PHỤ ĐỀ ---
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
        # Định dạng chuẩn: Dòng 0 (Số TT), Dòng 1 (Thời gian), Dòng 2 (Gốc), Dòng cuối (Bản dịch)
        if len(lines) >= 3:
            header = lines[:2]
            # Luôn lấy dòng cuối cùng làm dòng tiếng Việt (Bỏ qua ngôn ngữ gốc dù là Trung, Anh, Hàn...)
            vi_line = lines[-1].strip()
            cleaned_blocks.append("\n".join(header + [vi_line]))
        else:
            cleaned_blocks.append(block)
    return "\n\n".join(cleaned_blocks)

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
    back_color = "&H80000000" if cover_original else "&H00000000" # Nền đen mờ 50% nếu che chữ
    outline = "12" if cover_original else "2"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,26,&H00FFFFFF,&H00000000,&H00000000,{back_color},1,0,0,0,100,100,0,0,{border_style},{outline},0,2,10,10,25,1

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
                # Lấy trực tiếp văn bản ở các dòng còn lại
                text_lines = lines[2:]
                text = r"\N".join(text_lines).strip()
                if text:
                    if cover_original:
                        text = r"\h\h\h\h" + text + r"\h\h\h\h"
                    dialogues.append(f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{text}")
    
    with open(ass_filename, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(dialogues))

# ==========================================
# BƯỚC 1: TRÍCH XUẤT PHỤ ĐỀ / LỜI NÓI BẰNG GEMINI
# ==========================================
if st.button("🚀 Bắt đầu Phân tích & Dịch Video"):
    if not api_key:
        st.error("Vui lòng nhập Gemini API Key!")
    elif option == "Tải tệp video từ máy (MP4, MOV,...)" and not uploaded_file:
        st.warning("Vui lòng tải tệp video lên!")
    elif option == "Dán link Douyin / Xiaohongshu" and not raw_video_input:
        st.warning("Vui lòng nhập đường link video!")
    else:
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.5-flash')
            temp_video_path = "temp_video.mp4"
            cleanup_files(temp_video_path, "phu_de_vietsub.srt", "phu_de_vietsub.ass", "video_hoanchinh.mp4")

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
            
            st.info("📹 Đang tải video lên AI để phân tích hình ảnh và âm thanh...")
            uploaded_video = genai.upload_file(path=temp_video_path)
            while uploaded_video.state.name == "PROCESSING":
                time.sleep(3)
                uploaded_video = genai.get_file(uploaded_video.name)

            st.info("⚡ AI đang kiểm tra phụ đề màn hình và nghe giọng nói... (Vui lòng chờ khoảng 30s - 1 phút)")
            
            # ĐÃ FIX: Yêu cầu AI tự động nghe âm thanh nếu không có chữ
            prompt = """Bạn là một chuyên gia nhận diện hình ảnh, âm thanh và dịch thuật video.
            Nhiệm vụ của bạn:
            1. HÃY XEM VIDEO VÀ NGHE CẢ ÂM THANH TRONG VIDEO NÀY.
            2. Nếu trên màn hình CÓ PHỤ ĐỀ CHỮ: Hãy đọc chữ, ghi lại mốc thời gian và dịch sang Tiếng Việt.
            3. Nếu trên màn hình KHÔNG CÓ PHỤ ĐỀ: Hãy NGHE LỜI NÓI (giọng nói) trong video, ghi lại mốc thời gian người đó nói, viết lại nội dung nói và dịch sang Tiếng Việt.

            LƯU Ý CỰC KỲ QUAN TRỌNG:
            - BẮT BUỘC trả về kết quả theo chuẩn ĐỊNH DẠNG FILE .SRT:
              Dòng 1: Số thứ tự
              Dòng 2: Thời gian (Start --> End, ví dụ 00:00:01,000 --> 00:00:03,500)
              Dòng 3: Nội dung gốc (chữ trên màn hình HOẶC lời nói gốc nghe được)
              Dòng 4: Bản dịch Tiếng Việt
            - BẠN TUYỆT ĐỐI KHÔNG ĐƯỢC BỎ SÓT câu nói/phụ đề nào.
            - Tuyệt đối không thêm các lời giải thích, không viết thêm mã code, chỉ trả về nội dung SRT thuần túy."""

            generation_config = genai.types.GenerationConfig(max_output_tokens=8192, temperature=0.1)
            response = model.generate_content([prompt, uploaded_video], generation_config=generation_config)
            
            st.session_state.srt_content = response.text.strip().replace('```srt', '').replace('```', '').strip()
            genai.delete_file(uploaded_video.name)
            
            st.success("🎉 Phân tích xong! Vui lòng kiểm tra bảng phụ đề ở Bước 4.")
        except Exception as e:
            st.error(f"Đã xảy ra lỗi: {e}")

# ==========================================
# BƯỚC 2: XUẤT VIDEO VIETSUB
# ==========================================
if st.session_state.srt_content:
    st.divider()
    st.subheader("📝 4. Kiểm tra & Chỉnh sửa Phụ đề")
    edited_srt = st.text_area("Bạn có thể sửa trực tiếp lỗi chính tả hoặc thời gian tại đây trước khi xuất video:", value=st.session_state.srt_content, height=380)

    if st.button("🎬 Ghép Phụ Đề & Xuất Video Hoàn Chỉnh"):
        try:
            srt_filename = "phu_de_vietsub.srt"
            ass_filename = "phu_de_vietsub.ass"
            output_video_file = "video_hoanchinh.mp4"
            
            # Lưu file SRT và ASS
            with open(srt_filename, "w", encoding="utf-8") as f:
                f.write(filter_only_vietnamese_srt(edited_srt))
            create_ass_file(edited_srt, ass_filename, cover_original=cover_original)

            st.info("🎬 Đang burn (ghép cứng) phụ đề vào Video...")
            
            # Lệnh FFmpeg giữ nguyên audio gốc
            cmd = [
                "ffmpeg", "-y", 
                "-i", st.session_state.temp_video_path, 
                "-vf", f"subtitles={ass_filename}", 
                "-c:v", "libx264", 
                "-c:a", "copy",
                output_video_file
            ]
            
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            st.success("🎉 Hoàn tất! Video đã được Vietsub.")
            col_a, col_b = st.columns(2)
            with col_a:
                st.download_button("📝 Tải File Phụ Đề (.srt)", data=open(srt_filename, "rb"), file_name="vietsub.srt", mime="text/plain")
            with col_b:
                st.download_button("🎬 Tải Video Hoàn Chỉnh", data=open(output_video_file, "rb"), file_name="video_vietsub.mp4", mime="video/mp4")

        except subprocess.CalledProcessError as e:
            st.error(f"Lỗi ghép video từ FFmpeg: {e.stderr}")
        except Exception as e:
            st.error(f"Lỗi: {e}")
