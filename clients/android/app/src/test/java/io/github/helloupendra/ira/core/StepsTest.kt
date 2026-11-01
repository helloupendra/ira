package io.github.helloupendra.ira.core

import org.junit.Assert.assertEquals
import org.junit.Test

class StepsTest {
    @Test
    fun `tools in words, and a word for any other`() {
        assertEquals("Looking at the AI sessions on your Mac…", Steps.phrase("ai_sessions"))
        assertEquals("Searching the web…", Steps.phrase("web_search"))
        assertEquals("Working…", Steps.phrase("something_new"))
    }

    @Test
    fun `receipts and the seconds after three`() {
        assertEquals("web search · 1.2 s", Steps.receipt("web_search", 1.24))
        assertEquals("ai sessions · 13 s", Steps.receipt("ai_sessions", 12.6))
        assertEquals("Thinking…", Steps.line(Steps.THINKING, 2))
        assertEquals("Searching the web… 5 s", Steps.line("Searching the web…", 5))
    }

    @Test
    fun `tool steps on a live call`() {
        assertEquals(Live.Tool(3, "web_search"), LiveProtocol.parse("""{"type":"tool","turn":3,"name":"web_search"}"""))
        assertEquals(Live.ToolResult(3, "web_search", false), LiveProtocol.parse("""{"type":"tool_result","turn":3,"name":"web_search","ok":false}"""))
        assertEquals(AskStream.Event.ToolResult("web_search", true), AskStream.parseLine("""data: {"type":"tool_result","name":"web_search","ok":true}"""))
    }
}
