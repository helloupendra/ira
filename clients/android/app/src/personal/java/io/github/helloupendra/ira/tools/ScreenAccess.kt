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
import io.github.helloupendra.ira.core.ToolFailure
import java.lang.ref.WeakReference
import kotlinx.serialization.json.JsonElement

/**
 * "Use the phone like a person", for what no other tool can do: read the screen, tap,
 * type, scroll, go back or home. Personal (sideloaded) build only, off until the person
 * switches the service on in Android's settings after a strong warning, and every use is
 * Tier 3 on the server: it runs only after their PIN.
 *
 * The service reacts to no event on its own and reads the screen only when a tool asks.
 * Password fields are never read or typed into.
 */
object ScreenAccess {
    const val AVAILABLE = true

    fun serviceName(context: Context): String = ComponentName(context, IraAccessibilityService::class.java).flattenToString()

    fun openSettings(context: Context) {
        context.startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    suspend fun read(context: Context, args: Args): JsonElement {
        val service = IraAccessibilityService.current() ?: throw ToolFailure("Ira's Accessibility service is off")
        val root = service.rootInActiveWindow ?: throw ToolFailure("the screen cannot be read just now")
        val lines = ArrayList<String>()
        collect(root, lines, 0)
        val text = lines.joinToString("\n").take(4_000)
        val app = root.packageName?.toString()?.let { appLabel(context, it) }
        return Results.of("app" to app, "text" to text, "summary" to "On screen in ${app ?: "the app in front"}: ${text.take(300)}")
    }

    suspend fun act(context: Context, args: Args): JsonElement {
        val service = IraAccessibilityService.current() ?: throw ToolFailure("Ira's Accessibility service is off")
        val action = args.choice("action", listOf("tap", "type", "scroll_up", "scroll_down", "back", "home", "recents"))
            ?: throw ToolFailure("say what to do")
        val done =
            when (action) {
                "back" -> service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
                "home" -> service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_HOME)
                "recents" -> service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_RECENTS)
                "tap" -> tap(service, args.string("target", 100, required = true)!!)
                "type" -> type(service, args.string("text", 500, required = true)!!)
                else -> scroll(service, forward = action == "scroll_down")
            }
        if (!done) throw ToolFailure("that did not work on the screen")
        return Results.of("action" to action, "summary" to "Done: ${action.replace('_', ' ')}.")
    }

    private fun tap(service: AccessibilityService, target: String): Boolean {
        val root = service.rootInActiveWindow ?: return false
        val found = root.findAccessibilityNodeInfosByText(target).filter { it.isVisibleToUser }
        val node =
            found.firstOrNull { (it.text?.toString() ?: it.contentDescription?.toString()).equals(target, ignoreCase = true) }
                ?: found.firstOrNull()
                ?: throw ToolFailure("nothing on the screen says '$target'")
        var clickable: AccessibilityNodeInfo? = node
        while (clickable != null && !clickable.isClickable) clickable = clickable.parent
        return (clickable ?: node).performAction(AccessibilityNodeInfo.ACTION_CLICK)
    }

    private fun type(service: AccessibilityService, text: String): Boolean {
        val field = service.rootInActiveWindow?.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
            ?: throw ToolFailure("no text field is selected on the screen")
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

    private fun collect(node: AccessibilityNodeInfo, out: MutableList<String>, depth: Int) {
        if (depth > 40 || out.size > 300 || !node.isVisibleToUser) return
        if (!node.isPassword) {
            val text = node.text?.toString()?.trim().orEmpty().ifEmpty { node.contentDescription?.toString()?.trim().orEmpty() }
            if (text.isNotEmpty() && out.lastOrNull() != text) out += text
        }
        for (i in 0 until node.childCount) node.getChild(i)?.let { collect(it, out, depth + 1) }
    }

    private fun appLabel(context: Context, packageName: String): String =
        try {
            context.packageManager.getApplicationLabel(context.packageManager.getApplicationInfo(packageName, 0)).toString()
        } catch (_: Exception) {
            packageName
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
