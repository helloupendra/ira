package io.github.helloupendra.ira.core

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * Drop (`docs/api.md`): the person's own inbox, shared by their own devices. Text, a link or
 * a file sent from one is on the others at once. This phone lists it, sends to it, and hears
 * of changes on its device WebSocket as `drop` frames while the link is up.
 */
object Drop {
    const val PATH = "/v1/me/drop"

    /** What the server takes unless it says otherwise (`/v1/me/drop/settings`). */
    const val MAX_FILE_MB = 95

    private val LINK = Regex("^https?://\\S+$", RegexOption.IGNORE_CASE)

    data class Item(
        val id: Long,
        /** text, link or file. */
        val kind: String,
        /** The text or link; a file's caption. */
        val text: String?,
        val name: String?,
        val mime: String?,
        val size: Long?,
        val sha256: String?,
        val fromDeviceId: Int?,
        /** The device's name, or Web, CLI, Telegram, Ira. */
        val fromLabel: String,
        val createdAt: String,
    ) {
        val isFile: Boolean
            get() = kind == "file"

        /** A link this phone may open: one http(s) address, nothing else. */
        val link: String?
            get() = text?.trim()?.takeIf { kind == "link" && LINK.matches(it) }
    }

    data class Page(val items: List<Item>, val hasMore: Boolean)

    fun item(o: JsonObject): Item? {
        val id = o.long("id") ?: return null
        val kind = o.string("kind") ?: return null
        return Item(
            id = id,
            kind = kind,
            text = o.string("text"),
            name = o.string("name"),
            mime = o.string("mime"),
            size = o.long("size"),
            sha256 = o.string("sha256"),
            fromDeviceId = o.int("from_device_id"),
            fromLabel = o.string("from_label").orEmpty(),
            createdAt = o.string("created_at").orEmpty(),
        )
    }

    fun item(body: String): Item? = parseObject(body)?.let(::item)

    fun page(body: String): Page? {
        val o = parseObject(body) ?: return null
        val items = o.array("items")?.mapNotNull { (it as? JsonObject)?.let(::item) } ?: return null
        return Page(items, o.bool("has_more") == true)
    }

    /** The largest file the server takes, from its Drop settings. */
    fun maxFileMb(body: String): Int = parseObject(body)?.int("max_file_mb")?.takeIf { it > 0 } ?: MAX_FILE_MB

    fun listUrl(server: String, afterId: Long? = null, beforeId: Long? = null, limit: Int = 50): String {
        val query = buildList {
            add("limit=$limit")
            afterId?.let { add("after_id=$it") }
            beforeId?.let { add("before_id=$it") }
        }
        return "${server.trimEnd('/')}$PATH?${query.joinToString("&")}"
    }

    fun itemUrl(server: String, id: Long): String = "${server.trimEnd('/')}$PATH/$id"

    fun fileUrl(server: String, id: Long): String = "${itemUrl(server, id)}/file"

    fun textBody(text: String): String = jsonText { put("text", JsonPrimitive(text)) }

    /** Newest first, each item once: a page, a live frame and a catch-up all go through here. */
    fun merge(current: List<Item>, more: List<Item>): List<Item> = (more + current).distinctBy { it.id }.sortedByDescending { it.id }

    /**
     * What another app shared, as one text: its words (a page's address usually among them),
     * else its subject. The same rule as the web app's Share → Ira.
     */
    fun sharedText(text: String?, subject: String?): String = text?.trim().orEmpty().ifEmpty { subject?.trim().orEmpty() }

    /** Sizes as people say them. */
    fun size(bytes: Long): String =
        when {
            bytes < 1024 -> "$bytes B"
            bytes < 1024 * 1024 -> "%.1f KB".format(bytes / 1024.0)
            else -> "%.1f MB".format(bytes / 1024.0 / 1024.0)
        }

    /** A file name safe to save here: no folders, no control characters, never empty. */
    fun safeName(name: String?): String {
        val base = (name ?: "").replace('\\', '/').substringAfterLast('/')
        val clean = base.replace(Regex("[\\x00-\\x1f\\x7f]"), "").trim(' ', '.')
        return clean.take(200).ifEmpty { "file" }
    }

    /** One line for a notification or a list: a file's name and size, or the text. */
    fun preview(item: Item): String {
        val text = (item.text ?: "").replace(Regex("\\s+"), " ").trim()
        val line =
            if (item.isFile) {
                "${safeName(item.name)} (${size(item.size ?: 0)})" + if (text.isNotEmpty()) ": $text" else ""
            } else {
                text
            }
        return if (line.length <= 200) line else line.take(199) + "…"
    }
}
