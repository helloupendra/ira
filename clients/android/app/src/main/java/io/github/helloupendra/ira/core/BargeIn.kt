package io.github.helloupendra.ira.core

/**
 * Speech heard while Ira speaks is the person talking over her, or her own voice from the
 * speaker, which echo cancelling does not always take out. Stopping her for her own echo cut
 * her answers short. So it is checked first: her voice is turned down at once, and if the
 * sound stays loud for [Config.checkMs] with her quieter, it may be the person, and it goes to
 * the server, whose speech-to-text decides by the words (`interrupted` stops her,
 * `speech_ignored` brings her back up). If it fades with her voice, it was her echo, and
 * nothing is sent.
 */
class BargeIn(private val config: Config = Config()) {
    data class Config(val checkMs: Double = 300.0, val loudShare: Double = 0.6)

    sealed interface Step {
        /** Turn Ira down while the sound is checked. */
        data object Duck : Step

        /** It may be the person: send their speech, with what was held. */
        data class Confirm(val held: List<EnergyVad.Output>) : Step

        /** It was Ira's own voice: turn her up again, and forget it. */
        data object Release : Step
    }

    private var since: Double? = null
    private var frames = 0
    private var loud = 0
    private val held = ArrayList<EnergyVad.Output>()

    /** A check is going on: the voice detector's outputs are held. */
    val checking: Boolean
        get() = since != null

    /** One frame's voice-detector outputs while Ira speaks (or while a check goes on). */
    fun feed(outputs: List<EnergyVad.Output>, isLoud: Boolean, at: Double): List<Step> {
        val began = since
        if (began == null) {
            val index = outputs.indexOfFirst { it is EnergyVad.Output.SpeechStart }
            if (index < 0) return emptyList()
            since = at
            frames = 0
            loud = 0
            held.clear()
            held.addAll(outputs.subList(index, outputs.size))
            return listOf(Step.Duck)
        }
        held.addAll(outputs)
        frames++
        if (isLoud) loud++
        if (outputs.any { it is EnergyVad.Output.SpeechEnd }) {
            reset() // over before it was checked: too short to be the person talking over her
            return listOf(Step.Release)
        }
        if (at - began < config.checkMs) return emptyList()
        val person = loud >= config.loudShare * maxOf(frames, 1)
        val kept = held.toList()
        reset()
        return listOf(if (person) Step.Confirm(kept) else Step.Release)
    }

    fun reset() {
        since = null
        frames = 0
        loud = 0
        held.clear()
    }
}
