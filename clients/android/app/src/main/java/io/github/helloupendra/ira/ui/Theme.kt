package io.github.helloupendra.ira.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/** IRA's colours (docs/stylesheets/extra.css): a deep green, calm surfaces. */
private val Light =
    lightColorScheme(
        primary = Color(0xFF1F6F5C),
        onPrimary = Color.White,
        primaryContainer = Color(0xFFD5EBE3),
        onPrimaryContainer = Color(0xFF0B2A22),
        secondary = Color(0xFF4A635B),
        background = Color(0xFFF6F8F7),
        surface = Color(0xFFF6F8F7),
        surfaceVariant = Color(0xFFE3EAE7),
        onSurfaceVariant = Color(0xFF3F4945),
        error = Color(0xFFB3261E),
    )

private val Dark =
    darkColorScheme(
        primary = Color(0xFF4FB397),
        onPrimary = Color(0xFF00382C),
        primaryContainer = Color(0xFF175646),
        onPrimaryContainer = Color(0xFFD5EBE3),
        secondary = Color(0xFFB1CCC3),
        background = Color(0xFF121615),
        surface = Color(0xFF121615),
        surfaceVariant = Color(0xFF2C3532),
        onSurfaceVariant = Color(0xFFBFC9C4),
        error = Color(0xFFF2B8B5),
    )

@Composable
fun IraTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = if (isSystemInDarkTheme()) Dark else Light, content = content)
}
