package com.burjeel.edcall
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test

class DeviceLifecycleTest {
    @Test fun accountSwitchInvalidatesPreviousCredential() {
        val store=DeviceStore(InstrumentationRegistry.getInstrumentation().targetContext)
        store.credential="first-credential"
        assertEquals("first-credential",store.credential)
        store.credential="second-credential"
        assertNotEquals("first-credential",store.credential)
        assertFalse(NativePolicy.acceptsRegistration("old-generation",store.credential))
    }
    @Test fun offlineLogoutShowsPendingRevocation() {
        val store=DeviceStore(InstrumentationRegistry.getInstrumentation().targetContext)
        store.credential="credential-to-revoke"
        store.beginRevocation()
        assertTrue(store.pendingRevocation)
        assertFalse(store.registered)
        assertEquals("credential-to-revoke",store.pendingCredential)
        store.finishRevocation()
        assertFalse(store.pendingRevocation)
        assertEquals("credential-to-revoke",store.previousCredential)
    }
}
