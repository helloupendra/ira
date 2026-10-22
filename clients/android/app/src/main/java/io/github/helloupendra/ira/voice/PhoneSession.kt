package io.github.helloupendra.ira.voice

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognitionService
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import io.github.helloupendra.ira.core.AskStream
import io.github.helloupendra.ira.core.SentenceAudio
import io.github.helloupendra.ira.core.ServerInfo
import io.github.helloupendra.ira.core.toJson
import io.github.helloupendra.ira.net.IraLog
import io.github.helloupendra.ira.net.Net
import java.io.IOException
import java.util.Locale
import kotlin.concurrent.thread
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update

/**
 * Talking to Ira without a live call: typed text, or speech the phone recognises itself
 * (Android's SpeechRecognizer, on the device when it can), sent through `/v1/ask/stream`.
 * The answer streams into the conversation; in voice mode it is spoken by the server's voice
 * when it has one (`/v1/voice/speak`), else by the phone's own (TextToSpeech).
 *
 * This is what works on any Ira, including one with no streaming speech-to-text. On the main
 * thread; the network runs on threads of its own.
 */
class PhoneSession(
    private val context: Context,
    private val server: String,
    private val token: () -> String?,
    private val conversationId: () -> String?,
    private val transcript: Transcript,
    private val info: ServerInfo?,
    private val onConversation: (String) -> Unit,
    private val onEnded: (String?) -> Unit,
    notice: String? = null,
) : Conversation, SentencePlayer.Listener {
    private val main = Handler(Looper.getMainLooper())
    private val state = MutableStateFlow(CallUi(status = CallStatus.Listening, assistant = info?.name ?: "Ira", mode = TalkMode.TEXT, notice = notice))
    override val ui: StateFlow<CallUi> = state
    override val mode: TalkMode
        get() = state.value.mode

    private var ended = false
    private var busy = false
    private var asks = 0
    private var call: okhttp3.Call? = null
    private var stopped = false

    // Voice mode.
    private var voice = false
    private var recognizer: SpeechRecognizer? = null
    private var onDevice = true
    private var quietSince = 0L
    private var player: SentencePlayer? = null
    private var tts: TextToSpeech? = null
    private var ttsReady = false

    // Typing (and recognised speech).

    override fun send(text: String, done: (String?) -> Unit) {
        val clean = text.trim()
        if (clean.isEmpty()) return done(null)
        if (busy) return done("Ira is still answering. Send it again when she finishes.")
        val bearer = token() ?: return done("This phone is not paired with an Ira. Pair it from Settings.")
        busy = true
        // Not listening while Ira works on this and speaks (it would hear her); back after.
        recognizer?.cancel()
        val key = "ask${++asks}:${System.currentTimeMillis()}"
        state.update { it.copy(status = CallStatus.Thinking, notice = null, caption = "") }
        val speakAnswer = voice
        var accepted = false
        stopped = false
        thread(name = "ira-ask") {
            val status =
                try {
                    Net.streamLines(
                        server.trimEnd('/') + AskStream.PATH,
                        bearer,
                        AskStream.body(clean, conversationId()),
                        onCall = { call = it },
                    ) { line ->
                        val event = AskStream.parseLine(line) ?: return@streamLines
                        main.post {
                            if (!accepted) {
                                // The server has the question: show it, and let the field clear.
                                accepted = true
                                transcript.add(Transcript.Line("$key:you", false, clean))
                                done(null)
                            }
                            onEvent(key, event, speakAnswer)
                        }
                    }
                } catch (exc: IOException) {
                    IraLog.warn("ask: failed", exc)
                    -1
                }
            main.post {
                call = null
                busy = false
                if (!accepted) {
                    done(if (status < 0) AskStream.OFFLINE else AskStream.failure(status))
                    idle()
                } else if (status < 0 && !stopped && state.value.status == CallStatus.Thinking) {
                    state.update { it.copy(notice = "The answer was cut off: the connection to your Ira dropped. Ask again.") }
                    idle()
                }
            }
        }
    }

    private fun onEvent(key: String, event: AskStream.Event, speakAnswer: Boolean) {
        if (ended) return
        when (event) {
            is AskStream.Event.Start -> if (event.conversationId.isNotBlank()) onConversation(event.conversationId)
            is AskStream.Event.Tool -> Unit
            is AskStream.Event.Action -> state.update { it.copy(action = event.card) }
            is AskStream.Event.Delta -> transcript.ira(key) { it.copy(text = it.text + event.text) }
            is AskStream.Event.Error -> {
                state.update { it.copy(notice = "Ira could not answer just now: no model replied. Ask again in a moment.") }
            }
            is AskStream.Event.Done -> {
                if (event.conversationId.isNotBlank()) onConversation(event.conversationId)
                transcript.ira(key) { it.copy(text = event.text.ifBlank { it.text }, messageId = event.messageId) }
                busy = false
                if (speakAnswer && voice && event.text.isNotBlank()) speak(event.text) else idle()
            }
        }
    }

    private fun idle() {
        if (ended) return
        if (voice) listen() else state.update { it.copy(status = CallStatus.Listening) }
    }

    override fun answer(yes: Boolean) {
        state.update { it.copy(action = null) }
        send(if (yes) "yes" else "no") { error -> if (error != null) state.update { it.copy(notice = error) } }
    }

    override fun dismissAction() {
        state.update { it.copy(action = null) }
    }

    override fun note(text: String) {
        transcript.add(Transcript.Line("note:${System.currentTimeMillis()}", true, text))
    }

    // Voice: the phone's own recognition.

    override fun startListening() {
        if (ended) return
        if (!SpeechRecognizer.isRecognitionAvailable(context) && !onDeviceAvailable()) {
            state.update { it.copy(notice = "This phone has no speech recognition. Type to Ira instead, or set up speech on your Ira for live calls.") }
            return
        }
        voice = true
        quietSince = System.currentTimeMillis()
        state.update { it.copy(mode = TalkMode.PHONE, listening = true) }
        if (!busy) listen()
    }

    /** Stop listening (the talk button again); the conversation stays for typing. */
    fun stopListening(why: String? = null) {
        voice = false
        recognizer?.cancel()
        stopSpeaking()
        state.update { it.copy(listening = false, mode = TalkMode.TEXT, status = if (busy) CallStatus.Thinking else CallStatus.Listening, caption = "", level = 0f, notice = why ?: it.notice) }
    }

    private fun onDeviceAvailable(): Boolean = Build.VERSION.SDK_INT >= 31 && SpeechRecognizer.isOnDeviceRecognitionAvailable(context)

    private fun listen() {
        if (ended || !voice || busy) return
        if (System.currentTimeMillis() - quietSince > QUIET_MS) {
            stopListening("Stopped listening after two quiet minutes. Tap the microphone to talk again.")
            return
        }
        val r = recognizer ?: create().also { recognizer = it } ?: return
        val language = info?.micLanguage ?: "hi-IN"
        val intent =
            Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE, language)
                .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                // Offline when the phone can; once the offline model failed, the online one.
                .putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, onDevice)
                .putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
        if (Build.VERSION.SDK_INT >= 34) {
            // Hindi and English told apart, as the live call does.
            intent.putExtra(RecognizerIntent.EXTRA_ENABLE_LANGUAGE_DETECTION, true)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE_DETECTION_ALLOWED_LANGUAGES, arrayListOf("hi-IN", "en-IN"))
        }
        state.update { it.copy(status = CallStatus.Listening, listening = true) }
        try {
            r.startListening(intent)
        } catch (exc: Exception) {
            IraLog.warn("speech: could not start", exc)
            stopListening("The phone's speech recognition did not start. Type to Ira, or try the microphone again.")
        }
    }

    /**
     * The phone's recognizer: on the device when it can; else an online one, the Google
     * app's first (the on-device service cannot help once its language pack is missing), and
     * never this app's own stand-in.
     */
    private fun create(): SpeechRecognizer? {
        val r =
            if (onDevice && onDeviceAvailable()) {
                IraLog.info("speech: on-device recognizer")
                SpeechRecognizer.createOnDeviceSpeechRecognizer(context)
            } else {
                onDevice = false
                val services =
                    context.packageManager.queryIntentServices(Intent(RecognitionService.SERVICE_INTERFACE), 0)
                        .map { ComponentName(it.serviceInfo.packageName, it.serviceInfo.name) }
                        .filter { it.packageName != context.packageName && it.packageName != ON_DEVICE_SERVICE }
                val chosen = services.firstOrNull { it.packageName == GOOGLE_APP } ?: services.firstOrNull()
                IraLog.info("speech: recognizer ${chosen?.packageName ?: "default"}")
                if (chosen != null) SpeechRecognizer.createSpeechRecognizer(context, chosen) else SpeechRecognizer.createSpeechRecognizer(context)
            }
        r.setRecognitionListener(listener)
        return r
    }

    /** A message on the talk screen (why voice works the way it does just now). */
    fun inform(text: String?) {
        if (text != null) state.update { it.copy(notice = text) }
    }

    private val listener =
        object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) {
                state.update { it.copy(status = CallStatus.Listening) }
            }

            override fun onBeginningOfSpeech() {
                quietSince = System.currentTimeMillis()
                state.update { it.copy(status = CallStatus.Hearing) }
            }

            override fun onRmsChanged(rmsdB: Float) {
                state.update { it.copy(level = ((rmsdB + 2f) / 12f).coerceIn(0f, 1f) * 0.1f) }
            }

            override fun onBufferReceived(buffer: ByteArray?) = Unit

            override fun onEndOfSpeech() {
                state.update { it.copy(status = CallStatus.Thinking, level = 0f) }
            }

            override fun onPartialResults(partialResults: Bundle?) {
                val text = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
                if (text.isNotBlank()) state.update { it.copy(caption = text) }
            }

            override fun onResults(results: Bundle?) {
                val text = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty().trim()
                state.update { it.copy(caption = "", level = 0f) }
                if (text.isEmpty()) return listen()
                quietSince = System.currentTimeMillis()
                send(text) { error ->
                    if (error != null) {
                        state.update { it.copy(notice = error) }
                        listen()
                    }
                }
            }

            override fun onError(error: Int) {
                IraLog.info("speech: error $error")
                state.update { it.copy(level = 0f) }
                when (error) {
                    SpeechRecognizer.ERROR_NO_MATCH, SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> main.postDelayed({ listen() }, 200)
                    SpeechRecognizer.ERROR_RECOGNIZER_BUSY, SpeechRecognizer.ERROR_CLIENT -> main.postDelayed({ listen() }, 600)
                    SpeechRecognizer.ERROR_LANGUAGE_NOT_SUPPORTED, SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE -> {
                        if (onDevice) {
                            // The on-device model lacks the language: the phone's usual recognizer instead.
                            onDevice = false
                            recognizer?.destroy()
                            recognizer = null
                            listen()
                        } else {
                            stopListening("The phone cannot recognise Hindi or English speech yet. In Android's settings, add the language to speech recognition, or type to Ira.")
                        }
                    }
                    SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS ->
                        stopListening("Ira needs the microphone permission. Allow it in Android's settings, then tap the microphone.")
                    SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT, SpeechRecognizer.ERROR_SERVER, SpeechRecognizer.ERROR_SERVER_DISCONNECTED ->
                        stopListening("The phone's speech recognition needs the internet or an offline language pack. Check the connection, or type to Ira.")
                    else -> stopListening("The phone's speech recognition stopped (error $error). Tap the microphone to try again, or type.")
                }
            }

            override fun onEvent(eventType: Int, params: Bundle?) = Unit
        }

    // Speaking the answer.

    private fun speak(text: String) {
        state.update { it.copy(status = CallStatus.Speaking) }
        val bearer = token()
        IraLog.info(if (info?.tts != null) "speak: the server's voice" else "speak: the phone's voice")
        if (info?.tts != null && bearer != null) {
            thread(name = "ira-speak") {
                val mp3 =
                    try {
                        Net.postForBytes(server.trimEnd('/') + "/v1/voice/speak", bearer, toJson(mapOf("text" to text)).toString())
                            .takeIf { it.first == 200 && it.second.isNotEmpty() }?.second
                    } catch (_: IOException) {
                        null
                    }
                main.post {
                    if (ended || !voice) return@post
                    if (mp3 != null) {
                        val p = player ?: SentencePlayer(context, this).also { player = it }
                        p.enqueue(listOf(SentenceAudio(++asks, 0, "", mp3)))
                    } else {
                        speakOnPhone(text)
                    }
                }
            }
        } else {
            speakOnPhone(text)
        }
    }

    private fun speakOnPhone(text: String) {
        val engine = tts
        if (engine == null) {
            tts =
                TextToSpeech(context) { status ->
                    main.post {
                        ttsReady = status == TextToSpeech.SUCCESS
                        if (ttsReady) speakOnPhone(text) else idle()
                    }
                }.apply { setOnUtteranceProgressListener(progress) }
            return
        }
        if (!ttsReady) return idle()
        // Devanagari is spoken as Hindi; English and Hinglish in Latin letters as Indian English.
        val locale = if (Regex("[\\u0900-\\u097F]").containsMatchIn(text)) Locale.forLanguageTag("hi-IN") else Locale.forLanguageTag("en-IN")
        if (engine.isLanguageAvailable(locale) >= TextToSpeech.LANG_AVAILABLE) engine.language = locale
        engine.speak(text, TextToSpeech.QUEUE_FLUSH, null, "ira-${System.currentTimeMillis()}")
    }

    private val progress =
        object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) = Unit

            override fun onDone(utteranceId: String?) {
                main.post { idle() }
            }

            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) {
                main.post { idle() }
            }
        }

    override fun onSentenceStarted(turn: Int, seq: Int) = Unit

    override fun onSentenceFinished(turn: Int, seq: Int) {
        idle()
    }

    private fun stopSpeaking() {
        tts?.stop()
        player?.stop()
    }

    override fun stopIra() {
        stopSpeaking()
        stopped = true
        call?.cancel()
        idle()
    }

    override fun end(reason: String?) {
        if (ended) return
        ended = true
        voice = false
        main.removeCallbacksAndMessages(null)
        call?.cancel()
        recognizer?.destroy()
        recognizer = null
        tts?.shutdown()
        player?.release()
        state.update { it.copy(status = CallStatus.Ended, listening = false, level = 0f, notice = reason ?: it.notice) }
        onEnded(reason)
    }

    private companion object {
        const val QUIET_MS = 120_000L
        const val GOOGLE_APP = "com.google.android.googlequicksearchbox"

        /** Android System Intelligence: the on-device recognizer, already tried first. */
        const val ON_DEVICE_SERVICE = "com.google.android.as"
    }
}
