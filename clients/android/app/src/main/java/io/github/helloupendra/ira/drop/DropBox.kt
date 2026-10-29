package io.github.helloupendra.ira.drop

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.provider.OpenableColumns
import android.widget.Toast
import androidx.core.app.NotificationCompat
import io.github.helloupendra.ira.IraApp
import io.github.helloupendra.ira.R
import io.github.helloupendra.ira.core.DeviceFrame
import io.github.helloupendra.ira.core.Drop
import io.github.helloupendra.ira.core.HttpReply
import io.github.helloupendra.ira.core.parseObject
import io.github.helloupendra.ira.core.string
import io.github.helloupendra.ira.net.IraLog
import io.github.helloupendra.ira.net.Net
import io.github.helloupendra.ira.tools.PhoneState
import io.github.helloupendra.ira.ui.MainActivity
import java.io.IOException
import java.io.OutputStream
import java.security.MessageDigest
import kotlin.concurrent.thread
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update

/**
 * This phone's view of the person's Drop: the items, newest first, kept current by the
 * device link's `drop` frames while it runs, and caught up when it connects again. It sends
 * text and files, saves a file to Downloads/Ira, and says when something arrives from
 * another device, with Copy. Nothing it sends or saves is ever logged, only that it happened.
 */
class DropBox(private val app: IraApp) {
    /** A file on its way, for its progress bar; [error] when it did not go. */
    data class Sending(val key: Long, val name: String, val progress: Float, val error: String? = null)

    private val main = Handler(Looper.getMainLooper())
    private val list = MutableStateFlow<List<Drop.Item>>(emptyList())
    val items: StateFlow<List<Drop.Item>> = list
    private val older = MutableStateFlow(false)
    val hasMore: StateFlow<Boolean> = older
    private val sending = MutableStateFlow<List<Sending>>(emptyList())
    val uploads: StateFlow<List<Sending>> = sending
    private var loaded = false
    private var maxFileMb = Drop.MAX_FILE_MB

    /** The Drop screen is in front: new items show there, not as notifications. */
    @Volatile
    var visible = false

    private fun paired(): Pair<String, String>? {
        val server = app.settings.server ?: return null
        val token = app.secrets.token() ?: return null
        return server to token
    }

    /** Run [work] off the main thread, then [done] on it with what went wrong, or null. */
    private fun background(name: String, done: (String?) -> Unit, work: (server: String, token: String) -> String?) {
        val (server, token) = paired() ?: return done(NOT_PAIRED)
        thread(name = name) {
            val problem =
                try {
                    work(server, token)
                } catch (_: IOException) {
                    OFFLINE
                }
            main.post { done(problem) }
        }
    }

    private fun refused(reply: HttpReply): String =
        when (reply.status) {
            401 -> "Your Ira did not accept this phone. Pair it again in Settings."
            403 -> "Your account on this Ira cannot use Drop."
            else -> parseObject(reply.body)?.string("detail") ?: "Your Ira answered HTTP ${reply.status}."
        }

    /** The newest items, from the server. */
    fun refresh(done: (String?) -> Unit = {}) =
        background("ira-drop", done) { server, token ->
            val reply = Net.get(Drop.listUrl(server), token)
            val page = Drop.page(reply.body)
            if (reply.status != 200 || page == null) return@background refused(reply)
            Net.get("${server.trimEnd('/')}${Drop.PATH}/settings", token).takeIf { it.status == 200 }?.let { maxFileMb = Drop.maxFileMb(it.body) }
            main.post {
                list.value = page.items
                older.value = page.hasMore
                loaded = true
            }
            null
        }

    /** The next page of older items. */
    fun loadOlder(done: (String?) -> Unit = {}) {
        val oldest = list.value.lastOrNull() ?: return done(null)
        background("ira-drop", done) { server, token ->
            val reply = Net.get(Drop.listUrl(server, beforeId = oldest.id), token)
            val page = Drop.page(reply.body) ?: return@background refused(reply)
            main.post {
                list.update { Drop.merge(it, page.items) }
                older.value = page.hasMore
            }
            null
        }
    }

    /** The link is up again: what arrived meanwhile (quietly: the person was not here for it). */
    fun catchUp() {
        if (!loaded) return
        val newest = list.value.firstOrNull() ?: return refresh()
        background("ira-drop", {}) { server, token ->
            val page = Drop.page(Net.get(Drop.listUrl(server, afterId = newest.id), token).body) ?: return@background null
            main.post { list.update { Drop.merge(it, page.items) } }
            null
        }
    }

