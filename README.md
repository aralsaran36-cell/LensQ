# LensQ

**Private Image Question Answering for Mobile Browsers**

LensQ is a privacy-focused image question-answering application that allows users to upload or capture an image, ask questions about its contents, and receive text-based answers powered by **LiquidAI/LFM3-Omni-2B** running on a self-hosted server.

Images are processed temporarily in server memory and are never stored permanently.

## Features

- **Image Input:** Upload images from the device gallery or capture photos using the mobile browser camera.
- **Visual Question Answering:** Ask questions about an uploaded image and receive plain-text responses.
- **Follow-up Questions:** Continue asking questions without uploading the image again.
- **Privacy-focused Processing:** Images are stored temporarily in server memory.
- **Session Management:** Automatically expire inactive sessions and remove images when requested.
- **Responsive Interface:** Mobile-first design with dark and light themes.
- **Input Validation:** Questions must contain between 3 and 500 characters.
- **Image Restrictions:** Supports one image per session with a maximum upload size of 5 MB.
- **Self-hosted Inference:** Model inference runs on your own server.

## Privacy and Security

LensQ is designed to minimize the storage and exposure of user data.

- Images are stored exclusively in server memory.
- No images or user conversations are written to permanent storage.
- Sessions are automatically removed after 10 minutes of inactivity.
- Users can manually terminate sessions using the Remove Image action.
- Browser-side image processing converts images to JPEG and removes EXIF metadata, including GPS information.
- Server-side image processing performs an additional image re-encoding step.
- Application logs contain only explicitly approved fields.
- Images, questions, answers, and complete session identifiers are excluded from logs.
- Error responses do not expose user-submitted content.
- The AI model runs locally on the configured server rather than relying on a third-party inference API.

**Note:** Temporary image processing still involves server memory usage. Network traffic through external tunnels or reverse proxies may pass through those providers.

## Technology Stack

| Component | Technology |
|---|---|
| Programming Language | Python 3.11 |
| Backend Framework | FastAPI |
| ASGI Server | Uvicorn |
| Data Validation | Pydantic, Pydantic Settings |
| Image Processing | Pillow, pillow-heif |
| Media Processing | FFmpeg (fallback) |
| HTTP Client | httpx |
| AI Model | LiquidAI/LFM3-Omni-2B |
| Model Integration | Transformers / llama.cpp |
| Frontend | HTML, CSS, JavaScript |
| Session Storage | In-memory |
| Testing | pytest |
| Reverse Proxy | Nginx |
| Deployment Security | HTTPS |

## Project Structure

```text
LensQ/
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
│
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── requirements.txt
│   │
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── health.py
│   │   └── analyze.py
│   │
│   ├── schemas/
│   │   └── analyze.py
│   │
│   ├── services/
│   │   ├── model_service.py
│   │   ├── image_service.py
│   │   └── session_store.py
│   │
│   └── utils/
│       ├── validators.py
│       └── logger.py
│
├── tests/
├── deploy/
│   └── nginx.conf
│
├── .env.example
└── README.md
```

## Installation and Setup

### Prerequisites

- Python 3.11
- Git
- FFmpeg (optional fallback)
- llama.cpp or a compatible GPU environment for real model inference

### 1. Clone the Repository

```bash
git clone <repository-url>
cd LensQ
```

### 2. Create a Virtual Environment

```bash
python3.11 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r backend/requirements.txt
```

### 4. Configure Environment Variables

```bash
cp .env.example .env
```

Configure the required application and model settings in `.env`.

**Platform note:** On Intel-based Macs, PyTorch and Transformers are skipped automatically because the required PyTorch version is unavailable. Use the `mock` or `llamacpp` backend on these machines.

Activate the virtual environment whenever you open a new terminal:

```bash
cd /path/to/LensQ
source venv/bin/activate
```

## Model Configuration

LensQ supports three model backends.

| Backend | Purpose | Description |
|---|---|---|
| `mock` | Development and testing | Returns simulated responses without performing image analysis. |
| `llamacpp` | Local inference | Runs a quantized model through a local llama.cpp server. |
| `transformers` | GPU deployment | Loads the model using the Transformers framework. |

Configure the backend using the `MODEL_BACKEND` environment variable.

### 1. Mock Backend

Use this backend to validate frontend and backend functionality without loading the actual AI model.

```bash
MODEL_BACKEND=mock uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Access the application:

```text
http://127.0.0.1:8000
```

Responses are prefixed with `[MOCK ANSWER]`.

### 2. llama.cpp Backend

**Requirements:**
- llama.cpp b11960 or newer.
- Approximately 1.9 GB of initial model download space.

Start the model server:

```bash
llama serve -hf LiquidAI/LFM3-Omni-2B-GGUF:Q4_K_M --reasoning off --temp 0 --port 8080
```

Verify model server availability:

```bash
curl -s http://localhost:8080/health
```

Expected response:

```json
{"status":"ok"}
```

Start LensQ in a separate terminal:

```bash
MODEL_BACKEND=llamacpp uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Verify application health:

```bash
curl -s http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok","app":"LensQ","model_loaded":true}
```

If the model server is unavailable when LensQ starts, restart LensQ after starting the model server.

**Performance:** CPU inference may take approximately 15–60 seconds per request, depending on hardware and image complexity.

