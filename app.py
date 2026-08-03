import streamlit as st
import yt_dlp
import os
import google.generativeai as genai
import time

# Cấu hình giao diện Streamlit
st.set_page_config(page_title="Auto Vietsub Tool", page_icon="🎬")
st.title("🎬 Tool Auto Vietsub Phim Trung Quốc bằng Gemini")
st.write("Tải âm thanh từ Douyin/Xiaohongshu và tự động tạo file phụ đề Vietsub (.srt)")

# Form nhập liệu
api_key = st.text_input("Nhập Gemini API Key của bạn:", type="password", help="Lấy API Key miễn phí tại Google AI Studio")
video_url = st.text_input("Nhập link video:")

# Hàm dọn dẹp file tạm
def cleanup_files(*filepaths):
    for path in filepaths:
        if os.path.exists(path):
            os.remove(path)

if st.button("Bắt đầu xử lý"):
    if not api_key:
        st.error("Vui lòng nhập Gemini API Key!")
    elif not video_url:
        st.warning("Vui lòng nhập đường link video!")
    else:
        try:
            # 1. Cấu hình Gemini API
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-3.5-flash') # Có thể đổi thành gemini-2.5-pro nếu cần dịch sâu hơn
            
            # 2. Tải âm thanh từ video bằng yt-dlp
            st.info("Đang tách âm thanh từ video...")
            audio_filename = "temp_audio"
            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': f'{audio_filename}.%(ext)s',
                'quiet': True
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            
            mp3_file = f"{audio_filename}.mp3"
            st.success("Tách âm thanh thành công!")
            
            # 3. Gửi file âm thanh lên Gemini
            st.info("Đang tải âm thanh lên máy chủ AI...")
            uploaded_audio = genai.upload_file(path=mp3_file)
            
            # Đợi một chút để Google AI xử lý file vừa upload
            time.sleep(3) 

            # 4. Yêu cầu Gemini nghe và tạo file SRT
            st.info("Gemini đang nghe và dịch ra tiếng Việt. Vui lòng đợi...")
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
            
            # Làm sạch dữ liệu trả về (phòng trường hợp AI trả về kèm theo markdown code block)
            srt_content = response.text.strip().replace('```srt', '').replace('```', '').strip()
            
            # 5. Lưu kết quả ra file .srt
            srt_filename = "phu_de_vietsub.srt"
            with open(srt_filename, "w", encoding="utf-8") as f:
                f.write(srt_content)
                
            st.success("Dịch hoàn tất! Bạn có thể tải file phụ đề bên dưới.")
            
            # Nút tải file SRT về máy
            with open(srt_filename, "rb") as file:
                btn = st.download_button(
                    label="📥 Tải file phụ đề (.srt)",
                    data=file,
                    file_name="vietsub.srt",
                    mime="text/plain"
                )
            
            # Xóa file trên Google AI và server Streamlit để giải phóng dung lượng
            genai.delete_file(uploaded_audio.name)
            cleanup_files(mp3_file, srt_filename)

        except Exception as e:
            st.error(f"Đã xảy ra lỗi: {e}")
            cleanup_files("temp_audio.mp3", "temp_audio.webm", "temp_audio.m4a", "phu_de_vietsub.srt")
