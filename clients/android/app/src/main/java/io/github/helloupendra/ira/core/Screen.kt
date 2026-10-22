package io.github.helloupendra.ira.core

/**
 * The plain-Kotlin half of the screen tools (personal build): which window to use, which
 * element a tap means, and what to say when nothing matches. The Accessibility service turns
 * Android's view tree into [Node]s and does what these decide.
 */
object Screen {
    /** One element on the screen, as the Accessibility API describes it. */
    data class Node(
        val text: String? = null,
        val description: String? = null,
        /** The view's id, such as `com.google.android.youtube:id/menu_item_search`. */
        val viewId: String? = null,
        val hint: String? = null,
        /** The view's class, such as `android.widget.EditText`. */
        val role: String? = null,
        val clickable: Boolean = false,
        val editable: Boolean = false,
        val visible: Boolean = true,
        val password: Boolean = false,
        val children: List<Node> = emptyList(),
    )

    /** What to do before reading or acting, from which app is in front. */
    sealed interface Plan {
        /** The right app is in front: go ahead. */
        data object Proceed : Plan

        /** Bring this app (a package or a name) to the front first. */
        data class Bring(val app: String) : Plan

        /** Ira itself is in front and no app was named: step Ira aside, then look again. */
        data object StepAside : Plan
    }

    /**
     * Never Ira's own window: when Ira is in front (the person just typed the PIN there), the
     * named app is brought back, or Ira steps aside so the app under it is in front again.
     */
    fun plan(front: String?, own: String, target: String?, frontLabel: String? = null): Plan {
        val wanted = target?.trim()?.takeIf { it.isNotEmpty() }
        if (front == null || front == own) return if (wanted != null) Plan.Bring(wanted) else Plan.StepAside
        if (wanted == null) return Plan.Proceed
        val matches =
            front.equals(wanted, ignoreCase = true) ||
                (frontLabel != null && frontLabel.equals(wanted, ignoreCase = true)) ||
                (frontLabel != null && frontLabel.contains(wanted, ignoreCase = true) && wanted.length >= 3)
        return if (matches) Plan.Proceed else Plan.Bring(wanted)
    }

    /** What to tell the model when, after all that, the app in front is still not the one asked for. */
    fun notInFront(wanted: String, frontLabel: String?): String =
        "$wanted is not on screen" + (frontLabel?.let { " ($it is)" } ?: "") + "; open it first with app_open, or use url_open"

    /**
     * The element a tap on [target] means, best first: the visible words (text or spoken
     * description) exactly, then the view's id or its hint, then its role (a search box, a
     * button), then words that contain the target. Password fields are never chosen.
     */
    fun find(root: Node, target: String): Node? {
        val wanted = normal(target)
        if (wanted.isEmpty()) return null
        var best: Node? = null
        var bestScore = 0
        walk(root) { node ->
            if (!node.visible || node.password) return@walk
            val score = score(node, wanted)
            // Ties go to the element that can be tapped itself.
            if (score > bestScore || (score == bestScore && score > 0 && node.clickable && best?.clickable != true)) {
                best = node
                bestScore = score
            }
        }
        return best
    }

    private fun score(node: Node, wanted: String): Int {
        val text = normal(node.text)
        val description = normal(node.description)
        val id = normal(node.viewId?.substringAfter(":id/")?.replace('_', ' '))
        val hint = normal(node.hint)
        val role = normal(node.role?.substringAfterLast('.'))
        return when {
            text == wanted || description == wanted -> 100
            hint == wanted || id == wanted -> 80
            id.split(' ').contains(wanted) || hint.split(' ').contains(wanted) -> 70
            roleMatches(wanted, role, node) -> 50
            text.contains(wanted) || description.contains(wanted) -> 40
            hint.contains(wanted) || id.contains(wanted) -> 30
            else -> 0
        }
    }

    /** "search box", "text field", "button": an element by what it is, when it shows no words. */
    private fun roleMatches(wanted: String, role: String, node: Node): Boolean {
        val words = wanted.split(' ')
        val field = node.editable || role.contains("edittext") || role.contains("searchview")
        return when {
            words.any { it in setOf("field", "box", "input") } -> field
            words.contains("button") -> node.clickable && (role.contains("button") || role.contains("imageview"))
            else -> false
        }
    }

    /** The first few words on the screen, for a reply that lets the model find its way. */
    fun labels(root: Node, limit: Int = 8, maxEach: Int = 40): List<String> {
        val out = LinkedHashSet<String>()
        walk(root) { node ->
            if (out.size >= limit || !node.visible || node.password) return@walk
            val label = (node.text ?: node.description)?.trim()?.replace(Regex("\\s+"), " ")?.take(maxEach)
            if (!label.isNullOrEmpty()) out += label
        }
        return out.toList()
    }

    /** Nothing matched: say which app is on screen and what it shows, so the model can recover. */
    fun notFound(target: String, appLabel: String?, root: Node): String {
        val shown = labels(root)
        val app = appLabel ?: "the app in front"
        return "nothing on $app's screen matches '$target'" +
            if (shown.isEmpty()) "" else ". On screen: " + shown.joinToString(", ")
    }

    private fun walk(node: Node, visit: (Node) -> Unit) {
        visit(node)
        for (child in node.children) walk(child, visit)
    }

    private fun normal(value: String?): String = value.orEmpty().lowercase().replace(Regex("[^\\p{L}\\p{N}]+"), " ").trim()
}
