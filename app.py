import streamlit as st
import yt_dlp
import os
import google.generativeai as genai
import time
import re
import subprocess

st.set_page_config(page_title="Auto Vietsub Tool", page_icon="🎬", layout="wide")
st.title("🎬 Tool Auto Vietsub Phim Trung Quốc (Gemini 3.5 Flash)")
st.write("Dải đen che chữ thông minh (Hiện trước chữ, ẩn sau chữ)")

# Nhập API Key
api_key = st.text_input("Nhập Gemini API Key của bạn:", type="password")

if "srt_content" not in st.session_state:
    st.session_state.srt_content = ""
if "temp_video_path" not in st.session_state:
    st.session_state.temp_video_path = ""

# Tùy chọn hiển thị phụ đề
st.subheader("⚙️ Tùy chọn hiển thị")
display_mode = st.radio(
    "Cách hiển thị phụ đề Vietsub trên video:", 
    ("Che đè lên chữ gốc (Dải đen hiện ra trước chữ)", "Nổi bên trên chữ gốc (Không có dải đen)")
)

outline_size = st.number_input(
    "Độ dày/to của dải nền đen (Mặc định: 2. Tăng số này lên để nền đen phình to ra che chữ tốt hơn):", 
    min_value=0, max_value=50, value=2, step=1
)

st.divider()
st.subheader("📹 Chọn nguồn video")
option = st.radio("Chọn cách tải video lên:", ("Tải tệp video từ máy (MP4, MOV,...)", "Dán link Douyin / Xiaohongshu"))

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

