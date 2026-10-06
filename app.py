import streamlit as st
import time
import streamlit.components.v1 as components
import re
import json
import xml.etree.ElementTree as ET
from google import genai
from google.genai import types

st.set_page_config(page_title="AI 숏츠 메이커", page_icon="🎬")

# --- 브라우저 LocalStorage에서 API 키 자동 기억 로직 ---
# 쿼리 파라미터로 저장된 키 읽기
params = st.query_params
saved_key = params.get("key", "")

# 브라우저 localStorage와 주소창 파라미터 동기화용 자바스크립트
components.html(
    f"""
    <script>
    const saved = localStorage.getItem("gemini_api_key");
    const urlParams = new URLSearchParams(window.location.search);
    const currentKey = urlParams.get("key");

    if (saved && !currentKey) {{
        urlParams.set("key", saved);
        window.location.search = urlParams.toString();
    }}
    </script>
    """,
    height=0,
)

st.title("🎬YouTube롱폼 ➔ 9:16 숏츠 메이커")
st.write("유튜브 링크만 넣으면 Gemini가 영상을 직접 분석해 숏츠 구간과 9:16 XML/자막을 생성합니다.")

# 입력창 (기존에 저장된 키가 있으면 기본값으로 자동 채움)
api_key_input = st.text_input(
    "Gemini API Key", 
    value=saved_key, 
    type="password", 
    help="구글 Gemini API 키를 입력하세요. 브라우저에 자동으로 저장되어 다음 접속 시에도 유지됩니다."
)

# 사용자가 키를 새로 입력하거나 변경했을 때 브라우저에 즉시 저장
if api_key_input and api_key_input != saved_key:
    components.html(
        f"""
        <script>
        localStorage.setItem("gemini_api_key", "{api_key_input}");
        const urlParams = new URLSearchParams(window.location.search);
        urlParams.set("key", "{api_key_input}");
        window.location.search = urlParams.toString();
        </script>
        """,
        height=0,
    )

api_key = api_key_input or saved_key

# 💡 API 키 발급 가이드 (접이식)
with st.expander("❓ Gemini API 키는 어디서 무료로 발급받나요? (1분 컷)"):
    st.markdown("""
    1. **[Google AI Studio (클릭)](https://aistudio.google.com/app/apikey)** 에 접속해 구글 계정으로 로그인합니다.
    2. 화면 좌측 또는 상단의 **[Create API key]** 파란색 버튼을 클릭합니다.
    3. 안내창이 뜨면 **[Create API key in new project]** 를 선택합니다.
    4. 생성된 영문+숫자 긴 문자열(키)을 **[Copy]** 하여 위의 입력창에 붙여넣으시면 됩니다.
    
    * **비용 안내:** 신용카드 등록 없이 완전 무료(하루 1,500회)로 사용 가능합니다.
    * **자동 저장:** 한 번 입력해 두시면 브라우저를 껐다 켜도 자동으로 유지됩니다.
    """)

youtube_url = st.text_input("🔗 유튜브 영상 링크")

def analyze_video_with_gemini(yt_url, key):
    client = genai.Client(api_key=key)
    
    prompt = """
    이 유튜브 영상을 분석해서 바이럴 가능성이 높은 30초~55초 길이의 숏츠 구간 3개를 선정해 주세요.
    각 쇼츠 구간마다 해당 구간에서 말하는 대사(자막)와 정확한 타임스탬프(해당 쇼츠 기준 상대 시간, 0초부터 시작)도 함께 생성해야 합니다.

    반드시 아래와 같은 JSON 형식으로만 응답하세요:
    [
      {
        "title": "쇼츠 제목",
        "start_sec": 45.0,
        "end_sec": 92.0,
        "hook_reason": "추천 이유",
        "subtitles": [
          {"start": 0.0, "end": 2.5, "text": "첫 번째 한 줄 자막"},
          {"start": 2.5, "end": 4.8, "text": "두 번째 한 줄 자막"}
        ]
      }
    ]
    * 주의: 자막 텍스트(text)는 숏츠 화면에 맞게 한 줄(10~15자 내외)로 짧고 타격감 있게 끊어주세요.
    """

    candidate_models = [
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash"
    ]
    
    last_err = None
    for model_name in candidate_models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[
                    types.Part.from_uri(file_uri=yt_url, mime_type="video/*"),
                    prompt
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2
                )
            )
            return json.loads(response.text)
        except Exception as e:
            last_err = e
            time.sleep(1)
            continue
            
    raise last_err

