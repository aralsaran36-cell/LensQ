## 1. Project Overview & Problem Statement

**Project Title**

Mobile-Browser Image Question Answering System Using LFM3-Omni-2B

**Problem**

Mobile users often need quick information from an image, such as text in a bill, object details, product information, or content in a screenshot. Typing long questions is slow, and users may not know how to describe an image clearly.

This project builds a simple mobile-browser application where a user can upload an image or capture a photo using the camera, type a question, and receive an AI-generated text answer.

The system uses LiquidAI/LFM3-Omni-2B running on our own server, not a third-party cloud service.

**What It Is**

A mobile-browser image understanding system

A text-based image question answering system

A system that uses one uploaded image or camera-captured photo at a time

A privacy-focused system that processes images on our own server

A simple one-turn system: upload image, ask question, get answer

**What It Is NOT**

It is not a voice assistant

It does not accept voice questions

It does not support video or audio input

It does not support multiple image upload

It does not store uploaded images permanently

It is not an always-on camera system


**Intended Users**

Mobile browser users

Students who want help understanding diagrams, notes, or screenshots

Users who want information from bills, signs, products, or documents

Users who want their uploaded image handled privately

**Language Scope**

English: Primary language; must work completely


## 2. System Architecture

flowchart TD
    A["Browser UI: User opens application"] --> B{"Choose image input"}
    B -->|Upload Image| C["Select image from device"]
    B -->|Open Camera| D{"Camera permission?"}
    D -->|Denied| D1["Show camera permission error"]
    D -->|Granted| E["Capture photo using camera"]
    C --> F["Image selected"]
    E --> F


    F --> G["User types question"]
    G --> H{"Validate image and question"}
    H -->|Invalid| H1["Show validation error"]
    H -->|Valid| I["Send image + question to FastAPI"]


    I --> J["Backend validates image, size, and question"]
    J -->|Invalid| J1["Return 400 error to browser"]
    J -->|Valid| K["Prepare image for model"]


    K --> L["LFM3-Omni-2B analyzes image and question"]
    L --> M{"Inference successful?"}
    M -->|No| M1["Show error and retry option"]
    M -->|Yes| N["Generate text answer"]


    N --> O["Keep image in session memory for next question"]
    O --> P["Return text answer and status"]
    P --> Q["Browser displays answer"]


    Q --> R{"User wants another question?"}
    R -->|Yes| G
    R -->|No| S["Delete session image and end session"]


## 3. End-to-End Flow

- User opens the application in a mobile browser.
- User selects Upload Image or Open Camera.
- If Upload Image is selected, the user chooses an image from the device.
- If Open Camera is selected, the browser asks for camera permission.
- If permission is denied, the system shows an error.
- If permission is granted, the user captures a photo.
- The image is stored temporarily in the current session memory.
- User types a question about the image.
- Browser validates the image and question.
- If invalid, the system shows a validation error.
- If valid, the image and question are sent to the FastAPI backend.
- Backend validates the image, file size, and question.
- If invalid, the backend returns a 400 error.
- If valid, the backend prepares the image for the model.
- LFM3-Omni-2B analyzes the image and question.
- If inference fails, the system shows an error and retry option.
- If inference succeeds, the model generates a text answer.
- Backend returns the text answer and status to the browser.
- Browser displays the answer.
- User can ask another question for the same image.
- If a new image is uploaded or captured, the previous image is deleted.
- If the session ends, the current image and session data are deleted from memory.
- The image is not stored permanently on disk.

## 4. Technology Stack

| Technology              | Why It Is Used                                      |
| :---------------------- | :-------------------------------------------------- |
| Python 3.11+             | Handles backend logic and AI integration.          |
| FastAPI + Uvicorn        | Creates and runs backend APIs.                      |
| Pydantic                 | Validates incoming request data.                    |
| HTML, CSS, JavaScript    | Builds the mobile browser user interface.           |
| getUserMedia             | Opens and accesses the mobile camera.               |
| File API                 | Uploads images from the device.                     |
| FFmpeg                   | Converts or prepares images if required.             |
| LFM3-Omni-2B             | Understands images and generates text answers.      |
| In-memory session store  | Maintains temporary image and session information.  |
| Python logging           | Records errors and processing time.                 |
| pytest                   | Tests backend functionality.                        |
| HTTPS                    | Enables camera access on mobile browsers.           |



## 5. Risks and Tests

1. **Poor Image Quality**

   Blurry, dark, rotated, or low-resolution images may reduce answer quality.

   **Test:** Use clear, blurry, dark, rotated, and low-resolution images. Record whether the model gives useful answers.

2. **Unsupported Image Format**

   Some devices may provide images in formats the backend does not accept.

   **Test:** Upload JPG, PNG, WebP, and HEIC images. Check which formats are accepted and which produce errors.

3. **Large Image Files**

   Large images may slow down upload and processing.

   **Test:** Upload small, medium, and large images. Measure upload time, processing time, and failure rate.

4. **Model May Misread Text**

   The model may incorrectly read small, handwritten, or low-quality text in an image.

   **Test:** Use printed text, handwritten text, small text, and blurry text. Record accuracy and failure examples.

5. **Privacy Leakage**

   Uploaded images may accidentally appear in logs or temporary files.

   **Test:** Check server logs, temporary folders, and error messages. Confirm that images are not stored.



## 6. Milestone Plan with Measurable Completion Criteria

## Milestone 1: Model Feasibility

- Run LFM3-Omni-2B using the official model card.
- Test image input with English text questions.
- Measure inference latency, RAM/VRAM usage, and image limits.
- Document test results and hardware benchmarks.

**Done when:** English image question answering works end to end, and test results are documented.

## Milestone 2: Backend Development

- Build `/health` and `/analyze` API endpoints using FastAPI.
- Validate image format, file size, and question length.
- Prepare the image and integrate LFM3-Omni-2B.
- Add session memory, error handling, and privacy-safe logging.

**Done when:** All pytest cases pass and one real English image question works through `/analyze`.

## Milestone 3: Browser Image UI

- Add **Upload Image** and **Open Camera** options.
- Handle camera permission and show clear errors.
- Add text question input and image preview.
- Display the AI text answer and processing status.

**Done when:** A user can upload or capture an image, type a question, and see the answer on a real phone.

## Milestone 4: Integration and Hardening

- Test 10 different image-question cases.
- Test blurry, dark, rotated, and large images.
- Test camera permission denial and network failures.
- Verify that images and user content are not stored in logs or temporary files.

**Done when:** All 10 test cases pass, errors are handled correctly, and privacy checks are clean.

## Technical Decisions

Decision 1: Keep the Image in Session Memory

I keep the image in session memory so the user can ask multiple questions without uploading it again. The image is deleted when a new image is uploaded or the session ends. The trade-off is that it uses server memory during the session.

Decision 2: Use Backend FFmpeg

I use FFmpeg on the backend to prepare the image in a consistent format before model processing. Browser image handling can differ between Chrome and Safari. The trade-off is that FFmpeg must be installed on the server.

Decision 3: Use In-Memory Session Store

I use an in-memory session store because the project does not need permanent storage. It keeps the image and session data only during the active session and supports privacy. The trade-off is that session data is lost if the server restarts.


## 8. Questions for the Task Owner

- 1. What is the maximum allowed image file size?

- 2. Can the user ask multiple questions for the same image?