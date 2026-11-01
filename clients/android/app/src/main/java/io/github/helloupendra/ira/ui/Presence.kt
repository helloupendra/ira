package io.github.helloupendra.ira.ui

import android.provider.Settings
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.core.withInfiniteAnimationFrameMillis
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.painter.Painter
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin

/** Ira's look, "Presence": calm, dark first, and one hero object, the lens. */
@Immutable
data class PresenceColors(
    val bg: Color,
    val ink: Color,
    val muted: Color,
    val faint: Color,
    val line: Color,
    val card: Color,
    val raised: Color,
    val green: Color,
    val greenDeep: Color,
    val warn: Color,
    val down: Color,
    val dark: Boolean,
)

val DarkPresence =
    PresenceColors(
        bg = Color(0xFF0B0D0C),
        ink = Color(0xFFEEF2EF),
        muted = Color(0xFF8B958F),
        faint = Color(0xFF5A635E),
        line = Color.White.copy(alpha = 0.07f),
        card = Color.White.copy(alpha = 0.035f),
        raised = Color.White.copy(alpha = 0.06f),
        green = Color(0xFF3FBF98),
        greenDeep = Color(0xFF1F6F5C),
        warn = Color(0xFFE7B65C),
        down = Color(0xFFF07A6B),
        dark = true,
    )

val LightPresence =
    PresenceColors(
        bg = Color(0xFFF4F2ED),
        ink = Color(0xFF1B1F1D),
        muted = Color(0xFF6D736F),
        faint = Color(0xFFA5A79F),
        line = Color.Black.copy(alpha = 0.08f),
        card = Color.White.copy(alpha = 0.6f),
        raised = Color.White.copy(alpha = 0.85f),
        green = Color(0xFF1F6F5C),
        greenDeep = Color(0xFF1F6F5C),
        warn = Color(0xFF9A6512),
        down = Color(0xFFB3412F),
        dark = false,
    )

val LocalPresence = staticCompositionLocalOf { DarkPresence }

object Presence {
    val colors: PresenceColors
        @Composable get() = LocalPresence.current

    /** The serif, for the greeting and the words heard while listening only. */
    val serif = FontFamily.Serif

    val label = TextStyle(fontSize = 11.sp, fontWeight = FontWeight.Medium, letterSpacing = 1.2.sp)
}

/** Whether the person turned animations off (Settings, Accessibility): the lens then stays still. */
@Composable
private fun animationsOff(): Boolean {
    val context = LocalContext.current
    return remember { Settings.Global.getFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f }
}

/**
 * The lens: a glass sphere with Ira's four bars of light. Small at rest above the greeting,
 * large with two rings while listening (its bars follow [level]), 30 dp beside each answer.
 * With [heartbeat] (listening) it pulses every 1.2 s and sends out a fading ring, even in
 * silence, so the person always sees Ira is on; with animations off it fades gently instead.
 */
