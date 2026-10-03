package com.burjeel.edcall

import android.Manifest
import android.app.*
import android.content.*
import android.content.pm.PackageManager
import android.os.Build
import android.provider.Settings

 data class CallEvent(val eventId: String, val title: String, val body: String, val path: String)

object CallNotifications {
    const val CHANNEL = "burjeel_calls_v1"
    fun createChannel(context: Context) {
        val channel = NotificationChannel(CHANNEL, "ED calls and recalls", NotificationManager.IMPORTANCE_HIGH)
        channel.description = "Staff call bell alerts"
        channel.enableVibration(true)
        channel.vibrationPattern = longArrayOf(0,350,120,350,120,650)
        channel.lockscreenVisibility = Notification.VISIBILITY_PRIVATE
        context.getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }
    fun allowed(context: Context): Boolean {
        val manager=context.getSystemService(NotificationManager::class.java)
        val permission=Build.VERSION.SDK_INT<33 || context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)==PackageManager.PERMISSION_GRANTED
        return permission && manager.areNotificationsEnabled() && (manager.getNotificationChannel(CHANNEL)?.importance ?: 0)>=NotificationManager.IMPORTANCE_HIGH && manager.getNotificationChannel(CHANNEL)?.sound!=null
    }
    fun show(context: Context, event: CallEvent) {
        createChannel(context)
        if (!allowed(context)) return
        val intent=Intent(context,MainActivity::class.java).putExtra("url",NativePolicy.safePath(event.path))
        intent.action="com.burjeel.edcall.OPEN.${event.eventId}"
        val pending=PendingIntent.getActivity(context,0,intent,PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notification=Notification.Builder(context,CHANNEL).setSmallIcon(R.drawable.ic_call)
            .setContentTitle(event.title).setContentText(event.body).setContentIntent(pending)
            .setAutoCancel(true).setVisibility(Notification.VISIBILITY_PRIVATE).build()
        context.getSystemService(NotificationManager::class.java).notify(NativePolicy.notificationTag(event.eventId),1,notification)
    }
}