def generate_srt_content(subtitles):
    def to_srt_time(sec):
        hrs = int(sec // 3600)
        mins = int((sec % 3600) // 60)
        secs = int(sec % 60)
        msecs = int((sec - int(sec)) * 1000)
        return f"{hrs:02d}:{mins:02d}:{secs:02d},{msecs:03d}"

    output = []
    for idx, item in enumerate(subtitles, 1):
        s_time = to_srt_time(float(item['start']))
        e_time = to_srt_time(float(item['end']))
        txt = item['text'].strip()
        output.append(f"{idx}\n{s_time} --> {e_time}\n{txt}\n")
    return "\n".join(output)

def generate_xml_content(seq_name, start_sec, end_sec, fps=30):
    start_frame = int(start_sec * fps)
    end_frame = int(end_sec * fps)
    dur = end_frame - start_frame

    x_meta = ET.Element("xmeml", version="4")
    seq = ET.SubElement(x_meta, "sequence", id="sequence-1")
    ET.SubElement(seq, "name").text = seq_name
    ET.SubElement(seq, "duration").text = str(dur)
    
    rate = ET.SubElement(seq, "rate")
    ET.SubElement(rate, "timebase").text = str(fps)
    ET.SubElement(rate, "ntsc").text = "FALSE"
    
    media = ET.SubElement(seq, "media")
    video = ET.SubElement(media, "video")
    v_format = ET.SubElement(video, "format")
    sample_char = ET.SubElement(v_format, "samplecharacteristics")
    ET.SubElement(sample_char, "width").text = "1080"
    ET.SubElement(sample_char, "height").text = "1920"

    v_track = ET.SubElement(video, "track")
    clip_v = ET.SubElement(v_track, "clipitem", id="clipitem-video-1")
    ET.SubElement(clip_v, "name").text = seq_name
    ET.SubElement(clip_v, "duration").text = str(dur)
    c_rate = ET.SubElement(clip_v, "rate")
    ET.SubElement(c_rate, "timebase").text = str(fps)
    ET.SubElement(c_rate, "ntsc").text = "FALSE"
    ET.SubElement(clip_v, "in").text = str(start_frame)
    ET.SubElement(clip_v, "out").text = str(end_frame)
    ET.SubElement(clip_v, "start").text = "0"
    ET.SubElement(clip_v, "end").text = str(dur)

    file_elem = ET.SubElement(clip_v, "file", id="source-file-1")
    ET.SubElement(file_elem, "name").text = "source_video.mp4"
    ET.SubElement(file_elem, "pathurl").text = "source_video.mp4"
    f_rate = ET.SubElement(file_elem, "rate")
    ET.SubElement(f_rate, "timebase").text = str(fps)
    ET.SubElement(f_rate, "ntsc").text = "FALSE"
    ET.SubElement(file_elem, "duration").text = str(max(end_frame + 300, 3600 * fps))

    # 오디오 스테레오
    audio = ET.SubElement(media, "audio")
    for ch in [1, 2]:
        a_track = ET.SubElement(audio, "track")
        clip_a = ET.SubElement(a_track, "clipitem", id=f"clipitem-audio-{ch}")
        ET.SubElement(clip_a, "name").text = seq_name
        ET.SubElement(clip_a, "duration").text = str(dur)
        ac_rate = ET.SubElement(clip_a, "rate")
        ET.SubElement(ac_rate, "timebase").text = str(fps)
        ET.SubElement(ac_rate, "ntsc").text = "FALSE"
        ET.SubElement(clip_a, "in").text = str(start_frame)
        ET.SubElement(clip_a, "out").text = str(end_frame)
        ET.SubElement(clip_a, "start").text = "0"
        ET.SubElement(clip_a, "end").text = str(dur)
        ET.SubElement(clip_a, "file", id="source-file-1")

    return ET.tostring(x_meta, encoding="utf-8", xml_declaration=True)

# 세션 상태 초기화 (누적 보관용 리스트)
if "all_shorts" not in st.session_state:
    st.session_state.all_shorts = []

col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 0.5])

with col_btn1:
    btn_start = st.button("🚀 숏츠 구간 최초 추출 (3개)", type="primary", use_container_width=True)

with col_btn2:
    # 기존 결과가 1개 이상 있을 때만 활성화
    btn_more = st.button("➕ 다른 구간 3개 추가 추출", use_container_width=True, disabled=len(st.session_state.all_shorts) == 0)

with col_btn3:
    if st.button("🗑️ 전체 초기화", use_container_width=True):
        st.session_state.all_shorts = []
        st.rerun()

