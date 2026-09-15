# Исследование: реальный ai-service (STT → LLM → TTS)

**Дата:** 2026-09-14  
**Статус:** рекомендации для первого среза (Week 1 MVP)  
**Связанные документы:** `ai_docs/product.md`, `ai_docs/plans/mvp-plan.md`  
**Контракт в коде:** `HttpClipClient`, `ClipDtos`, stub `infra/ai-service-stub/main.py`

Цены и имена моделей ниже — снимок документации на сентябрь 2026. Перед реализацией перепроверить страницы провайдеров.

---

## 1. Цель и текущая архитектура

### Цель

Собрать **реальный** `ai-service`, который по уже зафиксированному clip-контракту превращает голосовое сообщение Telegram в голосовой ответ собеседника на английском. Не внедрять анализ grammar/vocab/pronunciation, не трогать мобильный клиент, не строить duplex/WebRTC.

Главная проверяемая ценность Week 1: пользователь может **последовательно** говорить голосом и получать осмысленный голосовой ответ **с памятью диалога** в рамках `sessionId`.

### Как сейчас устроен поток

```text
Telegram voice (OGG/Opus)
  → Ktor backend скачивает файл, contentType=audio/ogg, fileName=voice.ogg
  → SessionClipQueue сериализует клипы по sessionId
  → HttpClipClient:
       POST /v1/clips  multipart: sessionId, audio  → 202 { jobId }
       GET  /v1/clips/{jobId}  каждые 300 ms, таймаут 90 s
         pending | ok | error
       GET  /v1/clips/{jobId}/audio  → байты, Content-Type по умолчанию audio/ogg
  → sendVoice обратно в Telegram
```

`sessionId` уже равен `tg-{telegramChatId}` (`TelegramPollingBot`). Это единственный хук для истории диалога: один чат Telegram = одна speaking-сессия в MVP.

`ClipStatusResponse` в Kotlin содержит только `jobId`, `status`, `error`. В `Application.kt` включено `ignoreUnknownKeys = true`: **можно добавить transcript и другие поля в JSON статуса, не ломая поллер**.

`ai-service/` пуст. Stub (`infra/ai-service-stub/main.py`) кладёт jobs в dict и через 0.8 s отдаёт **тот же OGG**. Истории диалога нет.

Telegram `sendVoice`: предпочтителен **OGG + Opus** (`audio/ogg`), чтобы клиент показал голосовое сообщение, а не файл. MP3/M4A тоже принимаются, но хуже совпадают с текущим контрактом.

### Ограничение транспорта

Это **последовательные клипы**, не live duplex. Пользователь нажимает микрофон, отправляет готовый файл, ждёт ответ (до 90 s на стороне backend). Realtime/WebRTC API не ускоряют этот UX сами по себе: вход уже полный файл.

Целевой бюджет задержки для короткой реплики (5–15 s речи): **3–8 s** end-to-end внутри 90 s. Критично не упереться в холодный старт моделей и лишние конвертации.

---

## 2. STT: сравнение и рекомендация

Задача: Telegram OGG/Opus → английский transcript. Для learners важны акценты, хезитации (`um`, `like`), самоисправления. Word-level timestamps полезны **позже** (fluency, паузы), в Week 1 достаточно текста; API лучше сразу уметь timestamps, чтобы не менять провайдера на неделе 3.

### Сравнительная таблица