    /** A frame from the device link: a new item from another device, or one deleted there. */
    fun onFrame(frame: DeviceFrame.Drop) {
        when (frame.event) {
            "new" -> {
                val item = frame.item ?: return
                list.update { Drop.merge(it, listOf(item)) }
                if (!visible && item.fromDeviceId != app.settings.deviceId) notify(item)
            }
            "deleted" -> list.update { items -> items.filterNot { it.id == frame.id } }
        }
    }

    fun sendText(text: String, done: (String?) -> Unit) {
        val clean = text.trim()
        if (clean.isEmpty()) return done("Nothing to send.")
        background("ira-drop-send", done) { server, token ->
            val reply = Net.postJson("${server.trimEnd('/')}${Drop.PATH}", token, Drop.textBody(clean))
            val item = Drop.item(reply.body)
            if (reply.status != 201 || item == null) return@background refused(reply)
            IraLog.info("drop: sent ${item.kind}")
            main.post { list.update { Drop.merge(it, listOf(item)) } }
            null
        }
    }

    /**
     * Send files one after another, each with a progress bar; [caption] goes with the first.
     * [done] gets null when all went, else what went wrong with the last that did not.
     */
    fun sendFiles(uris: List<Uri>, caption: String?, done: (String?) -> Unit = {}) {
        val (server, token) = paired() ?: return done(NOT_PAIRED)
        val resolver = app.contentResolver
        thread(name = "ira-drop-send") {
            var problem: String? = null
            for ((index, uri) in uris.withIndex()) {
                val (name, length) = describe(uri)
                val key = System.nanoTime()
                val show = { progress: Float, error: String? ->
                    main.post {
                        sending.update { all -> all.filterNot { it.key == key } + Sending(key, name, progress, error) }
                    }
                }
                val failed = { why: String ->
                    show(0f, why)
                    problem = why
                }
                if (length > maxFileMb * 1024L * 1024L) {
                    failed("$name is over $maxFileMb MB, too large for Drop.")
                    continue
                }
                show(0f, null)
                try {
                    val reply =
                        Net.upload(
                            "${server.trimEnd('/')}${Drop.PATH}",
                            token,
                            name,
                            resolver.getType(uri),
                            length,
                            caption.takeIf { index == 0 },
                            { resolver.openInputStream(uri) ?: throw IOException("unreadable") },
                        ) { part -> show(part, null) }
                    val item = Drop.item(reply.body)
                    if (reply.status != 201 || item == null) {
                        failed(refused(reply))
                        continue
                    }
                    IraLog.info("drop: sent a file")
                    main.post {
                        sending.update { all -> all.filterNot { it.key == key } }
                        list.update { Drop.merge(it, listOf(item)) }
                    }
                } catch (exc: IOException) {
                    IraLog.warn("drop: a file did not go", exc)
                    failed(if (exc.message == "unreadable") "$name could not be read." else OFFLINE)
                } catch (exc: SecurityException) {
                    failed("$name could not be read.")
                }
            }
            main.post { done(problem) }
        }
    }

    /** Forget the progress rows that ended in an error. */
    fun clearFailed() {
        sending.update { all -> all.filter { it.error == null } }
    }

    /** A shared or picked file's name and size, as its app says them; -1 when unknown. */
    fun describe(uri: Uri): Pair<String, Long> {
        var name: String? = null
        var length = -1L
        try {
            app.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { cursor ->
                if (cursor.moveToFirst()) {
                    name = cursor.getString(0)
                    if (!cursor.isNull(1)) length = cursor.getLong(1)
                }
            }
        } catch (_: Exception) {
        }
        return Drop.safeName(name ?: uri.lastPathSegment) to length
    }

    fun delete(item: Drop.Item, done: (String?) -> Unit) =
        background("ira-drop", done) { server, token ->
            val status = Net.delete(Drop.itemUrl(server, item.id), token)
            if (status !in 200..299 && status != 404) return@background "Your Ira answered HTTP $status."
            main.post { list.update { items -> items.filterNot { it.id == item.id } } }
            null
        }

