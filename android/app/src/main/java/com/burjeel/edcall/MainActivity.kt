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
    private var testSent=false
    private var enrolling=false
    private var setupStarted=false
    private var waitingSettings=false
    private lateinit var nextAction: Button
    private fun showStep(message: String, action: String="", observed: Boolean=false) {
        state.text=message
        nextAction.visibility=if(action.isEmpty()) View.GONE else View.VISIBLE
        nextAction.text=action
        nextAction.setOnClickListener { if(observed) confirm() else { setupStarted=true; enable() } }
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store=DeviceStore(this); CallNotifications.createChannel(this)
        val layout=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL }
        setupPanel=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; setPadding(24,32,24,24); visibility=View.GONE }
        setupPanel.addView(TextView(this).apply { text="تجهيز إشعارات النداء"; textSize=24f })
        state=TextView(this).apply { textSize=18f; setPadding(0,20,0,20) }; setupPanel.addView(state)
        val actions=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL }
        fun button(label: String,action: ()->Unit) { actions.addView(Button(this).apply { text=label; setOnClickListener { action() } },LinearLayout.LayoutParams(-1,LinearLayout.LayoutParams.WRAP_CONTENT)) }
        nextAction=Button(this).apply { visibility=View.GONE }; actions.addView(nextAction)
        button("العودة لتسجيل الدخول") { logout() }
        setupPanel.addView(actions); layout.addView(setupPanel)
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
            override fun onReceivedHttpError(view: WebView,request: WebResourceRequest,response: WebResourceResponse) {
                if(NativePolicy.redirectExpiredSession(request.url.toString(),request.isForMainFrame,response.statusCode)) {
                    testSent=false; setupStarted=false
                    view.loadUrl(NativePolicy.ORIGIN+"/login")
                }
            }
            override fun onPageStarted(view: WebView,url: String,favicon: android.graphics.Bitmap?) {
                val setup=NativePolicy.isAllowedUrl(url) && android.net.Uri.parse(url).path=="/mobile/setup"
                setupPanel.visibility=if(setup) View.VISIBLE else View.GONE
                view.visibility=if(setup) View.GONE else View.VISIBLE
            }
            override fun onPageFinished(view: WebView,url: String) {
                if(!NativePolicy.isAllowedUrl(url)) { view.loadUrl(NativePolicy.ORIGIN+"/login"); return }
                if(android.net.Uri.parse(url).path=="/notification-setup") view.loadUrl(NativePolicy.ORIGIN+"/mobile/setup")
                CookieManager.getInstance().flush()
                val path=android.net.Uri.parse(url).path
                if(path=="/login") {
                    setupStarted=false
                    view.evaluateJavascript("document.querySelector('form')?.addEventListener('submit',function(){const b=this.querySelector('button[type=submit],button.btn');if(b){b.textContent='جارٍ التحقق من بيانات الدخول…';b.disabled=true;}})",null)
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
            else showStep("إشعارات النداء أو صوتها معطّلان. فعّلهما من إعدادات الهاتف.","فتح إعدادات الإشعارات")
        }
    }
    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); web.loadUrl(NativePolicy.ORIGIN+NativePolicy.safePath(intent.getStringExtra("url") ?: "/")) }
    private fun refreshStatus() {
        state.text=when { store.pendingRevocation -> "Logout pending server confirmation. Connect to the network."
            !CallNotifications.allowed(this) -> "Notifications are disabled. Tap Allow notifications to enable them."
            store.registered -> "Notifications enabled. Send a test, then continue after it arrives."
            else -> "Allow notifications so patient calls can reach you while the phone is locked." }
    }
    private fun enable() {
        if(enrolling) return
        if(store.pendingRevocation) { TokenRefreshWorker.schedule(this); showStep("جارٍ إكمال تسجيل الخروج السابق. أعد المحاولة بعد الاتصال.","إعادة المحاولة"); return }
        if(Build.VERSION.SDK_INT>=33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=android.content.pm.PackageManager.PERMISSION_GRANTED) {
            showStep("١. السماح بالإشعارات — وافق على طلب Android للمتابعة.")
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS),10); return
        }
        if(!CallNotifications.allowed(this)) { waitingSettings=true; showStep("فعّل إشعارات النداء والصوت من إعدادات الهاتف."); startActivity(Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(android.provider.Settings.EXTRA_APP_PACKAGE,packageName)); return }
        if(!NativePolicy.isAllowedUrl(web.url ?: "")) return
        if(android.net.Uri.parse(web.url).path!="/mobile/setup") { web.loadUrl(NativePolicy.ORIGIN+"/mobile/setup"); return }
        showStep("✓ الإذن والصوت\n٢. جارٍ تسجيل الجهاز وتحديث الاشتراك…")
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
                        if(accepted) resumeOrTest()
                    }
                } catch (_: Exception) { runOnUiThread { enrolling=false; showStep("تعذّر تسجيل الجهاز. أعد المحاولة.","إعادة المحاولة") } }
            }
        }.addOnFailureListener { enrolling=false; showStep("تعذّر الاتصال بخدمة الإشعارات. تحقق من الإنترنت وخدمات Google Play.","إعادة المحاولة") }
    }
    private fun resumeOrTest() {
        val attempt=store.lifecycle.snapshot()
        showStep("✓ الإذن والصوت\n✓ تسجيل الجهاز\n٣. جارٍ التحقق من جاهزية الإشعارات…")
        executor.execute {
            try {
                val result=EnrollmentClient(store).resume()
                runOnUiThread {
                    if(!store.lifecycle.isCurrent(attempt)) return@runOnUiThread
                    if(!CallNotifications.allowed(this)) { showStep("فعّل الإشعارات والصوت للمتابعة.","فتح الإعدادات"); return@runOnUiThread }
                    EnrollmentClient(store).applySessionCookies(result)
                    web.loadUrl(NativePolicy.ORIGIN+NativePolicy.safePath(result.getString("url")))
                }
            } catch(e: ApiFailure) {
                runOnUiThread { if(store.lifecycle.isCurrent(attempt)) {
                    if(e.status==409) sendTest()
                    else if(e.status==401) { setupStarted=false; web.loadUrl(NativePolicy.ORIGIN+"/login") }
                    else showStep("تعذّر التحقق من الإشعارات. أعد المحاولة.","إعادة المحاولة")
                } }
            } catch(_: Exception) { runOnUiThread { if(store.lifecycle.isCurrent(attempt)) showStep("تحقق من الاتصال وأعد المحاولة.","إعادة المحاولة") } }
        }
    }
    private fun sendTest() {
        if(!store.registered || !CallNotifications.allowed(this)) { refreshStatus(); return }
        val attempt=store.lifecycle.snapshot()
        showStep("✓ الإذن والصوت\n✓ تسجيل الجهاز\n٣. جارٍ إرسال إشعار الاختبار…")
        executor.execute {
            try { val result=EnrollmentClient(store).test(); val accepted=result.getJSONObject("provider").optInt("sent")==1
                runOnUiThread { if(!store.lifecycle.isCurrent(attempt)) return@runOnUiThread; EnrollmentClient(store).applySessionCookies(result); testSent=accepted; if(accepted) showStep("✓ الإذن والصوت\n✓ تسجيل الجهاز\nتم إرسال الاختبار. اضغط أدناه فقط بعد وصول الإشعار.","وصل الإشعار — دخول",true) else showStep("تعذّر إرسال الاختبار. أعد المحاولة.","إعادة المحاولة") }
            } catch (_: Exception) { runOnUiThread { showStep("تعذّر إرسال الاختبار. تحقق من اتصالك.","إعادة المحاولة") } }
        }
    }
    private fun confirm() {
        if(!testSent || !CallNotifications.allowed(this)) { state.text="Send a test and check that it appears before confirming."; return }
        val attempt=store.lifecycle.snapshot()
        showStep("✓ تم تأكيد وصول الإشعار\nجارٍ فتح لوحة التمريض…")
        executor.execute {
            try { val result=EnrollmentClient(store).confirm(); runOnUiThread {
                if(!store.lifecycle.isCurrent(attempt)) return@runOnUiThread
                EnrollmentClient(store).applySessionCookies(result)
                web.loadUrl(NativePolicy.ORIGIN+NativePolicy.safePath(result.getString("url")))
            } } catch(_: Exception) { runOnUiThread { showStep("انتهت مهلة الاختبار. أعد المحاولة.","إعادة المحاولة") } }
        }
    }
    private fun logout() {
        store.beginRevocation(); getSystemService(NotificationManager::class.java).cancelAll(); TokenRefreshWorker.schedule(this); testSent=false; setupStarted=false
        CookieManager.getInstance().removeAllCookies { CookieManager.getInstance().flush(); web.loadUrl(NativePolicy.ORIGIN+"/login"); refreshStatus() }
        web.clearHistory()
    }
    override fun onRequestPermissionsResult(requestCode: Int,permissions: Array<out String>,grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode,permissions,grantResults)
        if(requestCode==10 && grantResults.firstOrNull()==android.content.pm.PackageManager.PERMISSION_GRANTED) enable()
        else showStep("يحتاج التطبيق إذن الإشعارات لاستقبال النداءات.","السماح بالإشعارات")
    }
    override fun onDestroy() { executor.shutdown(); if(::web.isInitialized) web.destroy(); super.onDestroy() }
}