| Вариант | Формат входа | Латентность (короткий клип) | Качество EN / learners | Timestamps | Цена (ориентир, 2026) | API |
|---|---|---|---|---|---|---|
| **Groq Whisper** `whisper-large-v3` / `whisper-large-v3-turbo` | **ogg, wav, mp3, webm…** нативно | ~0.2–0.4 s (бенчмарки Groq vs OpenAI Whisper) | Хорошее Whisper large-v3; хуже GPT-transcribe на сильных акцентах; fillers иногда «вычищает» | `verbose_json` + `timestamp_granularities[]` word/segment | turbo **$0.04/час**, large **$0.111/час**; минимум биллинга **10 s** | OpenAI-совместимый `POST /openai/v1/audio/transcriptions`; `GROQ_API_KEY` |
| **OpenAI** `gpt-4o-mini-transcribe` / `gpt-4o-transcribe` | Гид: mp3/mp4/m4a/wav/webm; SDK также **flac, ogg** | ~0.8–2 s | Лучше Whisper по WER и языку; `prompt` помогает с именами/контекстом сессии | У mini/4o-transcribe в основном `json`/`text`, **без** whisper-style word timestamps. Word timestamps — у `whisper-1` | mini **~$0.003/мин**, 4o **~$0.006/мин**; есть `gpt-transcribe` **~$0.0045/мин** | `POST /v1/audio/transcriptions`; `OPENAI_API_KEY` |
| OpenAI `whisper-1` | те же | медленнее GPT-transcribe | Классический Whisper | `verbose_json` + word | исторически ~$0.006/мин | тот же endpoint |
| **Deepgram Nova-3** | широкий набор; OGG обычно ок | очень быстро (batch listen) | Сильный EN, noise/accents; не заточен под «ученические» disfluencies | word timestamps **по умолчанию** | Nova-3 ~**$0.0043–$0.0077/мин** (tier) | `POST /v1/listen`; `DEEPGRAM_API_KEY` |
| **AssemblyAI** Universal | автодетект формата, почти любые файлы | async: upload + poll (лишний цикл) | Высокая точность, entity/context фичи | utterances + words | async **~$0.21/час** (~$0.0035/мин) | create transcript + poll; плохо стыкуется с нашим 90 s, если делать двойной poll |
| Google / Azure Speech | WAV/FLAC предпочтительны; OGG Opus часто нужен явный encoding | низкая–средняя | Сильный EN; Azure хорош для pronunciation **позже** | word times есть | comparable $/мин, сложнее billing | REST/SDK; много env (region, keys) |
| **Yandex SpeechKit** | OggOpus в доке есть | низкая для RU | **RU сильный, EN слабее** чем Groq/OpenAI | есть в streaming | облако YC, IAM + folder | gRPC/REST v3; `IAM_TOKEN`, `x-folder-id` |
| **SaluteSpeech** | PCM, OPUS, MP3, FLAC | реалтайм + файлы | RU отличный; EN заявлен, голосов мало | да | Sber Studio OAuth | сертификаты/OAuth; EN не ядро продукта |
| **GigaAM** | self-host | зависит от GPU | заточен под RU | да | infra cost | не для EN MVP |
| **faster-whisper** self-host | любой через ffmpeg | GPU: десятки–сотни ms на клип **если модель в VRAM**; CPU: секунды; холодный старт убивает UX | large-v3 ≈ Groq | word timestamps (WhisperX точнее) | GPU idle дороже API на малом трафике | свой сервис; нужен ffmpeg |

### Конвертация аудио

- Telegram отдаёт **OGG/Opus**. Groq явно принимает `ogg`. OpenAI SDK тоже перечисляет `ogg`; публичный guide иногда **не** включает ogg — в реализации: сначала слать как есть с `filename=voice.ogg`; при 400 — ffmpeg → 16 kHz mono WAV/FLAC.
- Deepgram/AssemblyAI обычно автодетект.
- Yandex умеет OggOpus напрямую.
- ffmpeg всё равно держать в образе: (1) fallback STT, (2) TTS → Telegram OGG/Opus, (3) нормализация битрейта.

Пример fallback:

```text
ffmpeg -y -i in.ogg -ac 1 -ar 16000 -c:a pcm_s16le out.wav
```

### Рекомендация STT (MVP)

**Основной: Groq `whisper-large-v3`, `language=en`.**

Почему:

1. Нативный **ogg** — меньше ffmpeg на hot path.
2. Латентность лучше OpenAI Whisper/GPT-transcribe на коротких клипах (это доминирует в UX ожидания).
3. Дёшево даже с минимумом 10 s биллинга (~$0.0003 за клип на turbo; large чуть дороже).
4. Сразу `verbose_json` + word timestamps → складывать в job, не отдавать backend в Week 1.
5. API почти как OpenAI — смена на `gpt-4o-mini-transcribe` — это смена base URL/модели.

