package io.github.helloupendra.ira.core

import kotlin.random.Random

/**
 * How long to wait before the next connection attempt, as the Mac app does
 * (`clients/macos/Sources/IraKit/Device/DeviceClient.swift`):
 *
 * - a growing delay, 1 s up to 60 s, with jitter so many phones do not retry in step;
 * - a connection that stayed up for [stableSeconds] starts the delays again from 1 s;
 * - a refused token (revoked, or never paired: 4401, 4403, or HTTP 401/403 on the
 *   handshake) waits [refusedSeconds] between tries.
 */
class Backoff(
    private val steps: List<Double> = listOf(1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
    private val stableSeconds: Double = 60.0,
    private val refusedSeconds: Double = 300.0,
    private val jitter: Boolean = true,
    private val random: Random = Random.Default,
) {
    var attempt: Int = 0
        private set

    private var connectedAt: Double? = null

    /** The connection is up (seconds on a monotonic clock). */
    fun connected(now: Double) {
        connectedAt = now
    }

    /** The connection dropped or failed: the seconds to wait before the next try. */
    fun next(now: Double, refused: Boolean = false): Double {
        val since = connectedAt
        connectedAt = null
        if (since != null && now - since >= stableSeconds) attempt = 0
        if (refused) return refusedSeconds
        val base = steps[minOf(attempt, steps.size - 1)]
        attempt++
        if (!jitter) return base
        // Up to a quarter either way, never below half a second.
        return maxOf(0.5, base * (0.75 + random.nextDouble() * 0.5))
    }

    fun reset() {
        attempt = 0
        connectedAt = null
    }

    companion object {
        /** Close codes and HTTP statuses that mean the token is no good. */
        fun isRefusal(code: Int): Boolean = code == 4401 || code == 4403 || code == 401 || code == 403
    }
}
