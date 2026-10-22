package io.github.helloupendra.ira.core

import io.github.helloupendra.ira.core.Screen.Node
import io.github.helloupendra.ira.core.Screen.Plan
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ScreenTest {
    private val own = "io.github.helloupendra.ira.personal"
    private val youtube = "com.google.android.youtube"

    @Test
    fun `never Ira's own window - the named app is brought back, or Ira steps aside`() {
        assertEquals(Plan.Bring("YouTube"), Screen.plan(own, own, "YouTube"))
        assertEquals(Plan.StepAside, Screen.plan(own, own, null))
        assertEquals(Plan.StepAside, Screen.plan(null, own, ""))
    }

    @Test
    fun `another app in front is used, unless a different one was named`() {
        assertEquals(Plan.Proceed, Screen.plan(youtube, own, null, "YouTube"))
        assertEquals(Plan.Proceed, Screen.plan(youtube, own, "youtube", "YouTube"))
        assertEquals(Plan.Proceed, Screen.plan(youtube, own, youtube, "YouTube"))
        assertEquals(Plan.Bring("WhatsApp"), Screen.plan(youtube, own, "WhatsApp", "YouTube"))
        assertEquals("WhatsApp is not on screen (YouTube is); open it first with app_open, or use url_open", Screen.notInFront("WhatsApp", "YouTube"))
    }

    // YouTube's home screen, as its Accessibility tree looks: the search icon has no text.
    private val home =
        Node(
            role = "android.widget.FrameLayout",
            children =
                listOf(
                    Node(description = "YouTube", role = "android.widget.ImageView"),
                    Node(description = "Cast", clickable = true, role = "android.widget.ImageButton", viewId = "$youtube:id/media_route_button"),
                    Node(description = "Search", clickable = true, role = "android.widget.ImageView", viewId = "$youtube:id/menu_item_1"),
                    Node(text = "Home", clickable = true),
                    Node(text = "Shorts", clickable = true),
                    Node(text = "Breaking: Hindi news live", clickable = true),
                    Node(text = "hidden", visible = false),
                ),
        )

    @Test
    fun `a tap finds an icon by its spoken description`() {
        assertEquals("Search", Screen.find(home, "Search")?.description)
        assertEquals("Search", Screen.find(home, "search")?.description)
    }

    @Test
    fun `a tap finds an element by its view id or hint, then by what it is`() {
        val search =
            Node(
                children =
                    listOf(
                        Node(viewId = "$youtube:id/search_edit_text", hint = "Search YouTube", role = "android.widget.EditText", editable = true, clickable = true),
                        Node(text = "Voice search", clickable = true),
                    ),
            )
        assertEquals("Search YouTube", Screen.find(search, "Search YouTube")?.hint)
        assertEquals("Search YouTube", Screen.find(search, "search edit text")?.hint)
        assertEquals("Search YouTube", Screen.find(search, "search box")?.hint)
    }

    @Test
    fun `words that only contain the target come last, and clickable elements win ties`() {
        assertEquals("Breaking: Hindi news live", Screen.find(home, "hindi news")?.text)
        val tie = Node(children = listOf(Node(text = "OK"), Node(text = "OK", clickable = true)))
        assertTrue(Screen.find(tie, "ok")!!.clickable)
    }

    @Test
    fun `hidden elements and password fields are never chosen`() {
        assertNull(Screen.find(home, "hidden"))
        val login = Node(children = listOf(Node(text = "secret", password = true)))
        assertNull(Screen.find(login, "secret"))
        assertTrue(Screen.labels(login).isEmpty())
    }

    @Test
    fun `when nothing matches, the reply names the app and what it shows`() {
        assertNull(Screen.find(home, "Subscribe"))
        assertEquals(
            "nothing on YouTube's screen matches 'Subscribe'. On screen: YouTube, Cast, Search, Home, Shorts, Breaking: Hindi news live",
            Screen.notFound("Subscribe", "YouTube", home),
        )
        assertEquals("nothing on the app in front's screen matches 'x'", Screen.notFound("x", null, Node()))
    }
}
