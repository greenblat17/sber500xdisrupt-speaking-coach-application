package com.eliteteam.speakingcoach.ai

import com.eliteteam.speakingcoach.speaking.AudioClip
import com.eliteteam.speakingcoach.speaking.ClipProcessor
import com.eliteteam.speakingcoach.speaking.ClipReply
import com.eliteteam.speakingcoach.speaking.SessionGreeting
import com.eliteteam.speakingcoach.speaking.SessionId
import io.ktor.client.HttpClient
import io.ktor.client.call.body
import io.ktor.client.request.forms.formData
import io.ktor.client.request.forms.submitFormWithBinaryData
import io.ktor.client.request.get
import io.ktor.client.request.post
import io.ktor.client.request.setBody
import io.ktor.client.statement.bodyAsBytes
import io.ktor.http.ContentType
import io.ktor.http.Headers
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.contentType
import io.ktor.http.isSuccess
import kotlinx.coroutines.delay
import kotlin.time.Duration
import kotlin.time.Duration.Companion.milliseconds
import kotlin.time.Duration.Companion.seconds
import kotlin.time.TimeSource

class HttpClipClient(
    baseUrl: String,
    private val http: HttpClient,
    private val pollInterval: Duration = 300.milliseconds,
    private val timeout: Duration = 90.seconds,
) : ClipProcessor {
    private val root = baseUrl.trimEnd('/')

    suspend fun startSession(sessionId: SessionId? = null): SessionGreeting {
        val created = createSession(sessionId)
        val audio = http.get("$root/v1/sessions/${created.sessionId}/greeting/audio")
        if (!audio.status.isSuccess()) {
            error("ai-service GET greeting audio returned ${audio.status}")
        }
        val contentType = audio.headers[HttpHeaders.ContentType] ?: "audio/ogg"
        return SessionGreeting(
            sessionId = SessionId(created.sessionId),
            text = created.greeting.text,
            audio = AudioClip(
                bytes = audio.bodyAsBytes(),
                contentType = contentType.substringBefore(';'),
                fileName = "greeting.ogg",
            ),
        )
    }

    suspend fun ensureSession(sessionId: SessionId): SessionId {
        return SessionId(createSession(sessionId).sessionId)
    }

    private suspend fun createSession(sessionId: SessionId?): SessionCreatedResponse {
        val response = http.post("$root/v1/sessions") {
            if (sessionId != null) {
                contentType(ContentType.Application.Json)
                setBody(SessionCreateRequest(sessionId.value))
            }
        }
        if (response.status != HttpStatusCode.Created && !response.status.isSuccess()) {
            error("ai-service POST /v1/sessions returned ${response.status}")
        }
        return response.body()
    }

    override suspend fun process(sessionId: SessionId, clip: AudioClip): ClipReply {
        val jobId = submit(sessionId, clip)
        val deadline = TimeSource.Monotonic.markNow() + timeout
        while (deadline.hasNotPassedNow()) {
            when (val status = poll(jobId)) {
                ClipJobStatus.Pending -> delay(pollInterval)
                is ClipJobStatus.Ok -> return ClipReply(status.notes, downloadAudio(jobId))
                is ClipJobStatus.Failed -> error("ai-service job $jobId failed: ${status.message}")
            }
        }
        error("ai-service job $jobId timed out after $timeout")
    }

    private suspend fun submit(sessionId: SessionId, clip: AudioClip): String {
        val response = http.submitFormWithBinaryData(
            url = "$root/v1/clips",
            formData = formData {
                append("sessionId", sessionId.value)
                append(
                    "audio",
                    clip.bytes,
                    Headers.build {
                        append(HttpHeaders.ContentType, clip.contentType)
                        append(HttpHeaders.ContentDisposition, "filename=\"${clip.fileName}\"")
                    },
                )
            },
        )
        if (response.status != HttpStatusCode.Accepted) {
            error("ai-service POST /v1/clips returned ${response.status}")
        }
        return response.body<ClipAcceptedResponse>().jobId
    }

    private suspend fun poll(jobId: String): ClipJobStatus {
        val response = http.get("$root/v1/clips/$jobId")
        if (response.status == HttpStatusCode.NotFound) {
            return ClipJobStatus.Failed("unknown job")
        }
        if (!response.status.isSuccess()) {
            error("ai-service GET /v1/clips/$jobId returned ${response.status}")
        }
        val body = response.body<ClipStatusResponse>()
        return when (body.status) {
            "pending" -> ClipJobStatus.Pending
            "ok" -> ClipJobStatus.Ok(body.result?.notes.orEmpty())
            "error" -> ClipJobStatus.Failed(body.error?.message ?: "unknown error")
            else -> ClipJobStatus.Failed("unexpected status ${body.status}")
        }
    }

    private suspend fun downloadAudio(jobId: String): AudioClip {
        val response = http.get("$root/v1/clips/$jobId/audio")
        if (!response.status.isSuccess()) {
            error("ai-service GET /v1/clips/$jobId/audio returned ${response.status}")
        }
        val contentType = response.headers[HttpHeaders.ContentType] ?: "audio/ogg"
        return AudioClip(
            bytes = response.bodyAsBytes(),
            contentType = contentType.substringBefore(';'),
            fileName = "reply.ogg",
        )
    }
}

private sealed interface ClipJobStatus {
    data object Pending : ClipJobStatus
    data class Ok(val notes: List<String>) : ClipJobStatus
    data class Failed(val message: String) : ClipJobStatus
}