def fetch_shorts(is_additional=False):
    if not api_key:
        st.error("Gemini API 키를 입력해 주세요.")
        return
    if not youtube_url:
        st.error("유튜브 링크를 입력해 주세요.")
        return

    # 이미 뽑았던 구간 리스트를 텍스트로 정리
    excluded_info = ""
    if is_additional and st.session_state.all_shorts:
        ranges = [f"- {int(item['start_sec']//60)}분 {int(item['start_sec']%60)}초 ~ {int(item['end_sec']//60)}분 {int(item['end_sec']%60)}초" for item in st.session_state.all_shorts]
        excluded_info = f"\n\n[중요: 아래 이미 추천된 구간들과 겹치지 않는 완전히 새로운 구간을 뽑아주세요]:\n" + "\n".join(ranges)

    client = genai.Client(api_key=key if 'key' in locals() else api_key)
    prompt = f"""
    이 유튜브 영상을 분석해서 바이럴 가능성이 높은 30초~55초 길이의 숏츠 구간 3개를 선정해 주세요.
    각 쇼츠 구간마다 해당 구간에서 말하는 대사(자막)와 정확한 타임스탬프(해당 쇼츠 기준 상대 시간, 0초부터 시작)도 함께 생성해야 합니다.
    {excluded_info}

    반드시 아래와 같은 JSON 형식으로만 응답하세요:
    [
      {{
        "title": "쇼츠 제목",
        "start_sec": 45.0,
        "end_sec": 92.0,
        "hook_reason": "추천 이유",
        "subtitles": [
          {{"start": 0.0, "end": 2.5, "text": "첫 번째 한 줄 자막"}},
          {{"start": 2.5, "end": 4.8, "text": "두 번째 한 줄 자막"}}
        ]
      }}
    ]
    * 주의: 자막 텍스트(text)는 숏츠 화면에 맞게 한 줄(10~15자 내외)로 짧고 타격감 있게 끊어주세요.
    """

    candidate_models = [
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash"
    ]

    spinner_text = "이전 구간을 제외하고 새로운 구간 3개를 탐색 중입니다..." if is_additional else "Gemini가 유튜브 영상을 시청하고 분석 중입니다..."
    with st.spinner(spinner_text):
        last_err = None
        for model_name in candidate_models:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=[
                        types.Part.from_uri(file_uri=youtube_url, mime_type="video/*"),
                        prompt
                    ],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.3
                    )
                )
                new_results = json.loads(response.text)
                
                if is_additional:
                    st.session_state.all_shorts.extend(new_results)
                else:
                    st.session_state.all_shorts = new_results
                    
                st.success("분석 완료!")
                return
            except Exception as e:
                last_err = e
                time.sleep(1)
                continue
        st.error(f"분석 중 오류가 발생했습니다: {last_err}")

if btn_start:
    fetch_shorts(is_additional=False)

if btn_more:
    fetch_shorts(is_additional=True)

# 누적된 쇼츠 결과 출력
if st.session_state.all_shorts:
    st.write(f"### 📋 생성된 숏츠 후보 (총 {len(st.session_state.all_shorts)}개)")
    
    for idx, r in enumerate(st.session_state.all_shorts, 1):
        clean_t = re.sub(r'[^0-9a-zA-Z가-힣\s_-]', '', r['title'])[:15]
        start = float(r['start_sec'])
        end = float(r['end_sec'])
        dur = round(end - start, 1)

        with st.expander(f"후보 {idx}: {r['title']} ({dur}초)", expanded=(idx > len(st.session_state.all_shorts) - 3)):
            st.write(f"⏱ **구간:** {int(start//60):02d}:{int(start%60):02d} ~ {int(end//60):02d}:{int(end%60):02d}")
            st.write(f"💡 **선정 이유:** {r['hook_reason']}")

            srt_data = generate_srt_content(r.get('subtitles', []))
            xml_data = generate_xml_content(f"Shorts_{idx}_{clean_t}", start, end)

            c1, c2 = st.columns(2)
            with c1:
                st.download_button(
                    label="📥 9:16 XML 다운로드",
                    data=xml_data,
                    file_name=f"Shorts_{idx}_{clean_t}.xml",
                    mime="application/xml",
                    key=f"xml_btn_{idx}_{start}"
                )
            with c2:
                st.download_button(
                    label="📥 싱크 SRT 자막 다운로드",
                    data=srt_data,
                    file_name=f"Shorts_{idx}_{clean_t}.srt",
                    mime="text/plain",
                    key=f"srt_btn_{idx}_{start}"
                )
