package io.github.helloupendra.ira.core

import kotlin.random.Random
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class BackoffTest {
    @Test
    fun `delays grow from 1 s to 60 s and stay there`() {
        val b = Backoff(jitter = false)
        val waits = List(8) { b.next(now = it.toDouble()) }
        assertEquals(listOf(1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 60.0, 60.0), waits)
    }

    @Test
    fun `a connection that lasted a minute starts again from 1 s`() {
        val b = Backoff(jitter = false)
        repeat(4) { b.next(0.0) }
        b.connected(100.0)
        assertEquals(1.0, b.next(170.0), 0.0)
        assertEquals(2.0, b.next(171.0), 0.0)
    }

    @Test
    fun `a short-lived connection keeps growing`() {
        val b = Backoff(jitter = false)
        b.next(0.0)
        b.connected(10.0)
        assertEquals(2.0, b.next(20.0), 0.0)
    }

    @Test
    fun `a refused token waits five minutes`() {
        val b = Backoff(jitter = false)
        assertEquals(300.0, b.next(0.0, refused = true), 0.0)
        assertTrue(Backoff.isRefusal(4401))
        assertTrue(Backoff.isRefusal(4403))
        assertTrue(Backoff.isRefusal(403))
        assertTrue(!Backoff.isRefusal(1006))
        assertTrue(!Backoff.isRefusal(4408))
    }

    @Test
    fun `jitter stays within a quarter either way`() {
        val b = Backoff(random = Random(1))
        repeat(50) {
            b.reset()
            repeat(3) { b.next(0.0) }
            val wait = b.next(0.0)
            assertTrue(wait in 7.5..12.5)
        }
    }
}
