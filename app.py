import streamlit as st
import re
import json
import xml.etree.ElementTree as ET
from google import genai
from google.genai import types

st.set_page_config(page_title="AI 숏츠 메이커", page_icon="🎬")

st.title("🎬 YouTube 롱폼 ➔ 9:16 숏츠 메이커")
st.write("유튜브 링크만 넣으면 Gemini가 영상을 직접 분석해 숏츠 구간과 9:16 XML/자막을 생성합니다.")

api_key = st.text_input("Gemini API Key", type="password", help="구글 Gemini API 키를 입력하세요")
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

    # Gemini에 유튜브 링크와 프롬프트를 함께 직접 전달
    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
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

if st.button("🚀 숏츠 구간 추출 및 파일 생성", type="primary"):
    if not api_key:
        st.error("Gemini API 키를 입력해 주세요.")
    elif not youtube_url:
        st.error("유튜브 링크를 입력해 주세요.")
    else:
        with st.spinner("Gemini가 유튜브 영상을 직접 시청하고 분석 중입니다 (약 15~30초 소요)..."):
            try:
                results = analyze_video_with_gemini(youtube_url, api_key)
                st.success("영상 분석 완료!")

                for idx, r in enumerate(results, 1):
                    clean_t = re.sub(r'[^0-9a-zA-Z가-힣\s_-]', '', r['title'])[:15]
                    start = float(r['start_sec'])
                    end = float(r['end_sec'])
                    dur = round(end - start, 1)

                    with st.expander(f"후보 {idx}: {r['title']} ({dur}초)", expanded=True):
                        st.write(f"⏱ **구간:** {int(start//60):02d}:{int(start%60):02d} ~ {int(end//60):02d}:{int(end%60):02d}")
                        st.write(f"💡 **선정 이유:** {r['hook_reason']}")

                        srt_data = generate_srt_content(r.get('subtitles', []))
                        xml_data = generate_xml_content(f"Shorts_{idx}_{clean_t}", start, end)

                        col1, col2 = st.columns(2)
                        with col1:
                            st.download_button(
                                label="📥 9:16 XML 다운로드",
                                data=xml_data,
                                file_name=f"Shorts_{idx}_{clean_t}.xml",
                                mime="application/xml",
                                key=f"xml_{idx}"
                            )
                        with col2:
                            st.download_button(
                                label="📥 싱크 SRT 자막 다운로드",
                                data=srt_data,
                                file_name=f"Shorts_{idx}_{clean_t}.srt",
                                mime="text/plain",
                                key=f"srt_{idx}"
                            )
            except Exception as e:
                st.error(f"분석 중 오류가 발생했습니다: {e}")
