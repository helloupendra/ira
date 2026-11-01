package io.github.helloupendra.ira.ui

import androidx.annotation.DrawableRes
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.helloupendra.ira.R

/*
 * The parts every screen is built from, as on the web console: a header with a back arrow,
 * each part of a screen in a quiet card with hairlines between its rows, rows with the name in
 * bold over a muted line and the control on the right, and a segmented pill for a few choices.
 */

/** A screen's header: a back arrow, the title (with a muted line under it), and icon buttons on the right. */
@Composable
fun ScreenHeader(title: String, onBack: (() -> Unit)? = null, subtitle: String? = null, actions: @Composable RowScope.() -> Unit = {}) {
    val colors = Presence.colors
    Row(
        Modifier.fillMaxWidth().heightIn(min = 56.dp).padding(start = if (onBack != null) 4.dp else 20.dp, end = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (onBack != null) IconAction(R.drawable.ic_back, "Back", onBack)
        Column(Modifier.padding(start = if (onBack != null) 4.dp else 0.dp).weight(1f)) {
            Text(title, fontSize = 20.sp, fontWeight = FontWeight.SemiBold, color = colors.ink, maxLines = 1)
            if (subtitle != null) Text(subtitle, fontSize = 12.sp, color = colors.muted, maxLines = 1)
        }
        actions()
    }
}

/**
 * Where a row sits in its card, in a list that cannot nest the rows in one: its corners and
 * fill make the rows of a group read as one quiet card.
 */
fun Modifier.groupRow(colors: PresenceColors, first: Boolean, last: Boolean, radius: androidx.compose.ui.unit.Dp = 16.dp): Modifier {
    val shape =
        RoundedCornerShape(
            topStart = if (first) radius else 0.dp,
            topEnd = if (first) radius else 0.dp,
            bottomStart = if (last) radius else 0.dp,
            bottomEnd = if (last) radius else 0.dp,
        )
    return this.clip(shape).background(colors.card)
}

/** A round 44dp touch target with one icon, tinted like text. */
@Composable
fun IconAction(@DrawableRes icon: Int, label: String, onClick: () -> Unit, tint: Color = Presence.colors.ink) {
    Box(
        Modifier
            .size(44.dp)
            .clip(CircleShape)
            .clickable(onClick = onClick)
            .semantics {
                contentDescription = label
                role = Role.Button
            },
        contentAlignment = Alignment.Center,
    ) {
        Icon(painterResource(icon), contentDescription = null, tint = tint, modifier = Modifier.size(22.dp))
    }
}

/**
 * One part of a screen: a small uppercase title over a quiet card, and a muted note under it.
 * The rows inside are separated with [Hairline].
 */
@Composable
fun Section(title: String? = null, note: String? = null, modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    val colors = Presence.colors
    Column(modifier.fillMaxWidth()) {
        if (title != null) {
            Text(title.uppercase(), style = Presence.label, color = colors.muted, modifier = Modifier.padding(start = 4.dp, bottom = 8.dp))
        }
        Column(Modifier.fillMaxWidth().presenceCard(colors, radius = 16.dp)) { content() }
        if (note != null) {
            Text(note, fontSize = 13.sp, lineHeight = 18.sp, color = colors.muted, modifier = Modifier.padding(start = 4.dp, end = 4.dp, top = 8.dp))
        }
    }
}

/** The line between two rows of a card. */
@Composable
fun Hairline(inset: Boolean = true) {
    Box(Modifier.padding(start = if (inset) 16.dp else 0.dp).fillMaxWidth().height(1.dp).background(Presence.colors.line))
}

/**
 * A row in a card: the name in bold, a muted line under it, and what goes on the right (a
 * switch, a value, a chevron). Tappable when [onClick] is given.
 */
@Composable
fun ItemRow(
    title: String,
    detail: String? = null,
    onClick: (() -> Unit)? = null,
    titleColor: Color = Presence.colors.ink,
    trailing: @Composable RowScope.() -> Unit = {},
) {
    val colors = Presence.colors
    Row(
        Modifier
            .fillMaxWidth()
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .heightIn(min = 56.dp)
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(title, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = titleColor)
            if (!detail.isNullOrBlank()) Text(detail, fontSize = 13.sp, lineHeight = 18.sp, color = colors.muted)
        }
        trailing()
    }
}

/** The chevron a row that opens something shows on its right. */
@Composable
fun Chevron() {
    Icon(painterResource(R.drawable.ic_chevron), contentDescription = null, tint = Presence.colors.faint, modifier = Modifier.size(18.dp))
}

/** A switch in Ira's colours. */
@Composable
fun IraSwitch(checked: Boolean, onCheckedChange: ((Boolean) -> Unit)?, enabled: Boolean = true) {
    val colors = Presence.colors
    Switch(
        checked = checked,
        onCheckedChange = onCheckedChange,
        enabled = enabled,
        colors =
            SwitchDefaults.colors(
                checkedThumbColor = Color.White,
                checkedTrackColor = colors.greenDeep,
                checkedBorderColor = colors.greenDeep,
                uncheckedThumbColor = colors.muted,
                uncheckedTrackColor = colors.raised,
                uncheckedBorderColor = colors.line,
            ),
    )
}

/** A few choices as one segmented pill: the chosen one raised. */
@Composable
fun SegmentedPill(options: List<String>, selected: Int, onSelect: (Int) -> Unit, modifier: Modifier = Modifier) {
    val colors = Presence.colors
    Row(
        modifier
            .clip(RoundedCornerShape(999.dp))
            .background(if (colors.dark) Color.White.copy(alpha = 0.05f) else Color.Black.copy(alpha = 0.05f))
            .padding(3.dp),
    ) {
        options.forEachIndexed { index, option ->
            val on = index == selected
            Box(
                Modifier
                    .weight(1f)
                    .clip(RoundedCornerShape(999.dp))
                    .background(if (on) (if (colors.dark) Color.White.copy(alpha = 0.12f) else Color.White) else Color.Transparent)
                    .then(if (on && !colors.dark) Modifier.border(BorderStroke(1.dp, colors.line), RoundedCornerShape(999.dp)) else Modifier)
                    .clickable { onSelect(index) }
                    .semantics {
                        role = Role.RadioButton
                        this.selected = on
                    }
                    .padding(vertical = 9.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(option, fontSize = 14.sp, fontWeight = if (on) FontWeight.SemiBold else FontWeight.Medium, color = if (on) colors.ink else colors.muted)
            }
        }
    }
}

/** A small status chip: a dot and a word ("Connected"). */
@Composable
fun StatusChip(text: String, color: Color = Presence.colors.green) {
    val colors = Presence.colors
    Row(
        Modifier.clip(RoundedCornerShape(999.dp)).background(color.copy(alpha = 0.12f)).padding(horizontal = 10.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(6.dp).clip(CircleShape).background(color))
        Spacer(Modifier.width(6.dp))
        Text(text, fontSize = 12.sp, fontWeight = FontWeight.Medium, color = if (color == colors.green && !colors.dark) colors.greenDeep else color)
    }
}
