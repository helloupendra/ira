package io.github.helloupendra.ira.ui

import android.graphics.Color as AndroidColor
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.graphics.Color
import io.github.helloupendra.ira.IraApp

/** IRA's colours, "Presence" (see Presence.kt): near-black when the phone is dark, warm paper when light. */
private val Light =
    lightColorScheme(
        primary = LightPresence.greenDeep,
        onPrimary = Color.White,
        primaryContainer = Color(0xFFE3EEE9),
        onPrimaryContainer = Color(0xFF0B2A22),
        secondary = LightPresence.muted,
        background = LightPresence.bg,
        onBackground = LightPresence.ink,
        surface = LightPresence.bg,
        onSurface = LightPresence.ink,
        surfaceVariant = Color(0xFFFAF9F6),
        onSurfaceVariant = LightPresence.muted,
        // Dialogs and menus sit a little lighter than the paper; tracks a little darker.
        surfaceContainerLowest = Color.White,
        surfaceContainerLow = Color(0xFFF8F7F3),
        surfaceContainer = Color(0xFFF9F8F5),
        surfaceContainerHigh = Color(0xFFFBFAF7),
        surfaceContainerHighest = Color(0xFFE6E4DE),
        secondaryContainer = Color(0xFFDCEBE5),
        onSecondaryContainer = Color(0xFF0B2A22),
        outline = Color(0xFFE2E0DA),
        error = LightPresence.down,
    )

private val Dark =
    darkColorScheme(
        primary = DarkPresence.green,
        onPrimary = Color(0xFF00382C),
        primaryContainer = DarkPresence.greenDeep,
        onPrimaryContainer = Color.White,
        secondary = DarkPresence.muted,
        background = DarkPresence.bg,
        onBackground = DarkPresence.ink,
        surface = DarkPresence.bg,
        onSurface = DarkPresence.ink,
        surfaceVariant = Color(0xFF141615),
        onSurfaceVariant = DarkPresence.muted,
        surfaceContainerLowest = Color(0xFF080A09),
        surfaceContainerLow = Color(0xFF111312),
        surfaceContainer = Color(0xFF141716),
        surfaceContainerHigh = Color(0xFF181B1A),
        surfaceContainerHighest = Color(0xFF232625),
        secondaryContainer = Color(0xFF16362E),
        onSecondaryContainer = DarkPresence.ink,
        outline = Color(0xFF1D1F1E),
        error = DarkPresence.down,
    )

@Composable
fun IraTheme(dark: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    CompositionLocalProvider(LocalPresence provides if (dark) DarkPresence else LightPresence) {
        MaterialTheme(colorScheme = if (dark) Dark else Light, content = content)
    }
}

/**
 * The person's theme (Settings: System, Light or Dark), live: System follows the phone as it
 * changes. A full-screen `activity` has its status and navigation bars follow it too.
 */
@Composable
fun IraTheme(app: IraApp, activity: ComponentActivity? = null, content: @Composable () -> Unit) {
    val choice by app.theme.collectAsState()
    val dark = choice.dark(isSystemInDarkTheme())
    if (activity != null) {
        LaunchedEffect(dark) {
            val bars =
                if (dark) SystemBarStyle.dark(AndroidColor.TRANSPARENT) else SystemBarStyle.light(AndroidColor.TRANSPARENT, AndroidColor.TRANSPARENT)
            activity.enableEdgeToEdge(statusBarStyle = bars, navigationBarStyle = bars)
        }
    }
    IraTheme(dark, content)
}
