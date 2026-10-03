package com.burjeel.edcall
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

class CallMessagingService : FirebaseMessagingService() {
    override fun onMessageReceived(message: RemoteMessage) {
        val data=message.data
        val eventId=data["event_id"] ?: return
        val store=DeviceStore(this)
        if (!store.registered || !NativePolicy.acceptsRegistration(data["registration_hash"] ?: "",store.credential)) return
        CallNotifications.show(this,CallEvent(eventId,data["title"] ?: "Burjeel ED Call",data["body"] ?: "New alert",data["url"] ?: "/nurse"))
    }
    override fun onNewToken(token: String) {
        DeviceStore(this).lifecycle.rotateToken(token)
        TokenRefreshWorker.schedule(this)
    }
}