**Не turbo как default**, если качество learners просядет (turbo WER выше). Начать с `whisper-large-v3`, замерить 20–30 реальных русских акцентов; при ок — можно turbo.

**Запасной путь качества:** OpenAI `gpt-4o-mini-transcribe` + `prompt` с последними репликами сессии (имена, тема). Включать, если Groq глотает fillers или ломает акцент. Timestamps тогда брать отдельным проходом не нужно до недели 3.

**Не брать в первый срез:** AssemblyAI (двойной poll), Azure/Google (тяжёлый онбординг), Yandex/Salute/GigaAM как primary EN, self-host GPU.

Секреты: `GROQ_API_KEY` (primary), опционально `OPENAI_API_KEY` для fallback.

---

## 3. TTS: сравнение и рекомендация

Задача: короткая английская реплика партнёра по разговору (не «робот-репетитор») → файл, который Telegram играет как voice. Предпочтительно **OGG/Opus**.

Streaming TTS **не даёт выигрыша** при текущем контракте: backend ждёт **полный** `GET .../audio`. Стримить имеет смысл только внутри ai-service (ранний старт синтеза, пока LLM ещё пишет) — это уже оптимизация, не MVP.

### Сравнительная таблица

| Вариант | Естественность (собеседник) | Формат vs Telegram | Латентность полного файла | Цена | SSML / стиль | Заметки |
|---|---|---|---|---|---|---|
| **OpenAI** `gpt-4o-mini-tts` | Высокая; `instructions` («warm conversational partner, not a teacher») | `response_format=opus` (и mp3/aac/flac/wav/pcm). Контейнер opus часто Ogg — **проверить на sendVoice**; иначе ffmpeg wrap | секунды на 1–3 фразы | ~$0.60/1M text tokens + $12/1M audio tokens; на практике порядка **~$0.015/мин** аудио | нет классического SSML; есть **voice instructions** | Один ключ с LLM. Лимит ~2000 input tokens. Голоса alloy/coral/verse и др. |
| OpenAI `tts-1` | Средняя, чуть «API-голос» | opus/mp3 | быстрее mini-tts | **$15 / 1M символов** | нет instructions | Если mini-tts медленный |
| **ElevenLabs** Flash/Turbo | Часто лучший «живой» голос | `opus_48000_*` — raw Opus chunks, **не OGG-контейнер** → ffmpeg `-f ogg` | Flash ~75 ms model + сеть; полный файл всё равно ждём | **$0.05 / 1k символов** Flash | нет SSML в том же виде; voice settings | Второй вендор, дороже OpenAI TTS |
| Azure Neural / Google Cloud TTS | Хорошие neural EN | OGG Opus часто есть нативно | средняя | $/символ, comparable | **SSML** сильный | Тяжёлый IAM; имеет смысл, если позже pronunciation assessment на Azure |
| **Yandex SpeechKit** TTS | EN голоса есть, но продукт про RU | OggOpus в API v1/v3 | низкая | YC | SSML | Слабее как EN conversation partner |
| **SaluteSpeech** | EN голос Kira и др.; отзывы сильнее про RU | OPUS/MP3 | 2–5 s типично | Studio | SSML, эмоции | Мало EN голосов |
| **Cartesia** Sonic | очень низкий TTFA, агентный голос | **raw/wav/mp3**, нет opus | отлично для стрима, плохо стыкуется без ffmpeg | credit plans | нет SSML | лишний конверт в OGG |
| **Groq Orpheus** | выразительный EN | **только wav**; **max 200 символов** | быстро | **$22 / 1M символов** | `[cheerful]` tags | **200 символов ломают ответы коуча** — не подходит |
| **Piper** local | приемлемо, не «premium partner» | wav → ffmpeg opus | CPU ок | infra | ограничено | запасной offline, не MVP |

Telegram: обернуть Opus в OGG, если провайдер отдал голый `.opus`:

```text
ffmpeg -y -i in.opus -c:a copy out.ogg
# или перекодировать:
ffmpeg -y -i in.wav -c:a libopus -b:a 32k -application voip -vn out.ogg
```

### Рекомендация TTS (MVP)

