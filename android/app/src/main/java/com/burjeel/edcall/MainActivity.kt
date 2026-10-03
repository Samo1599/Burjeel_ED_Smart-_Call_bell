package com.burjeel.edcall
import android.Manifest
import android.app.*
import android.content.*
import android.os.Build
import android.os.Bundle
import android.webkit.*
import android.widget.*
import android.view.View
import com.google.firebase.messaging.FirebaseMessaging
import java.util.concurrent.Executors

class MainActivity: Activity() {
    private lateinit var web: WebView
    private lateinit var state: TextView
    private lateinit var store: DeviceStore
    private lateinit var setupPanel: LinearLayout
    private val executor=Executors.newSingleThreadExecutor()
    private val receiptHandler=android.os.Handler(android.os.Looper.getMainLooper())
    private var testEvent=""
    private var receivedToken=""
    private var receiptDeadline=0L
    private var progressStage=0
    private var testSent=false
    private var enrolling=false
    private var setupStarted=false
    private var waitingSettings=false
    private lateinit var nextAction: Button
    private fun showStep(message: String, action: String="", observed: Boolean=false) {
        state.text=message
        if(::web.isInitialized) web.evaluateJavascript("window.nativeProgress?.($progressStage,${org.json.JSONObject.quote(message)},${org.json.JSONObject.quote(action)})",null)
        nextAction.visibility=if(action.isEmpty()) View.GONE else View.VISIBLE
        nextAction.text=action
        nextAction.setOnClickListener { if(observed) confirm() else { setupStarted=true; enable() } }
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store=DeviceStore(this); CallNotifications.createChannel(this)
        val layout=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL }
        setupPanel=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; setPadding(24,32,24,24); visibility=View.GONE }
        setupPanel.addView(TextView(this).apply { text="Notifications Required"; textSize=24f })
        state=TextView(this).apply { textSize=18f; setPadding(0,20,0,20) }; setupPanel.addView(state)
        val actions=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL }
        fun button(label: String,action: ()->Unit) { actions.addView(Button(this).apply { text=label; setOnClickListener { action() } },LinearLayout.LayoutParams(-1,LinearLayout.LayoutParams.WRAP_CONTENT)) }
        nextAction=Button(this).apply { visibility=View.GONE }; actions.addView(nextAction)
        button("Back to Sign in") { logout() }
        setupPanel.addView(actions); layout.addView(setupPanel)
        web=WebView(this)
        web.settings.javaScriptEnabled=true; web.settings.domStorageEnabled=true
        web.settings.allowFileAccess=false; web.settings.allowContentAccess=false
        web.settings.mixedContentMode=WebSettings.MIXED_CONTENT_NEVER_ALLOW
        CookieManager.getInstance().setAcceptThirdPartyCookies(web,false)
        val bridgeReady=NativeBridge.attach(web,retry={ enable() }) { enroll(it) }
        web.webViewClient=object: WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView,request: WebResourceRequest): Boolean {
                val target=request.url.toString()
                if(!NativePolicy.isAllowedUrl(target)) return true
                if(request.url.path=="/logout") { logout(); return true }
                if(request.url.path=="/notification-setup") { view.loadUrl(NativePolicy.ORIGIN+"/mobile/setup"); return true }
                return false
            }
            override fun onReceivedHttpError(view: WebView,request: WebResourceRequest,response: WebResourceResponse) {
                if(NativePolicy.redirectExpiredSession(request.url.toString(),request.isForMainFrame,response.statusCode)) {
                    testSent=false; setupStarted=false
                    view.loadUrl(NativePolicy.ORIGIN+"/login")
                }
            }
            override fun onPageStarted(view: WebView,url: String,favicon: android.graphics.Bitmap?) {
                setupPanel.visibility=View.GONE
                view.visibility=View.VISIBLE
            }
            override fun onPageFinished(view: WebView,url: String) {
                if(!NativePolicy.isAllowedUrl(url)) { view.loadUrl(NativePolicy.ORIGIN+"/login"); return }
                if(android.net.Uri.parse(url).path=="/notification-setup") view.loadUrl(NativePolicy.ORIGIN+"/mobile/setup")
                CookieManager.getInstance().flush()
                val path=android.net.Uri.parse(url).path
                if(path=="/login") {
                    setupStarted=false
                    view.evaluateJavascript("if(!document.getElementById('native-login-script')){const s=document.createElement('script');s.id='native-login-script';s.src='/static/native-login.js';document.body.appendChild(s);}",null)
                }
                if(path=="/mobile/setup" && !setupStarted) { setupStarted=true; enable() }
            }
            override fun onRenderProcessGone(view: WebView,detail: RenderProcessGoneDetail): Boolean { view.destroy(); state.text="Page stopped. Restart the app."; return true }
        }
        layout.addView(web,LinearLayout.LayoutParams(-1,0,1f)); setContentView(layout)
        if(!bridgeReady) state.text="Update Android System WebView to enable secure registration."
        web.loadUrl(NativePolicy.ORIGIN+NativePolicy.safePath(intent.getStringExtra("url") ?: "/"))
        FirebaseMessaging.getInstance().token.addOnSuccessListener { store.lifecycle.rotateToken(it); TokenRefreshWorker.schedule(this) }
    }
    override fun onResume() {
        super.onResume()
        if(waitingSettings && ::web.isInitialized) {
            waitingSettings=false
            if(CallNotifications.allowed(this)) enable()
            else showStep("Call notifications or sound are disabled. Enable them in Android settings.","Open Notification Settings")
        }
    }
    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); if(android.net.Uri.parse(web.url ?: "").path=="/mobile/setup" && testEvent.isNotEmpty()) return; web.loadUrl(NativePolicy.ORIGIN+NativePolicy.safePath(intent.getStringExtra("url") ?: "/")) }
    private fun refreshStatus() {
        state.text=when { store.pendingRevocation -> "Logout pending server confirmation. Connect to the network."
            !CallNotifications.allowed(this) -> "Notifications are disabled. Tap Allow notifications to enable them."
            store.registered -> "Notifications enabled. Send a test, then continue after it arrives."
            else -> "Allow notifications so patient calls can reach you while the phone is locked." }
    }
    private fun enable() {
        if(enrolling) return
        progressStage=0
        if(store.pendingRevocation) { TokenRefreshWorker.schedule(this); showStep("Completing the previous sign-out. Connect and retry.","Retry"); return }
        if(Build.VERSION.SDK_INT>=33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=android.content.pm.PackageManager.PERMISSION_GRANTED) {
            showStep("Allow notifications in the Android permission dialog to continue.")
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS),10); return
        }
        if(!CallNotifications.allowed(this)) { waitingSettings=true; showStep("Enable call notifications and sound in Android settings."); startActivity(Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(android.provider.Settings.EXTRA_APP_PACKAGE,packageName)); return }
        if(!NativePolicy.isAllowedUrl(web.url ?: "")) return
        if(android.net.Uri.parse(web.url).path!="/mobile/setup") { web.loadUrl(NativePolicy.ORIGIN+"/mobile/setup"); return }
        progressStage=1
        showStep("Permission and sound enabled. Registering this device…")
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
                        val accepted=store.lifecycle.acceptEnrollment(attempt,result.getString("credential"))
                        if(accepted) {
                            EnrollmentClient(store).applySessionCookies(result)
                            if(store.token.isEmpty()) store.lifecycle.rotateToken(token)
                            testSent=false
                        }
                        TokenRefreshWorker.schedule(this)
                        if(accepted) sendTest()
                    }
                } catch (_: Exception) { runOnUiThread { enrolling=false; showStep("Device registration failed. Please retry.","Retry") } }
            }
        }.addOnFailureListener { enrolling=false; showStep("Cannot connect to notifications. Check internet and Google Play services.","Retry") }
    }
    private fun sendTest() {
        if(!store.registered || !CallNotifications.allowed(this)) { showStep("Notifications are disabled. Enable permission and sound.","Retry"); return }
        val attempt=store.lifecycle.snapshot()
        receiptHandler.removeCallbacksAndMessages(null)
        store.testReceipt=""; testEvent=""; receivedToken=""; testSent=false
        progressStage=2
        showStep("Sending a test alert to this device…")
        executor.execute {
            try {
                val result=EnrollmentClient(store).test()
                runOnUiThread {
                    if(!store.lifecycle.isCurrent(attempt)) return@runOnUiThread
                    EnrollmentClient(store).applySessionCookies(result)
                    testSent=result.getJSONObject("provider").optInt("sent")==1
                    if(!testSent) { showStep("Test alert could not be sent. Check your connection.","Retry"); return@runOnUiThread }
                    testEvent=result.getString("event_id"); receiptDeadline=System.currentTimeMillis()+60000
                    showStep("Waiting for the test alert to arrive on this device…")
                    awaitReceipt()
                }
            } catch(_: Exception) { runOnUiThread { if(store.lifecycle.isCurrent(attempt)) showStep("Test alert failed. Check your connection and retry.","Retry") } }
        }
    }
    private fun awaitReceipt() {
        if(!testSent || testEvent.isEmpty() || !store.registered) return
        val receipt=try { org.json.JSONObject(store.testReceipt) } catch(_: Exception) { org.json.JSONObject() }
        if(CallNotifications.allowed(this) && getSystemService(NotificationManager::class.java).activeNotifications.any { it.tag==NativePolicy.notificationTag(testEvent) && it.id==1 } && TestReceipt.matches(testEvent,receipt.optString("event"),java.security.MessageDigest.getInstance("SHA-256").digest(store.credential.toByteArray()).joinToString("") { "%02x".format(it) },receipt.optString("registration"),receipt.optLong("at"),System.currentTimeMillis())) {
            receivedToken=receipt.optString("token")
            if(receivedToken.isNotEmpty()) { progressStage=3; confirm(); return }
        }
        if(System.currentTimeMillis()>=receiptDeadline) { testSent=false; showStep("Test alert has not arrived. Check your connection and notification settings.","Retry"); return }
        receiptHandler.postDelayed({ awaitReceipt() },500)
    }
    private fun confirm() {
        if(!testSent || receivedToken.isEmpty() || !CallNotifications.allowed(this)) return
        val attempt=store.lifecycle.snapshot()
        val receipt=receivedToken
        testSent=false
        showStep("Test alert received and displayed. Confirming this device…")
        executor.execute {
            try { val result=EnrollmentClient(store).confirmReceived(receipt); runOnUiThread {
                if(!store.lifecycle.isCurrent(attempt)) return@runOnUiThread
                if(!CallNotifications.allowed(this)) { showStep("Notification settings changed. Please retry.","Retry"); return@runOnUiThread }
                EnrollmentClient(store).applySessionCookies(result)
                progressStage=4; showStep("Device confirmed. Opening your workspace…")
                web.postDelayed({ if(store.lifecycle.isCurrent(attempt)) web.loadUrl(NativePolicy.ORIGIN+NativePolicy.safePath(result.getString("url"))) },350)
            } } catch(_: Exception) { runOnUiThread { if(store.lifecycle.isCurrent(attempt)) showStep("Device confirmation failed. Please retry.","Retry") } }
        }
    }
    private fun logout() {
        receiptHandler.removeCallbacksAndMessages(null); testEvent=""; receivedToken=""; store.testReceipt=""
        store.beginRevocation(); getSystemService(NotificationManager::class.java).cancelAll(); TokenRefreshWorker.schedule(this); testSent=false; setupStarted=false
        CookieManager.getInstance().removeAllCookies { CookieManager.getInstance().flush(); web.loadUrl(NativePolicy.ORIGIN+"/login"); refreshStatus() }
        web.clearHistory()
    }
    override fun onRequestPermissionsResult(requestCode: Int,permissions: Array<out String>,grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode,permissions,grantResults)
        if(requestCode==10 && grantResults.firstOrNull()==android.content.pm.PackageManager.PERMISSION_GRANTED) enable()
        else showStep("Notification permission is required to receive patient calls.","Allow Notifications")
    }
    override fun onDestroy() { receiptHandler.removeCallbacksAndMessages(null); executor.shutdown(); if(::web.isInitialized) web.destroy(); super.onDestroy() }
}
