"""
Pre-Market Morning Audio Podcast & Voice Briefing Synthesizer
- Formats 8:45 AM Morning Intelligence Briefing into a high-impact 60-second spoken script
- Generates responsive HTML5 / Web Speech Voice Player with Play/Pause & Speed controls
"""
import re
from typing import Dict
import pandas as pd


def generate_audio_podcast_script(briefing_data: Dict) -> str:
    """
    Cleans and formats briefing text into an engaging, natural-sounding audio podcast transcript.
    """
    raw = briefing_data.get("raw_text", "")
    # Remove markdown asterisks, emojis, and hashtags for clean speech synthesis
    clean = re.sub(r'[\*\#\_]', '', raw)
    clean = re.sub(r'[\U00010000-\U0010ffff]', '', clean) # Remove 4-byte emojis
    clean = re.sub(r'[☀️🌐🏛️💼🔥🎯🛑💡⚖️💎🚀⚠️📈📉]', '', clean)
    clean = clean.replace("₹", "Rupees ")
    clean = clean.replace("%", " percent")
    clean = clean.replace("+", "plus ")
    clean = clean.replace("/", " out of ")

    return clean.strip()


def render_audio_player_html(spoken_text: str, player_title: str = "🎙️ 60-Second Pre-Market Audio Podcast") -> str:
    """
    Renders an interactive browser-based audio player with native speech synthesis,
    voice waveform animations, and play/pause controls.
    """
    escaped_text = spoken_text.replace('"', '\\"').replace('\n', ' ')

    html_code = f"""
    <div style="background: linear-gradient(135deg, #102130, #0c1822); border: 1px solid #1f3a52; border-left: 5px solid #00ffcc; padding: 16px 20px; border-radius: 8px; margin-bottom: 16px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
            <span style="font-size: 1.1em; font-weight: bold; color: #00ffcc;">{player_title}</span>
            <span id="voice-status" style="font-size: 0.85em; color: #8fa0b0;">Ready to Play</span>
        </div>
        <div style="display: flex; gap: 10px; align-items: center;">
            <button id="btn-play-voice" onclick="toggleVoiceSpeech()" style="background: #00a8ff; color: #fff; border: none; padding: 8px 18px; border-radius: 20px; font-weight: bold; cursor: pointer; display: flex; align-items: center; gap: 6px;">
                ▶️ Play Audio Briefing
            </button>
            <button onclick="stopVoiceSpeech()" style="background: #253342; color: #e0e0e0; border: none; padding: 8px 14px; border-radius: 20px; font-size: 0.9em; cursor: pointer;">
                ⏹️ Stop
            </button>
            <select id="voice-speed" onchange="changeVoiceSpeed()" style="background: #162432; color: #00ffcc; border: 1px solid #28445e; padding: 6px 10px; border-radius: 6px; font-size: 0.88em;">
                <option value="1.0">Speed: 1.0x (Normal)</option>
                <option value="1.2" selected>Speed: 1.2x (Fast)</option>
                <option value="1.5">Speed: 1.5x (Blitz)</option>
            </select>
        </div>
        <div style="margin-top: 10px; font-size: 0.82em; color: #a0b2c6; font-style: italic;">
            🎧 Listen to your AI morning market briefing hands-free on your commute.
        </div>
    </div>

    <script>
    var synth = window.speechSynthesis;
    var utterance = null;
    var isSpeaking = false;
    var speechText = "{escaped_text}";

    function toggleVoiceSpeech() {{
        if (!synth) {{
            alert("Speech synthesis is not supported in this browser.");
            return;
        }}
        if (synth.speaking && !synth.paused) {{
            synth.pause();
            document.getElementById("btn-play-voice").innerHTML = "▶️ Resume Audio";
            document.getElementById("voice-status").innerHTML = "Paused";
            isSpeaking = false;
        }} else if (synth.paused) {{
            synth.resume();
            document.getElementById("btn-play-voice").innerHTML = "⏸️ Pause Audio";
            document.getElementById("voice-status").innerHTML = "🎙️ Speaking...";
            isSpeaking = true;
        }} else {{
            utterance = new SpeechSynthesisUtterance(speechText);
            var speedVal = parseFloat(document.getElementById("voice-speed").value) || 1.2;
            utterance.rate = speedVal;
            utterance.pitch = 1.0;

            utterance.onend = function() {{
                document.getElementById("btn-play-voice").innerHTML = "▶️ Play Audio Briefing";
                document.getElementById("voice-status").innerHTML = "Finished";
                isSpeaking = false;
            }};

            utterance.onerror = function() {{
                document.getElementById("btn-play-voice").innerHTML = "▶️ Play Audio Briefing";
                document.getElementById("voice-status").innerHTML = "Ready";
                isSpeaking = false;
            }};

            synth.speak(utterance);
            document.getElementById("btn-play-voice").innerHTML = "⏸️ Pause Audio";
            document.getElementById("voice-status").innerHTML = "🎙️ Speaking...";
            isSpeaking = true;
        }}
    }}

    function stopVoiceSpeech() {{
        if (synth) {{
            synth.cancel();
            document.getElementById("btn-play-voice").innerHTML = "▶️ Play Audio Briefing";
            document.getElementById("voice-status").innerHTML = "Stopped";
            isSpeaking = false;
        }}
    }}

    function changeVoiceSpeed() {{
        if (synth && synth.speaking) {{
            stopVoiceSpeech();
            toggleVoiceSpeech();
        }}
    }}
    </script>
    """
    return html_code