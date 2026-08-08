# Portable Chatterbox media routes

`portable_media.py` extends the Chatterbox FastAPI service with only the two
OS-heavy operations that n8n cannot perform natively:

- `POST /v1/audio/assemble-six` — ordered six-file decode, concatenate,
  loudness-normalize, and encode.
- `POST /v1/audio/objective-qa` — duration, integrated loudness, true peak,
  clipping, and long-silence metrics.

The n8n graph still owns six separate TTS requests, validation, branching,
Whisper, subtitles, persistence, distribution, and notifications. Deployment
copies this module beside `server.py` and adds:

```python
from portable_media import router as portable_media_router
app.include_router(portable_media_router)
```

The endpoints are stateless and use per-request temporary directories. No
podcast artifacts survive on the voice host after a response is returned.
