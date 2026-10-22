package io.github.helloupendra.ira.assist

import android.content.Intent
import android.os.Bundle
import android.service.voice.VoiceInteractionService
import android.service.voice.VoiceInteractionSession
import android.service.voice.VoiceInteractionSessionService
import android.speech.RecognitionService
import android.speech.SpeechRecognizer
import io.github.helloupendra.ira.ui.MainActivity

/**
 * Ira as the phone's digital assistant (Settings, Apps, Default apps, Digital assistant
 * app). A long press of the power button, or the assistant gesture, opens Ira ready to
 * listen.
 *
 * A wake word ("Hey Ira") would start a session from here too: [IraVoiceInteractionService]
 * is where an always-on hotword detector would be created. It is a later step; see
 * docs/clients/android.md.
 */
class IraVoiceInteractionService : VoiceInteractionService()

class IraSessionService : VoiceInteractionSessionService() {
    override fun onNewSession(args: Bundle?): VoiceInteractionSession = IraSession(this)
}

/** Opens Ira's own screen, which starts a call at once. */
class IraSession(service: VoiceInteractionSessionService) : VoiceInteractionSession(service) {
    override fun onShow(args: Bundle?, showFlags: Int) {
        super.onShow(args, showFlags)
        val intent =
            Intent(context, MainActivity::class.java)
                .setAction(MainActivity.ACTION_TALK)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        startAssistantActivity(intent)
        hide()
    }
}

/**
 * Android requires a digital assistant to name a speech recognizer. Ira's speech is
 * recognised on the person's own Ira server during a call, so this one offers nothing to
 * other apps and says so with an error at once. Its metadata asks Android never to make it
 * the phone's default recognizer (`selectableAsDefault="false"`).
 */
class IraRecognitionService : RecognitionService() {
    override fun onStartListening(recognizerIntent: Intent?, listener: Callback?) {
        listener?.error(SpeechRecognizer.ERROR_CLIENT)
    }

    override fun onCancel(listener: Callback?) = Unit

    override fun onStopListening(listener: Callback?) = Unit
}