**OpenAI `gpt-4o-mini-tts`, `voice=coral` (или `verse`), `response_format=opus`.**

Почему:

1. Один `OPENAI_API_KEY` уже нужен для LLM.
2. `instructions` позволяют звучать как спокойный собеседник, а не как диктор учебника — ближе к продукту, чем `tts-1`.
3. Opus ближе всего к Telegram voice без второго вендора.
4. Цена на короткие реплики копеечная относительно LLM.

**Проверка в первый день реализации:** сыграть ответ в реальном Telegram. Если клиент не показывает waveform voice — ffmpeg в OGG/Opus 48 kHz.

ElevenLabs оставить **plan B**, если голос OpenAI «плоский» на пилоте (нужен ffmpeg + `ELEVENLABS_API_KEY` + voice_id).

Не брать Groq TTS (лимит 200 символов), Cartesia (нет opus), Piper, Salute/Yandex как primary EN.

---

## 4. LLM и полный контекст диалога

Это критичный слой: без истории каждая реплика — новый холодный тьютор.

### Паттерн API

Рекомендуемый паттерн для MVP: **Chat Completions** (`POST /v1/chat/completions`) со своим массивом `messages[]`.

Почему не Responses API / Conversations API как единственный store:

- История должна жить у **нас** (диагностика недели 3, профиль, смена модели).
- `previous_response_id` привязывает к OpenAI; рестарт процесса + истёкшее хранение у провайдера = потеря контекста.
- Chat Completions портативен на Groq/Anthropic-совместимые шлюзы.
- Responses можно включить позже для tools; для Week 1 это лишняя сложность (reasoning items, 400 при replay).

Схема на каждый клип:

```text
messages = [
  { role: "system", content: SPEAKING_COACH_SYSTEM },
  ...history[sessionId],          // user/assistant пары
  { role: "user", content: transcript }
]
→ assistant_text
→ append user + assistant в history[sessionId]
```

`sessionId` (`tg-123`) — ключ словаря. Не парсить chat id в LLM.

### Где хранить историю

| Store | Сейчас | Рестарт | Позже (профиль, аналитика) |
|---|---|---|---|
| **dict в процессе** | идеально для Week 1 | **история умирает** | нет |
| Redis | чуть больше ops | переживает рестарт ai-service | TTL сессии, не профиль |
| Postgres | избыточно на пустом `ai-service/` | да | да, стык с backend-сессиями |

**Рекомендация пути:**

1. **Сейчас:** in-memory `dict[sessionId, list[Message]]` + TTL (например 24 h / max 200 сообщений) + lock по sessionId (очередь уже есть на backend, но ai-service должен быть идемпотентен к параллели).
2. **Сразу заложить интерфейс** `DialogueStore` (get/append), чтобы заменить dict на Redis одной реализацией, когда появится второй инстанс или боль от рестартов.
3. **Не** дублировать каноническую историю только у OpenAI.
4. Долгосрок: Postgres на backend (speaking session) — источник правды; ai-service либо получает summary/profile в будущем поле запроса, либо читает Redis, куда backend пишет. Это **не** Week 1: контракт POST clips менять не обязательно.

Поведение при рестарте MVP: пользователь начинает «с чистого листа» в том же Telegram-чате. Задокументировать. Для пилота 1 инстанс + редкие деплои приемлемо. Перед пользовательским тестом — Redis или persist.

### Бюджет токенов

Короткий speaking-turn: user ~20–80 слов, assistant ~40–80 слов. 30 минут диалога ≈ несколько тысяч токенов — влезает даже в маленькие окна **без** summarization.

Правила на вырост (заложить константы, не алгоритмы):

- Жёсткий sliding window: последние **N=40** сообщений (20 пар) + system.
- Если оценка токенов > 8k: свернуть старую голову в одно `system`/`user` summary («Topics covered, user level, recurring mistakes — do not lecture now»).
- Не суммаризировать **последние 6–8 реплик** — иначе теряется локальный контекст «what did I just say».
- Профиль пользователя (неделя 3) — отдельный короткий блок в system, не вся сырая история всех сессий.

