package io.github.helloupendra.ira.core

/**
 * Notices a microphone that gives Ira nothing.
 *
 * A live microphone always picks up something: breath, a fan, the hum of the room. One that
 * Android has cut off (another app holding it, a privacy toggle, a broken route) delivers zeros,
 * or no frames at all. So when listening has run [afterMs] (3 s) and no frame rose above
 * [floor], the input is silent, and [check] says so once per listen. A frame above the floor
 * later clears it.
 */
class MicSilence(val afterMs: Double = 3000.0, val floor: Float = FLOOR) {
    /** The input stayed silent past [afterMs]; false again once a frame rises above the floor. */
    var silent = false
        private set
    private var startedAt: Double? = null
    private var heard = false
    private var told = false

    /** Listening started at this time (ms, the caller's clock). */
    fun start(at: Double) {
        startedAt = at
        heard = false
        silent = false
        told = false
    }

    /** Listening stopped: nothing to watch until the next start. */
    fun reset() {
        startedAt = null
        heard = false
        silent = false
        told = false
    }

    /** One frame of input. */
    fun feed(samples: ShortArray) {
        if (startedAt == null || EnergyVad.rms(samples) <= floor) return
        heard = true
        silent = false
    }

    /**
     * True once per listen: the moment the input has been silent for [afterMs]. Call it on each
     * frame and on a timer, since a cut-off input may send no frames at all.
     */
    fun check(at: Double): Boolean {
        val started = startedAt ?: return false
        if (heard || told || at - started < afterMs) return false
        told = true
        silent = true
        return true
    }

    companion object {
        /** About -100 dBFS: below any real room, above the zeros of a cut-off input. */
        const val FLOOR = 0.00001f
    }
}
