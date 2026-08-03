import streamlit as st
import yt_dlp
import os

st.title("🎬 Tool Auto Vietsub Phim Trung Quốc")
st.write("Dán link video Douyin / Xiaohongshu / TikTok để trích xuất sub")

# Ô nhập URL video
video_url = st.text_input("Nhập link video:")

if st.button("Xử lý Video"):
    if video_url:
        st.info("Đang tải video không logo...")
        
        # Cấu hình yt-dlp để tải video
        ydl_opts = {
            'outtmpl': 'input_video.mp4',
            'format': 'bestvideo+bestaudio/best',
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            st.success("Tải video thành công!")
            st.video("input_video.mp4")
            
            # Tới bước này, bạn gọi API (Gemini/Whisper) để nhận diện audio và dịch text
            st.info("Đang trích xuất giọng nói và dịch vietsub...")
            
        except Exception as e:
            st.error(f"Có lỗi xảy ra: {e}")
    else:
        st.warning("Vui lòng nhập đường link video!")
