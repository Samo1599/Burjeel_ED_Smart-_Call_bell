package com.burjeel.edcall
import java.net.URI
import java.security.MessageDigest

object NativePolicy {
    const val ORIGIN=BuildConfig.API_ORIGIN
    fun isAllowedUrl(value: String): Boolean = try {
        val url=URI(value); val base=URI(ORIGIN)
        url.scheme=="https" && url.host==base.host && (url.port==-1 || url.port==443) && url.userInfo==null
    } catch (_: Exception) { false }
    fun safePath(value: String): String = if (value in setOf("/","/nurse","/charge","/manager","/alerts")) value else "/nurse"
    fun notificationTag(eventId: String): String = "burjeel-$eventId"
    fun ready(registered: Boolean, permission: Boolean, channel: Boolean): Boolean = registered && permission && channel
    fun revocationState(confirmed: Boolean): String = if (confirmed) "confirmed" else "pending"
    fun shouldRetry(status: Int): Boolean = status==0 || status==429 || status>=500
    fun acceptsRegistration(generation: String, credential: String): Boolean {
        if (credential.isEmpty()) return false
        val hash=MessageDigest.getInstance("SHA-256").digest(credential.toByteArray()).joinToString("") { "%02x".format(it) }
        return generation==hash
    }
}
