from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
import requests
import base64
import uvicorn
import re
import time
import logging
from omegaconf import OmegaConf

app = FastAPI()

# Load configuration from YAML
config = OmegaConf.load("config.yaml")
MODEL_URL_MAP = dict(config.model_url_map)
SERVER_HOST = config.server.host
SERVER_PORT = config.server.port

logger = logging.getLogger("uvicorn.error")


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/gateway/stt")
async def gateway_stt(
    audio_file: UploadFile = File(...),
    model_name: str = Form("vnp/stt_a1"),
    enhance_speech: bool = Form(True),
    postprocess_text: bool = Form(True),
):
    try:
        # check model_name mapping
        if model_name not in MODEL_URL_MAP:
            raise HTTPException(status_code=400, detail=f"Model '{model_name}' not supported")

        target_url = MODEL_URL_MAP[model_name]

        # vnp/stt_a1: simple forward
        if model_name == "vnp/stt_a1":
            
            audio_bytes = await audio_file.read()

            files = {"audio_file": (audio_file.filename, audio_bytes, audio_file.content_type)}
            data = {
                "model_name": model_name,
                "enhance_speech": str(enhance_speech).lower(),
                "postprocess_text": str(postprocess_text).lower()
            }

            response = requests.post(target_url, files=files, data=data, timeout=300)

            upstream_response = response.json()
            
            # Reorder to match vnp/stt_b1 structure: model_name first
            response_data = {"model_name": model_name}
            response_data.update(upstream_response)

            return JSONResponse(
                status_code=response.status_code,
                content=response_data
            )

        # vnp/stt_b1: special processing
        if model_name == "vnp/stt_b1":

            total_start_time = time.time()

            # speech enhancement timing
            speech_enhancement_start = time.time()
            speech_enhancement_time = None
            enhance_speech = False
            if enhance_speech:
                # placeholder for speech enhancement
                speech_enhancement_time = round((time.time() - speech_enhancement_start) * 1000, 3)

            # read audio bytes
            audio_bytes = await audio_file.read()

            # calculate audio duration (only for MP3 using rough bitrate estimate)
            # for MP3, typical bitrate is 128 kbps, so duration = (bytes * 8) / (128 * 1000)
            audio_duration_ms = None

            # encode base64
            audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")

            # mime type
            mime_type = audio_file.content_type
            if not mime_type:
                filename = (audio_file.filename or "").lower()
                if filename.endswith(".mp3"):
                    mime_type = "audio/mpeg"
                elif filename.endswith(".wav"):
                    mime_type = "audio/wav"
                elif filename.endswith(".m4a"):
                    mime_type = "audio/mp4"
                elif filename.endswith(".ogg"):
                    mime_type = "audio/ogg"
                elif filename.endswith(".flac"):
                    mime_type = "audio/flac"
                elif filename.endswith(".aac"):
                    mime_type = "audio/aac"
                elif filename.endswith(".opus"):
                    mime_type = "audio/opus"
                elif filename.endswith(".webm"):
                    mime_type = "audio/webm"
                else:
                    mime_type = "application/octet-stream"
            else:
                # strip parameters like ;codecs=opus to keep only type/subtype
                mime_type = mime_type.split(";")[0].strip()

            # set duration for MP3 only (others like webm/opus are VBR and need proper probing)
            if mime_type == "audio/mpeg" or (audio_file.filename or "").lower().endswith(".mp3"):
                audio_duration_ms = (len(audio_bytes) * 8) / (128 * 1000) * 1000

            # data url format
            audio_data_url = f"data:{mime_type};base64,{audio_base64}"

            payload = {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "audio_url",
                                "audio_url": {
                                    "url": audio_data_url
                                }
                            }
                        ]
                    }
                ],
                "stream": False
            }

            headers = {
                "accept": "application/json",
                "content-type": "application/json"
            }

            # ASR timing
            asr_start = time.time()
            # Log only the header part of data URL (before comma) and base64 length to reduce noise
            try:
                data_url_header = audio_data_url.split(",", 1)[0]
                logger.info("Audio data URL header: %s, base64_len=%d", data_url_header, len(audio_base64))
            except Exception:
                pass
            logger.info("Posting to %s with headers=%s payload=%s", target_url, headers, payload)
            response = requests.post(
                target_url,
                json=payload,
                headers=headers,
                timeout=300
            )
            try:
                logger.info("Upstream response status=%s body=%s", response.status_code, response.text[:1000])
            except Exception:
                pass
            asr_time = round((time.time() - asr_start) * 1000, 3)

            # extract text from response
            response_data = response.json()
            content = response_data["choices"][0]["message"]["content"]

            # text postprocessing timing
            postprocess_start = time.time()
            # extract text between <asr_text> tags
            match = re.search(r"<asr_text>(.*)", content, re.DOTALL)
            if match:
                transcribed_text = match.group(1).strip()
            else:
                transcribed_text = content
            text_postprocessing_time = round((time.time() - postprocess_start) * 1000, 3)

            total_processing_time = round((time.time() - total_start_time) * 1000, 3)

            result = {
                "model_name": model_name,
                "text": transcribed_text,
                "duration": audio_duration_ms,
                "total_processing_time": total_processing_time,
                "speech_enhancement_time": speech_enhancement_time,
                "asr_time": asr_time,
                "text_postprocessing_time": text_postprocessing_time
            }

            return JSONResponse(content=result)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)