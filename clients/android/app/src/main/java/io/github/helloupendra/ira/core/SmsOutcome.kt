package io.github.helloupendra.ira.core

/** What the phone said of an SMS it was given, part by part: sent, failed, or not yet known. */
object SmsOutcome {
    /** Activity.RESULT_OK, as the send callback carries it. */
    const val OK = -1

    /** Why it did not go, from the first part that failed; null when none failed. */
    fun failure(codes: List<Int?>): String? =
        codes.firstOrNull { it != null && it != OK }?.let { code ->
            when (code) {
                1 -> "the carrier or the phone refused it"
                2 -> "the phone's mobile radio is off (flight mode?)"
                3 -> "the phone could not build the message"
                4 -> "there is no mobile service"
                else -> "the phone reported error $code"
            }
        }

    /** Every part confirmed sent (not delivered: that is the carrier's to say). */
    fun sent(codes: List<Int?>): Boolean = codes.isNotEmpty() && codes.all { it == OK }
}
