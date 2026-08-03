import streamlit as st
import yt_dlp
import os
import google.generativeai as genai
import time
import re
import subprocess

st.set_page_config(page_title="Auto Vietsub Tool", page_icon="🎬", layout="wide")
st.title("🎬 Tool Auto Vietsub Phim Trung Quốc bằng Gemini")
st.write("Soi câu dịch với chữ Trung gốc -> Tự động lọc chỉ lấy Tiếng Việt & Ghép đè vào Video")

# Nhập API Key
api_key = st.text_input("Nhập Gemini API Key của bạn:", type="password", help="Lấy API Key miễn phí tại Google AI Studio")

if "srt_content" not in st.session_state:
    st.session_state.srt_content = ""
if "temp_video_path" not in st.session_state:
    st.session_state.temp_video_path = ""

# Tùy chọn che chữ Trung gốc
cover_original = st.checkbox("Tự động tạo khung nền đen che lên chữ Trung Quốc gốc ở dưới video", value=True)

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

# Hàm tự động lọc bỏ chữ tiếng Trung, chỉ giữ lại tiếng Việt khi đóng dấu vào video
def filter_only_vietnamese_srt(srt_text):
    cleaned_blocks = []
    blocks = srt_text.strip().split("\n\n")
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            header = lines[:2]  # Số thứ tự & mốc thời gian
            content_lines = lines[2:]
            # Lọc bỏ các dòng có chứa chữ Hán (tiếng Trung)
            vi_lines = [l for l in content_lines if not re.search(r'[\u4e00-\u9fff]', l)]
            if vi_lines:
                cleaned_blocks.append("\n".join(header + vi_lines))
            else:
                cleaned_blocks.append("\n".join(lines))
        else:
            cleaned_blocks.append(block)
    return "\n\n".join(cleaned_blocks)

# ==========================================
# BƯỚC 1: TRÍCH XUẤT PHỤ ĐỀ (CÓ TIẾNG TRUNG ĐỂ KIỂM TRA)
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
            cleanup_files(temp_video_path, "phu_de_vietsub.srt", "video_vietsub_output.mp4")

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
# BƯỚC 2: KIỂM TRA (TRUNG - VIỆT) -> LỌC CHỈ LẤY TIẾNG VIỆT ĐỂ GHÉP
# ==========================================
if st.session_state.srt_content:
    st.divider()
    st.subheader("Bước 2: Đối chiếu Tiếng Trung gốc & Sửa bản dịch Tiếng Việt")
    st.info("💡 Ô bên dưới hiển thị cả chữ Trung gốc để bạn đối chiếu. Khi bấm nút ghép video, ứng dụng sẽ TỰ ĐỘNG XÓA tiếng Trung và chỉ lấy chữ Tiếng Việt!")
    
    edited_srt = st.text_area(
        label="Nội dung phụ đề (Bạn có thể xem chữ Trung gốc và chỉnh sửa câu tiếng Việt):",
        value=st.session_state.srt_content,
        height=380
    )

    if st.button("🎬 Xác nhận & Ghép Vietsub vào Video"):
        try:
            srt_filename = "phu_de_vietsub.srt"
            output_video_file = "video_vietsub_output.mp4"

            # TỰ ĐỘNG LỌC CHỈ GIỮ LAỊ TIẾNG VIỆT
            vi_only_srt = filter_only_vietnamese_srt(edited_srt)

            with open(srt_filename, "w", encoding="utf-8") as f:
                f.write(vi_only_srt)

            st.info("Đang tiến hành ghép Vietsub tiếng Việt vào video...")
            
            # Cấu hình kiểu chữ & Khung nền che chữ cũ
            if cover_original:
                # BorderStyle=3 tạo ô dải nền đen mờ che đè lên chữ Trung cũ ở đằng sau
                style_cmd = "force_style='FontName=Arial,FontSize=16,PrimaryColour=&H00FFFFFF,BorderStyle=3,BackColour=&H90000000,MarginV=20'"
            else:
                style_cmd = "force_style='FontName=Arial,FontSize=16,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,MarginV=20'"

            cmd_merge = f'ffmpeg -i "{st.session_state.temp_video_path}" -vf "subtitles=\'{srt_filename}\':{style_cmd}" -c:a copy "{output_video_file}" -y'
            subprocess.run(cmd_merge, shell=True, check=True)

            st.success("🎉 Hoàn tất ghép Vietsub sạch đẹp vào video!")

            col1, col2 = st.columns(2)
            with col1:
                with open(srt_filename, "rb") as file_srt:
                    st.download_button(
                        label="📝 Tải file phụ đề Vietsub (.srt)",
                        data=file_srt,
                        file_name="vietsub.srt",
                        mime="text/plain"
                    )
            with col2:
                with open(output_video_file, "rb") as file_vid:
                    st.download_button(
                        label="🎬 Tải Video Vietsub hoàn chỉnh (.mp4)",
                        data=file_vid,
                        file_name="video_vietsub_hoanchinh.mp4",
                        mime="video/mp4"
                    )

        except Exception as e:
            st.error(f"Lỗi khi ghép phụ đề vào video: {e}")
