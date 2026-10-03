package com.burjeel.edcall
import android.webkit.CookieManager
import org.json.JSONObject
import java.net.URL
import javax.net.ssl.HttpsURLConnection

class ApiFailure(val status: Int): Exception("Request failed ($status)")
class EnrollmentClient(private val store: DeviceStore) {
    private fun request(path: String, body: JSONObject?=null, credential: String="", csrf: String="", session: Boolean=false): JSONObject {
        require(path.startsWith("/api/mobile/"))
        val connection=URL(NativePolicy.ORIGIN+path).openConnection() as HttpsURLConnection
        connection.connectTimeout=10000; connection.readTimeout=10000; connection.instanceFollowRedirects=false
        connection.requestMethod=if(body==null) "GET" else "POST"
        connection.setRequestProperty("Content-Type","application/json")
        if(credential.isNotEmpty()) connection.setRequestProperty("Authorization","Bearer $credential")
        if(session) { connection.setRequestProperty("Cookie",CookieManager.getInstance().getCookie(NativePolicy.ORIGIN) ?: ""); connection.setRequestProperty("Origin",NativePolicy.ORIGIN) }
        if(csrf.isNotEmpty()) connection.setRequestProperty("X-CSRF-Token",csrf)
        try {
            if(body!=null) { connection.doOutput=true; connection.outputStream.use { it.write(body.toString().toByteArray()) } }
            val status=connection.responseCode
            if(status !in 200..299) throw ApiFailure(status)
            val cookies=if(session) connection.headerFields.filterKeys { it?.equals("Set-Cookie",true)==true }.values.flatten() else emptyList()
            return JSONObject(connection.inputStream.bufferedReader().use { it.readText() }.ifEmpty { "{}" }).put("_session_cookies",org.json.JSONArray(cookies))
        } finally { connection.disconnect() }
    }
    fun applySessionCookies(response: JSONObject) {
        val cookies=response.optJSONArray("_session_cookies") ?: return
        for(i in 0 until cookies.length()) CookieManager.getInstance().setCookie(NativePolicy.ORIGIN,cookies.getString(i))
        CookieManager.getInstance().flush()
    }
    fun enroll(challenge: String, installationId: String, token: String): JSONObject = request("/api/mobile/enroll",JSONObject().put("challenge",challenge).put("installation_id",installationId).put("fcm_token",token),store.credential.ifEmpty { store.previousCredential },session=true)
    fun refresh(token: String,credential: String=store.credential): JSONObject = request("/api/mobile/token",JSONObject().put("fcm_token",token),credential)
    fun revoke(credential: String=store.pendingCredential): JSONObject = request("/api/mobile/revoke",JSONObject(),credential)
    fun test(): JSONObject {
        val status=request("/api/mobile/status",session=true)
        return request("/api/mobile/test",JSONObject().put("installation_id",store.installationId),csrf=status.getString("csrf_token"),session=true)
    }
    fun confirm(): JSONObject = request("/api/mobile/ready",JSONObject(),store.credential,session=true)
}
