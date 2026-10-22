package io.github.helloupendra.ira.core

/**
 * Pairing with another Ira while keeping the current one until the new pairing works, as
 * Ira for Mac does. The old server is told to forget the phone only when the person asks.
 */
object Repair {
    /** Where the current pairing lives (the Keystore token, the address): swapped in one step. */
    interface Holder {
        val server: String?
        val token: String?
        val websocketPath: String

        fun replace(paired: Paired)
    }

    /** Tells a server to forget this phone: `bye` on its device WebSocket with its token. */
    fun interface Farewell {
        fun send(server: String, path: String, token: String)
    }

    sealed interface Result {
        data class Paired(val paired: io.github.helloupendra.ira.core.Paired, val forgotOld: Boolean) : Result

        /** The new pairing failed: the current one is untouched. */
        data class Kept(val message: String) : Result
    }

    /** The network half (off the main thread): the new server's token, or why not. */
    fun pair(entry: String, typedServer: String?, version: String, post: HttpPost): Pair<Paired?, String?> =
        try {
            val (server, code) = Pairing.parse(entry, typedServer?.ifBlank { null })
            Pairing.exchange(server, code, version, post) to null
        } catch (exc: PairError) {
            null to Plain.sentence(exc.message)
        } catch (_: Exception) {
            null to "That did not work. Check the address and the code, then try again."
        }

    /**
     * The switch, after the new server answered 200: the old pairing is read first, replaced
     * by the new one, and only then, if asked, the old server is told to forget the phone.
     */
    fun commit(holder: Holder, paired: Paired, removeOld: Boolean, farewell: Farewell): Result.Paired {
        val oldServer = holder.server
        val oldToken = holder.token
        val oldPath = holder.websocketPath
        holder.replace(paired)
        val forget = removeOld && oldServer != null && oldToken != null && oldToken != paired.token
        if (forget) farewell.send(oldServer, oldPath, oldToken)
        return Result.Paired(paired, forget)
    }

    /** Both halves on one thread (tests, and callers already off the main thread). */
    fun run(entry: String, typedServer: String?, version: String, post: HttpPost, removeOld: Boolean, holder: Holder, farewell: Farewell): Result {
        val (paired, error) = pair(entry, typedServer, version, post)
        return if (paired == null) Result.Kept(error ?: "That did not work.") else commit(holder, paired, removeOld, farewell)
    }
}
