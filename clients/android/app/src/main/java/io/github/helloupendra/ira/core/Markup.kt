package io.github.helloupendra.ira.core

/**
 * The Markdown models write, as spans a Text can draw: bold, italic, code and links inside a line,
 * headings and lists at its start. Anything half-written, as in an answer still streaming, stays as
 * it is until it closes.
 */
object Markup {
    data class Span(
        val text: String,
        val bold: Boolean = false,
        val italic: Boolean = false,
        val code: Boolean = false,
    )

    private val INLINE =
        Regex(
            """\*\*(.+?)\*\*|(?<![\w*])\*(?![\s*])(.+?)(?<![\s*])\*(?![\w*])|`([^`]+)`""" +
                """|\[([^\]]+)]\((https?://[^)\s]+)\)""",
        )
    private val HEADING = Regex("""^#{1,6}\s+(.*)$""")
    private val BULLET = Regex("""^(\s*)[-*]\s+""")

    fun spans(text: String): List<Span> {
        val out = ArrayList<Span>()
        text.split("\n").forEachIndexed { index, line ->
            if (index > 0) out += Span("\n")
            val heading = HEADING.find(line)?.groupValues?.get(1)
            val body = heading ?: BULLET.replace(line) { "${it.groupValues[1]}\u2022 " }
            inline(body, heading != null, out)
        }
        return out.filter { it.text.isNotEmpty() }
    }

    private fun inline(line: String, bold: Boolean, out: MutableList<Span>) {
        var at = 0
        for (match in INLINE.findAll(line)) {
            out += Span(line.substring(at, match.range.first), bold = bold)
            val (strong, italic, code, label, link) = match.destructured
            out +=
                when {
                    strong.isNotEmpty() -> Span(strong, bold = true)
                    italic.isNotEmpty() -> Span(italic, bold = bold, italic = true)
                    code.isNotEmpty() -> Span(code, bold = bold, code = true)
                    else -> Span("$label ($link)", bold = bold)
                }
            at = match.range.last + 1
        }
        out += Span(line.substring(at), bold = bold)
    }
}

/** How many messages there are: a model counts the list it is given, otherwise, as all there is. */
object SmsCount {
    fun line(found: Int, unread: Int, shown: Int, stoppedLooking: Boolean): String {
        val many = if (stoppedLooking) "$found or more" else "$found"
        val rest = if (shown < found) "; the newest $shown are here." else "."
        return "$many messages, $unread unread$rest"
    }
}
