package io.github.helloupendra.ira.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DropTest {
    private val file =
        """{"id": 42, "kind": "file", "text": "v2", "name": "plan.pdf", "mime": "application/pdf", "size": 3000,
            "sha256": "ab", "from_device_id": 7, "from_label": "Mac", "created_at": "2026-10-30T10:00:00Z", "expires_at": "2026-11-29T10:00:00Z"}"""

    @Test
    fun `a page of items, newest first, and whether there are older ones`() {
        val page = Drop.page("""{"items": [$file, {"id": 41, "kind": "link", "text": "https://example.com/a", "from_label": "Web"}], "has_more": true}""")!!
        assertEquals(listOf(42L, 41L), page.items.map { it.id })
        assertTrue(page.hasMore)
        val pdf = page.items[0]
        assertEquals(Drop.Item(42, "file", "v2", "plan.pdf", "application/pdf", 3000, "ab", 7, "Mac", "2026-10-30T10:00:00Z"), pdf)
        assertTrue(pdf.isFile)
        assertEquals("https://example.com/a", page.items[1].link)
        assertNull(Drop.page("""{"detail": "no"}"""))
    }

    @Test
    fun `only a plain http address is a link to open`() {
        fun item(kind: String, text: String) = Drop.Item(1, kind, text, null, null, null, null, null, "Web", "")
        assertEquals("https://example.com", item("link", " https://example.com ").link)
        assertNull(item("link", "javascript:alert(1)").link)
        assertNull(item("link", "intent://x#Intent;end").link)
        assertNull(item("text", "https://example.com").link)
    }

    @Test
    fun `addresses for a page, the next older page, and catching up`() {
        assertEquals("https://ira.example.com/v1/me/drop?limit=50", Drop.listUrl("https://ira.example.com/"))
        assertEquals("https://ira.example.com/v1/me/drop?limit=50&before_id=40", Drop.listUrl("https://ira.example.com", beforeId = 40))
        assertEquals("https://ira.example.com/v1/me/drop?limit=50&after_id=42", Drop.listUrl("https://ira.example.com", afterId = 42))
        assertEquals("https://ira.example.com/v1/me/drop/42/file", Drop.fileUrl("https://ira.example.com", 42))
        assertEquals("""{"text":"call the CA"}""", Drop.textBody("call the CA"))
        assertEquals(50, Drop.maxFileMb("""{"telegram": true, "max_file_mb": 50}"""))
        assertEquals(Drop.MAX_FILE_MB, Drop.maxFileMb("not json"))
    }

    @Test
    fun `a live frame, a page and a catch-up merge without twins`() {
        fun item(id: Long) = Drop.Item(id, "text", "n$id", null, null, null, null, null, "Web", "")
        assertEquals(listOf(5L, 4L, 3L, 2L), Drop.merge(listOf(item(4), item(3), item(2)), listOf(item(5), item(3))).map { it.id })
    }

    @Test
    fun `saved names never leave the folder, and previews stay short`() {
        assertEquals("plan.pdf", Drop.safeName("../../plan.pdf"))
        assertEquals("evil.sh", Drop.safeName("C:\\x\\evil.sh"))
        assertEquals("file", Drop.safeName(" .. "))
        assertEquals("file", Drop.safeName(null))
        assertEquals("ab", Drop.safeName("a\u0000b"))
        assertEquals("plan.pdf (2.9 KB): v2", Drop.preview(Drop.item(parseObject(file)!!)!!))
        assertEquals(200, Drop.preview(Drop.Item(1, "text", "x".repeat(500), null, null, null, null, null, "Web", "")).length)
        assertEquals("512 B", Drop.size(512))
        assertEquals("1.5 MB", Drop.size(1572864))
    }

    @Test
    fun `what another app shared becomes one text`() {
        assertEquals("Look https://example.com/a", Drop.sharedText(" Look https://example.com/a ", "A page"))
        assertEquals("A page", Drop.sharedText(null, "A page"))
        assertEquals("", Drop.sharedText(null, null))
    }

    @Test
    fun `drop frames from the device link`() {
        val new = DeviceProtocol.parse("""{"type": "drop", "event": "new", "item": $file}""") as DeviceFrame.Drop
        assertEquals("new", new.event)
        assertEquals(42L, new.item?.id)
        val gone = DeviceProtocol.parse("""{"type": "drop", "event": "deleted", "id": 42}""") as DeviceFrame.Drop
        assertEquals(42L, gone.id)
        assertNull(gone.item)
        assertTrue(DeviceProtocol.parse("""{"type": "drop", "event": "new"}""") is DeviceFrame.Unknown)
    }
}
