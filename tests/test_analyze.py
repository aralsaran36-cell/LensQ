import logging
import re
import time

from backend.config import settings
from backend.services.model_service import model_service
from backend.services.session_store import session_store

SECRET = "SECRETQUESTION123"


def post_image(client, image, question="What is this?", session_id=None, name="photo.jpg"):
    data = {"question": question}
    if session_id:
        data["session_id"] = session_id
    return client.post("/analyze", data=data, files={"image": (name, image, "image/jpeg")})


def post_followup(client, question="And what else?", session_id=None):
    data = {"question": question}
    if session_id is not None:
        data["session_id"] = session_id
    return client.post("/analyze", data=data)


def test_first_question_returns_answer_and_session(client, jpeg):
    r = post_image(client, jpeg)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["answer"]
    assert re.fullmatch(r"[a-f0-9]{32}", body["session_id"])


def test_followup_without_image_keeps_same_session(client, jpeg):
    sid = post_image(client, jpeg).json()["session_id"]
    r = post_followup(client, session_id=sid)
    assert r.status_code == 200
    assert r.json()["session_id"] == sid


def test_new_image_replaces_old_image(client, make_image):
    first, second = make_image(color="red"), make_image(color="blue")
    sid = post_image(client, first).json()["session_id"]
    old_bytes = session_store._sessions[sid].image_bytes
    r = post_image(client, second, session_id=sid)
    assert r.json()["session_id"] == sid
    assert session_store._sessions[sid].image_bytes != old_bytes


def test_followup_without_session_is_410(client):
    r = post_followup(client)
    assert r.status_code == 410
    assert r.json()["error_code"] == "SESSION_EXPIRED"


def test_bad_session_id_is_400(client):
    r = post_followup(client, session_id="abc")
    assert r.status_code == 400
    assert r.json()["error_code"] == "INVALID_SESSION"


def test_short_question_is_400(client, jpeg):
    r = post_image(client, jpeg, question="hi")
    assert r.status_code == 400
    assert r.json()["error_code"] == "INVALID_QUESTION"


def test_unsupported_format_is_415(client):
    r = post_image(client, b"GIF89a" + b"0" * 100, name="x.gif")
    assert r.status_code == 415
    assert r.json()["error_code"] == "UNSUPPORTED_FORMAT"


def test_empty_image_is_400(client):
    r = post_image(client, b"")
    assert r.status_code == 400
    assert r.json()["error_code"] == "EMPTY_IMAGE"


def test_large_image_is_413(client):
    big = b"\xff\xd8\xff" + b"0" * (settings.max_file_size_bytes + 1)
    r = post_image(client, big)
    assert r.status_code == 413
    assert r.json()["error_code"] == "IMAGE_TOO_LARGE"


def test_corrupt_image_is_422(client):
    r = post_image(client, b"\xff\xd8\xff" + b"0" * 100)
    assert r.status_code == 422
    assert r.json()["error_code"] == "IMAGE_PROCESSING_FAILED"


def test_end_session_deletes_image(client, jpeg):
    sid = post_image(client, jpeg).json()["session_id"]
    assert client.post("/session/end", data={"session_id": sid}).json() == {"status": "ok"}
    assert sid not in session_store._sessions
    assert post_followup(client, session_id=sid).status_code == 410


def test_expired_session_is_410(client, jpeg, monkeypatch):
    sid = post_image(client, jpeg).json()["session_id"]
    monkeypatch.setattr(settings, "session_ttl_seconds", 0)
    time.sleep(0.05)
    r = post_followup(client, session_id=sid)
    assert r.status_code == 410


def test_model_not_ready_is_503_with_retry(client, jpeg):
    model_service.unload()
    r = post_image(client, jpeg)
    assert r.status_code == 503
    assert r.json()["error_code"] == "MODEL_NOT_READY"
    assert r.json()["retry"] is True


# ---------- privacy ----------

def test_errors_never_echo_user_input(client):
    r = post_followup(client, question=SECRET, session_id="0" * 32)  # 410
    assert SECRET not in r.text
    r = post_image(client, b"GIF89a" + b"0" * 50, question=f"{SECRET} x")  # 415
    assert r.status_code == 415
    assert SECRET not in r.text


def test_logs_contain_no_user_content(client, jpeg, caplog):
    caplog.set_level(logging.INFO)
    sid = post_image(client, jpeg, question=f"{SECRET} what is this?").json()["session_id"]
    post_followup(client, question=f"{SECRET} again", session_id=sid)
    post_followup(client, question="hi")  # rejected request
    client.post("/session/end", data={"session_id": sid})

    assert "analyze_done" in caplog.text  # logging really happened
    assert SECRET not in caplog.text  # no question text
    assert sid not in caplog.text  # no full session id (only first 8 chars)
    assert "MOCK ANSWER" not in caplog.text  # no answer text