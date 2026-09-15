from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import FakeLlm, FakeStt, FakeTts, build_app


def _start_session(client: TestClient) -> str:
    response = client.post("/v1/sessions")
    assert response.status_code == 201
    body = response.json()
    assert "greeting" in body and "text" in body["greeting"]
    return body["sessionId"]


def _wait_status(client: TestClient, job_id: str) -> dict:
    for _ in range(50):
        response = client.get(f"/v1/clips/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] != "pending":
            return body
    raise AssertionError(f"job {job_id} stayed pending")


def test_health() -> None:
    app, _, _, _ = build_app()
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_unknown_job_is_404() -> None:
    app, _, _, _ = build_app()
    with TestClient(app) as client:
        assert client.get("/v1/clips/missing").status_code == 404
        assert client.get("/v1/clips/missing/audio").status_code == 404


def test_unknown_session_clip_is_404() -> None:
    app, _, _, _ = build_app()
    with TestClient(app) as client:
        created = client.post(
            "/v1/clips",
            data={"sessionId": "missing"},
            files={"audio": ("voice.ogg", b"fake-ogg", "audio/ogg")},
        )
        assert created.status_code == 404


def test_session_greeting_audio() -> None:
    tts = FakeTts()
    app, _, _, tts = build_app(tts=tts)
    with TestClient(app) as client:
        session_id = _start_session(client)
        audio = client.get(f"/v1/sessions/{session_id}/greeting/audio")
        assert audio.status_code == 200
        assert audio.content.startswith(b"OggS")
        assert client.get("/v1/sessions/missing/greeting/audio").status_code == 404


def test_clip_contract_returns_audio() -> None:
    app, _, _, tts = build_app(stt=FakeStt(["I went to the shop"]))
    with TestClient(app) as client:
        session_id = _start_session(client)
        created = client.post(
            "/v1/clips",
            data={"sessionId": session_id},
            files={"audio": ("voice.ogg", b"fake-ogg", "audio/ogg")},
        )
        assert created.status_code == 202
        job_id = created.json()["jobId"]
        body = _wait_status(client, job_id)
        assert body["status"] == "ok"
        assert body["jobId"] == job_id
        assert body["transcript"] == "I went to the shop"
        assert body["replyText"] == "Got it: I went to the shop"
        assert body["result"]["notes"] == []
        assert "timingsMs" in body
        audio = client.get(f"/v1/clips/{job_id}/audio")
        assert audio.status_code == 200
        assert audio.headers["content-type"].startswith("audio/ogg")
        assert audio.content.startswith(b"OggS")
        assert tts.texts == ["Got it: I went to the shop"]


def test_empty_transcript_clarifies_without_llm() -> None:
    llm = FakeLlm()
    tts = FakeTts()
    app, _, llm, tts = build_app(stt=FakeStt([""]), llm=llm, tts=tts)
    with TestClient(app) as client:
        session_id = _start_session(client)
        created = client.post(
            "/v1/clips",
            data={"sessionId": session_id},
            files={"audio": ("voice.ogg", b"silence", "audio/ogg")},
        )
        job_id = created.json()["jobId"]
        body = _wait_status(client, job_id)
        assert body["status"] == "ok"
        assert body["replyText"] == "I didn't catch that. Could you say it again?"
        assert body["result"]["notes"] == []
        assert llm.calls == []
        assert tts.texts == ["I didn't catch that. Could you say it again?"]


def test_second_clip_includes_dialogue_history() -> None:
    llm = FakeLlm()
    app, _, llm, _ = build_app(stt=FakeStt(["my name is Alex", "what is my name"]))
    with TestClient(app) as client:
        session_id = _start_session(client)
        first = client.post(
            "/v1/clips",
            data={"sessionId": session_id},
            files={"audio": ("voice.ogg", b"one", "audio/ogg")},
        )
        first_id = first.json()["jobId"]
        assert _wait_status(client, first_id)["status"] == "ok"

        second = client.post(
            "/v1/clips",
            data={"sessionId": session_id},
            files={"audio": ("voice.ogg", b"two", "audio/ogg")},
        )
        second_id = second.json()["jobId"]
        assert _wait_status(client, second_id)["status"] == "ok"

    assert len(llm.calls) == 2
    second_history, second_user = llm.calls[1]
    assert second_user == "what is my name"
    assert second_history == ["my name is Alex", "Got it: my name is Alex"]


def test_create_session_with_id_is_get_or_create() -> None:
    app, _, _, _ = build_app()
    with TestClient(app) as client:
        first = client.post("/v1/sessions", json={"sessionId": "tg-42"})
        assert first.status_code == 201
        assert first.json()["sessionId"] == "tg-42"
        second = client.post("/v1/sessions", json={"sessionId": "tg-42"})
        assert second.status_code == 201
        assert second.json()["sessionId"] == "tg-42"
        created = client.post(
            "/v1/clips",
            data={"sessionId": "tg-42"},
            files={"audio": ("voice.ogg", b"fake-ogg", "audio/ogg")},
        )
        assert created.status_code == 202
        assert _wait_status(client, created.json()["jobId"])["status"] == "ok"


def test_clip_includes_coaching_notes() -> None:
    notes = [
        "You said: I was in Turkey last summer with my friends.",
        "Better: I went to Turkey last summer with my friends.",
        "We usually say 'went to' here.",
    ]
    llm = FakeLlm(notes=notes)
    app, _, _, tts = build_app(stt=FakeStt(["I was in Turkey last summer"]), llm=llm)
    with TestClient(app) as client:
        session_id = _start_session(client)
        created = client.post(
            "/v1/clips",
            data={"sessionId": session_id},
            files={"audio": ("voice.ogg", b"voice", "audio/ogg")},
        )
        body = _wait_status(client, created.json()["jobId"])
        assert body["status"] == "ok"
        assert body["result"]["notes"] == notes
        assert body["replyText"] == "Got it: I was in Turkey last summer"
        assert tts.texts == ["Got it: I was in Turkey last summer"]

