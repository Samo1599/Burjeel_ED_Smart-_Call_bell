package com.burjeel.edcall
import android.net.Uri
import android.webkit.WebView
import androidx.webkit.*
import org.json.JSONObject

object NativeBridge {
    fun attach(view: WebView, retry: ()->Unit = {}, enroll: (String)->Unit): Boolean {
        if(!WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) return false
        WebViewCompat.addWebMessageListener(view,"BurjeelNative",setOf(NativePolicy.ORIGIN)) { _,message,origin,isMainFrame,_ ->
            if(!isMainFrame || !NativePolicy.isAllowedUrl(origin.toString()) || !NativePolicy.isAllowedUrl(view.url ?: "")) return@addWebMessageListener
            try { val payload=JSONObject(message.data ?: ""); if(payload.optString("command")=="retry") { retry(); return@addWebMessageListener }; if(payload.optString("command")=="enroll") { val challenge=payload.optString("challenge"); if(challenge.length in 16..128) enroll(challenge) } } catch(_: Exception) { }
        }
        return true
    }
}
