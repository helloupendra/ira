package io.github.helloupendra.ira.core

import kotlin.coroutines.AbstractCoroutineContextElement
import kotlin.coroutines.CoroutineContext

/**
 * Whether the server's call was asked for on this phone, carried with the call while it runs.
 * Google Play lets the play build read SMS and the call log only while the person talks to Ira
 * on the phone: a request from the Mac or the web, with the app merely open, is not that.
 */
class AskedHere(val here: Boolean) : AbstractCoroutineContextElement(AskedHere) {
    companion object Key : CoroutineContext.Key<AskedHere>
}
