import streamlit as st
import yt_dlp
import os
import google.generativeai as genai
import time
import re
import subprocess

st.set_page_config(page_title="Auto Vietsub Tool", page_icon="🎬", layout="wide")
st.title("🎬 Tool Auto Vietsub Phim Trung Quốc bằng Gemini")
st.write("Tạo phụ đề Song ngữ (Trung - Việt) -> Kiểm tra & Sửa -> Ghép vào Video")

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
# BƯỚC 1: PHÂN TÍCH & DỊCH SONG NGỮ (TRUNG - VIỆT)
# ==========================================
st.subheader("Bước 1: Trích xuất & Dịch phụ đề Song ngữ")

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
            
            # Khuyên dùng 'gemini-3.5-flash' hoặc 'gemini-2.5-flash-latest' để đảm bảo không bị lỗi 404
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
            st.info("Đang tải Video lên AI để phân tích hình ảnh và âm thanh...")
            uploaded_video = genai.upload_file(path=temp_video_path)
            
            while uploaded_video.state.name == "PROCESSING":
                time.sleep(3)
                uploaded_video = genai.get_file(uploaded_video.name)

            if uploaded_video.state.name == "FAILED":
                raise Exception("Tải video lên Gemini AI thất bại.")

            st.info("Gemini đang trích xuất tiếng Trung và dịch sang tiếng Việt...")
            
            # PROMPT YÊU CẦU TẠO PHỤ ĐỀ SONG NGỮ (TIẾNG TRUNG + TIẾNG VIỆT)
            prompt = """
            Bạn là chuyên gia dịch thuật phim Trung Quốc.

            NHIỆM VỤ:
            1. Nghe âm thanh thoại và quan sát chữ trên màn hình video để tạo phụ đề SONG NGỮ TRUNG - VIỆT.
            2. Căn mốc thời gian (start_time --> end_time) khớp chính xác theo nhịp cất giọng nói của nhân vật.
            3. QUY TẮC ĐỊNH DẠNG SONG NGỮ: Mỗi ô phụ đề BẮT BUỘC có 2 dòng:
               - Dòng 1: Câu tiếng Trung gốc (Chữ Hán)
               - Dòng 2: Bản dịch tiếng Việt tương ứng (ngắn gọn, tự nhiên, dưới 9 từ)
            4. Xuất ra chuẩn định dạng tệp .srt. Không thêm bất kỳ lời giải thích hay ký tự markdown nào khác.

            Ví dụ định dạng chuẩn bắt buộc:
            1
            00:00:01,200 --> 00:00:03,150
            胡说八道！
            Nói bậy bạ!

            2
            00:00:03,400 --> 00:00:05,000
            终于露面了。
            Cuối cùng cũng lộ diện rồi.
            """

            response = model.generate_content([prompt, uploaded_video])
            srt_text = response.text.strip().replace('```srt', '').replace('```', '').strip()

            st.session_state.srt_content = srt_text
            genai.delete_file(uploaded_video.name)
            st.success("Tạo phụ đề Song ngữ thành công! Hãy kiểm tra nội dung dưới đây.")

        except Exception as e:
            st.error(f"Đã xảy ra lỗi: {e}")

# ==========================================
# BƯỚC 2: KIỂM TRA SONG NGỮ & GHÉP VÀO VIDEO
# ==========================================
if st.session_state.srt_content:
    st.divider()
    st.subheader("Bước 2: Kiểm tra Phụ đề Song ngữ (Trung - Việt) & Ghép vào Video")
    
    edited_srt = st.text_area(
        label="Nội dung phụ đề Song ngữ (Bạn có thể xem chữ Trung gốc và chỉnh sửa tiếng Việt trực tiếp tại đây):",
        value=st.session_state.srt_content,
        height=380
    )

    if st.button("🎬 Xác nhận & Ghép phụ đề vào Video"):
        try:
            srt_filename = "phu_de_vietsub.srt"
            output_video_file = "video_vietsub_output.mp4"

            with open(srt_filename, "w", encoding="utf-8") as f:
                f.write(edited_srt)

            st.info("Đang tiến hành ghép phụ đề vào video bằng FFmpeg...")
            
            cmd_merge = f'ffmpeg -i "{st.session_state.temp_video_path}" -vf "subtitles=\'{srt_filename}\'" -c:a copy "{output_video_file}" -y'
            subprocess.run(cmd_merge, shell=True, check=True)

            st.success("🎉 Hoàn tất ghép phụ đề vào video!")

            col1, col2 = st.columns(2)
            with col1:
                with open(srt_filename, "rb") as file_srt:
                    st.download_button(
                        label="📝 Tải file phụ đề song ngữ (.srt)",
                        data=file_srt,
                        file_name="vietsub_songngu.srt",
                        mime="text/plain"
                    )
            with col2:
                with open(output_video_file, "rb") as file_vid:
                    st.download_button(
                        label="🎬 Tải Video gắn phụ đề hoàn chỉnh (.mp4)",
                        data=file_vid,
                        file_name="video_vietsub_hoanchinh.mp4",
                        mime="video/mp4"
                    )

        except Exception as e:
            st.error(f"Lỗi khi ghép phụ đề vào video: {e}")
