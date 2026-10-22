package io.github.helloupendra.ira.tools

import io.github.helloupendra.ira.core.toJson
import kotlinx.serialization.json.JsonElement

/**
 * A tool's answer: a JSON object with a short `summary` (what a no-key demo reads out, and
 * a help to the model) and the details. Text is capped so a result stays well under the
 * server's 1 MB frame.
 */
object Results {
    const val MAX_TEXT = 2_000

    fun of(vararg pairs: Pair<String, Any?>): JsonElement = toJson(pairs.filter { it.second != null }.toMap())

    fun clip(text: String?, max: Int = MAX_TEXT): String? = text?.let { if (it.length <= max) it else it.take(max - 1) + "…" }
}