### System prompt (направление, не финальный текст)

Роль: **разговорный партнёр**, который учит через диалог, а не через разбор на лету.

Должно быть:

- Говори только по-английски, уровень чуть выше пользователя, короткие реплики (2–4 предложения).
- Задавай follow-up, помогай сформулировать мысль, перефразируй естественно, если пользователь застрял.
- Не исправляй каждую ошибку вслух; максимум один мягкий recast, вплетённый в ответ.
- Не выдавай списки правил, оценки CEFR, «let’s practice present perfect».
- Тема: daily conversation / onboarding goal, пока нет профиля.

Не должно быть: grammar dump, JSON анализа, переключение на русский без просьбы.

### Провайдер LLM

| Провайдер | EN conversation | Латентность | Контекст | Заметки |
|---|---|---|---|---|
| **OpenAI** `gpt-5.6-luna` | достаточно для партнёра; дёшево | низкая | short-context $0.20 / $1.20 за 1M | лучший default MVP |
| OpenAI `gpt-5.6-terra` | богаче нюанс | чуть выше | $2 / $12 | если luna слишком «тонкий» |
| Anthropic Claude | отличный EN partner | хорошая | отдельный ключ | не нужен, пока один вендор тянет |
| **Groq** Llama/GPT-OSS | быстрый, дешевле | очень низкая | OpenAI-compatible | запас по latency; качество партнёра проверить на 10 диалогах |
| **GigaChat** 2.x | EN слабее западных (ориентиры MMLU EN заметно ниже) | ок | OAuth, SSL нюансы | для RU экосистемы Sber500 — **фаза 2**, не EN speaking MVP |
| **YandexGPT** | слабее EN conversation | ок | YC | то же |

**Рекомендация:** OpenAI **`gpt-5.6-luna`** (или актуальный дешёвый chat alias на момент кода), `temperature` ~0.7, `max_tokens` ~200, чтобы TTS оставался коротким.

Один ключ OpenAI на LLM+TTS; Groq — STT.

### Realtime / gpt-4o-audio vs явный пайплайн

OpenAI Realtime (`gpt-realtime-2.1`, GPT-Live-1 ~$0.05/мин voice layer) заточен под **WebRTC/WebSocket duplex**, barge-in, TTFA.

Почему **не** для этого Telegram-контракта:

| | Clip STT→LLM→TTS | Realtime S2S |
|---|---|---|
| Вход | готовый OGG | поток PCM |
| Выход, который ждёт backend | целый файл | стрим |
| Transcript для диагностики | явный артефакт | надо вытаскивать отдельно |
| Смена TTS/STT | модульно | vendor lock |
| Цена на 15 s клип | центы долей | поминутная сессия + audio tokens дороже |
| Стык с poller 202/pending/ok | естественный | нужен адаптер «дождаться конца ответа, склеить аудио» |

Realtime выигрывает на **неделе 4 duplex** в приложении. Для Week 1 явный пайплайн совпадает с `mvp-plan.md`, даёт логи этапов, transcript в job, укладывается в 90 s.

Не путать со **streaming LLM→TTS внутри процесса** (можно позже): это всё ещё chained pipeline, не Realtime API.

### Расширение статуса job без поломки поллера

Сейчас клиент читает только `status` ∈ pending|ok|error.

Безопасно (ignoreUnknownKeys):

```json
{
  "jobId": "...",
  "status": "ok",
  "transcript": "I went to the shop yesterday",
  "replyText": "Nice — what did you buy?",
  "timingsMs": { "stt": 320, "llm": 900, "tts": 1100, "total": 2400 }
}
```

`error`: `{ "code": "stt_failed", "message": "..." }` — уже в DTO.

Аудио по-прежнему только `GET .../audio`. Не класть base64 в статус.

---

## 5. Рекомендуемый end-to-end стек MVP

```text
Telegram OGG
  → FastAPI (или аналог) POST /v1/clips
  → job pending
  → [optional ffmpeg only on STT 400]
  → Groq whisper-large-v3  (language=en, verbose_json сохранён внутри)
  → OpenAI chat gpt-5.6-luna  (messages[] по sessionId)
  → OpenAI gpt-4o-mini-tts  (opus)
  → [ffmpeg → audio/ogg если Telegram не ест сырой opus]
  → status=ok, GET audio
```

