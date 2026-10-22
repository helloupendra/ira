package io.github.helloupendra.ira.tools

import android.accessibilityservice.AccessibilityService
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import io.github.helloupendra.ira.core.Args
import io.github.helloupendra.ira.core.Screen
import io.github.helloupendra.ira.core.ToolFailure
import io.github.helloupendra.ira.ui.MainActivity
import java.lang.ref.WeakReference
import java.util.IdentityHashMap
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonElement

/**
 * "Use the phone like a person", for what no other tool can do: read the screen, tap,
 * type, scroll, go back or home. Personal (sideloaded) build only, off until the person
 * switches the service on in Android's settings after a strong warning, and every use is
 * Tier 3 on the server: it runs only after their PIN.
 *
 * It never reads or uses Ira's own window. After the person types the PIN in Ira, Ira is in
 * front, so the app the tool names is brought back (or Ira steps aside) first. The service
 * reacts to no event on its own and reads the screen only when a tool asks. Password fields
 * are never read or typed into.
 */
object ScreenAccess {
    const val AVAILABLE = true

    fun serviceName(context: Context): String? = ComponentName(context, IraAccessibilityService::class.java).flattenToString()

    fun openSettings(context: Context) {
        context.startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    suspend fun read(context: Context, args: Args): JsonElement {
        val service = IraAccessibilityService.current() ?: throw ToolFailure("Ira's Accessibility service is off")
        val (pkg, front) = prepare(context, service, args.string("app", 120))
        val root = service.rootInActiveWindow ?: throw ToolFailure("the screen cannot be read just now")
        val tree = tree(root, IdentityHashMap())
        val lines = Screen.labels(tree, limit = 300, maxEach = 500)
        val text = lines.joinToString("\n").take(4_000)
        // "app": the package in front (com.google.android.youtube), which the server's trusted apps use.
        return Results.of("app" to pkg, "app_name" to front, "text" to text, "summary" to "On screen in ${front ?: "the app in front"}: ${text.take(300)}")
    }

    suspend fun act(context: Context, args: Args): JsonElement {
        val service = IraAccessibilityService.current() ?: throw ToolFailure("Ira's Accessibility service is off")
        val action = args.choice("action", listOf("tap", "type", "scroll_up", "scroll_down", "back", "home", "recents"))
            ?: throw ToolFailure("say what to do")
        val (pkg, front) = if (action == "home" || action == "recents") null to null else prepare(context, service, args.string("app", 120))
        val done =
            withContext(Dispatchers.Main) {
                when (action) {
                    "back" -> service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
                    "home" -> service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_HOME)
                    "recents" -> service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_RECENTS)
                    "tap" -> tap(service, args.string("target", 100, required = true)!!, front)
                    "type" -> type(service, args.string("text", 500, required = true)!!, args.string("target", 100), front)
                    else -> scroll(service, forward = action == "scroll_down")
                }
            }
        if (!done) throw ToolFailure("that did not work on ${front ?: "the screen"}")
        val after = service.rootInActiveWindow?.packageName?.toString() ?: pkg
        return Results.of(
            "action" to action,
            "app" to after,
            "app_name" to (Apps.label(context, after) ?: front),
            "summary" to "Done in ${front ?: "the phone"}: ${action.replace('_', ' ')}.",
        )
    }

    /**
     * Make sure the right app is in front, never Ira (Screen.plan); returns its package and name.
     * Brings the named app back, or asks Ira to step aside, and waits up to three seconds.
     */
    private suspend fun prepare(context: Context, service: AccessibilityService, target: String?): Pair<String?, String?> {
        val own = context.packageName
        repeat(2) {
            val front = service.rootInActiveWindow?.packageName?.toString()
            when (val plan = Screen.plan(front, own, target, Apps.label(context, front))) {
                Screen.Plan.Proceed -> return front to (Apps.label(context, front) ?: front)
                is Screen.Plan.Bring -> {
                    val app = Apps.find(context, plan.app) ?: throw ToolFailure("no app called '${plan.app}' is on the phone")
                    val launch = context.packageManager.getLaunchIntentForPackage(app.pkg) ?: throw ToolFailure("${app.label} cannot be opened")
                    // An Accessibility service may bring an app to the front; its task keeps its place.
                    withContext(Dispatchers.Main) { context.startActivity(launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
                    if (!waitFor(service) { it == app.pkg }) {
                        throw ToolFailure(Screen.notInFront(app.label, Apps.label(context, service.rootInActiveWindow?.packageName?.toString())))
                    }
                }
                Screen.Plan.StepAside -> {
                    withContext(Dispatchers.Main) { MainActivity.stepAside() }
                    if (!waitFor(service) { it != null && it != own }) {
                        throw ToolFailure("Ira is on screen and no app is open behind it: say which app (app), or open it first with app_open")
                    }
                }
            }
        }
        val front = service.rootInActiveWindow?.packageName?.toString()
        return front to Apps.label(context, front)
    }

    private suspend fun waitFor(service: AccessibilityService, ok: (String?) -> Boolean): Boolean {
        repeat(20) {
            if (ok(service.rootInActiveWindow?.packageName?.toString())) {
                delay(300) // let the app finish drawing
                return true
            }
            delay(150)
        }
        return false
    }

    private fun tap(service: AccessibilityService, target: String, front: String?): Boolean {
        val root = service.rootInActiveWindow ?: return false
        val nodes = IdentityHashMap<Screen.Node, AccessibilityNodeInfo>()
        val tree = tree(root, nodes)
        val chosen = Screen.find(tree, target) ?: throw ToolFailure(Screen.notFound(target, front, tree))
        var node: AccessibilityNodeInfo? = nodes[chosen]
        while (node != null && !node.isClickable) node = node.parent
        return (node ?: nodes[chosen])?.performAction(AccessibilityNodeInfo.ACTION_CLICK) == true
    }

    private fun type(service: AccessibilityService, text: String, target: String?, front: String?): Boolean {
        val root = service.rootInActiveWindow ?: return false
        var field = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
        if (field == null || target != null) {
            val nodes = IdentityHashMap<Screen.Node, AccessibilityNodeInfo>()
            val tree = tree(root, nodes)
            val chosen = Screen.find(tree, target ?: "text field") ?: throw ToolFailure(Screen.notFound(target ?: "a text field", front, tree))
            field = nodes[chosen]
        }
        field ?: throw ToolFailure("no text field is selected on the screen")
        if (field.isPassword) throw ToolFailure("Ira never types into a password field")
        val arguments = Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text) }
        return field.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, arguments)
    }

    private fun scroll(service: AccessibilityService, forward: Boolean): Boolean {
        val root = service.rootInActiveWindow ?: return false
        val queue = ArrayDeque(listOf(root))
        while (queue.isNotEmpty()) {
            val node = queue.removeFirst()
            if (node.isScrollable && node.isVisibleToUser) {
                return node.performAction(if (forward) AccessibilityNodeInfo.ACTION_SCROLL_FORWARD else AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD)
            }
            for (i in 0 until node.childCount) node.getChild(i)?.let { queue.addLast(it) }
        }
        return false
    }

    /** Android's view tree as Screen nodes (at most 500, 40 deep), remembering which is which. */
    private fun tree(info: AccessibilityNodeInfo, map: IdentityHashMap<Screen.Node, AccessibilityNodeInfo>, depth: Int = 0): Screen.Node {
        val children =
            if (depth >= 40 || map.size >= 500) {
                emptyList()
            } else {
                (0 until info.childCount).mapNotNull { i -> info.getChild(i)?.let { tree(it, map, depth + 1) } }
            }
        val node =
            Screen.Node(
                text = if (info.isPassword) null else info.text?.toString(),
                description = info.contentDescription?.toString(),
                viewId = info.viewIdResourceName,
                hint = info.hintText?.toString(),
                role = info.className?.toString(),
                clickable = info.isClickable,
                editable = info.isEditable,
                visible = info.isVisibleToUser,
                password = info.isPassword,
                children = children,
            )
        map[node] = info
        return node
    }
}

class IraAccessibilityService : AccessibilityService() {
    override fun onServiceConnected() {
        current = WeakReference(this)
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // Nothing: the screen is read only when a tool asks, after the person's PIN.
    }

    override fun onInterrupt() = Unit

    override fun onDestroy() {
        current = WeakReference(null)
        super.onDestroy()
    }

    companion object {
        @Volatile
        private var current: WeakReference<IraAccessibilityService> = WeakReference(null)

        fun current(): IraAccessibilityService? = current.get()
    }
}
