package com.eliteteam.speakingcoach.telegram

import com.eliteteam.speakingcoach.ai.HttpClipClient
import com.eliteteam.speakingcoach.speaking.AudioClip
import com.eliteteam.speakingcoach.speaking.ClipSubmitResult
import com.eliteteam.speakingcoach.speaking.SessionClipQueue
import com.eliteteam.speakingcoach.speaking.SessionId
import dev.inmo.tgbotapi.bot.ktor.telegramBot
import dev.inmo.tgbotapi.extensions.api.files.downloadFile
import dev.inmo.tgbotapi.extensions.api.send.media.sendVoice
import dev.inmo.tgbotapi.extensions.api.send.reply
import dev.inmo.tgbotapi.extensions.behaviour_builder.BehaviourContext
import dev.inmo.tgbotapi.extensions.behaviour_builder.triggers_handling.onCommand
import dev.inmo.tgbotapi.extensions.behaviour_builder.triggers_handling.onContentMessage
import dev.inmo.tgbotapi.requests.abstracts.asMultipartFile
import dev.inmo.tgbotapi.types.message.content.TextContent
import dev.inmo.tgbotapi.types.message.content.VoiceContent
import dev.inmo.tgbotapi.utils.DefaultKTgBotAPIKSLog
import org.slf4j.LoggerFactory
import java.util.concurrent.ConcurrentHashMap

internal const val TELEGRAM_WEBHOOK_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"

internal fun speakingCoachTelegramBot(token: String) = telegramBot(token) {
    logger = RedactingKSLog(DefaultKTgBotAPIKSLog, token)
}

internal fun BehaviourContext.installSpeakingCoachHandlers(
    ai: HttpClipClient,
    sessionClipQueue: SessionClipQueue,
) {
    val log = LoggerFactory.getLogger("TelegramHandlers")
    val chats = ConcurrentHashMap<String, SessionId>()
    onCommand("start") { message ->
        val chatKey = message.chat.id.toString()
        try {
            val greeting = ai.startSession()
            chats[chatKey] = greeting.sessionId
            reply(message, greeting.text)
            sendVoice(message.chat.id, greeting.audio.bytes.asMultipartFile(greeting.audio.fileName))
            log.info("Started session {} for tg-{}", greeting.sessionId.value, message.chat.id)
        } catch (error: Throwable) {
            log.error("Failed to start session for tg-{}", message.chat.id, error)
            reply(message, ERROR_TEXT)
        }
    }
    onContentMessage { message ->
        when (val content = message.content) {
            is VoiceContent -> {
                val chatKey = message.chat.id.toString()
                try {
                    val sessionId = chats.getOrPut(chatKey) { ai.startSession().sessionId }
                    val result = sessionClipQueue.submit(
                        sessionId = sessionId,
                        source = {
                            val bytes = downloadFile(content.media)
                            AudioClip(bytes, "audio/ogg", "voice.ogg")
                        },
                        onQueuedBehind = {
                            reply(message, QUEUED_TEXT)
                        },
                    )
                    when (result) {
                        ClipSubmitResult.QueueFull -> {
                            reply(message, QUEUE_FULL_TEXT)
                            log.info("Voice queue is full for {}", sessionId.value)
                        }
                        is ClipSubmitResult.Completed -> {
                            if (result.reply.notes.isNotEmpty()) {
                                reply(message, result.reply.notes.joinToString("\n\n"))
                            }
                            sendVoice(
                                message.chat.id,
                                result.reply.audio.bytes.asMultipartFile(result.reply.audio.fileName),
                            )
                            log.info("Sent voice reply for {}", sessionId.value)
                        }
                    }
                } catch (error: Throwable) {
                    log.error("Failed to handle voice for tg-{}", message.chat.id, error)
                    reply(message, ERROR_TEXT)
                }
            }
            is TextContent -> {
                if (!content.text.startsWith("/")) {
                    reply(message, SEND_VOICE_HINT)
                }
            }
            else -> Unit
        }
    }
}