- **Один процесс**, как stub: in-memory jobs + in-memory dialogue.
- **ffmpeg** в Docker-образе обязательно, на happy path Groq может не понадобиться.
- Логировать ms: receive, stt, llm, tts, encode (план недели 1).
- Не оркестрировать через n8n.

Ожидаемый бюджет времени (клип 8–12 s, тёплые HTTP-клиенты): STT 0.3–1 s + LLM 0.5–2 s + TTS 0.5–2 s + сеть ≈ **2–6 s**, далеко от 90 s.

Стоимость порядка **<$0.02 за ход** при коротких репликах (STT Groq почти ноль, основная доля LLM+TTS).

Sber/Yandex: зафиксировать как **опцию локализации/данных в РФ**, не как EN quality path.

---

## 6. Шаги job pipeline и переменные окружения

### Состояния job

`pending` → (внутри: `stt` / `llm` / `tts`, можно не светить наружу) → `ok` | `error`

Наружу по контракту только три статуса. Внутренние стадии — в логах и опционально в extra JSON.

### Алгоритм обработки

1. Принять multipart, прочитать `sessionId`, `audio` bytes, `content-type`, filename.
2. Создать `jobId` (uuid), сохранить audio во временный файл, вернуть 202.
3. Worker (asyncio task / thread pool — не блокировать event loop синхронным HTTP):
   4. STT Groq: file=ogg, `model=whisper-large-v3`, `language=en`, `response_format=verbose_json`.
   5. Если пустой transcript / no_speech — `error` `empty_transcript` (или короткий TTS «I didn’t catch that, could you say it again?»).
   6. Загрузить history[sessionId]; собрать messages; Chat Completions; truncate window.
   7. Append user+assistant; обновить TTL.
   8. TTS mini-tts opus; при необходимости ffmpeg OGG.
   9. Положить audio bytes, `status=ok`.
10. GET status / GET audio как в stub.
11. TTL jobs (например 10 мин), чтобы не копить OGG в RAM.
12. Ошибки провайдера: один retry на 429/5xx; иначе `error` с коротким message без секретов.

### Env (предложение имён)

```text
# обязательно
GROQ_API_KEY=
OPENAI_API_KEY=

# модели (чтобы не хардкодить)
STT_MODEL=whisper-large-v3
STT_PROVIDER=groq          # groq | openai
LLM_MODEL=gpt-5.6-luna
TTS_MODEL=gpt-4o-mini-tts
TTS_VOICE=coral
TTS_RESPONSE_FORMAT=opus

# опционально
OPENAI_BASE_URL=https://api.openai.com/v1
GROQ_BASE_URL=https://api.groq.com/openai/v1
FFMPEG_BIN=ffmpeg
DIALOGUE_TTL_SECONDS=86400
DIALOGUE_MAX_MESSAGES=40
JOB_TTL_SECONDS=600
LOG_LEVEL=INFO

# plan B, не для первого дня
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=
```

Не коммитить ключи. Локально — `.env` у ai-service, как у stub/backend.

Health: оставить `GET /health`.

---

## 7. Риски

