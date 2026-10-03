package com.burjeel.edcall
import org.junit.Assert.*
import org.junit.Test

class PolicyTest {
    @Test fun distinctEventsRemainVisible() {
        assertNotEquals(NativePolicy.notificationTag("first"), NativePolicy.notificationTag("recall1"))
    }
    @Test fun duplicateEventUsesSameNotification() {
        assertEquals(NativePolicy.notificationTag("same"), NativePolicy.notificationTag("same"))
    }
    @Test fun externalNavigationCannotEnroll() {
        assertTrue(NativePolicy.isAllowedUrl(NativePolicy.ORIGIN + "/nurse"))
        assertFalse(NativePolicy.isAllowedUrl("https://evil.example/nurse"))
        assertFalse(NativePolicy.isAllowedUrl(NativePolicy.ORIGIN + ".evil.example/nurse"))
        assertFalse(NativePolicy.isAllowedUrl("http://burjeel-ed-smart-call-bell-dct3.onrender.com/nurse"))
        assertEquals("/nurse", NativePolicy.safePath("//evil.example"))
    }
    @Test fun disabledPermissionBlocksReadiness() {
        assertFalse(NativePolicy.ready(true, false, true))
        assertFalse(NativePolicy.ready(true, true, false))
        assertTrue(NativePolicy.ready(true, true, true))
    }
    @Test fun offlineLogoutShowsPendingRevocation() {
        assertEquals("pending", NativePolicy.revocationState(false))
        assertEquals("confirmed", NativePolicy.revocationState(true))
    }
    @Test fun offlineTokenRotationRetries() {
        assertTrue(NativePolicy.shouldRetry(503))
        assertTrue(NativePolicy.shouldRetry(0))
        assertFalse(NativePolicy.shouldRetry(401))
    }
}
