package com.eliteteam.speakingcoach.ai

import kotlinx.serialization.Serializable

@Serializable
data class SessionCreateRequest(
    val sessionId: String? = null,
)

@Serializable
data class SessionCreatedResponse(
    val sessionId: String,
    val greeting: GreetingResponse,
)

@Serializable
data class GreetingResponse(
    val text: String,
)

@Serializable
data class ClipAcceptedResponse(
    val jobId: String,
)

@Serializable
data class ClipStatusResponse(
    val jobId: String,
    val status: String,
    val result: ClipResultResponse? = null,
    val error: ClipErrorResponse? = null,
)

@Serializable
data class ClipResultResponse(
    val notes: List<String> = emptyList(),
)

@Serializable
data class ClipErrorResponse(
    val code: String,
    val message: String,
)
