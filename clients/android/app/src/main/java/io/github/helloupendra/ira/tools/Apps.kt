package io.github.helloupendra.ira.tools

import android.content.Context
import android.content.Intent

/** The apps on the home screen, found by name or package (visible through the manifest's <queries>). */
object Apps {
    data class App(val label: String, val pkg: String)

    fun launchable(context: Context): List<App> {
        val pm = context.packageManager
        return pm.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0)
            .map { App(it.loadLabel(pm).toString(), it.activityInfo.packageName) }
            .filter { it.pkg != context.packageName }
            .distinctBy { it.pkg }
    }

    /** By package first, then by name: exact, then the shortest name containing it. */
    fun find(context: Context, nameOrPackage: String): App? {
        val wanted = nameOrPackage.trim().lowercase()
        if (wanted.isEmpty()) return null
        val apps = launchable(context)
        return apps.firstOrNull { it.pkg.lowercase() == wanted }
            ?: apps.firstOrNull { it.label.lowercase() == wanted }
            ?: apps.filter { it.label.lowercase().contains(wanted) }.minByOrNull { it.label.length }
            ?: apps.firstOrNull { wanted.contains(it.label.lowercase()) && it.label.length >= 3 }
    }

    fun label(context: Context, pkg: String?): String? {
        if (pkg == null) return null
        return try {
            context.packageManager.getApplicationLabel(context.packageManager.getApplicationInfo(pkg, 0)).toString()
        } catch (_: Exception) {
            null
        }
    }
}
