package com.eliteteam.speakingcoach.telegram

import kotlin.test.Test
import kotlin.test.assertEquals

class TelegramSessionIdTest {

    @Test
    fun prefixesChatId() {
        assertEquals("tg-12345", telegramSessionId(12345L).value)
        assertEquals("tg--100", telegramSessionId(-100).value)
    }
}
