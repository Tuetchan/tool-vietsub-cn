import streamlit as st
import yt_dlp
import os
import google.generativeai as genai
import time
import re
import subprocess

st.set_page_config(page_title="Auto Vietsub Tool", page_icon="🎬")
st.title("🎬 Tool Auto Vietsub Phim Trung Quốc bằng Gemini")
st.write("Tạo file phụ đề Vietsub (.srt) và gắn trực tiếp vào video")

# Nhập API Key
api_key = st.text_input("Nhập Gemini API Key của bạn:", type="password", help="Lấy API Key miễn phí tại Google AI Studio")

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

if st.button("Bắt đầu xử lý"):
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

            mp3_file = "temp_audio.mp3"
            output_video_file = "video_vietsub_output.mp4"
            temp_video_path = "temp_video.mp4"
            
            # Dọn dẹp file cũ
            cleanup_files(mp3_file, output_video_file, temp_video_path, "phu_de_vietsub.srt") 

            # TRƯỜNG HỢP 1: Tải video trực tiếp từ thiết bị
            if option == "Tải tệp video từ máy (MP4, MOV,...)":
                st.info("Đang xử lý tệp video tải lên...")
                
                # Lưu file video tạm thời
                file_ext = uploaded_file.name.split('.')[-1]
                temp_video_path = f"temp_uploaded_video.{file_ext}"
                with open(temp_video_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())

                st.info("Đang tách âm thanh bằng FFmpeg...")
                cmd = f'ffmpeg -i "{temp_video_path}" -vn -ar 44100 -ac 2 -b:a 192k "{mp3_file}" -y'
                subprocess.run(cmd, shell=True, check=True)

            # TRƯỜNG HỢP 2: Tải video từ Link Douyin / Xiaohongshu
            else:
                clean_url = extract_clean_url(raw_video_input)
                st.write(f"🔗 Link xử lý: `{clean_url}`")
                st.info("Đang tải toàn bộ Video từ đường link...")

                # Đổi thiết lập yt-dlp để tải VIDEO thay vì chỉ tải AUDIO
                ydl_opts = {
                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                    'outtmpl': temp_video_path, # Lưu thành temp_video.mp4
                    'quiet': True,
                    'no_warnings': True,
                    'http_headers': {
                        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    }
                }

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([clean_url])
                
                st.info("Đang tách âm thanh từ video đã tải...")
                cmd = f'ffmpeg -i "{temp_video_path}" -vn -ar 44100 -ac 2 -b:a 192k "{mp3_file}" -y'
                subprocess.run(cmd, shell=True, check=True)

            st.success("Tách âm thanh thành công!")

            # Gửi file MP3 lên Gemini AI
            st.info("Đang tải âm thanh lên máy chủ AI...")
            uploaded_audio = genai.upload_file(path=mp3_file)
            time.sleep(3)

            st.info("Gemini đang nghe và dịch phụ đề ra tiếng Việt...")
            prompt = """
            Bạn là một biên dịch viên chuyên nghiệp. Hãy nghe file âm thanh tiếng Trung này.
            Nhiệm vụ của bạn là dịch nội dung sang tiếng Việt và trình bày kết quả CHÍNH XÁC theo định dạng file phụ đề .srt.
            Bắt buộc phải có số thứ tự, mốc thời gian (hours:minutes:seconds,milliseconds) và nội dung tiếng Việt.
            Không giải thích, không in đậm, không thêm bất kỳ ký tự hoặc định dạng markdown nào khác ngoài chuẩn SRT.

            Ví dụ định dạng chuẩn:
            1
            00:00:00,000 --> 00:00:05,000
            Xin chào mọi người.
            """

            response = model.generate_content([prompt, uploaded_audio])
            srt_content = response.text.strip().replace('```srt', '').replace('```', '').strip()

            srt_filename = "phu_de_vietsub.srt"
            with open(srt_filename, "w", encoding="utf-8") as f:
                f.write(srt_content)
            
            genai.delete_file(uploaded_audio.name)

            # ==== BƯỚC MỚI: GHÉP PHỤ ĐỀ VÀO VIDEO BẰNG FFMPEG ====
            st.info("Đang tiến hành ghép phụ đề cứng vào video (Quá trình này có thể mất vài phút tùy độ dài video)...")
            
            # Sử dụng bộ lọc subtitles của ffmpeg. Lưu ý: ffmpeg cần ghi đè file lại nên sẽ tốn chút thời gian render
            cmd_merge = f'ffmpeg -i "{temp_video_path}" -vf "subtitles={srt_filename}" -c:a copy "{output_video_file}" -y'
            subprocess.run(cmd_merge, shell=True, check=True)

            st.success("🎉 Hoàn tất toàn bộ quá trình! Bạn có thể tải thành quả bên dưới.")

            # Nút tải file SRT
            with open(srt_filename, "rb") as file_srt:
                st.download_button(
                    label="📝 Tải file phụ đề (.srt)",
                    data=file_srt,
                    file_name="vietsub.srt",
                    mime="text/plain"
                )
            
            # Nút tải file Video đã có phụ đề
            with open(output_video_file, "rb") as file_vid:
                st.download_button(
                    label="🎬 Tải Video đã gắn Vietsub (.mp4)",
                    data=file_vid,
                    file_name="video_vietsub_thanhcong.mp4",
                    mime="video/mp4"
                )

            # Tùy chọn: Dọn dẹp file tạm để tiết kiệm dung lượng server
            cleanup_files(mp3_file, temp_video_path)

        except Exception as e:
            st.error(f"Đã xảy ra lỗi: {e}")
            cleanup_files("temp_audio.mp3", "temp_uploaded_video.*", "temp_video.mp4", "phu_de_vietsub.srt", "video_vietsub_output.mp4")
