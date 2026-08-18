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
cover_original = st.checkbox("Tạo hộp đen đặc 100% linh hoạt để che chữ gốc (Sẽ tự động chạy theo chữ)", value=True)

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
    srt_text = srt_text.replace('\r', '')
    cleaned_blocks = []
    blocks = re.split(r'\n\s*\n', srt_text.strip())
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            header = lines[:2]
            # Lấy dòng cuối (bản dịch) và loại bỏ thẻ định vị vị trí như [TOP], [BOTTOM] để chữ hiển thị sạch
            vi_line = lines[-1].strip()
            vi_line = re.sub(r'\[(TOP|MID|BOTTOM)\]\s*', '', vi_line, flags=re.IGNORECASE)
            cleaned_blocks.append("\n".join(header + [vi_line]))
        else:
            cleaned_blocks.append(block)
    return "\n\n".join(cleaned_blocks)

def convert_srt_time_to_ass(srt_time_str):
    srt_time_str = srt_time_str.replace(',', '.')
    parts = srt_time_str.split(':')
    if len(parts) == 3:
        h, m = int(parts[0]), int(parts[1])
        s_parts = parts[2].split('.')
    elif len(parts) == 2:
        h, m = 0, int(parts[0])
        s_parts = parts[1].split('.')
    else:
        return "0:00:00.00"

    s = int(s_parts[0])
    cs = int(s_parts[1][:2].ljust(2, '0')) if len(s_parts) > 1 else 0
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

# ĐÃ FIX TẬN GỐC: Nhận diện vị trí từ bản gốc và dịch chuyển hộp đen linh hoạt
def create_ass_file(srt_text, ass_filename, cover_original=True):
    srt_text = srt_text.replace('\r', '')
    blocks = re.split(r'\n\s*\n', srt_text.strip())
    
    border_style = "3" if cover_original else "1"
    box_color = "&H00000000" if cover_original else "&H00000000" 
    outline = "18" if cover_original else "2"

    # Default an2 (Bottom Center), MarginV=15 để sát đáy
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 1

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,28,&H00FFFFFF,&H00000000,{box_color},{box_color},1,0,0,0,100,100,0,0,{border_style},{outline},0,2,10,10,15,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"""
    
    dialogues = []
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            time_match = re.match(r'((?:\d{1,2}:)?\d{1,2}:\d{1,2}(?:[,\.]\d{1,3})?)\s*-->\s*((?:\d{1,2}:)?\d{1,2}:\d{1,2}(?:[,\.]\d{1,3})?)', lines[1].strip())
            if time_match:
                start_ass = convert_srt_time_to_ass(time_match.group(1))
                end_ass = convert_srt_time_to_ass(time_match.group(2))
                
                raw_text_vi = lines[-1].strip() # Lấy dòng cuối (tiếng việt)
                raw_text_goc = lines[-2].strip() # Lấy dòng trên nó (tiếng gốc, có chứa tag vị trí)
                
                # Quét thẻ vị trí từ văn bản gốc do AI trả về
                alignment_tag = ""
                if "[TOP]" in raw_text_goc.upper():
                    alignment_tag = r"{\an8}" # an8: Top Center
                elif "[MID]" in raw_text_goc.upper():
                    alignment_tag = r"{\an5}" # an5: Middle Center
                else:
                    alignment_tag = r"{\an2}" # an2: Bottom Center (Mặc định)

                # Dọn sạch thẻ vị trí trong chữ Tiếng Việt để không hiện lên màn hình
                text = re.sub(r'\[(TOP|MID|BOTTOM)\]\s*', '', raw_text_vi, flags=re.IGNORECASE)
                
                if text:
                    if cover_original:
                        text = "     " + text + "     "
                    # Chèn alignment_tag vào đầu câu thoại
                    dialogues.append(f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{alignment_tag}{text}")
    
    with open(ass_filename, "w", encoding="utf-8-sig") as f:
        f.write(header + "\n".join(dialogues))
        
    return len(dialogues) > 0

# ==========================================
# BƯỚC 1: TRÍCH XUẤT PHỤ ĐỀ BẰNG GEMINI
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
            
            # --- ĐÃ FIX: Bổ sung lệnh bắt AI phải gán mác vị trí (TOP/MID/BOTTOM) ---
            prompt = """Bạn là một chuyên gia làm phụ đề video. HÃY XEM VIDEO VÀ NGHE CẢ ÂM THANH TRONG VIDEO NÀY.
            
            QUY TẮC BẮT BUỘC (TUYỆT ĐỐI TUÂN THỦ):
            
            TRƯỜNG HỢP 1: NẾU TRÊN MÀN HÌNH CÓ SẴN CHỮ (Hardsub / Phụ đề gốc)
            - BẠN BẮT BUỘC PHẢI lấy đúng mốc thời gian xuất hiện và biến mất của TỪNG KHỐI CHỮ trên màn hình.
            - TUYỆT ĐỐI KHAN TRỌNG: Bạn phải XÁC ĐỊNH VỊ TRÍ của dòng chữ gốc đó trên màn hình đang nằm ở đâu.
               + Nếu chữ ở trên cùng màn hình (đỉnh đầu): Bạn chèn thêm tag [TOP] vào đầu câu gốc.
               + Nếu chữ nằm chình ình ở giữa màn hình: Bạn chèn thêm tag [MID] vào đầu câu gốc.
               + Nếu chữ nằm ở dưới đáy màn hình như bình thường: Bạn chèn thêm tag [BOTTOM] vào đầu câu gốc.

            TRƯỜNG HỢP 2: NẾU TRÊN MÀN HÌNH KHÔNG CÓ CHỮ (Chỉ nghe lời nói)
            - Hãy lắng nghe giọng nói và chia nhỏ thành các đoạn ngắn. Chèn tag [BOTTOM] vào đầu câu gốc.

            ĐỊNH DẠNG ĐẦU RA (SRT CHUẨN - TUYỆT ĐỐI KHÔNG VIẾT THIẾU):
            Dòng 1: Số thứ tự
            Dòng 2: Thời gian (ví dụ 00:00:01,000 --> 00:00:03,500)
            Dòng 3: Nội dung gốc (BẮT BUỘC phải có tag [TOP] hoặc [MID] hoặc [BOTTOM] đứng đầu)
            Dòng 4: Bản dịch Tiếng Việt tương ứng
            
            LƯU Ý: Tuyệt đối không viết gì thêm ngoài định dạng SRT."""

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
            
            # Xuất file SRT sạch (không có tag vị trí) cho người dùng tải về
            with open(srt_filename, "w", encoding="utf-8") as f:
                f.write(filter_only_vietnamese_srt(edited_srt))
            
            # Xuất file ASS có chèn mã định vị 
            has_dialogue = create_ass_file(edited_srt, ass_filename, cover_original=cover_original)
            
            if not has_dialogue:
                st.error("❌ Cảnh báo: Tool không đọc được mốc thời gian nào hợp lệ từ ô văn bản phía trên.")
            else:
                st.info("🎬 Đang burn (ghép cứng) phụ đề vào Video...")
                
                cmd = [
                    "ffmpeg", "-y", 
                    "-i", st.session_state.temp_video_path, 
                    "-vf", "subtitles=phu_de_vietsub.ass", 
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
