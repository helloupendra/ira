package io.github.helloupendra.ira.core

/**
 * The turn-taking of one live call, with no Android in it: what the voice detector and
 * the server say go in, and what the app must do comes out as [Effect]s.
 *
 * Barge-in: when the person starts speaking while Ira answers (thinking or talking), the
 * app stops playing at once, without waiting for the server, drops every sentence of the
 * answer it already has or will still receive, and sends `speech_start`, which the server
 * takes as the interruption. Audio of an interrupted turn that was already on its way is
 * dropped here, so nothing of the old answer is heard after the person spoke.
 */
class CallMachine(private val assembler: AudioAssembler = AudioAssembler()) {
    enum class Phase { Connecting, Listening, UserSpeaking, Thinking, Speaking }

    sealed interface Effect {
        /** A JSON text frame for the server. */
        data class Send(val json: String) : Effect

        /** Stop the speaker now and forget what is queued. */
        data object StopPlayback : Effect

        /** Queue these sentences, in this order, after what is already queued. */
        data class Play(val sentences: List<SentenceAudio>) : Effect

        /** A proposed action to show: a yes for Tier 2, the PIN in the Ira app for Tier 3. */
        data class ShowAction(val turn: Int, val card: ActionCard) : Effect

        /** The server ended the call (a fatal error): say why and stop. */
        data class End(val reason: String) : Effect
    }

    var phase: Phase = Phase.Connecting
        private set

    /** The highest turn number the server has used so far. */
    var latestTurn: Int = 0
        private set

    /** True while sentences are playing: the voice detector raises its threshold. */
    var playing: Boolean = false
        private set

    var conversationId: String? = null
        private set

    private val doneTurns = HashSet<Int>()
    private val playedTurns = HashSet<Int>()
    private var queued = 0

    val droppedThrough: Int
        get() = assembler.droppedThrough

    // The voice detector.

    fun onSpeechStart(at: Double): List<Effect> {
        val out = ArrayList<Effect>()
        if (phase == Phase.Thinking || phase == Phase.Speaking || playing) {
            out += bargeIn()
        }
        phase = Phase.UserSpeaking
        out += Effect.Send(LiveProtocol.speechStart(at))
        return out
    }

    fun onSpeechEnd(at: Double): List<Effect> {
        phase = Phase.Thinking
        return listOf(Effect.Send(LiveProtocol.speechEnd(at)))
    }

    // The person's buttons.

    /** The stop button: stop talking and stop this answer. */
    fun stop(): List<Effect> {
        val out = ArrayList<Effect>()
        out += bargeIn()
        out += Effect.Send(LiveProtocol.interrupt())
        if (phase != Phase.UserSpeaking) phase = Phase.Listening
        return out
    }

    /** A typed turn. While Ira is answering, it stops her first, as speaking would. */
    fun typed(text: String): List<Effect> {
        val clean = text.trim()
        if (clean.isEmpty()) return emptyList()
        val out = ArrayList<Effect>()
        if (phase == Phase.Thinking || phase == Phase.Speaking || playing) {
            out += bargeIn()
            out += Effect.Send(LiveProtocol.interrupt())
        }
        out += Effect.Send(LiveProtocol.text(clean))
        phase = Phase.Thinking
        return out
    }

    // The server.

    fun onServer(message: Live, now: Double): List<Effect> {
        assembler.onMessage(message)
        return when (message) {
            is Live.Ready -> {
                conversationId = message.conversationId.ifBlank { null }
                phase = Phase.Listening
                emptyList()
            }
            is Live.Heard -> {
                seen(message.turn)
                if (phase != Phase.UserSpeaking) phase = Phase.Thinking
                emptyList()
            }
            is Live.Delta, is Live.AudioHeader, is Live.Partial -> {
                if (message is Live.Delta) seen(message.turn)
                if (message is Live.AudioHeader) seen(message.turn)
                emptyList()
            }
            is Live.Action -> {
                seen(message.turn)
                if (message.turn <= assembler.droppedThrough) emptyList()
                else listOf(Effect.ShowAction(message.turn, message.card))
            }
            is Live.Done -> {
                seen(message.turn)
                doneTurns += message.turn
                if (!playing && phase == Phase.Thinking && message.turn >= latestTurn) phase = Phase.Listening
                emptyList()
            }
            is Live.Interrupted -> {
                val out = ArrayList<Effect>()
                if (playing) {
                    out += Effect.StopPlayback
                    playing = false
                    queued = 0
                }
                if (phase == Phase.Speaking || phase == Phase.Thinking) phase = Phase.Listening
                out
            }
            is Live.Ping -> listOf(Effect.Send(LiveProtocol.pong()))
            is Live.Error ->
                if (message.fatal) {
                    listOf(Effect.End(message.message))
                } else {
                    if (phase == Phase.Thinking) phase = Phase.Listening
                    emptyList()
                }
            is Live.Unknown -> emptyList()
        }
    }

    fun onBinary(bytes: ByteArray): List<Effect> {
        val ready = assembler.onBinary(bytes)
        if (ready.isEmpty()) return emptyList()
        queued += ready.size
        return listOf(Effect.Play(ready))
    }

    // The player.

    /** A sentence began to play: the first one of a turn is reported as `played`. */
    fun onSentenceStarted(turn: Int, at: Double): List<Effect> {
        if (turn <= assembler.droppedThrough) return emptyList()
        playing = true
        if (phase != Phase.UserSpeaking) phase = Phase.Speaking
        if (playedTurns.add(turn)) return listOf(Effect.Send(LiveProtocol.played(turn, at)))
        return emptyList()
    }

    fun onSentenceFinished() {
        if (queued > 0) queued--
        if (queued == 0) {
            playing = false
            if (phase == Phase.Speaking) {
                phase = if (latestTurn in doneTurns) Phase.Listening else Phase.Thinking
            }
        }
    }

    private fun bargeIn(): List<Effect> {
        // Stopping an idle player is harmless, and a sentence may be about to start.
        assembler.drop(latestTurn)
        playing = false
        queued = 0
        return listOf(Effect.StopPlayback)
    }

    private fun seen(turn: Int) {
        if (turn > latestTurn) latestTurn = turn
    }
}
