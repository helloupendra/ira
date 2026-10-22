package io.github.helloupendra.ira.tools

import android.annotation.SuppressLint
import android.content.Context
import android.location.Geocoder
import android.location.Location
import android.location.LocationManager
import android.os.Build
import android.os.CancellationSignal
import io.github.helloupendra.ira.core.Args
import io.github.helloupendra.ira.core.ToolFailure
import java.util.Locale
import kotlin.coroutines.resume
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.JsonElement

/**
 * Where the phone is, once, when asked. Android gives the location to an app only while it
 * is on screen (this app asks for no background location), and the phone keeps nothing.
 */
class LocationTools(private val context: Context) {
    @SuppressLint("MissingPermission") // the gate checked the permission before this runs
    suspend fun now(@Suppress("UNUSED_PARAMETER") args: Args): JsonElement {
        if (!PhoneState.visible) {
            throw ToolFailure("open Ira on the phone's screen first: Android shares the location only with an app on screen")
        }
        val manager = context.getSystemService(LocationManager::class.java)
        if (!manager.isLocationEnabled) throw ToolFailure("location is switched off on the phone")
        val provider =
            listOf(
                if (Build.VERSION.SDK_INT >= 31) LocationManager.FUSED_PROVIDER else null,
                LocationManager.NETWORK_PROVIDER,
                LocationManager.GPS_PROVIDER,
            ).filterNotNull().firstOrNull { manager.isProviderEnabled(it) }
                ?: throw ToolFailure("no location source is on")
        val fix =
            withTimeoutOrNull(12_000) { current(manager, provider) }
                ?: manager.getLastKnownLocation(provider)
                ?: throw ToolFailure("the phone could not find where it is just now")
        val address = address(fix)
        val ageSeconds = (System.currentTimeMillis() - fix.time) / 1000
        return Results.of(
            "latitude" to Math.round(fix.latitude * 1e5) / 1e5,
            "longitude" to Math.round(fix.longitude * 1e5) / 1e5,
            "accuracy_m" to fix.accuracy.toInt(),
            "age_s" to maxOf(0, ageSeconds),
            "address" to address,
            "summary" to (address ?: "%.5f, %.5f".format(Locale.ROOT, fix.latitude, fix.longitude)) + " (within ${fix.accuracy.toInt()} m)",
        )
    }

    @SuppressLint("MissingPermission")
    private suspend fun current(manager: LocationManager, provider: String): Location? =
        suspendCancellableCoroutine { done ->
            if (Build.VERSION.SDK_INT >= 30) {
                val cancel = CancellationSignal()
                done.invokeOnCancellation { cancel.cancel() }
                manager.getCurrentLocation(provider, cancel, context.mainExecutor) { done.resume(it) }
            } else {
                done.resume(manager.getLastKnownLocation(provider))
            }
        }

    private fun address(fix: Location): String? {
        if (!Geocoder.isPresent()) return null
        return try {
            @Suppress("DEPRECATION")
            Geocoder(context).getFromLocation(fix.latitude, fix.longitude, 1)?.firstOrNull()?.let { a ->
                (0..a.maxAddressLineIndex).mapNotNull { a.getAddressLine(it) }.joinToString(", ").ifBlank { null }
            }
        } catch (_: Exception) {
            null
        }
    }
}
