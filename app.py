import streamlit as st
import yt_dlp
import os
import google.generativeai as genai
import time
import re
import subprocess
import pandas as pd

st.set_page_config(page_title="Auto Vietsub & Dubbing Studio", page_icon="🎬", layout="wide")
st.title("🎬 Studio Vietsub & Lồng Tiếng Phim Trung Quốc")
st.write("Quét phụ đề siêu tốc, chống tràn viền & Ghép Audio tự động như CapCut")

# Tạo thư mục lưu trữ video vĩnh viễn
OUTPUT_DIR = "output_videos"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

def get_saved_videos():
    if not os.path.exists(OUTPUT_DIR):
        return []
    files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith('.mp4')]
    files.sort(key=lambda x: os.path.getmtime(os.path.join(OUTPUT_DIR, x)), reverse=True)
    return files

# Nhập API Key chung cho cả 2 Tab
api_key = st.text_input("🔑 Nhập Gemini API Key của bạn:", type="password")
st.divider()

# --- CÁC HÀM XỬ LÝ CHUNG ---
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

def wrap_text_for_ass(text, font_size):
    max_chars = int(1100 / (font_size * 0.65)) 
    words = text.split()
    lines = []
    current_line = []
    current_len = 0
    for word in words:
        if current_len + len(word) > max_chars and current_line:
            lines.append(" ".join(current_line))
            current_line = [word]
            current_len = len(word)
        else:
            current_line.append(word)
            current_len += len(word) + 1
    if current_line:
        lines.append(" ".join(current_line))
    return lines