### 3. Transformers Backend

Use this backend for GPU-based deployment.

Requirements:

- Compatible GPU hardware.
- Supported PyTorch installation.
- Transformers 5.20.2 or newer.

Start the application:

```bash
MODEL_BACKEND=transformers TMPDIR=/dev/shm uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers
```

**Deployment considerations:**

- Use a single Uvicorn worker because session data is maintained in process memory.
- Pin the model revision when using `trust_remote_code`.
- Configure sufficient GPU memory for model loading and inference.

## Mobile Browser Testing

Mobile browsers require HTTPS access for camera functionality.

For local mobile testing, Cloudflare Quick Tunnels can provide a temporary HTTPS endpoint.

### 1. Install cloudflared

macOS using Homebrew:

```bash
brew install cloudflared
```

For Intel Macs where Homebrew installation is problematic:

```bash
cd ~

curl -L -o cloudflared.tgz \
https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz

tar -xzf cloudflared.tgz
chmod +x cloudflared

./cloudflared --version
```

For Apple Silicon, use the `cloudflared-darwin-arm64.tgz` binary.

### 2. Start the Tunnel

Ensure that both the model server and LensQ application are running.

Open a third terminal:

```bash
~/cloudflared tunnel --url http://127.0.0.1:8000
```

Cloudflare generates a temporary HTTPS URL:

```text
https://<random-subdomain>.trycloudflare.com
```

Open this URL on your mobile device.

### 3. Mobile Testing Workflow

1. Open the HTTPS URL in Chrome or Safari.
2. Grant camera permissions when prompted.
3. Capture a photo or upload an image from the gallery.
4. Enter a question about the image.
5. Submit the question using the Ask button.
6. Wait for the model response.
7. Submit follow-up questions without uploading the image again.
8. Test image replacement and session termination.

**Security warning:** Quick Tunnel traffic passes through Cloudflare infrastructure. Use only non-sensitive sample images during testing. Do not upload personal photographs, identification documents, or confidential information.

**Limitations:** Quick Tunnels are temporary, and connections may time out after approximately 100 seconds. Use smaller images to reduce upload time.

### 4. Camera Permission Troubleshooting

If camera access is denied:

- Verify that the application is accessed over HTTPS.
- Use a standard mobile browser instead of an in-app browser.
- Check the browser's site permissions.
- Enable camera access in the device or browser settings.
- Use the Upload Image option as an alternative.

## API Documentation

LensQ exposes the following REST API endpoints.

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Returns application and model health status. |
| POST | `/analyze` | Analyzes an image and answers user questions. |
| POST | `/session/end` | Terminates an active session. |

### Image Analysis

**Endpoint:** `POST /analyze`

**Content-Type:** `multipart/form-data`

| Parameter | Type | Required | Description |
|---|---|---|---|
| `question` | String | Yes | User's question about the image. |
| `session_id` | String | No | Existing session identifier. |
| `image` | File | Conditional | Image required for a new session or image replacement. |

**Supported request scenarios:**

1. **Initial analysis:** Submit an image and question.
2. **Follow-up analysis:** Submit a question and existing `session_id`.
3. **Image replacement:** Submit a new image, question, and existing `session_id`.

**Successful response:**

```json
{
  "status": "success",
  "answer": "The image contains a book on a table.",
  "session_id": "<session-id>",
  "latency_ms": 2450
}
```

**Error response:**

```json
{
  "status": "error",
  "error_code": "ERROR_CODE",
  "message": "A descriptive error message.",
  "retry": true
}
```

### Health Check

**Endpoint:** `GET /health`

Example response:

```json
{
  "status": "ok",
  "app": "LensQ",
  "model_loaded": true
}
```

### Session Termination

**Endpoint:** `POST /session/end`

Request parameter:

| Parameter | Type | Required |
|---|---|---|
| `session_id` | String | Yes |

Terminates the specified session and removes its associated image from server memory.

## Testing

Run the automated test suite:

```bash
python -m pytest -v
```

Tests use the mock backend to avoid loading or invoking the actual AI model.

The test suite should validate:

- API endpoint functionality.
- Image upload and validation.
- Question validation.
- Session creation and management.
- Follow-up question handling.
- Image replacement.
- Session expiration and termination.
- Error handling.
- Health-check responses.

## Production Deployment

For production environments, deploy LensQ behind Nginx with a valid HTTPS certificate.

The provided `deploy/nginx.conf` includes:

- HTTP-to-HTTPS redirection.
- Maximum request body size of 6 MB.
- Rate limiting for `/analyze`.
- Request read timeout of 120 seconds.

Recommended deployment configuration:

- Run Uvicorn on `127.0.0.1`.
- Use Nginx as the reverse proxy.
- Configure HTTPS using a trusted certificate provider such as Certbot.
- Run a single application worker to preserve in-memory session consistency.
- Allocate sufficient system memory and GPU resources for model inference.

## Known Limitations

- English-only question answering.
- Supports one image per session.
- No voice, audio, or video input.
- Sessions are lost when the server restarts.
- CPU-based inference can be relatively slow.
- Quantized GGUF inference may produce different results from full-precision inference.
- The 2B model may generate inaccurate responses, particularly when identifying people or fictional characters.

AI-generated responses should be treated as assistance rather than verified factual evidence.

## License

License: To be determined.