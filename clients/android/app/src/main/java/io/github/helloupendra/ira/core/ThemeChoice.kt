package io.github.helloupendra.ira.core

/**
 * How Ira looks: as the phone is set (System, the default), or always Light or Dark. Kept in
 * the app's settings by name, so an unknown or missing value reads as System.
 */
enum class ThemeChoice(val label: String) {
    SYSTEM("System"),
    LIGHT("Light"),
    DARK("Dark"),
    ;

    /** Whether to draw dark, given whether the phone is in dark mode now. */
    fun dark(phoneDark: Boolean): Boolean =
        when (this) {
            SYSTEM -> phoneDark
            LIGHT -> false
            DARK -> true
        }

    companion object {
        fun from(stored: String?): ThemeChoice = entries.firstOrNull { it.name == stored } ?: SYSTEM
    }
}
