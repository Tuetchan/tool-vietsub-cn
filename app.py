import streamlit as st
import yt_dlp
import os
import google.generativeai as genai
import time
import re
import subprocess

st.set_page_config(page_title="Auto Vietsub Tool", page_icon="🎬", layout="wide")
st.title("🎬 Tool Auto Vietsub Phim Trung Quốc bằng Gemini")
st.write("Căn chỉnh phụ đề khớp chính xác theo giọng nói trong Video -> Xem/Sửa -> Ghép video")

# Nhập API Key
api_key = st.text_input("Nhập Gemini API Key của bạn:", type="password", help="Lấy API Key miễn phí tại Google AI Studio")

# Lưu trạng thái Streamlit
if "srt_content" not in st.session_state:
    st.session_state.srt_content = ""
if "temp_video_path" not in st.session_state:
    st.session_state.temp_video_path = ""

# Lựa chọn phương thức đầu vào
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

# ==========================================
# BƯỚC 1: PHÂN TÍCH & DỊCH KHỚP THEO TIẾNG NÓI
# ==========================================
st.subheader("Bước 1: Trích xuất & Dịch chuẩn khớp nhịp thoại")

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
            
            # Khai báo model theo yêu cầu
            model = genai.GenerativeModel('gemini-3.5-flash')

            temp_video_path = "temp_video.mp4"
            cleanup_files(temp_video_path, "phu_de_vietsub.srt", "video_vietsub_output.mp4")

            # 1. Tải / Lưu Video
            if option == "Tải tệp video từ máy (MP4, MOV,...)":
                st.info("Đang xử lý tệp video tải lên...")
                file_ext = uploaded_file.name.split('.')[-1]
                temp_video_path = f"temp_input_video.{file_ext}"
                with open(temp_video_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
            else:
                clean_url = extract_clean_url(raw_video_input)
                st.write(f"🔗 Link xử lý: `{clean_url}`")
                st.info("Đang tải Video...")
                ydl_opts = {
                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                    'outtmpl': temp_video_path,
                    'quiet': True,
                    'no_warnings': True,
                    'http_headers': {
                        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
                    }
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([clean_url])

            st.session_state.temp_video_path = temp_video_path

            # 2. Upload Video lên Gemini File API
            st.info("Đang tải Video lên AI để bắt nhịp âm thanh giọng nói...")
            uploaded_video = genai.upload_file(path=temp_video_path)
            
            while uploaded_video.state.name == "PROCESSING":
                time.sleep(3)
                uploaded_video = genai.get_file(uploaded_video.name)

            if uploaded_video.state.name == "FAILED":
                raise Exception("Tải video lên Gemini AI thất bại.")

            st.info("Gemini đang nghe giọng nói, căn mốc thời gian và dịch ra tiếng Việt...")
            
            # PROMPT TẬP TRUNG VÀO BẮT MỐC THỜI GIAN KHỚP ÂM THANH
            prompt = """
            Bạn là chuyên gia làm phụ đề phim chuyên nghiệp.

            NHIỆM VỤ QUAN TRỌNG NHẤT - CẮN CHỈNH THỜI GIAN THEO ÂM THANH (AUDIO SYNCHRONIZATION):
            1. Mốc thời gian (start_time --> end_time) của từng câu phụ đề BẮT BUỘC phải căn theo GIỌNG NÓI / ÂM THANH THOẠI thực tế trong video:
               - Thời gian bắt đầu: Đúng khoảnh khắc nhân vật BẮT ĐẦU cất tiếng nói.
               - Thời gian kết thúc: Đúng khoảnh khắc nhân vật DỪNG nói câu đó.
            2. Tuyệt đối KHÔNG căn thời gian theo độ dài của chữ viết trên màn hình hay độ dài câu dịch, để tránh bị lệch tiếng.
            3. QUY TẮC CÂU NGẮN: Mới mỗi nhịp nói ngắt câu, ngắt phụ đề thành dòng ngắn (tối đa 5-8 từ). Không gộp nhiều câu nói vào một dòng dài.
            4. Trình bày CHÍNH XÁC theo chuẩn định dạng tệp phụ đề .srt (hh:mm:ss,ms). Không thêm ký tự hay giải thích markdown nào ngoài chuẩn SRT.

            Ví dụ định dạng chuẩn:
            1
            00:00:01,200 --> 00:00:03,150
            Tôi không tin chuyện này.

            2
            00:00:03,400 --> 00:00:05,000
            Anh nói thật chứ?
            """

            response = model.generate_content([prompt, uploaded_video])
            srt_text = response.text.strip().replace('```srt', '').replace('```', '').strip()

            st.session_state.srt_content = srt_text
            genai.delete_file(uploaded_video.name)
            st.success("Dịch và căn khớp thời gian thành công! Hãy kiểm tra nội dung dưới đây.")

        except Exception as e:
            st.error(f"Đã xảy ra lỗi: {e}")

# ==========================================
# BƯỚC 2: XEM / SỬA PHỤ ĐỀ & ĐÓNG VÀO VIDEO
# ==========================================
if st.session_state.srt_content:
    st.divider()
    st.subheader("Bước 2: Kiểm tra, Sửa lời dịch & Ghép vào Video")
    
    edited_srt = st.text_area(
        label="Chỉnh sửa nội dung hoặc mốc thời gian nếu cần:",
        value=st.session_state.srt_content,
        height=350
    )

    if st.button("🎬 Xác nhận & Ghép phụ đề vào Video"):
        try:
            srt_filename = "phu_de_vietsub.srt"
            output_video_file = "video_vietsub_output.mp4"

            with open(srt_filename, "w", encoding="utf-8") as f:
                f.write(edited_srt)

            st.info("Đang dùng FFmpeg đóng phụ đề chuẩn khớp vào video...")
            
            cmd_merge = f'ffmpeg -i "{st.session_state.temp_video_path}" -vf "subtitles=\'{srt_filename}\'" -c:a copy "{output_video_file}" -y'
            subprocess.run(cmd_merge, shell=True, check=True)

            st.success("🎉 Hoàn tất đóng phụ đề vào video!")

            col1, col2 = st.columns(2)
            with col1:
                with open(srt_filename, "rb") as file_srt:
                    st.download_button(
                        label="📝 Tải file phụ đề (.srt)",
                        data=file_srt,
                        file_name="vietsub_chuan.srt",
                        mime="text/plain"
                    )
            with col2:
                with open(output_video_file, "rb") as file_vid:
                    st.download_button(
                        label="🎬 Tải Video Vietsub hoàn chỉnh (.mp4)",
                        data=file_vid,
                        file_name="video_vietsub_chuan.mp4",
                        mime="video/mp4"
                    )

        except Exception as e:
            st.error(f"Lỗi khi ghép phụ đề vào video: {e}")