@Composable
fun Lens(
    size: Dp,
    modifier: Modifier = Modifier,
    level: Float = 0f,
    breathing: Boolean = false,
    rings: Int = 0,
    heartbeat: Boolean = false,
    thinking: Boolean = false,
) {
    val still = animationsOff()
    val transition = rememberInfiniteTransition(label = "lens")
    val phase by transition.animateFloat(0f, 1f, infiniteRepeatable(tween(4000, easing = LinearEasing)), label = "breath")
    val wave by transition.animateFloat(0f, (2 * PI).toFloat(), infiniteRepeatable(tween(700, easing = LinearEasing)), label = "wave")
    // While Ira works: a slow ripple across the bars, bar after bar, every 1.6 s.
    val ripple by transition.animateFloat(0f, (2 * PI).toFloat(), infiniteRepeatable(tween(1600, easing = LinearEasing)), label = "ripple")
    // The heartbeat runs on the frame clock, which animations-off does not stop, so the fade still shows.
    var beatMs by remember { mutableLongStateOf(0L) }
    if (heartbeat) LaunchedEffect(Unit) { while (true) withInfiniteAnimationFrameMillis { beatMs = it } }
    // Where in the 1.2 s beat: the ring's spread (0 to 1), and the pulse (0 at rest, 1 at its fullest).
    val spread = (beatMs % 1200L) / 1200f
    val beat = 0.5f - 0.5f * cos(spread * 2 * PI).toFloat()
    // Scale 1 to 1.02 and back over 4 seconds, or 1 to 1.04 with each beat.
    val breathe =
        when {
            still -> 1f
            heartbeat -> 1f + 0.04f * beat
            breathing -> 1f + 0.01f * (1f - cos(phase * 2 * PI).toFloat())
            else -> 1f
        }
    val colors = Presence.colors
    val sphere = size
    val outer = sphere * (1f + rings * 0.22f)
    Box(modifier.size(outer), contentAlignment = Alignment.Center) {
        Canvas(Modifier.size(outer).scale(breathe).alpha(if (heartbeat && still) 1f - 0.25f * beat else 1f)) {
            val s = sphere.toPx()
            val center = Offset(this.size.width / 2, this.size.height / 2)
            val r = s / 2
            if (heartbeat && !still) {
                // The ring each beat sends out: from the sphere's edge to half again, fading.
                drawCircle(colors.green.copy(alpha = 0.45f * (1f - spread)), radius = r * (1f + 0.5f * spread), center = center, style = Stroke(1.5.dp.toPx()))
            }
            // A soft green glow below the sphere.
            drawCircle(
                Brush.radialGradient(
                    listOf(Color(0xFF1F6F5C).copy(alpha = if (colors.dark) 0.5f else 0.28f), Color.Transparent),
                    center = center + Offset(0f, s * 0.16f),
                    radius = r * 1.35f,
                ),
                radius = r * 1.35f,
                center = center + Offset(0f, s * 0.16f),
            )
            for (ring in 1..rings) {
                drawCircle(colors.line, radius = r + ring * s * 0.11f, center = center, style = Stroke(1.dp.toPx()))
            }
            drawCircle(
                Brush.radialGradient(
                    listOf(Color(0xFF1C5F4F), Color(0xFF0F3A30), Color(0xFF08201B)),
                    center = center + Offset(0f, -s * 0.12f),
                    radius = s * 0.62f,
                ),
                radius = r,
                center = center,
            )
            drawCircle(
                Brush.radialGradient(
                    listOf(Color.White.copy(alpha = 0.22f), Color.Transparent),
                    center = center + Offset(-s * 0.15f, -s * 0.22f),
                    radius = s * 0.42f,
                ),
                radius = r,
                center = center,
            )
            drawCircle(
                Brush.verticalGradient(listOf(Color.Transparent, Color.Black.copy(alpha = 0.28f)), startY = center.y, endY = center.y + r),
                radius = r,
                center = center,
            )
            drawCircle(
                Brush.verticalGradient(listOf(Color.White.copy(alpha = 0.18f), Color.Transparent), startY = center.y - r, endY = center.y),
                radius = r - 0.5.dp.toPx(),
                center = center,
                style = Stroke(maxOf(1f, s / 96f)),
            )
            // The four bars, taller with the voice.
            val heights = floatArrayOf(0.17f, 0.33f, 0.42f, 0.25f)
            val width = maxOf(2f, s * 0.038f)
            val gap = s * 0.04f
            val total = heights.size * width + (heights.size - 1) * gap
            val voice = min(level * 10f, 1f)
            heights.forEachIndexed { index, base ->
                val lift =
                    when {
                        level > 0.002f -> 1f + voice * 0.9f * (0.7f + 0.3f * sin(wave + index * 1.7f))
                        thinking && !still -> 1f + 0.45f * maxOf(0f, sin(ripple - index * 0.9f))
                        else -> 1f
                    }
                val h = s * base * lift
                val x = center.x - total / 2 + index * (width + gap)
                drawRoundRect(
                    Brush.verticalGradient(listOf(Color(0xFFD9FFF1), Color(0xFF7EE8C4)), startY = center.y - h / 2, endY = center.y + h / 2),
                    topLeft = Offset(x, center.y - h / 2),
                    size = Size(width, h),
                    cornerRadius = CornerRadius(width / 2, width / 2),
                )
            }
        }
    }
}

