package io.github.helloupendra.ira.tools

import android.content.Context
import io.github.helloupendra.ira.BuildConfig
import io.github.helloupendra.ira.core.Args
import io.github.helloupendra.ira.core.Flavor
import io.github.helloupendra.ira.core.ToolCatalog
import io.github.helloupendra.ira.core.ToolFailure
import io.github.helloupendra.ira.core.ToolGate
import io.github.helloupendra.ira.core.ToolSpec
import io.github.helloupendra.ira.device.ToolRunner
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

/**
 * The phone's tools, as offered in the hello. Each call is checked first (the build, the
 * assistant role and the live call where Google Play requires them, the permissions), then
 * run with its arguments validated by the tool itself.
 */
class PhoneTools(private val context: Context) : ToolRunner {
    val flavor: Flavor = Flavor.of(BuildConfig.FLAVOR)

    override val tools: List<ToolSpec> = ToolCatalog.forFlavor(flavor)

    private val byName = tools.associateBy { it.name }
    private val calls = CallTools(context)
    private val messages = MessageTools(context)
    private val notifications = NotificationTools(context)
    private val clock = ClockTools(context)
    private val calendar = CalendarTools(context)
    private val apps = AppTools(context)
    private val location = LocationTools(context)
    private val settings = SettingsTools(context)

    fun gateState(): ToolGate.State =
        ToolGate.State(
            flavor = flavor,
            assistantRole = PhoneState.isAssistant(context),
            callOn = PhoneState.callOn,
            granted = PhoneState.granted(context, tools.flatMap { it.permissions + it.optionalPermissions }.toSet()),
            special = PhoneState.special(context),
        )

    override suspend fun run(name: String, args: JsonObject): JsonElement {
        val spec = byName[name] ?: throw ToolFailure("this phone has no tool called $name")
        ToolGate.check(spec, gateState())?.let { throw ToolFailure(it) }
        val a = Args(args)
        // Content providers and the system services they need are called off the main thread;
        // the few that start a screen post to the main thread themselves.
        return withContext(Dispatchers.IO) {
            when (name) {
                "calls_recent" -> calls.callsRecent(a)
                "contacts_lookup" -> calls.contactsLookup(a)
                "call_place" -> withContext(Dispatchers.Main) { calls.callPlace(a) }
                "sms_read" -> messages.smsRead(a)
                "sms_send" -> messages.smsSend(a)
                "notifications_read" -> notifications.read(a)
                "notification_reply" -> notifications.reply(a)
                "alarm_set" -> withContext(Dispatchers.Main) { clock.alarm(a) }
                "timer_set" -> withContext(Dispatchers.Main) { clock.timer(a) }
                "reminder_set" -> clock.reminder(a)
                "calendar_read" -> calendar.read(a)
                "calendar_add" -> calendar.add(a)
                "app_open" -> withContext(Dispatchers.Main) { apps.open(a) }
                "url_open" -> withContext(Dispatchers.Main) { apps.url(a) }
                "media_play" -> withContext(Dispatchers.Main) { apps.mediaPlay(a) }
                "maps_navigate" -> withContext(Dispatchers.Main) { apps.navigate(a) }
                "media_control" -> apps.media(a)
                "location_now" -> location.now(a)
                "settings_toggle" -> withContext(Dispatchers.Main) { settings.toggle(a) }
                "screen_read" -> ScreenAccess.read(context, a)
                "screen_act" -> ScreenAccess.act(context, a)
                else -> throw ToolFailure("this phone has no tool called $name")
            }
        }
    }
}
