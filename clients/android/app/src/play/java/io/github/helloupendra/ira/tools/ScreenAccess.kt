package io.github.helloupendra.ira.tools

import android.content.Context
import io.github.helloupendra.ira.core.Args
import io.github.helloupendra.ira.core.ToolFailure
import kotlinx.serialization.json.JsonElement

/**
 * The Google Play build has no Accessibility service: Play's policy does not allow an
 * assistant to use the Accessibility API. The screen tools exist only in the personal build.
 */
object ScreenAccess {
    const val AVAILABLE = false

    fun serviceName(context: Context): String? = null

    fun openSettings(context: Context) = Unit

    suspend fun read(context: Context, args: Args): JsonElement = throw ToolFailure("this build of the app cannot read the screen")

    suspend fun act(context: Context, args: Args): JsonElement = throw ToolFailure("this build of the app cannot use the screen")
}