/**
 * A quiet pill button ("Drop", "Not now"), or a filled green one ("Confirm", "Done"); a
 * [compact] one for the actions on a list row.
 */
@Composable
fun PillButton(text: String, onClick: () -> Unit, filled: Boolean = false, enabled: Boolean = true, compact: Boolean = false) {
    val colors = Presence.colors
    Box(
        Modifier
            .clip(CircleShape)
            .background(if (filled) colors.greenDeep else colors.card)
            .border(BorderStroke(1.dp, if (filled) Color.Transparent else colors.line), CircleShape)
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = if (compact) 12.dp else 16.dp, vertical = if (compact) 6.dp else 8.dp),
    ) {
        Text(
            text,
            fontSize = if (compact) 13.sp else 14.sp,
            fontWeight = FontWeight.Medium,
            color = (if (filled) Color.White else colors.ink).copy(alpha = if (enabled) 1f else 0.45f),
        )
    }
}

/** An uppercase label with a dot: "● WAITING FOR YOU". */
@Composable
fun DotLabel(text: String, color: Color = Presence.colors.green) {
    val colors = Presence.colors
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(6.dp).clip(CircleShape).background(color))
        Spacer(Modifier.width(6.dp))
        Text(text.uppercase(), style = Presence.label, color = if (color == colors.green) colors.muted else color)
    }
}

/**
 * The ask pill, fixed at the bottom: type, or press the mic; the mic becomes Send while there
 * is text. [micIcon] and [micLabel] say what the round button does now (talk, stop, end).
 */
@Composable
fun AskPill(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    micIcon: Painter,
    sendIcon: Painter,
    micLabel: String,
    onMic: () -> Unit,
    onSend: () -> Unit,
    sending: Boolean,
    modifier: Modifier = Modifier,
) {
    val colors = Presence.colors
    val typing = value.isNotBlank()
    Row(
        modifier
            .clip(RoundedCornerShape(999.dp))
            .background(colors.raised)
            .border(BorderStroke(1.dp, colors.line), RoundedCornerShape(999.dp))
            .padding(start = 20.dp, end = 6.dp, top = 6.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Box(Modifier.weight(1f), contentAlignment = Alignment.CenterStart) {
            if (value.isEmpty()) Text(placeholder, fontSize = 16.sp, color = colors.faint, maxLines = 1)
            BasicTextField(
                value = value,
                onValueChange = onValueChange,
                textStyle = TextStyle(fontSize = 16.sp, color = colors.ink),
                cursorBrush = SolidColor(colors.green),
                maxLines = 4,
            )
        }
        Box(
            Modifier
                .size(42.dp)
                .clip(CircleShape)
                // Dimmed while a typed message is on its way.
                .background(colors.greenDeep.copy(alpha = if (sending) 0.5f else 1f))
                .clickable(enabled = !sending, onClick = if (typing) onSend else onMic)
                .semantics { contentDescription = if (typing) "Send" else micLabel },
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                if (typing) sendIcon else micIcon,
                contentDescription = null,
                tint = Color.White,
                modifier = Modifier.size(20.dp),
            )
        }
    }
}

/** A tool Ira used and how long it took ("web search · 1.2 s"), under an answer. */
@Composable
fun ReceiptChip(text: String) {
    val colors = Presence.colors
    Row(
        Modifier.border(BorderStroke(1.dp, colors.line), RoundedCornerShape(5.dp)).padding(horizontal = 7.dp, vertical = 3.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(4.dp).clip(CircleShape).background(colors.green))
        Spacer(Modifier.width(5.dp))
        Text(text, fontSize = 11.sp, fontFamily = FontFamily.Monospace, color = colors.muted)
    }
}

/** A quiet surface with a hairline border: cards and rows. */
fun Modifier.presenceCard(colors: PresenceColors, radius: Dp = 14.dp, fill: Color = colors.card, border: Color = colors.line): Modifier =
    this.clip(RoundedCornerShape(radius)).background(fill).border(BorderStroke(1.dp, border), RoundedCornerShape(radius))