# HÀM: Tự động cộng/trừ thời gian (sớm lên, trễ đi)
def adjust_time_str(time_str, offset_sec):
    time_str = time_str.replace(',', '.')
    parts = time_str.split(':')
    if len(parts) == 3:
        h, m = int(parts[0]), int(parts[1])
        s = float(parts[2])
    elif len(parts) == 2:
        h, m = 0, int(parts[0])
        s = float(parts[1])
    else:
        return time_str
    
    total_sec = h * 3600 + m * 60 + s + offset_sec
    total_sec = max(0, total_sec)
    
    new_h = int(total_sec // 3600)
    new_m = int((total_sec % 3600) // 60)
    new_s = total_sec % 60
    
    return f"{new_h:02d}:{new_m:02d}:{new_s:06.3f}".replace('.', ',')

def apply_timing_offsets(srt_text, start_offset, end_offset):
    blocks = re.split(r'\n\s*\n', srt_text.strip())
    new_blocks = []
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            time_match = re.match(r'((?:\d{1,2}:)?\d{1,2}:\d{1,2}(?:[,\.]\d{1,3})?)\s*-->\s*((?:\d{1,2}:)?\d{1,2}:\d{1,2}(?:[,\.]\d{1,3})?)', lines[1].strip())
            if time_match:
                new_start = adjust_time_str(time_match.group(1), start_offset)
                new_end = adjust_time_str(time_match.group(2), end_offset)
                lines[1] = f"{new_start} --> {new_end}"
        new_blocks.append('\n'.join(lines))
    return '\n\n'.join(new_blocks)

def filter_only_vietnamese_srt(srt_text):
    srt_text = srt_text.replace('\r', '')
    cleaned_blocks = []
    blocks = re.split(r'\n\s*\n', srt_text.strip())
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            header = lines[:2]
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

# HÀM MỚI: Tách nền đen (Lớp 0) và Chữ (Lớp 1), Nền đen hiện trước và biến mất sau
def create_ass_file(srt_text, ass_filename, display_mode, outline_size, box_early, box_late):
    srt_text = srt_text.replace('\r', '')
    blocks = re.split(r'\n\s*\n', srt_text.strip())
    
    border_style = "1"       
    box_color = "&H00000000" 
    
    if display_mode == "Che đè lên chữ gốc (Dải đen hiện ra trước chữ)":
        margin_v = "15"
    else:
        margin_v = "75" 

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 1

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,28,&H00FFFFFF,&H00000000,{box_color},{box_color},1,0,0,0,100,100,0,0,{border_style},{outline_size},0,2,10,10,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"""
    
    dialogues = []
    
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            time_match = re.match(r'((?:\d{1,2}:)?\d{1,2}:\d{1,2}(?:[,\.]\d{1,3})?)\s*-->\s*((?:\d{1,2}:)?\d{1,2}:\d{1,2}(?:[,\.]\d{1,3})?)', lines[1].strip())
            if time_match:
                # Thời gian của chữ Tiếng Việt
                start_ass = convert_srt_time_to_ass(time_match.group(1))
                end_ass = convert_srt_time_to_ass(time_match.group(2))
                
                raw_text_vi = lines[-1].strip()
                raw_text_goc = lines[-2].strip()
                
                alignment_tag = ""
                if "[TOP]" in raw_text_goc.upper():
                    alignment_tag = r"{\an8}" 
                elif "[MID]" in raw_text_goc.upper():
                    alignment_tag = r"{\an5}" 
                else:
                    alignment_tag = r"{\an2}"

                text = re.sub(r'\[(TOP|MID|BOTTOM)\]\s*', '', raw_text_vi, flags=re.IGNORECASE)
                
                if text:
                    if display_mode == "Che đè lên chữ gốc (Dải đen hiện ra trước chữ)":
                        # Căn chỉnh thời gian ĐỘC LẬP cho hộp đen (Hiện sớm hơn và nán lại lâu hơn)
                        box_start_str = adjust_time_str(time_match.group(1), -box_early)
                        box_end_str = adjust_time_str(time_match.group(2), box_late)
                        box_start_ass = convert_srt_time_to_ass(box_start_str)
                        box_end_ass = convert_srt_time_to_ass(box_end_str)
                        
                        # Vẽ hộp đen dạng Vector tĩnh (Không bị co giãn)
                        box_height = 35 + (outline_size * 4)
                        box_draw = f"{{\\an2\\pos(640,715)\\p1\\1c&H000000&\\bord0\\shad0}}m -1280 -{box_height} l 1280 -{box_height} l 1280 10 l -1280 10{{\\p0}}"
                        
                        # Layer 0: Đổ dải đen ra TRƯỚC 1.5s
                        dialogues.append(f"Dialogue: 0,{box_start_ass},{box_end_ass},Default,,0,0,0,,{box_draw}")
                        
                        # Layer 1: Chữ tiếng Việt hiện lên SAU
                        dialogues.append(f"Dialogue: 1,{start_ass},{end_ass},Default,,0,0,0,,{alignment_tag}{text}")
                    else:
                        dialogues.append(f"Dialogue: 1,{start_ass},{end_ass},Default,,0,0,0,,{alignment_tag}{text}")
    
    with open(ass_filename, "w", encoding="utf-8-sig") as f:
        f.write(header + "\n".join(dialogues))
        
    return len(dialogues) > 0

# ==========================================
# BƯỚC 1: TRÍCH XUẤT PHỤ ĐỀ
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
            cleanup_files(temp_video_path, "phu_de_vietsub.srt", "phu_de_vietsub.ass", "video_vietsub_output.mp4")

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

            st.info("⚡ Gemini 3.5 Flash đang quét phụ đề siêu tốc... (Vui lòng đợi vài giây)")

            prompt = """
            Bạn là một hệ thống Cỗ Máy Quét Phụ Đề (OCR) chuyên nghiệp.
            Nhiệm vụ QUAN TRỌNG NHẤT của bạn là ĐỌC BẰNG MẮT TẤT CẢ CÁC CHỮ (hardsub) xuất hiện trên màn hình video.

            QUY TẮC QUÉT CHỮ (TUYỆT ĐỐI TUÂN THỦ):
            1. ƯU TIÊN SỐ 1: Hãy nhìn xuống DƯỚI ĐÁY màn hình, quét từng giây một. BẤT CỨ LÚC NÀO CÓ CHỮ TRUNG QUỐC HIỆN LÊN, bạn BẮT BUỘC phải ghi lại chữ đó và mốc thời gian. TUYỆT ĐỐI KHÔNG ĐƯỢC BỎ SÓT!
            2. VỊ TRÍ CHỮ: 
               - Chữ nằm ở trên đỉnh: Chèn [TOP] vào đầu câu tiếng Trung.
               - Chữ nằm ở giữa: Chèn [MID] vào đầu câu tiếng Trung.
               - Chữ nằm ở dưới đáy: Chèn [BOTTOM] vào đầu câu tiếng Trung.
            3. TRƯỜNG HỢP KHÔNG CÓ CHỮ: Nếu màn hình hoàn toàn trống trơn không có chữ, bạn mới chuyển sang nghe giọng nói để dịch. Chèn [BOTTOM] vào đầu câu gốc.
            
            ĐỊNH DẠNG ĐẦU RA BẮT BUỘC (SRT):
            1
            00:00:01,000 --> 00:00:03,000
            [BOTTOM] Tiếng Trung Gốc
            Bản dịch Tiếng Việt

            (Tuyệt đối không bỏ qua phần Giờ (00:) trong thời gian. Không thêm các giải thích thừa thãi).
            """

            response = model.generate_content([prompt, uploaded_video])
            srt_text = response.text.strip().replace('```srt', '').replace('```', '').strip()

            st.session_state.srt_content = srt_text
            genai.delete_file(uploaded_video.name)
            st.success("Trích xuất phụ đề thành công! Hãy kiểm tra nội dung bên dưới.")

        except Exception as e:
            st.error(f"Đã xảy ra lỗi: {e}")

# ==========================================
# BƯỚC 2: KIỂM TRA -> LỌC & GHÉP VÀO VIDEO
# ==========================================
if st.session_state.srt_content:
    st.divider()
    st.subheader("Bước 2: Đối chiếu Tiếng Trung gốc & Sửa bản dịch Tiếng Việt")
    
    st.markdown("⏱ **Tùy chỉnh Nhịp độ Phụ đề & Nền đen:**")
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        start_offset = st.number_input("⏳ Chữ Tiếng Việt hiện SỚM HƠN (giây):", value=-1.0, step=0.5)
        box_early = st.number_input("⬛ Nền đen trải ra TRƯỚC chữ (giây):", value=1.5, step=0.5, help="Dải đen hiện ra sớm để lót đường che chữ Trung Quốc.")
    with col_t2:
        end_offset = st.number_input("⏳ Chữ Tiếng Việt nán lại LÂU HƠN (giây):", value=2.0, step=0.5)
        box_late = st.number_input("⬛ Nền đen nán lại SAU chữ (giây):", value=0.5, step=0.5, help="Để nền đen không bị biến mất đột ngột khi khoảng cách giữa 2 câu quá ngắn.")
    
    edited_srt = st.text_area(
        label="Nội dung phụ đề (Bạn có thể xem chữ Trung gốc và chỉnh sửa câu tiếng Việt):",
        value=st.session_state.srt_content,
        height=380
    )

    if st.button("🎬 Xác nhận & Ghép Vietsub vào Video"):
        try:
            srt_filename = "phu_de_vietsub.srt"
            ass_filename = "phu_de_vietsub.ass"
            output_video_file = "video_vietsub_output.mp4"

            # Đẩy thời gian cho chữ Tiếng Việt
            adjusted_srt = apply_timing_offsets(edited_srt, start_offset, end_offset)

            with open(srt_filename, "w", encoding="utf-8") as f:
                f.write(filter_only_vietnamese_srt(adjusted_srt))

            # Chuyển tham số thời gian riêng biệt của dải đen vào hàm vẽ
            has_dialogue = create_ass_file(adjusted_srt, ass_filename, display_mode, outline_size, box_early, box_late)

            if not has_dialogue:
                st.error("❌ Cảnh báo: Tool không đọc được mốc thời gian nào hợp lệ.")
            else:
                st.info("🎬 Đang tiến hành ghép Vietsub tiếng Việt vào video...")
                
                ass_abspath = os.path.abspath(ass_filename).replace('\\', '/').replace(':', '\\:')
                
                cmd = [
                    "ffmpeg", "-y", 
                    "-i", st.session_state.temp_video_path, 
                    "-vf", f"subtitles='{ass_abspath}'", 
                    "-c:v", "libx264", 
                    "-c:a", "copy",
                    output_video_file
                ]

                subprocess.run(cmd, check=True)
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

        except subprocess.CalledProcessError as e:
            st.error(f"Lỗi ghép video từ FFmpeg: {e}")
        except Exception as e:
            st.error(f"Lỗi khi ghép phụ đề vào video: {e}")
