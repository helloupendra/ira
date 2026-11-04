package io.github.helloupendra.ira.core

import org.junit.Assert.assertEquals
import org.junit.Test

class MarkupTest {
    private fun plain(text: String) = Markup.spans(text).joinToString("") { it.text }

    @Test
    fun `bold loses its stars, in any script`() {
        val spans = Markup.spans("\u0915\u0941\u0932 **20** SMS")
        assertEquals("\u0915\u0941\u0932 20 SMS", spans.joinToString("") { it.text })
        assertEquals(listOf("20"), spans.filter { it.bold }.map { it.text })
    }

    @Test
    fun `italic and code`() {
        val spans = Markup.spans("an *easy* one, run `ls -l`")
        assertEquals("an easy one, run ls -l", spans.joinToString("") { it.text })
        assertEquals(listOf("easy"), spans.filter { it.italic }.map { it.text })
        assertEquals(listOf("ls -l"), spans.filter { it.code }.map { it.text })
    }

    @Test
    fun `headings are bold and lists get a bullet`() {
        val spans = Markup.spans("## Today\n- one\n* two\n  - three")
        assertEquals("Today\n\u2022 one\n\u2022 two\n  \u2022 three", spans.joinToString("") { it.text })
        assertEquals(listOf("Today"), spans.filter { it.bold }.map { it.text })
    }

    @Test
    fun `a link keeps its address in sight`() {
        assertEquals(
            "the page (https://example.com/a) now",
            plain("[the page](https://example.com/a) now"),
        )
    }

    @Test
    fun `what only looks like Markdown stays`() {
        for (text in listOf("2*3*4 is 24", "5 * 6 * 7", "a_b_c.py", "**half written", "#1 on the list")) {
            assertEquals(text, plain(text))
        }
    }

    @Test
    fun `the count of messages says what the list leaves out`() {
        assertEquals("32 messages, 0 unread; the newest 5 are here.", SmsCount.line(32, 0, 5, false))
        assertEquals("2 messages, 1 unread.", SmsCount.line(2, 1, 2, false))
        assertEquals("500 or more messages, 3 unread; the newest 5 are here.", SmsCount.line(500, 3, 5, true))
    }
}