    /**
     * Save a file to Downloads/Ira, checked against its SHA-256 as it comes; [done] gets the
     * saved file to open, or what went wrong. Needs no storage permission (Android 10 and up).
     */
    fun save(item: Drop.Item, done: (Uri?, String?) -> Unit) {
        val (server, token) = paired() ?: return done(null, NOT_PAIRED)
        val resolver = app.contentResolver
        thread(name = "ira-drop-save") {
            val values =
                ContentValues().apply {
                    put(MediaStore.Downloads.DISPLAY_NAME, Drop.safeName(item.name))
                    put(MediaStore.Downloads.MIME_TYPE, item.mime ?: "application/octet-stream")
                    put(MediaStore.Downloads.RELATIVE_PATH, "${Environment.DIRECTORY_DOWNLOADS}/Ira")
                    put(MediaStore.Downloads.IS_PENDING, 1)
                }
            val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
            if (uri == null) {
                main.post { done(null, "This phone would not make a file in Downloads.") }
                return@thread
            }
            val digest = MessageDigest.getInstance("SHA-256")
            val problem =
                try {
                    val status =
                        (resolver.openOutputStream(uri) ?: throw IOException("no output")).use { out ->
                            Net.download(Drop.fileUrl(server, item.id), token, Hashing(out, digest))
                        }
                    val hash = digest.digest().joinToString("") { "%02x".format(it) }
                    when {
                        status == 404 -> "That item is not in your Drop any more."
                        status != 200 -> "Your Ira answered HTTP $status."
                        item.sha256 != null && hash != item.sha256 -> "The download did not match the file. Try again."
                        else -> null
                    }
                } catch (exc: IOException) {
                    IraLog.warn("drop: a file did not save", exc)
                    OFFLINE
                }
            if (problem == null) {
                resolver.update(uri, ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) }, null, null)
                IraLog.info("drop: saved a file")
            } else {
                resolver.delete(uri, null, null)
            }
            main.post { if (problem == null) done(uri, null) else done(null, problem) }
        }
    }

    /** A new item from another device, with Copy for text and links; a tap opens Drop. */
    private fun notify(item: Drop.Item) {
        if (!PhoneState.has(app, android.Manifest.permission.POST_NOTIFICATIONS)) return
        val nm = app.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "Drop", NotificationManager.IMPORTANCE_DEFAULT))
        val id = (item.id % 100_000).toInt() + 200_000
        val open =
            PendingIntent.getActivity(
                app,
                id,
                Intent(app, MainActivity::class.java).setAction(MainActivity.ACTION_DROP),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
        val text = Drop.preview(item)
        val builder =
            NotificationCompat.Builder(app, CHANNEL)
                .setSmallIcon(R.drawable.ic_ira)
                .setContentTitle("In your Drop, from ${item.fromLabel.ifBlank { "a device" }}")
                .setContentText(text)
                .setStyle(NotificationCompat.BigTextStyle().bigText(text))
                .setContentIntent(open)
                .setAutoCancel(true)
        if (!item.isFile && !item.text.isNullOrEmpty()) {
            val copy =
                Intent(app, CopyReceiver::class.java)
                    .putExtra(CopyReceiver.TEXT, item.text)
                    .putExtra(CopyReceiver.NOTIFICATION, id)
            builder.addAction(0, "Copy", PendingIntent.getBroadcast(app, id, copy, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT))
        }
        nm.notify(id, builder.build())
    }

    /** Writes through to [out] and into [digest]. */
    private class Hashing(private val out: OutputStream, private val digest: MessageDigest) : OutputStream() {
        override fun write(b: Int) {
            out.write(b)
            digest.update(b.toByte())
        }

        override fun write(b: ByteArray, off: Int, len: Int) {
            out.write(b, off, len)
            digest.update(b, off, len)
        }

        override fun flush() = out.flush()
    }

    companion object {
        const val CHANNEL = "ira_drop"
        private const val NOT_PAIRED = "This phone is not paired with an Ira. Pair it from Settings."
        private const val OFFLINE = "Could not reach your Ira. Check that the phone is online, then try again."

        /** Put text on the clipboard and say so (Android 13 and up say it themselves). */
        fun copy(context: Context, text: String) {
            val clipboard = context.getSystemService(ClipboardManager::class.java) ?: return
            clipboard.setPrimaryClip(ClipData.newPlainText("Drop", text))
            if (Build.VERSION.SDK_INT < 33) Toast.makeText(context, "Copied", Toast.LENGTH_SHORT).show()
        }
    }
}

/** The notification's Copy: the item's text onto the clipboard, and the notification goes. */
class CopyReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val text = intent.getStringExtra(TEXT) ?: return
        DropBox.copy(context, text)
        context.getSystemService(NotificationManager::class.java)?.cancel(intent.getIntExtra(NOTIFICATION, 0))
    }

    companion object {
        const val TEXT = "text"
        const val NOTIFICATION = "notification"
    }
}