| Риск | Суть | Митигация |
|---|---|---|
| **Latency** | Холодный DNS/TLS, очередь Groq 429, медленный TTS, ffmpeg на каждом клипе | keep-alive HTTP; retry с backoff; ffmpeg только fallback; не грузить large-v3 локально |
| **90 s timeout** | маловероятен на happy path; возможен при cascade retries | жёсткий внутренний deadline ~60 s; fail job раньше, чем backend |
| **Стоимость** | пилот дешёвый; ElevenLabs и realtime съедят бюджет | Groq STT + luna + mini-tts; лимиты на длину TTS |
| **Формат** | OpenAI opus ≠ Telegram OGG; Groq ogg вдруг 400 | золотой тест: один sendVoice roundtrip; ffmpeg в образе |
| **Потеря контекста** | рестарт dict; один sessionId на всю жизнь чата смешивает дни | TTL; позже Redis + явная команда `/new`; не плодить сессии без продукта |
| **Качество STT learners** | Whisper сглаживает «uh», ломает L1-акцент | prompt не лечит всё; A/B mini-transcribe; хранить verbose_json |
| **Галлюцинации Whisper** | тишина → выдуманный текст | `no_speech_prob` / пустой текст → уточняющий вопрос |
| **PII / аудио** | голос = биометрия; чаты личные | не логировать raw audio; ключи в env; retention jobs минуты; не слать аудио в третий лишний облачный сервис; политика: провайдеры US (OpenAI/Groq) — явно для пилота |
| **Порядок реплик** | два voice подряд | backend `SessionClipQueue` уже сериализует; ai-service всё равно lock на sessionId при append |
| **Контракт** | лишние required поля в JSON | только additive optional; не менять 202/pending/ok |

---

## 8. Чего не делать в этом срезе

- Анализ Grammar / Vocabulary / Fluency / Pronunciation API.
- Мобильное приложение, VAD, auto-listen.
- Duplex, barge-in, OpenAI Realtime, GPT-Live, WebRTC.
- GigaChat/Yandex/Salute как основной EN-стек «потому что Sber500».
- Self-host faster-whisper/Piper «чтобы бесплатно».
- Смена clip-контракта (новые обязательные поля, синхронный POST вместо 202).
- Streaming audio наружу (backend не умеет).
- Хранить историю только в `previous_response_id`.
- Grammar-коррекцию в system prompt.
- Multi-instance без shared store.
- Транскрипт обязательным для `HttpClipClient` (он его не читает).

---

## 9. Конкретные следующие шаги (порядок)

1. Поднять FastAPI в `ai-service/` с тем же контрактом, что stub (health, POST 202, GET status, GET audio), jobs в dict.
2. Добавить Docker с `ffmpeg` и env из §6; прогнать существующий backend на stub URL → сменить URL.
3. Вставить Groq STT; прогнать реальный Telegram OGG; залогировать transcript (не в Telegram).
4. In-memory `DialogueStore` + Chat Completions `gpt-5.6-luna` + system prompt собеседника; два подряд voice в одном чате должны ссылаться друг на друга.
5. TTS `gpt-4o-mini-tts` opus → `sendVoice`; если не voice bubble — ffmpeg OGG/Opus.
6. Timings в логах; timeout/retry; пустой STT.
7. Additive поля в GET status (`transcript`, `replyText`) — backend не трогать.
8. Ручной тест: 8–10 ходов, акцент, тишина, длинная пауза, рестарт процесса (ожидаемая потеря памяти).
9. Решение go/no-go: Groq STT vs OpenAI mini-transcribe по 10 клипам learners.
10. Перед пилотом >1 инстанса или частых деплоев — Redis за `DialogueStore`.
11. Неделя 3: word timestamps из уже сохранённого `verbose_json`; не менять STT-провайдера без нужды.

---

## Источники (сентябрь 2026)

- OpenAI Speech to text: https://developers.openai.com/api/docs/guides/speech-to-text  
- OpenAI Pricing (transcribe, realtime, GPT-5.6): https://developers.openai.com/api/docs/pricing  
- OpenAI TTS: https://developers.openai.com/api/docs/guides/text-to-speech  
- OpenAI conversation state / Responses: https://developers.openai.com/api/docs/guides/conversation-state  
- OpenAI Voice agents (chained vs live audio): https://developers.openai.com/api/docs/guides/voice-agents  
- Groq STT: https://console.groq.com/docs/speech-to-text  
- Groq TTS Orpheus: https://console.groq.com/docs/text-to-speech  
- Deepgram pricing / listen: https://deepgram.com/pricing  
- ElevenLabs TTS API / pricing: https://elevenlabs.io/docs/api-reference/text-to-speech/convert  
- Cartesia output formats: https://docs.cartesia.ai/build-with-cartesia/capability-guides/tts-output-audio-format  
- Yandex SpeechKit: https://docs.yandex.cloud/  
- Telegram Bot API `sendVoice`: https://core.telegram.org/bots/api  
