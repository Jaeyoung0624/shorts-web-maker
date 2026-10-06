import streamlit as st
import os
import re
import json
import io
import xml.etree.ElementTree as ET
from youtube_transcript_api import YouTubeTranscriptApi
from google import genai
from google.genai import types

st.set_page_config(page_title="AI 숏츠 메이커", page_icon="🎬")

st.title("🎬 YouTube 롱폼 ➔ 9:16 숏츠 메이커")
st.write("유튜브 링크를 넣으면 AI가 바이럴 구간을 뽑고, 프리미어용 9:16 XML과 SRT 자막을 만들어줍니다.")

# 사이드바 또는 설정에서 API 키 입력
api_key = st.text_input("Gemini API Key", type="password", help="발급받은 구글 Gemini API 키를 입력하세요")
youtube_url = st.text_input("🔗 유튜브 영상 링크")

def extract_video_id(url):
    match = re.search(r"(?:v=|\/|youtu\.be\/)([0-9A-Za-z_-]{11})", url)
    return match.group(1) if match else None

def get_transcript(video_id):
    try:
        ytt = YouTubeTranscriptApi()
        try:
            fetched = ytt.fetch(video_id, languages=['ko', 'en'])
            transcript_list = fetched.to_raw_data()
        except AttributeError:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['ko', 'en'])
    except Exception as e:
        return None, None

    transcript_text = ""
    subtitles = []
    for item in transcript_list:
        start = round(item['start'], 2)
        end = round(item['start'] + item['duration'], 2)
        text = item['text'].replace("\n", " ").strip()
        subtitles.append({"start": start, "end": end, "text": text})
        transcript_text += f"[{round(start, 1)}s - {round(end, 1)}s] {text}\n"
    return transcript_text, subtitles

def analyze_shorts(transcript_text, key):
    client = genai.Client(api_key=key)
    prompt = f"""
    당신은 전문 유튜브 숏츠 편집자입니다.
    아래 대본을 보고 시청자의 흥미를 끌 수 있는 30초~55초 사이의 완결성 있는 숏츠 후보 3개를 선정하세요.
    [대본]
    {transcript_text}
    반드시 아래 JSON 포맷으로만 응답하세요:
    [
      {{"title": "쇼츠 제목", "start_sec": 시작_초, "end_sec": 종료_초, "hook_reason": "추천 이유"}}
    ]
    """
    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.3
        )
    )
    return json.loads(response.text)

def generate_srt_content(subtitles, start_sec, end_sec):
    def to_srt_time(sec):
        hrs = int(sec // 3600)
        mins = int((sec % 3600) // 60)
        secs = int(sec % 60)
        msecs = int((sec - int(sec)) * 1000)
        return f"{hrs:02d}:{mins:02d}:{secs:02d},{msecs:03d}"

    matched = [s for s in subtitles if s['end'] >= start_sec and s['start'] <= end_sec]
    output = []
    prev_text = ""
    counter = 1

    for item in matched:
        raw_text = item['text'].strip()
        if prev_text and raw_text.startswith(prev_text):
            cur = raw_text[len(prev_text):].strip()
        elif prev_text and prev_text in raw_text:
            cur = raw_text.replace(prev_text, "").strip()
        else:
            cur = raw_text
        if not cur:
            continue
        rel_start = max(0.0, item['start'] - start_sec)
        rel_end = max(rel_start + 0.5, item['end'] - start_sec)
        output.append(f"{counter}\n{to_srt_time(rel_start)} --> {to_srt_time(rel_end)}\n{cur}\n")
        prev_text = raw_text
        counter += 1
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
        v_id = extract_video_id(youtube_url)
        with st.spinner("자막 추출 및 하이라이트 분석 중..."):
            transcript, subs = get_transcript(v_id)
            if not transcript:
                st.error("자막을 불러오지 못했습니다. 자막이 지원되는 영상인지 확인해 주세요.")
            else:
                results = analyze_shorts(transcript, api_key)
                st.success("분석 완료!")

                for idx, r in enumerate(results, 1):
                    clean_t = re.sub(r'[^0-9a-zA-Z가-힣\s_-]', '', r['title'])[:15]
                    start = float(r['start_sec'])
                    end = float(r['end_sec'])
                    dur = round(end - start, 1)

                    with st.expander(f"후보 {idx}: {r['title']} ({dur}초)", expanded=True):
                        st.write(f"⏱ **구간:** {int(start//60):02d}:{int(start%60):02d} ~ {int(end//60):02d}:{int(end%60):02d}")
                        st.write(f"💡 **선정 이유:** {r['hook_reason']}")

                        srt_data = generate_srt_content(subs, start, end)
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