def create_ass_file(srt_text, ass_filename, display_mode, outline_size, font_size):
    srt_text = srt_text.replace('\r', '')
    blocks = re.split(r'\n\s*\n', srt_text.strip())
    
    border_style = "3"       
    box_color = "&H00000000" 
    
    if display_mode == "Che đè lên chữ gốc (Tạo hộp đen)":
        margin_v = "15"
    else:
        margin_v = "75" 
        border_style = "1"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 1

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H00000000,{box_color},{box_color},1,0,0,0,100,100,0,0,{border_style},{outline_size},0,2,10,10,{margin_v},1

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
                    wrapped_lines = wrap_text_for_ass(text, font_size)
                    if display_mode == "Che đè lên chữ gốc (Tạo hộp đen)":
                        padded_lines = [r"\h\h\h\h" + line + r"\h\h\h\h" for line in wrapped_lines]
                        final_text = r"\N".join(padded_lines)
                    else:
                        final_text = r"\N".join(wrapped_lines)
                    dialogues.append(f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{alignment_tag}{final_text}")
    
    with open(ass_filename, "w", encoding="utf-8-sig") as f:
        f.write(header + "\n".join(dialogues))
    return len(dialogues) > 0

def time_to_ms(time_str):
    time_str = time_str.replace(',', '.')
    parts = time_str.split(':')
    if len(parts) == 3:
        h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
    elif len(parts) == 2:
        h, m, s = 0, int(parts[0]), float(parts[1])
    else:
        return 0
    return int((h * 3600 + m * 60 + s) * 1000)

def parse_srt_to_dict(srt_text):
    blocks = re.split(r'\n\s*\n', srt_text.strip())
    parsed = []
    for idx, block in enumerate(blocks):
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            time_match = re.match(r'((?:\d{1,2}:)?\d{1,2}:\d{1,2}(?:[,\.]\d{1,3})?)\s*-->\s*((?:\d{1,2}:)?\d{1,2}:\d{1,2}(?:[,\.]\d{1,3})?)', lines[1].strip())
            if time_match:
                zh_text = re.sub(r'\[(TOP|MID|BOTTOM)\]\s*', '', lines[-2].strip(), flags=re.IGNORECASE)
                vi_text = re.sub(r'\[(TOP|MID|BOTTOM)\]\s*', '', lines[-1].strip(), flags=re.IGNORECASE)
                parsed.append({
                    "id": idx + 1,
                    "time": lines[1].strip(),
                    "start_ms": time_to_ms(time_match.group(1)),
                    "zh": zh_text,
                    "vi": vi_text
                })
    return parsed

# TẠO 2 TABS
tab1, tab2 = st.tabs(["🎬 Tự Động Vietsub (Tiêu Chuẩn)", "🎙️ CapCut Studio (Lồng Tiếng & Audio)"])

# ==========================================
# TAB 1: AUTO VIETSUB (GIỮ NGUYÊN)
# ==========================================
with tab1:
    if "t1_srt_content" not in st.session_state:
        st.session_state.t1_srt_content = ""
    if "t1_temp_video_path" not in st.session_state:
        st.session_state.t1_temp_video_path = ""

    st.subheader("⚙️ Tùy chọn hiển thị & Kích thước")
    col_opt1, col_opt2 = st.columns(2)
    with col_opt1:
        t1_display_mode = st.radio("Cách hiển thị phụ đề:", ("Che đè lên chữ gốc (Tạo hộp đen)", "Nổi bên trên chữ gốc (Không che)"), key="t1_mode")
    with col_opt2:
        t1_font_size = st.number_input("🔠 Cỡ chữ Tiếng Việt:", min_value=10, max_value=100, value=28, step=2, key="t1_font")
        t1_outline_size = st.number_input("⬛ Độ to của hộp đen nền:", min_value=0, max_value=50, value=2, step=1, key="t1_outline")

    st.subheader("🎵 Lách bản quyền âm thanh")
    t1_audio_option = st.radio("Xử lý âm thanh gốc:",("Giữ nguyên âm thanh", "Đổi Tone/Méo tiếng nhẹ", "Tắt hoàn toàn âm thanh"), key="t1_audio")

    st.divider()
    st.subheader("📹 Chọn nguồn video")
    t1_option = st.radio("Cách tải video:", ("Tải tệp video từ máy", "Dán link Douyin/Xiaohongshu"), key="t1_opt")

    t1_uploaded = None
    t1_raw_link = ""
    if t1_option == "Tải tệp video từ máy":
        t1_uploaded = st.file_uploader("Chọn video:", type=["mp4", "mov", "mkv", "avi", "webm"], key="t1_up")
    else:
        t1_raw_link = st.text_input("Nhập link video:", key="t1_link")

    if st.button("🚀 Bắt đầu phân tích Video & Dịch", key="t1_btn1"):
        if not api_key:
            st.error("Vui lòng nhập API Key!")
        else:
            try:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel('gemini-3.5-flash')
                temp_video = "t1_temp.mp4"
                cleanup_files(temp_video, "t1_sub.srt", "t1_sub.ass")

                if t1_option == "Tải tệp video từ máy" and t1_uploaded:
                    with open(temp_video, "wb") as f:
                        f.write(t1_uploaded.getbuffer())
                elif t1_raw_link:
                    clean_url = extract_clean_url(t1_raw_link)
                    with yt_dlp.YoutubeDL({'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best', 'outtmpl': temp_video, 'quiet': True}) as ydl:
                        ydl.download([clean_url])
                
                st.session_state.t1_temp_video_path = temp_video
                st.info("Đang tải Video lên AI...")
                uploaded_v = genai.upload_file(path=temp_video)
                while uploaded_v.state.name == "PROCESSING":
                    time.sleep(3)
                    uploaded_v = genai.get_file(uploaded_v.name)

                st.info("⚡ AI đang quét...")
                prompt = """Bạn là Cỗ Máy OCR. ĐỌC CHỮ TRÊN MÀN HÌNH VÀ NGHE ÂM THANH.
                1. KHÔNG GỘP CÂU. 
                2. Dòng tiếng Việt KHÔNG QUÁ 15 TỪ.
                3. Đánh dấu [TOP], [MID], [BOTTOM] đầu câu tiếng Trung.
                Định dạng SRT:
                1
                00:00:01,000 --> 00:00:03,000
                [BOTTOM] Tiếng Trung
                Tiếng Việt"""
                
                res = model.generate_content([prompt, uploaded_v])
                st.session_state.t1_srt_content = res.text.strip().replace('```srt', '').replace('```', '').strip()
                genai.delete_file(uploaded_v.name)
                st.success("Xong!")
            except Exception as e:
                st.error(f"Lỗi: {e}")

    if st.session_state.t1_srt_content:
        st.divider()
        col_t1, col_t2 = st.columns(2)
        with col_t1: t1_s_off = st.number_input("⏳ Sớm hơn (s):", value=-0.1, step=0.1, key="t1_s_off")
        with col_t2: t1_e_off = st.number_input("⏳ Nán lại (s):", value=0.5, step=0.1, key="t1_e_off")
        
        t1_edited = st.text_area("Chỉnh sửa phụ đề:", value=st.session_state.t1_srt_content, height=300, key="t1_area")
        
        if st.button("🎬 Xác nhận & Ghép Vietsub", key="t1_btn2"):
            ts = int(time.time())
            out_vid = os.path.join(OUTPUT_DIR, f"vid_t1_{ts}.mp4")
            adj_srt = apply_timing_offsets(t1_edited, t1_s_off, t1_e_off)
            
            with open("t1_sub.srt", "w", encoding="utf-8") as f:
                f.write(filter_only_vietnamese_srt(adj_srt))
            create_ass_file(adj_srt, "t1_sub.ass", t1_display_mode, t1_outline_size, t1_font_size)
            
            cmd = ["ffmpeg", "-y", "-i", st.session_state.t1_temp_video_path, "-vf", "subtitles=t1_sub.ass", "-c:v", "libx264"]
            if t1_audio_option == "Tắt hoàn toàn âm thanh": cmd.append("-an")
            elif t1_audio_option == "Đổi Tone/Méo tiếng nhẹ": cmd.extend(["-af", "asetrate=44100*1.05,aresample=44100,atempo=1/1.05", "-c:a", "aac"])
            else: cmd.extend(["-c:a", "copy"])
            cmd.append(out_vid)
            
            subprocess.run(cmd, check=True)
            st.success("Xong!")
            st.rerun()

# ==========================================
# TAB 2: STUDIO LỒNG TIẾNG (DUBBING)
# ==========================================
with tab2:
    if "t2_srt_content" not in st.session_state:
        st.session_state.t2_srt_content = ""
    if "t2_temp_video_path" not in st.session_state:
        st.session_state.t2_temp_video_path = ""

    st.subheader("1️⃣ Chọn Nguồn Video")
    t2_vsource = st.radio("Lấy video từ đâu?", ("Chọn video đã lưu ở Tab 1", "Tải video mới từ máy"), key="t2_vsrc")
    
    t2_selected_vid = None
    t2_uploaded = None
    if t2_vsource == "Chọn video đã lưu ở Tab 1":
        saved = get_saved_videos()
        if saved:
            t2_selected_vid = st.selectbox("Chọn video trong thư viện:", saved, key="t2_sel")
        else:
            st.warning("Chưa có video nào trong thư viện. Vui lòng tải mới.")
    else:
        t2_uploaded = st.file_uploader("Tải video lên:", type=["mp4", "mov"], key="t2_up")

    st.subheader("2️⃣ Quét Phụ Đề Gốc (Chỉ đọc chữ)")
    if st.button("🚀 Quét Phụ Đề (OCR)", key="t2_btn1"):
        if not api_key:
            st.error("Nhập API Key trước!")
        else:
            try:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel('gemini-3.5-flash')
                temp_video = "t2_temp.mp4"
                
                if t2_vsource == "Chọn video đã lưu ở Tab 1" and t2_selected_vid:
                    import shutil
                    shutil.copy(os.path.join(OUTPUT_DIR, t2_selected_vid), temp_video)
                elif t2_vsource == "Tải video mới từ máy" and t2_uploaded:
                    with open(temp_video, "wb") as f:
                        f.write(t2_uploaded.getbuffer())
                
                st.session_state.t2_temp_video_path = temp_video
                st.info("Đang tải Video lên AI...")
                uploaded_v = genai.upload_file(path=temp_video)
                while uploaded_v.state.name == "PROCESSING":
                    time.sleep(3)
                    uploaded_v = genai.get_file(uploaded_v.name)

                st.info("⚡ Đang quét Text (Không nghe âm thanh)...")
                prompt = """Bạn là Cỗ Máy OCR. CHỈ ĐỌC CHỮ TRÊN MÀN HÌNH, BỎ QUA HOÀN TOÀN ÂM THANH.
                1. KHÔNG GỘP CÂU.
                2. Dòng dịch tiếng Việt ngắn gọn.
                Định dạng SRT chuẩn:
                1
                00:00:01,000 --> 00:00:03,000
                [BOTTOM] Tiếng Trung
                Tiếng Việt"""
                
                res = model.generate_content([prompt, uploaded_v])
                st.session_state.t2_srt_content = res.text.strip().replace('```srt', '').replace('```', '').strip()
                genai.delete_file(uploaded_v.name)
                st.success("Xong Bước 2!")
            except Exception as e:
                st.error(f"Lỗi: {e}")

    if st.session_state.t2_srt_content:
        st.divider()
        st.subheader("3️⃣ Chỉnh sửa Dịch thuật & Tải Audio")
        
        t2_edited = st.text_area("Bảng 1: Sửa chữ & Thời gian (SRT):", value=st.session_state.t2_srt_content, height=250, key="t2_area")
        
        st.info("Bảng 2: Tải lên các file Audio lồng tiếng (Tên file theo thứ tự vd: 1.mp3, 2.mp3...). Tool sẽ tự khớp với các câu dịch ở trên.")
        t2_audios = st.file_uploader("Tải lên danh sách Audio lồng tiếng:", type=["mp3", "wav", "m4a"], accept_multiple_files=True, key="t2_audios")
        
        st.subheader("4️⃣ Bảng Tổng Hợp & Mix Âm Thanh")
        
        if st.button("🔄 Tạo Bảng Kết Hợp"):
            parsed_data = parse_srt_to_dict(t2_edited)
            sorted_audios = sorted(t2_audios, key=lambda x: x.name) if t2_audios else []
            
            table_data = []
            for i, item in enumerate(parsed_data):
                audio_name = sorted_audios[i].name if i < len(sorted_audios) else "Không có audio"
                table_data.append({
                    "Thời gian": item['time'],
                    "Tiếng Trung": item['zh'],
                    "Tiếng Việt": item['vi'],
                    "File Lồng tiếng": audio_name
                })
            
            df = pd.DataFrame(table_data)
            st.table(df)
            
        st.markdown("**🔊 Tùy chỉnh Âm lượng & Phụ đề:**")
        col_v1, col_v2 = st.columns(2)
        with col_v1:
            orig_vol = st.slider("Âm lượng Video Gốc (%) - Làm nhạc nền", 0, 100, 10)
        with col_v2:
            dub_vol = st.slider("Âm lượng Giọng Lồng Tiếng (%)", 0, 200, 100)
            
        col_v3, col_v4 = st.columns(2)
        with col_v3:
            t2_display_mode = st.radio("Hiển thị Sub:", ("Che đè lên chữ gốc (Tạo hộp đen)", "Nổi bên trên chữ gốc (Không che)"), key="t2_mode")
        with col_v4:
            t2_font = st.number_input("Cỡ chữ:", value=28, key="t2_font")
            t2_outline = st.number_input("Hộp đen:", value=2, key="t2_outline")

        if st.button("🎬 KẾT HỢP & XUẤT VIDEO LỒNG TIẾNG", type="primary"):
            try:
                st.info("Đang xử lý Audio và Video...")
                parsed_data = parse_srt_to_dict(t2_edited)
                sorted_audios = sorted(t2_audios, key=lambda x: x.name) if t2_audios else []
                
                ts = int(time.time())
                out_vid = os.path.join(OUTPUT_DIR, f"dubbed_{ts}.mp4")
                
                # Tạo file phụ đề
                create_ass_file(t2_edited, "t2_sub.ass", t2_display_mode, t2_outline, t2_font)
                ass_abspath = os.path.abspath("t2_sub.ass").replace('\\', '/').replace(':', '\\:')
                
                # Cấu trúc lệnh FFmpeg
                cmd = ["ffmpeg", "-y", "-i", st.session_state.t2_temp_video_path]
                
                mapped_count = min(len(parsed_data), len(sorted_audios))
                
                if mapped_count == 0:
                    # Nếu không có audio nào, chỉ ghép sub và chỉnh âm gốc
                    cmd.extend([
                        "-vf", f"subtitles='{ass_abspath}'",
                        "-filter:a", f"volume={orig_vol/100.0}",
                        "-c:v", "libx264", "-c:a", "aac", out_vid
                    ])
                else:
                    filter_complex = f"[0:a]volume={orig_vol/100.0}[orig_a];"
                    mix_inputs = "[orig_a]"
                    
                    for i in range(mapped_count):
                        audio_file = sorted_audios[i]
                        temp_a_path = f"t2_temp_audio_{i}.mp3"
                        with open(temp_a_path, "wb") as f:
                            f.write(audio_file.read())
                        cmd.extend(["-i", temp_a_path])
                        
                        delay_ms = parsed_data[i]['start_ms']
                        idx = i + 1
                        # normalize=0 giữ nguyên âm lượng không bị giảm khi mix nhiều track
                        filter_complex += f"[{idx}:a]adelay={delay_ms}|{delay_ms},volume={dub_vol/100.0}[a{idx}];"
                        mix_inputs += f"[a{idx}]"
                        
                    filter_complex += f"{mix_inputs}amix=inputs={mapped_count+1}:duration=first:normalize=0[aout]"
                    
                    cmd.extend([
                        "-filter_complex", filter_complex,
                        "-map", "0:v", "-map", "[aout]",
                        "-vf", f"subtitles='{ass_abspath}'",
                        "-c:v", "libx264", "-c:a", "aac", out_vid
                    ])
                
                subprocess.run(cmd, check=True)
                st.success("🎉 Xuất Video Lồng Tiếng Thành Công!")
                st.rerun()
            except Exception as e:
                st.error(f"Lỗi render: {e}")

# ==========================================
# BƯỚC 3: QUẢN LÝ LỊCH SỬ VIDEO ĐÃ TẠO
# ==========================================
st.divider()
st.subheader("📁 Thư Viện Video Đã Xuất")

saved_videos = get_saved_videos()
if saved_videos:
    for vid_file in saved_videos:
        vid_path = os.path.join(OUTPUT_DIR, vid_file)
        col_name, col_dl, col_del = st.columns([6, 2, 2])
        with col_name:
            st.write(f"🎥 **{vid_file}**")
        with col_dl:
            with open(vid_path, "rb") as f:
                st.download_button("⬇️ Tải", data=f, file_name=vid_file, mime="video/mp4", key=f"dl_{vid_file}")
        with col_del:
            if st.button("❌ Xóa", key=f"del_{vid_file}"):
                os.remove(vid_path)
                st.rerun()
else:
    st.info("Chưa có video nào được lưu.")
