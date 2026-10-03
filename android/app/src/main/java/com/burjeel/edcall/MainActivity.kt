package com.burjeel.edcall
import android.Manifest
import android.app.*
import android.content.*
import android.os.Build
import android.os.Bundle
import android.webkit.*
import android.widget.*
import com.google.firebase.messaging.FirebaseMessaging
import java.util.concurrent.Executors

class MainActivity: Activity() {
    private lateinit var web: WebView
    private lateinit var state: TextView
    private lateinit var store: DeviceStore
    private val executor=Executors.newSingleThreadExecutor()
    private var testSent=false
    private var enrolling=false
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store=DeviceStore(this); CallNotifications.createChannel(this)
        val layout=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL }
        state=TextView(this); layout.addView(state)
        val actions=LinearLayout(this)
        fun button(label: String,action: ()->Unit) { actions.addView(Button(this).apply { text=label; setOnClickListener { action() } },LinearLayout.LayoutParams(0,LinearLayout.LayoutParams.WRAP_CONTENT,1f)) }
        button("Enable") { enable() }; button("Test") { sendTest() }; button("Confirm") { confirm() }; button("Logout") { logout() }
        layout.addView(actions)
        web=WebView(this)
        web.settings.javaScriptEnabled=true; web.settings.domStorageEnabled=true
        web.settings.allowFileAccess=false; web.settings.allowContentAccess=false
        web.settings.mixedContentMode=WebSettings.MIXED_CONTENT_NEVER_ALLOW
        CookieManager.getInstance().setAcceptThirdPartyCookies(web,false)
        val bridgeReady=NativeBridge.attach(web) { enroll(it) }
        web.webViewClient=object: WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView,request: WebResourceRequest): Boolean {
                val target=request.url.toString()
                if(!NativePolicy.isAllowedUrl(target)) return true
                if(request.url.path=="/logout") { logout(); return true }
                if(request.url.path=="/notification-setup") { view.loadUrl(NativePolicy.ORIGIN+"/mobile/setup"); return true }
                return false
            }
            override fun onPageFinished(view: WebView,url: String) {
                if(!NativePolicy.isAllowedUrl(url)) { view.loadUrl(NativePolicy.ORIGIN+"/login"); return }
                if(android.net.Uri.parse(url).path=="/notification-setup") view.loadUrl(NativePolicy.ORIGIN+"/mobile/setup")
                refreshStatus()
            }
            override fun onRenderProcessGone(view: WebView,detail: RenderProcessGoneDetail): Boolean { view.destroy(); state.text="Page stopped. Restart the app."; return true }
        }
        layout.addView(web,LinearLayout.LayoutParams(-1,0,1f)); setContentView(layout)
        if(!bridgeReady) state.text="Update Android System WebView to enable secure registration."
        web.loadUrl(NativePolicy.ORIGIN+NativePolicy.safePath(intent.getStringExtra("url") ?: "/nurse"))
        FirebaseMessaging.getInstance().token.addOnSuccessListener { store.lifecycle.rotateToken(it); TokenRefreshWorker.schedule(this) }
    }
    override fun onResume() { super.onResume(); if(::state.isInitialized) refreshStatus() }
    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); web.loadUrl(NativePolicy.ORIGIN+NativePolicy.safePath(intent.getStringExtra("url") ?: "/nurse")) }
    private fun refreshStatus() {
        state.text=when { store.pendingRevocation -> "Logout pending server confirmation. Connect to the network."
            !CallNotifications.allowed(this) -> "Notifications blocked. Enable permission and the ED calls channel."
            store.registered -> "Android registered. Test, then confirm after seeing the notification."
            else -> "Sign in, then tap Enable for Android notifications." }
    }
    private fun enable() {
        if(enrolling) { state.text="Registration in progress. Please wait."; return }
        if(store.pendingRevocation) { TokenRefreshWorker.schedule(this); refreshStatus(); return }
        if(Build.VERSION.SDK_INT>=33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=android.content.pm.PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS),10); return
        }
        if(!CallNotifications.allowed(this)) { startActivity(Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(android.provider.Settings.EXTRA_APP_PACKAGE,packageName)); return }
        if(!NativePolicy.isAllowedUrl(web.url ?: "")) return
        if(android.net.Uri.parse(web.url).path!="/mobile/setup") { web.loadUrl(NativePolicy.ORIGIN+"/mobile/setup"); return }
        web.evaluateJavascript("enrollNative()",null)
    }
    private fun enroll(challenge: String) {
        if(store.pendingRevocation || enrolling) return
        enrolling=true
        val attempt=store.lifecycle.snapshot()
        FirebaseMessaging.getInstance().token.addOnSuccessListener { token ->
            executor.execute {
                try {
                    val result=EnrollmentClient(store).enroll(challenge,store.installationId,token)
                    runOnUiThread {
                        enrolling=false
                        if(store.lifecycle.acceptEnrollment(attempt,result.getString("credential"))) {
                            EnrollmentClient(store).applySessionCookies(result)
                            if(store.token.isEmpty()) store.lifecycle.rotateToken(token)
                            testSent=false
                        }
                        TokenRefreshWorker.schedule(this)
                        refreshStatus()
                    }
                } catch (_: Exception) { runOnUiThread { enrolling=false; state.text="Registration failed. Sign in and retry." } }
            }
        }.addOnFailureListener { enrolling=false; state.text="FCM unavailable. Check Firebase configuration and Google Play services." }
    }
    private fun sendTest() {
        if(!store.registered || !CallNotifications.allowed(this)) { refreshStatus(); return }
        val attempt=store.lifecycle.snapshot()
        executor.execute {
            try { val result=EnrollmentClient(store).test(); val accepted=result.getJSONObject("provider").optInt("sent")==1
                runOnUiThread { if(!store.lifecycle.isCurrent(attempt)) return@runOnUiThread; EnrollmentClient(store).applySessionCookies(result); testSent=accepted; state.text=if(accepted) "Test sent. Confirm only after seeing the notification." else "Test was not accepted. Check server configuration." }
            } catch (_: Exception) { runOnUiThread { state.text="Test failed. Sign in and retry." } }
        }
    }
    private fun confirm() {
        if(!testSent || !CallNotifications.allowed(this)) { state.text="Send a test and check that it appears before confirming."; return }
        AlertDialog.Builder(this).setMessage("Did the Android test notification appear?").setNegativeButton("No",null).setPositiveButton("Yes") { _,_ ->
            val attempt=store.lifecycle.snapshot()
            executor.execute {
                try { val result=EnrollmentClient(store).confirm(); runOnUiThread { if(!store.lifecycle.isCurrent(attempt)) return@runOnUiThread; EnrollmentClient(store).applySessionCookies(result); web.loadUrl(NativePolicy.ORIGIN+NativePolicy.safePath(result.getString("url"))) } }
                catch (_: Exception) { runOnUiThread { state.text="Confirmation failed. Sign in and test again." } }
            }
        }.show()
    }
    private fun logout() {
        store.beginRevocation(); getSystemService(NotificationManager::class.java).cancelAll(); TokenRefreshWorker.schedule(this); testSent=false
        CookieManager.getInstance().removeAllCookies { CookieManager.getInstance().flush(); web.loadUrl(NativePolicy.ORIGIN+"/login"); refreshStatus() }
        web.clearHistory()
    }
    override fun onDestroy() { executor.shutdown(); if(::web.isInitialized) web.destroy(); super.onDestroy() }
}
